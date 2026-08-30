from typing import Any, Dict, Tuple, cast
from unittest.mock import Mock

import pytest
from nashdom_sync.contracts import NashDomExtractSettings, NashDomRegion
from nashdom_sync.extract import NashDomClientError, NashDomUnavailableError
from nashdom_sync.extract.nashdom.client import (
    NashDomClient,
    _ApiBatch,  # pyright: ignore[reportPrivateUsage]
    _CapturedRequest,  # pyright: ignore[reportPrivateUsage]
)
from selenium.common.exceptions import WebDriverException
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
    return NashDomClient(cast(WebDriver, driver)), driver


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
