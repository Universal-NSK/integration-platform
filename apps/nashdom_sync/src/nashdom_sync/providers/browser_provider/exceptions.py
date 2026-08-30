from pathlib import Path


class BrowserProviderError(Exception):
    """Ошибка создания браузера."""


class BrowserBinaryNotFoundError(BrowserProviderError):
    """Файл браузера отсутствует."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Не найден файл браузера: {path}")


class DriverBinaryNotFoundError(BrowserProviderError):
    """Файл ChromeDriver отсутствует."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Не найден файл ChromeDriver: {path}")


class BrowserLaunchError(BrowserProviderError):
    """Selenium не смог создать браузерную сессию."""

    def __init__(self, browser_path: Path, driver_path: Path) -> None:
        super().__init__(
            "Не удалось запустить Chrome через ChromeDriver: "
            f"browser_path={browser_path}, driver_path={driver_path}"
        )
