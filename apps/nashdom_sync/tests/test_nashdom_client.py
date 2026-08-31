from typing import Any, Dict, Tuple, cast
from unittest.mock import Mock

import pytest
from nashdom_sync.contracts import NashDomExtractSettings, NashDomRegion
from nashdom_sync.extract import NashDomClientError, NashDomUnavailableError
from nashdom_sync.extract.nashdom.client import (
    _INSTALL_INTERCEPTOR_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    _PUBLIC_BROWSER_FETCH_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    NashDomClient,
    _ApiBatch,  # pyright: ignore[reportPrivateUsage]
    _CapturedRequest,  # pyright: ignore[reportPrivateUsage]
    _DeveloperApiBatch,  # pyright: ignore[reportPrivateUsage]
)
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver


def _raw_object(object_id: int) -> Dict[str, Any]:
    return {
        "objId": object_id,
        "objAddr": f"Адрес {object_id}",
        "objCommercNm": f"Объект {object_id}",
        "developer": {"devId": 1000 + object_id},
        "objReady100PercDt": "IV кв. 2028",
        "buildType": "Жилое",
        "rpdRegionCd": 22,
        "publicationDate": "21.08.2026",
    }


def _raw_developer(developer_id: int) -> Dict[str, Any]:
    return {
        "devId": developer_id,
        "devShortCleanNm": f"Застройщик {developer_id}",
        "devFullCleanNm": f"Полное имя застройщика {developer_id}",
        "devInn": "7701651356",
        "devKpp": "720301001",
        "devOgrn": "1067746424899",
        "devOrgRegRegionCd": 72,
        "devLegalAddr": "Юридический адрес",
        "devFactAddr": "Фактический адрес",
        "devEmplMainFullNm": "Иванов Иван Иванович",
        "devPhoneNum": "+70000000000",
        "devEmail": "developer@example.test",
        "devSite": None,
    }


def _settings(target_count: int) -> NashDomExtractSettings:
    return NashDomExtractSettings(
        objects_to_parse_count=target_count,
        regions=(
            NashDomRegion(
                code=22,
                name="Алтайский край",
                slug="алтайский-край",
            ),
        ),
    )


def _client() -> Tuple[NashDomClient, Mock]:
    driver = Mock()
    driver.current_url = "https://xn--80az8a.xn--d1aqf.xn--p1ai/"
    return NashDomClient(cast(WebDriver, driver)), driver


def test_interceptor_script_returns_installation_result_to_selenium() -> None:
    assert _INSTALL_INTERCEPTOR_SCRIPT.lstrip().startswith("return ")


def test_ssr_fallback_returns_every_available_object_without_xhr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    ssr_objects = [_raw_object(1), _raw_object(2)]
    open_region = Mock()
    bootstrap = Mock()
    collect_api = Mock()
    monkeypatch.setattr(client, "_open_region", open_region)
    monkeypatch.setattr(client, "_read_ssr_objects", Mock(return_value=ssr_objects))
    monkeypatch.setattr(client, "_find_load_more_locator", Mock(return_value=None))
    monkeypatch.setattr(client, "_bootstrap_api_request", bootstrap)
    monkeypatch.setattr(client, "_collect_api_objects", collect_api)

    result = client.get_objects(_settings(target_count=3))

    assert [extracted_object.id for extracted_object in result] == [1, 2]
    open_region.assert_called_once()
    bootstrap.assert_not_called()
    collect_api.assert_not_called()


def test_ssr_path_stops_at_target_without_searching_for_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    find_button = Mock()
    monkeypatch.setattr(client, "_open_region", Mock())
    monkeypatch.setattr(
        client,
        "_read_ssr_objects",
        Mock(return_value=[_raw_object(1), _raw_object(2), _raw_object(3)]),
    )
    monkeypatch.setattr(client, "_find_load_more_locator", find_button)

    result = client.get_objects(_settings(target_count=2))

    assert [extracted_object.id for extracted_object in result] == [1, 2]
    find_button.assert_not_called()


