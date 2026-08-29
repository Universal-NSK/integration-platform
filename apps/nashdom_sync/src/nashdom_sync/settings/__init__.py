"""Настройки синхронизации NashDom."""

from nashdom_sync.settings.exceptions import (
    ConfigurationError,
    ConfigurationOverlapError,
)
from nashdom_sync.settings.models import BrowserSettings, SyncSettings
from nashdom_sync.settings.provider import SettingsProvider

__all__ = [
    "BrowserSettings",
    "ConfigurationError",
    "ConfigurationOverlapError",
    "SettingsProvider",
    "SyncSettings",
]
