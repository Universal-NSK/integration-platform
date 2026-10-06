from typing import Protocol, cast

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.remote.webdriver import WebDriver

from nashdom_sync.contracts import BrowserSettings
from nashdom_sync.providers.browser_provider.exceptions import (
    BrowserBinaryNotFoundError,
    BrowserLaunchError,
    DriverBinaryNotFoundError,
)

_BACKGROUND_ARGUMENTS = (
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--no-first-run",
)
_HEADLESS_ARGUMENT = "--headless=new"


class _MutableChromeOptions(Protocol):
    binary_location: str
    page_load_strategy: str

    def add_experimental_option(self, name: str, value: object) -> None: ...

    def add_argument(self, argument: str) -> None: ...


class BrowserProvider:
    """Создаёт WebDriver по проверенным настройкам браузера."""

    def provide(self, settings: BrowserSettings) -> WebDriver:
        """Проверить бинарники и вернуть готовый WebDriver."""
        if not settings.browser_path.is_file():
            raise BrowserBinaryNotFoundError(settings.browser_path)

        if not settings.driver_path.is_file():
            raise DriverBinaryNotFoundError(settings.driver_path)

        options = self._build_options(settings)
        service = Service(executable_path=str(settings.driver_path))

        try:
            driver = webdriver.Chrome(service=service, options=options)
        except WebDriverException as exc:
            raise BrowserLaunchError(settings.browser_path, settings.driver_path) from exc

        try:
            driver.set_page_load_timeout(settings.page_load_timeout_seconds)
            driver.set_script_timeout(settings.script_timeout_seconds)
        except Exception as exc:
            try:
                driver.quit()
            except Exception:
                pass
            raise BrowserLaunchError(settings.browser_path, settings.driver_path) from exc
        return driver

    @staticmethod
    def _build_options(settings: BrowserSettings) -> Options:
        options = Options()
        mutable_options = cast(_MutableChromeOptions, options)
        mutable_options.binary_location = str(settings.browser_path)
        mutable_options.page_load_strategy = settings.page_load_strategy
        mutable_options.add_argument(
            f"--window-size={settings.window_width},{settings.window_height}"
        )
        for argument in _BACKGROUND_ARGUMENTS:
            mutable_options.add_argument(argument)
        if settings.disable_images:
            mutable_options.add_experimental_option(
                "prefs", {"profile.managed_default_content_settings.images": 2}
            )

        if settings.headless:
            mutable_options.add_argument(_HEADLESS_ARGUMENT)

        return options