def test_successful_xhr_path_replaces_ssr_with_offset_zero_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    locator = ("css selector", "button")
    captured_request = object()
    bootstrap = Mock(return_value=captured_request)
    collect_api = Mock(return_value=[_raw_object(10), _raw_object(11)])
    monkeypatch.setattr(client, "_open_region", Mock())
    monkeypatch.setattr(client, "_read_ssr_objects", Mock(return_value=[_raw_object(1)]))
    monkeypatch.setattr(client, "_find_load_more_locator", Mock(return_value=locator))
    monkeypatch.setattr(client, "_bootstrap_api_request", bootstrap)
    monkeypatch.setattr(client, "_collect_api_objects", collect_api)

    result = client.get_objects(_settings(target_count=2))

    assert [extracted_object.id for extracted_object in result] == [10, 11]
    bootstrap.assert_called_once_with(locator)
    collect_api.assert_called_once_with(captured_request, 2)


def test_api_collection_starts_at_zero_and_uses_actual_batch_offsets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    first_batch = [_raw_object(object_id) for object_id in range(10, 30)]
    second_batch = [_raw_object(object_id) for object_id in range(30, 35)]
    fetch_batch = Mock(
        side_effect=[
            _ApiBatch(items=first_batch, total=25),
            _ApiBatch(items=second_batch, total=25),
        ]
    )
    monkeypatch.setattr(client, "_fetch_api_batch", fetch_batch)
    captured_request = _CapturedRequest(
        request_url=(
            "https://xn--80az8a.xn--d1aqf.xn--p1ai/"
            "%D1%81%D0%B5%D1%80%D0%B2%D0%B8%D1%81%D1%8B/api/kn/object"
            "?offset=20&limit=20&place=22&objStatus=0"
        ),
        authorization="test-only",
    )

    result = client._collect_api_objects(  # pyright: ignore[reportPrivateUsage]
        captured_request,
        target_count=25,
    )

    assert [raw_object["objId"] for raw_object in result] == list(range(10, 35))
    assert fetch_batch.call_args_list[0].kwargs == {"offset": 0, "limit": 20}
    assert fetch_batch.call_args_list[1].kwargs == {"offset": 20, "limit": 5}


def test_build_api_url_preserves_query_and_replaces_pagination() -> None:
    result = NashDomClient._build_api_url(  # pyright: ignore[reportPrivateUsage]
        "https://example.test/api/kn/object?offset=20&limit=20&place=22&objStatus=0",
        offset=0,
        limit=7,
    )

    assert "offset=0" in result
    assert "limit=7" in result
    assert "place=22" in result
    assert "objStatus=0" in result


def test_region_url_keeps_constructing_status_and_newest_first_sort() -> None:
    result = NashDomClient._build_region_url(  # pyright: ignore[reportPrivateUsage]
        "алтайский-край"
    )

    assert "/новостройки/строящиеся/" in result
    assert "%D0%B0%D0%BB%D1%82%D0%B0%D0%B9%D1%81%D0%BA%D0%B8%D0%B9" in result
    assert "sortName=objPublDt&sortDirection=desc" in result


@pytest.mark.parametrize("status", [429, 500, 503])
def test_temporary_http_statuses_are_unavailable(status: int) -> None:
    with pytest.raises(NashDomUnavailableError):
        NashDomClient._raise_for_http_status(  # pyright: ignore[reportPrivateUsage]
            status,
            None,
            "теста",
        )


def test_plain_forbidden_response_is_not_masked_as_unavailable() -> None:
    with pytest.raises(NashDomClientError):
        NashDomClient._raise_for_http_status(  # pyright: ignore[reportPrivateUsage]
            403,
            {"message": "forbidden"},
            "теста",
        )


def test_captured_authorization_is_hidden_from_repr() -> None:
    captured_request = _CapturedRequest(
        request_url="https://example.test/api/kn/object",
        authorization="must-not-appear",
    )

    assert "must-not-appear" not in repr(captured_request)


def test_browser_fetch_failure_does_not_retain_authorization_in_exception() -> None:
    client, driver = _client()
    driver.execute_async_script.side_effect = WebDriverException("must-not-appear")
    captured_request = _CapturedRequest(
        request_url="https://example.test/api/kn/object?place=22",
        authorization="must-not-appear",
    )

    with pytest.raises(NashDomClientError) as exc_info:
        client._fetch_api_batch(  # pyright: ignore[reportPrivateUsage]
            captured_request,
            offset=0,
            limit=20,
        )

    assert "must-not-appear" not in str(exc_info.value)
    assert exc_info.value.__context__ is None


def test_empty_developer_ids_return_without_fetch() -> None:
    client, driver = _client()

    result = client.get_developers(set())

    assert result == []
    driver.execute_async_script.assert_not_called()
    driver.get.assert_not_called()


