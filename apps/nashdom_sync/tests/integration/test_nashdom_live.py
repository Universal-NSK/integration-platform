import os
from pathlib import Path
from typing import List

import pytest
from nashdom_sync.contracts import (
    BrowserSettings,
    ExtractedObject,
    NashDomExtractSettings,
    NashDomRegion,
)
from nashdom_sync.extract import NashDomClient, NashDomUnavailableError, SourceDataValidator
from nashdom_sync.providers.browser_provider import BrowserProvider
from nashdom_sync.providers.settings_provider import ConfigurationError, SettingsProvider
from runtime_files import RuntimePaths

_RUN_ENV = "NASHDOM_RUN_LIVE_TEST"
_BROWSER_PATH_ENV = "NASHDOM_BROWSER_PATH"
_DRIVER_PATH_ENV = "NASHDOM_DRIVER_PATH"
_RESEARCH_REGION = NashDomRegion(
    code=22,
    name="Алтайский край",
    slug="алтайский-край",
)


def _live_browser_settings() -> BrowserSettings:
    if os.environ.get(_RUN_ENV) != "1":
        pytest.skip(f"Для live-запуска установите {_RUN_ENV}=1")

    browser_path = os.environ.get(_BROWSER_PATH_ENV)
    driver_path = os.environ.get(_DRIVER_PATH_ENV)
    if browser_path and driver_path:
        return BrowserSettings(
            headless=False,
            browser_path=Path(browser_path),
            driver_path=Path(driver_path),
        )
    if browser_path or driver_path:
        pytest.skip(f"Нужно задать обе переменные {_BROWSER_PATH_ENV} и {_DRIVER_PATH_ENV}")

    paths = RuntimePaths.from_project(Path(__file__))
    try:
        return SettingsProvider(paths).provide().browser
    except ConfigurationError as exc:
        pytest.skip(f"Не удалось получить BrowserSettings: {exc}")


def _live_objects(target_count: int) -> List[ExtractedObject]:
    settings = NashDomExtractSettings(
        objects_to_parse_count=target_count,
        regions=(_RESEARCH_REGION,),
    )
    driver = BrowserProvider().provide(_live_browser_settings())

    try:
        try:
            objects = NashDomClient(driver).get_objects(settings)
        except NashDomUnavailableError as exc:
            pytest.skip(f"наш.дом.рф временно недоступен: {exc}")

        SourceDataValidator().validate_objects(objects, {_RESEARCH_REGION.code})
        return objects
    finally:
        driver.quit()


@pytest.mark.browser
@pytest.mark.nashdom_live
def test_live_ssr_path_returns_typed_objects() -> None:
    limit = 3
    objects = _live_objects(limit)
    if not objects:
        pytest.skip("В исследуемом регионе сейчас нет строящихся объектов")
    if len(objects) < limit:
        pytest.skip("В исследуемом регионе недостаточно объектов для проверки SSR limit")

    assert len(objects) == limit
    assert all(isinstance(extracted_object, ExtractedObject) for extracted_object in objects)
    assert all(extracted_object.region_id == _RESEARCH_REGION.code for extracted_object in objects)


@pytest.mark.browser
@pytest.mark.nashdom_live
def test_live_xhr_path_returns_typed_objects() -> None:
    limit = 25
    objects = _live_objects(limit)
    if not objects:
        pytest.skip("В исследуемом регионе сейчас нет строящихся объектов")
    if len(objects) <= 20:
        pytest.skip(
            "В исследуемом регионе сейчас недостаточно объектов для проверки XHR-ветки"
        )

    assert 21 <= len(objects) <= limit
    assert all(isinstance(extracted_object, ExtractedObject) for extracted_object in objects)
    assert all(extracted_object.region_id == _RESEARCH_REGION.code for extracted_object in objects)
