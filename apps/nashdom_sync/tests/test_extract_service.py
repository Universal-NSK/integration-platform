from datetime import date
from typing import cast
from unittest.mock import Mock

import nashdom_sync.extract.service as service_module
import pytest
from nashdom_sync.contracts import (
    CommissioningPeriod,
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


def test_extract_runs_object_stage_but_does_not_return_false_full_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    client.get_objects.return_value = [_object()]
    client_type = Mock(return_value=client)
    monkeypatch.setattr(service_module, "NashDomClient", client_type)
    driver_mock = Mock()
    driver = cast(WebDriver, driver_mock)

    with pytest.raises(NotImplementedError, match="застройщиков и групп компаний"):
        ExtractService().extract(driver, _settings())

    client_type.assert_called_once_with(driver)
    client.get_objects.assert_called_once_with(_settings().nashdom)
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
