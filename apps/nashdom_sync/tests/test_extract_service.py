from dataclasses import replace
from datetime import date
from typing import List, Optional, Sequence, Set, cast
from unittest.mock import Mock

import nashdom_sync.extract.service as service_module
import pytest
from nashdom_sync.contracts import (
    CommissioningPeriod,
    ExtractedCompanyGroup,
    ExtractedDeveloper,
    ExtractedObject,
    ExtractedObjectTypeEnum,
    ExtractionSettings,
    NashDomExtractSettings,
    NashDomRegion,
)
from nashdom_sync.extract import ExtractService, SourceDataValidationError
from selenium.webdriver.remote.webdriver import WebDriver


def _settings() -> ExtractionSettings:
    return ExtractionSettings(
        nashdom=NashDomExtractSettings(
            objects_to_parse_count=5,
            regions=(
                NashDomRegion(
                    code=22,
                    name="Алтайский край",
                    slug="алтайский-край",
                ),
            ),
        )
    )


def _object(region_id: int = 22) -> ExtractedObject:
    return ExtractedObject(
        id=1,
        title="Объект",
        address="Город Барнаул",
        region_id=region_id,
        publication_date=date(2026, 8, 21),
        commissioning_period=CommissioningPeriod(2028, 4),
        object_type=ExtractedObjectTypeEnum.RESIDENTIAL,
        developer_id=100,
        company_group_id=None,
    )


def _developer(
    developer_id: int = 100,
    company_group_id: Optional[int] = None,
) -> ExtractedDeveloper:
    return ExtractedDeveloper(
        id=developer_id,
        short_name="Застройщик",
        full_name="Полное имя застройщика",
        inn="7701651356",
        kpp="720301001",
        ogrn="1067746424899",
        region_id=72,
        legal_address="Юридический адрес",
        fact_address="Фактический адрес",
        contact_name="Иванов Иван Иванович",
        phone="+70000000000",
        email="developer@example.test",
        url=None,
        company_group_id=company_group_id,
    )


def _company_group(company_group_id: int = 5776) -> ExtractedCompanyGroup:
    return ExtractedCompanyGroup(
        id=company_group_id,
        name=f"Группа компаний {company_group_id}",
    )


def test_extract_returns_full_typed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    client.get_objects.return_value = [_object()]
    client.get_developers.return_value = [_developer()]
    client.get_company_groups.return_value = []
    client_type = Mock(return_value=client)
    monkeypatch.setattr(service_module, "NashDomClient", client_type)
    driver_mock = Mock()
    driver = cast(WebDriver, driver_mock)

    result = ExtractService().extract(driver, _settings())

    client_type.assert_called_once_with(driver)
    client.get_objects.assert_called_once_with(_settings().nashdom)
    client.get_developers.assert_called_once_with({100})
    client.get_company_groups.assert_called_once_with(set())
    assert result.objects == [_object()]
    assert result.developers == [_developer()]
    assert result.company_groups == []
    assert isinstance(result.objects[0], ExtractedObject)
    assert isinstance(result.developers[0], ExtractedDeveloper)
    driver_mock.quit.assert_not_called()


def test_extract_validates_objects_before_unimplemented_later_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    client.get_objects.return_value = [_object(region_id=54)]
    monkeypatch.setattr(service_module, "NashDomClient", Mock(return_value=client))

    with pytest.raises(SourceDataValidationError, match="незапрошенных регионов: 54"):
        ExtractService().extract(cast(WebDriver, Mock()), _settings())


def test_collect_developer_ids_returns_unique_ids() -> None:
    objects = [_object(), _object()]

    result = ExtractService._collect_developer_ids(  # pyright: ignore[reportPrivateUsage]
        objects
    )

    assert result == {100}


def test_extract_runs_all_validation_stages_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: List[str] = []
    client = Mock()
    validator = Mock()

    def get_objects(settings: NashDomExtractSettings) -> List[ExtractedObject]:
        events.append("get_objects")
        return [_object()]

    def validate_objects(
        objects: Sequence[ExtractedObject],
        regions: Set[int],
    ) -> None:
        events.append("validate_objects")

    def get_developers(ids: Set[int]) -> List[ExtractedDeveloper]:
        events.append("get_developers")
        return [_developer()]

    def validate_developers(
        developers: Sequence[ExtractedDeveloper],
        ids: Set[int],
    ) -> None:
        events.append("validate_developers")

    def validate_consistency(
        objects: Sequence[ExtractedObject],
        developers: Sequence[ExtractedDeveloper],
    ) -> None:
        events.append("validate_consistency")

    def get_company_groups(ids: Set[int]) -> List[ExtractedCompanyGroup]:
        events.append("get_company_groups")
        return []

    def validate_company_groups(
        company_groups: Sequence[ExtractedCompanyGroup],
        ids: Set[int],
    ) -> None:
        events.append("validate_company_groups")

    client.get_objects.side_effect = get_objects
    validator.validate_objects.side_effect = validate_objects
    client.get_developers.side_effect = get_developers
    validator.validate_developers.side_effect = validate_developers
    validator.validate_company_group_consistency.side_effect = validate_consistency
    client.get_company_groups.side_effect = get_company_groups
    validator.validate_company_groups.side_effect = validate_company_groups
    monkeypatch.setattr(service_module, "NashDomClient", Mock(return_value=client))
    monkeypatch.setattr(
        service_module,
        "SourceDataValidator",
        Mock(return_value=validator),
    )

    result = ExtractService().extract(cast(WebDriver, Mock()), _settings())

    assert events == [
        "get_objects",
        "validate_objects",
        "get_developers",
        "validate_developers",
        "validate_consistency",
        "get_company_groups",
        "validate_company_groups",
    ]
    assert result.company_groups == []


def test_developer_validation_failure_stops_before_consistency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    validator = Mock()
    client.get_objects.return_value = [_object()]
    client.get_developers.return_value = [_developer()]
    validator.validate_developers.side_effect = SourceDataValidationError("broken")
    monkeypatch.setattr(service_module, "NashDomClient", Mock(return_value=client))
    monkeypatch.setattr(
        service_module,
        "SourceDataValidator",
        Mock(return_value=validator),
    )

    with pytest.raises(SourceDataValidationError, match="broken"):
        ExtractService().extract(cast(WebDriver, Mock()), _settings())

    validator.validate_company_group_consistency.assert_not_called()
    client.get_company_groups.assert_not_called()


def test_collect_company_group_ids_unions_object_and_developer_sources() -> None:
    objects = [
        _object(),
        replace(_object(), id=2, company_group_id=5776),
    ]
    developers = [_developer(company_group_id=9999)]

    result = ExtractService._collect_company_group_ids(  # pyright: ignore[reportPrivateUsage]
        objects,
        developers,
    )

    assert result == {5776, 9999}


def test_extract_requests_union_company_group_ids_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    client.get_objects.return_value = [
        replace(_object(), company_group_id=5776),
        replace(_object(), id=2, developer_id=200, company_group_id=6442),
    ]
    client.get_developers.return_value = [
        _developer(company_group_id=5776),
        _developer(developer_id=200, company_group_id=6442),
    ]
    client.get_company_groups.return_value = [_company_group(5776), _company_group(6442)]
    monkeypatch.setattr(service_module, "NashDomClient", Mock(return_value=client))

    result = ExtractService().extract(cast(WebDriver, Mock()), _settings())

    client.get_company_groups.assert_called_once_with({5776, 6442})
    assert {company_group.id for company_group in result.company_groups} == {5776, 6442}
