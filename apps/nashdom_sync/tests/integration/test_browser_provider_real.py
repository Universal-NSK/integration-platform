import os
from pathlib import Path
from typing import Optional, Protocol, cast

import pytest
from nashdom_sync.contracts import BrowserSettings
from nashdom_sync.providers.browser_provider import BrowserProvider
from nashdom_sync.providers.settings_provider import ConfigurationError, SettingsProvider
from runtime_files import RuntimePaths

_RUN_ENV = "NASHDOM_RUN_BROWSER_TEST"
_BROWSER_PATH_ENV = "NASHDOM_BROWSER_PATH"
_DRIVER_PATH_ENV = "NASHDOM_DRIVER_PATH"


class _DriverSession(Protocol):
    session_id: Optional[str]


def _real_browser_settings() -> BrowserSettings:
    if os.environ.get(_RUN_ENV) != "1":
        pytest.skip(f"Для реального запуска установите {_RUN_ENV}=1")

    browser_path = os.environ.get(_BROWSER_PATH_ENV)
    driver_path = os.environ.get(_DRIVER_PATH_ENV)

    if browser_path and driver_path:
        return BrowserSettings(
            headless=True,
            browser_path=Path(browser_path),
            driver_path=Path(driver_path),
        )

    if browser_path or driver_path:
        pytest.skip(f"Нужно задать обе переменные {_BROWSER_PATH_ENV} и {_DRIVER_PATH_ENV}")

    paths = RuntimePaths.from_project(Path(__file__))
    try:
        return SettingsProvider(paths).provide().browser
    except ConfigurationError as exc:
        pytest.skip(f"Не удалось получить BrowserSettings из runtime-конфигурации: {exc}")


@pytest.mark.browser
def test_real_browser_session() -> None:
    settings = _real_browser_settings()
    driver = BrowserProvider().provide(settings)

    try:
        assert cast(_DriverSession, driver).session_id is not None
        driver.get("about:blank")
        assert driver.current_url == "about:blank"
    finally:
        driver.quit()