def test_public_developer_fetch_script_does_not_send_authorization() -> None:
    assert "Authorization" not in _PUBLIC_BROWSER_FETCH_SCRIPT


def test_all_developer_ids_on_first_full_page_stop_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    first_page = [{"devId": 10000 + index} for index in range(1000)]
    first_page[306] = _raw_developer(306)
    fetch_batch = Mock(
        return_value=_DeveloperApiBatch(items=first_page, count=4735)
    )
    read_detail = Mock()
    monkeypatch.setattr(client, "_fetch_developer_batch", fetch_batch)
    monkeypatch.setattr(client, "_read_detail_developer", read_detail)

    result = client.get_developers({306})

    assert [developer.id for developer in result] == [306]
    fetch_batch.assert_called_once_with(offset=0, limit=1000)
    read_detail.assert_not_called()


def test_developer_ids_on_different_pages_use_actual_offsets_and_stable_sort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    first_page = [{"devId": 10000 + index} for index in range(1000)]
    first_page[306] = _raw_developer(306)
    fetch_batch = Mock(
        side_effect=[
            _DeveloperApiBatch(items=first_page, count=4735),
            _DeveloperApiBatch(items=[_raw_developer(16750)], count=4735),
        ]
    )
    monkeypatch.setattr(client, "_fetch_developer_batch", fetch_batch)
    monkeypatch.setattr(client, "_read_detail_developer", Mock())

    result = client.get_developers({16750, 306})

    assert [developer.id for developer in result] == [306, 16750]
    assert fetch_batch.call_args_list[0].kwargs == {"offset": 0, "limit": 1000}
    assert fetch_batch.call_args_list[1].kwargs == {"offset": 1000, "limit": 1000}


def test_changing_developer_count_does_not_break_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    first_page = [{"devId": 20000 + index} for index in range(1000)]
    fetch_batch = Mock(
        side_effect=[
            _DeveloperApiBatch(items=first_page, count=5000),
            _DeveloperApiBatch(items=[_raw_developer(306)], count=1),
        ]
    )
    monkeypatch.setattr(client, "_fetch_developer_batch", fetch_batch)
    monkeypatch.setattr(client, "_read_detail_developer", Mock())

    result = client.get_developers({306})

    assert [developer.id for developer in result] == [306]
    assert fetch_batch.call_count == 2


def test_short_developer_page_ends_bulk_before_missing_detail_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    fetch_batch = Mock(
        return_value=_DeveloperApiBatch(items=[_raw_developer(306)], count=4735)
    )

    def detail_after_bulk(developer_id: int) -> Dict[str, Any]:
        assert fetch_batch.call_count == 1
        return _raw_developer(developer_id)

    read_detail = Mock(side_effect=detail_after_bulk)
    monkeypatch.setattr(client, "_fetch_developer_batch", fetch_batch)
    monkeypatch.setattr(client, "_read_detail_developer", read_detail)

    result = client.get_developers({306, 16750})

    assert [developer.id for developer in result] == [306, 16750]
    read_detail.assert_called_once_with(16750)


def test_missing_developer_fallback_waits_for_complete_bulk_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    first_page = [{"devId": 30000 + index} for index in range(1000)]
    fetch_batch = Mock(
        side_effect=[
            _DeveloperApiBatch(items=first_page, count=1001),
            _DeveloperApiBatch(items=[], count=1001),
        ]
    )

    def detail_after_all_pages(developer_id: int) -> Dict[str, Any]:
        assert fetch_batch.call_count == 2
        return _raw_developer(developer_id)

    read_detail = Mock(side_effect=detail_after_all_pages)
    monkeypatch.setattr(client, "_fetch_developer_batch", fetch_batch)
    monkeypatch.setattr(client, "_read_detail_developer", read_detail)

    result = client.get_developers({306})

    assert [developer.id for developer in result] == [306]
    read_detail.assert_called_once_with(306)


def test_identical_duplicate_developer_is_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    first_page = [{"devId": 40000 + index} for index in range(999)]
    first_page.append(_raw_developer(306))
    fetch_batch = Mock(
        side_effect=[
            _DeveloperApiBatch(items=first_page, count=1001),
            _DeveloperApiBatch(
                items=[_raw_developer(306), _raw_developer(16750)],
                count=1001,
            ),
        ]
    )
    monkeypatch.setattr(client, "_fetch_developer_batch", fetch_batch)
    monkeypatch.setattr(client, "_read_detail_developer", Mock())

    result = client.get_developers({306, 16750})

    assert [developer.id for developer in result] == [306, 16750]


