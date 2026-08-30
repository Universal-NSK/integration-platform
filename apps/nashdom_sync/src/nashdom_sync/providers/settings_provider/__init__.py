"""Настройки синхронизации NashDom."""

from nashdom_sync.providers.settings_provider.exceptions import (
    ConfigurationError,
    ConfigurationOverlapError,
)
from nashdom_sync.providers.settings_provider.provider import SettingsProvider

__all__ = [
    "ConfigurationError",
    "ConfigurationOverlapError",
    "SettingsProvider",
]
