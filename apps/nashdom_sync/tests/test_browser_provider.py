from pathlib import Path
from typing import Any, Dict, List, Protocol, cast
from unittest.mock import Mock

import pytest
from nashdom_sync.contracts import BrowserSettings
from nashdom_sync.providers.browser_provider import (
    BrowserBinaryNotFoundError,
    BrowserLaunchError,
    BrowserProvider,
    BrowserProviderError,
    DriverBinaryNotFoundError,
)
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


class _OptionsArguments(Protocol):
    arguments: List[str]


def _settings(
    tmp_path: Path,
    *,
    headless: bool = False,
    browser_exists: bool = True,
    driver_exists: bool = True,
) -> BrowserSettings:
    browser_path = tmp_path / "chrome.exe"
    driver_path = tmp_path / "chromedriver.exe"

    if browser_exists:
        browser_path.touch()
    if driver_exists:
        driver_path.touch()

    return BrowserSettings(
        page_load_timeout_seconds=120.0,
        script_timeout_seconds=60.0,
        page_load_strategy="eager",
        disable_images=True,
        window_width=1280,
        window_height=720,
        headless=headless,
        browser_path=browser_path,
        driver_path=driver_path,
    )


def _capture_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    headless: bool,
) -> Options:
    chrome = Mock(return_value=Mock())
    monkeypatch.setattr(webdriver, "Chrome", chrome)

    BrowserProvider().provide(_settings(tmp_path, headless=headless))

    return cast(Options, chrome.call_args.kwargs["options"])


def _arguments(options: Options) -> List[str]:
    return cast(_OptionsArguments, options).arguments


def test_missing_browser_binary_stops_before_selenium(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chrome = Mock()
    monkeypatch.setattr(webdriver, "Chrome", chrome)
    settings = _settings(tmp_path, browser_exists=False)

    with pytest.raises(BrowserBinaryNotFoundError) as exc_info:
        BrowserProvider().provide(settings)

    assert str(settings.browser_path) in str(exc_info.value)
    chrome.assert_not_called()


def test_missing_driver_binary_stops_before_selenium(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chrome = Mock()
    monkeypatch.setattr(webdriver, "Chrome", chrome)
    settings = _settings(tmp_path, driver_exists=False)

    with pytest.raises(DriverBinaryNotFoundError) as exc_info:
        BrowserProvider().provide(settings)

    assert str(settings.driver_path) in str(exc_info.value)
    chrome.assert_not_called()


def test_provide_configures_service_and_returns_exact_driver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_driver = Mock()
    chrome = Mock(return_value=fake_driver)
    monkeypatch.setattr(webdriver, "Chrome", chrome)
    settings = _settings(tmp_path)

    result = BrowserProvider().provide(settings)

    chrome.assert_called_once()
    service = cast(Service, chrome.call_args.kwargs["service"])
    options = cast(Options, chrome.call_args.kwargs["options"])
    assert service.path == str(settings.driver_path)
    assert options.binary_location == str(settings.browser_path)
    assert result is fake_driver


def test_headless_false_does_not_add_headless_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _capture_options(tmp_path, monkeypatch, headless=False)

    assert not any(argument.startswith("--headless") for argument in _arguments(options))


def test_headless_true_adds_chrome_109_compatible_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _capture_options(tmp_path, monkeypatch, headless=True)

    assert "--headless=new" in _arguments(options)


def test_options_contain_stable_window_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _capture_options(tmp_path, monkeypatch, headless=False)

    assert "--window-size=1280,720" in _arguments(options)


def test_selenium_launch_error_is_wrapped_with_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selenium_error = WebDriverException("session not created")
    monkeypatch.setattr(
        webdriver,
        "Chrome",
        Mock(side_effect=selenium_error),
    )

    with pytest.raises(BrowserLaunchError) as exc_info:
        BrowserProvider().provide(_settings(tmp_path))

    assert exc_info.value.__cause__ is selenium_error


def test_provider_exception_hierarchy() -> None:
    assert issubclass(BrowserBinaryNotFoundError, BrowserProviderError)
    assert issubclass(DriverBinaryNotFoundError, BrowserProviderError)
    assert issubclass(BrowserLaunchError, BrowserProviderError)


def test_runtime_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    options = _capture_options(tmp_path, monkeypatch, headless=False)
    capabilities = cast(Dict[str, Any], options.to_capabilities())  # pyright: ignore[reportUnknownMemberType]
    assert capabilities["pageLoadStrategy"] == "eager"
    assert capabilities["goog:chromeOptions"]["prefs"] == {
        "profile.managed_default_content_settings.images": 2
    }
    arguments = _arguments(options)
    for flag in (
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--no-first-run",
    ):
        assert flag in arguments
    for flag in (
        "--single-process",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-web-security",
        "--disable-gpu",
        "--disable-javascript",
    ):
        assert flag not in arguments
    assert "javascript" not in str(capabilities).lower()


def test_images_enabled_and_custom_viewport(tmp_path: Path) -> None:
    settings = _settings(tmp_path).copy(
        update={"disable_images": False, "window_width": 800, "window_height": 600}
    )
    options = BrowserProvider._build_options(settings)  # pyright: ignore[reportPrivateUsage]
    assert "--window-size=800,600" in _arguments(options)
    capabilities = cast(Dict[str, Any], options.to_capabilities())  # pyright: ignore[reportUnknownMemberType]
    assert "prefs" not in capabilities["goog:chromeOptions"]


def test_provider_sets_timeouts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    driver = Mock()
    monkeypatch.setattr(webdriver, "Chrome", Mock(return_value=driver))
    BrowserProvider().provide(_settings(tmp_path))
    driver.set_page_load_timeout.assert_called_once_with(120.0)
    driver.set_script_timeout.assert_called_once_with(60.0)


@pytest.mark.parametrize("method", ["set_page_load_timeout", "set_script_timeout"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_timeout_setup_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, cleanup_fails: bool
) -> None:
    driver = Mock()
    primary = WebDriverException("timeout setup failed")
    getattr(driver, method).side_effect = primary
    if cleanup_fails:
        driver.quit.side_effect = RuntimeError("cleanup failed")
    monkeypatch.setattr(webdriver, "Chrome", Mock(return_value=driver))
    with pytest.raises(BrowserLaunchError) as error:
        BrowserProvider().provide(_settings(tmp_path))
    assert error.value.__cause__ is primary
    driver.quit.assert_called_once_with()
