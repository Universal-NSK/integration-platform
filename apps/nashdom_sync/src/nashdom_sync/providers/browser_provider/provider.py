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

_WINDOW_SIZE_ARGUMENT = "--window-size=1920,1080"
_HEADLESS_ARGUMENT = "--headless=new"


class _MutableChromeOptions(Protocol):
    binary_location: str

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
            return webdriver.Chrome(service=service, options=options)
        except WebDriverException as exc:
            raise BrowserLaunchError(settings.browser_path, settings.driver_path) from exc

    @staticmethod
    def _build_options(settings: BrowserSettings) -> Options:
        options = Options()
        mutable_options = cast(_MutableChromeOptions, options)
        mutable_options.binary_location = str(settings.browser_path)
        mutable_options.add_argument(_WINDOW_SIZE_ARGUMENT)

        if settings.headless:
            mutable_options.add_argument(_HEADLESS_ARGUMENT)

        return options
