"""Создание Chrome WebDriver для NashDom Sync."""

from nashdom_sync.providers.browser_provider.exceptions import (
    BrowserBinaryNotFoundError,
    BrowserLaunchError,
    BrowserProviderError,
    DriverBinaryNotFoundError,
)
from nashdom_sync.providers.browser_provider.provider import BrowserProvider

__all__ = [
    "BrowserBinaryNotFoundError",
    "BrowserLaunchError",
    "BrowserProvider",
    "BrowserProviderError",
    "DriverBinaryNotFoundError",
]
