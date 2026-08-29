from pathlib import Path

from pydantic import BaseModel, StrictBool


class _StrictSettingsModel(BaseModel):
    class Config:
        extra = "forbid"


class BrowserSettings(_StrictSettingsModel):
    """Настройки запуска браузера для синхронизации."""

    headless: StrictBool
    browser_path: Path
    driver_path: Path


class SyncSettings(_StrictSettingsModel):
    """Единая проверенная конфигурация синхронизации."""

    browser: BrowserSettings