def test_conflicting_duplicate_developer_is_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    first_page = [{"devId": 50000 + index} for index in range(999)]
    first_page.append(_raw_developer(306))
    conflicting_developer = _raw_developer(306)
    conflicting_developer["devEmail"] = "conflict@example.test"
    fetch_batch = Mock(
        side_effect=[
            _DeveloperApiBatch(items=first_page, count=1001),
            _DeveloperApiBatch(items=[conflicting_developer], count=1001),
        ]
    )
    monkeypatch.setattr(client, "_fetch_developer_batch", fetch_batch)

    with pytest.raises(NashDomClientError, match="различающиеся записи.*devId=306"):
        client.get_developers({16750})


def test_full_duplicate_page_without_progress_stops_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    page = [{"devId": 60000 + index} for index in range(1000)]
    fetch_batch = Mock(
        side_effect=[
            _DeveloperApiBatch(items=page, count=5000),
            _DeveloperApiBatch(items=page, count=5000),
        ]
    )
    read_detail = Mock(return_value=_raw_developer(306))
    monkeypatch.setattr(client, "_fetch_developer_batch", fetch_batch)
    monkeypatch.setattr(client, "_read_detail_developer", read_detail)

    result = client.get_developers({306})

    assert [developer.id for developer in result] == [306]
    assert fetch_batch.call_count == 2
    read_detail.assert_called_once_with(306)


def test_developer_api_url_has_confirmed_filters_and_pagination() -> None:
    result = NashDomClient._build_developers_api_url(  # pyright: ignore[reportPrivateUsage]
        offset=1000,
        limit=1000,
    )

    assert "/сервисы/api/erz/main/filter?" in result
    assert "offset=1000" in result
    assert "limit=1000" in result
    assert "sortField=devShortNm" in result
    assert "sortType=asc" in result
    assert "objStatus=0" in result


def test_developer_detail_url_uses_confirmed_nashdom_route() -> None:
    result = NashDomClient._build_developer_detail_url(  # pyright: ignore[reportPrivateUsage]
        306
    )

    assert result == (
        "https://xn--80az8a.xn--d1aqf.xn--p1ai/"
        "сервисы/единый-реестр-застройщиков/застройщик/306"
    )
    assert "/сервисы/единый-реестр-застройщиков/застройщик/306" in result
    assert "/developer/306" not in result


def test_open_developer_detail_uses_confirmed_nashdom_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, driver = _client()
    check_page = Mock()
    monkeypatch.setattr(client, "_raise_if_unavailable_developer_page", check_page)

    client._open_developer_detail(306)  # pyright: ignore[reportPrivateUsage]

    driver.get.assert_called_once_with(
        "https://xn--80az8a.xn--d1aqf.xn--p1ai/"
        "сервисы/единый-реестр-застройщиков/застройщик/306"
    )
    check_page.assert_called_once_with("застройщика 306")


@pytest.mark.parametrize(
    "body, expected_message",
    [
        ({"errcode": "1", "data": {}}, "errcode"),
        ({"errcode": "0", "data": []}, "объект data"),
        (
            {"errcode": "0", "data": {"developers": {}, "count": 1}},
            "data.developers",
        ),
        (
            {"errcode": "0", "data": {"developers": [], "count": -1}},
            "data.count",
        ),
        (
            {"errcode": "0", "data": {"developers": ["bad"], "count": 1}},
            "не объект JSON",
        ),
    ],
)
def test_malformed_developer_bulk_schema_is_client_error(
    body: Dict[str, Any],
    expected_message: str,
) -> None:
    client, driver = _client()
    driver.execute_async_script.return_value = {"status": 200, "body": body}

    with pytest.raises(NashDomClientError, match=expected_message):
        client._fetch_developer_batch(  # pyright: ignore[reportPrivateUsage]
            offset=0,
            limit=1000,
        )


@pytest.mark.parametrize("status", [429, 500, 503])
def test_developer_bulk_unavailable_http_is_unavailable(status: int) -> None:
    client, driver = _client()
    driver.execute_async_script.return_value = {"status": status, "body": {}}

    with pytest.raises(NashDomUnavailableError):
        client._fetch_developer_batch(  # pyright: ignore[reportPrivateUsage]
            offset=0,
            limit=1000,
        )


