import logging
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
from nashdom_sync.providers.browser_provider import provider as module
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


@pytest.fixture(autouse=True)
def no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "sleep", Mock())


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
        launch_max_attempts=3,
        launch_retry_delay_seconds=10.0,
        extract_session_max_attempts=2,
        extract_session_retry_delay_seconds=10.0,
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
    assert driver.quit.call_count == 3


@pytest.mark.parametrize("failures", [0, 1, 3])
def test_launch_attempts_and_safe_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failures: int,
) -> None:
    services = [Mock() for _ in range(3)]
    service = Mock(side_effect=services)
    primary = WebDriverException("SECRET launch payload")
    driver = Mock()
    chrome = Mock(side_effect=[primary] * failures + [driver])
    pause = Mock()
    event = Mock()
    monkeypatch.setattr(module, "Service", service)
    monkeypatch.setattr(webdriver, "Chrome", chrome)
    monkeypatch.setattr(module, "sleep", pause)
    monkeypatch.setattr(module, "perf_counter", Mock(side_effect=[10.0, 12.0, 15.0, 19.0]))
    monkeypatch.setattr(module, "log_event", event)
    settings = _settings(tmp_path)
    if failures == 3:
        with pytest.raises(BrowserLaunchError) as caught:
            BrowserProvider().provide(settings)
        assert caught.value.__cause__ is primary
    else:
        assert BrowserProvider().provide(settings) is driver
    attempts = min(failures + 1, 3)
    assert chrome.call_count == service.call_count == attempts
    assert pause.call_count == min(failures, 2)
    assert [call.kwargs["service"] for call in chrome.call_args_list] == services[:attempts]
    for previous in services[:failures]:
        previous.stop.assert_called_once_with()
    for call in pause.call_args_list:
        assert call.args == (10.0,)
    retries = [call for call in event.call_args_list if call.args[2] == "browser_launch_retry"]
    assert len(retries) == min(failures, 2)
    for attempt, call in enumerate(retries, 1):
        assert call.kwargs == dict(
            attempt=attempt,
            max_attempts=3,
            retry_delay_seconds=10.0,
            reason="creation_failed",
        )
    started = [call for call in event.call_args_list if call.args[2] == "browser_started"]
    assert len(started) == int(failures < 3)
    if started:
        assert started[0].args[1] == logging.INFO
        assert started[0].kwargs == dict(
            attempt=attempts, duration_seconds=2.0 if failures == 0 else 3.0
        )
    assert "SECRET" not in str(event.call_args_list)


@pytest.mark.parametrize("method", ["set_page_load_timeout", "set_script_timeout"])
def test_initialization_retry_cleans_driver_and_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    first, second = Mock(), Mock()
    services = [Mock(), Mock()]
    getattr(first, method).side_effect = RuntimeError("SECRET initialization")
    first.quit.side_effect = RuntimeError("SECRET cleanup")
    services[0].stop.side_effect = RuntimeError("SECRET service cleanup")
    monkeypatch.setattr(module, "Service", Mock(side_effect=services))
    chrome = Mock(side_effect=[first, second])
    monkeypatch.setattr(webdriver, "Chrome", chrome)
    assert BrowserProvider().provide(_settings(tmp_path)) is second
    assert chrome.call_count == 2
    first.quit.assert_called_once_with()
    services[0].stop.assert_called_once_with()
    second.quit.assert_not_called()
    services[1].stop.assert_not_called()


def test_last_primary_survives_both_cleanup_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver, service = Mock(), Mock()
    primary = RuntimeError("primary")
    driver.set_page_load_timeout.side_effect = primary
    driver.quit.side_effect = ValueError("quit")
    service.stop.side_effect = ValueError("stop")
    monkeypatch.setattr(module, "Service", Mock(return_value=service))
    monkeypatch.setattr(webdriver, "Chrome", Mock(return_value=driver))
    with pytest.raises(BrowserLaunchError) as caught:
        BrowserProvider().provide(_settings(tmp_path))
    assert caught.value.__cause__ is primary
    assert driver.quit.call_count == service.stop.call_count == 3