def test_developer_bulk_timeout_is_unavailable() -> None:
    client, driver = _client()
    driver.execute_async_script.side_effect = TimeoutException()

    with pytest.raises(NashDomUnavailableError):
        client._fetch_developer_batch(  # pyright: ignore[reportPrivateUsage]
            offset=0,
            limit=1000,
        )


def test_developer_bulk_http_200_challenge_is_unavailable() -> None:
    client, driver = _client()
    driver.execute_async_script.return_value = {
        "status": 200,
        "body": (
            "<!DOCTYPE html><noscript><meta http-equiv=\"refresh\" "
            "content=\"0; url=/challenge\"></noscript>"
        ),
    }

    with pytest.raises(NashDomUnavailableError, match="anti-bot/challenge"):
        client._fetch_developer_batch(  # pyright: ignore[reportPrivateUsage]
            offset=0,
            limit=1000,
        )


def test_developer_bulk_non_json_without_challenge_is_client_error() -> None:
    client, driver = _client()
    driver.execute_async_script.return_value = {
        "status": 200,
        "body": "plain malformed response",
    }

    with pytest.raises(NashDomClientError, match="не JSON-объект"):
        client._fetch_developer_batch(  # pyright: ignore[reportPrivateUsage]
            offset=0,
            limit=1000,
        )


def test_detail_ssr_extracts_confirmed_builder_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    raw_developer = _raw_developer(306)
    next_data = {
        "props": {
            "pageProps": {"statusCode": 200, "id": 306},
            "initialState": {"erz": {"builder": {"builder": raw_developer}}},
        }
    }
    open_detail = Mock()
    monkeypatch.setattr(client, "_open_developer_detail", open_detail)
    monkeypatch.setattr(
        client,
        "_read_developer_next_data",
        Mock(return_value=next_data),
    )

    result = client._read_detail_developer(306)  # pyright: ignore[reportPrivateUsage]

    assert result == raw_developer
    open_detail.assert_called_once_with(306)


def test_detail_ssr_rejects_mismatching_page_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    next_data = {
        "props": {
            "pageProps": {"id": 999},
            "initialState": {
                "erz": {"builder": {"builder": _raw_developer(306)}}
            },
        }
    }
    monkeypatch.setattr(client, "_open_developer_detail", Mock())
    monkeypatch.setattr(
        client,
        "_read_developer_next_data",
        Mock(return_value=next_data),
    )

    with pytest.raises(NashDomClientError, match="не соответствует"):
        client._read_detail_developer(306)  # pyright: ignore[reportPrivateUsage]


def test_detail_ssr_rejects_malformed_status_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    next_data = {
        "props": {
            "pageProps": {"statusCode": "200", "id": 306},
            "initialState": {
                "erz": {"builder": {"builder": _raw_developer(306)}}
            },
        }
    }
    monkeypatch.setattr(client, "_open_developer_detail", Mock())
    monkeypatch.setattr(
        client,
        "_read_developer_next_data",
        Mock(return_value=next_data),
    )

    with pytest.raises(NashDomClientError, match="statusCode.*неверный тип"):
        client._read_detail_developer(306)  # pyright: ignore[reportPrivateUsage]


def test_detail_ssr_unavailable_status_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    next_data = {
        "props": {
            "pageProps": {"statusCode": 503, "id": 306},
            "initialState": {
                "erz": {"builder": {"builder": _raw_developer(306)}}
            },
        }
    }
    monkeypatch.setattr(client, "_open_developer_detail", Mock())
    monkeypatch.setattr(
        client,
        "_read_developer_next_data",
        Mock(return_value=next_data),
    )

    with pytest.raises(NashDomUnavailableError):
        client._read_detail_developer(306)  # pyright: ignore[reportPrivateUsage]


def test_detail_ssr_rejects_mismatching_builder_developer_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client()
    next_data = {
        "props": {
            "pageProps": {"id": 306},
            "initialState": {
                "erz": {"builder": {"builder": _raw_developer(999)}}
            },
        }
    }
    monkeypatch.setattr(client, "_open_developer_detail", Mock())
    monkeypatch.setattr(
        client,
        "_read_developer_next_data",
        Mock(return_value=next_data),
    )

    with pytest.raises(NashDomClientError, match="devId=999 вместо 306"):
        client._read_detail_developer(306)  # pyright: ignore[reportPrivateUsage]
