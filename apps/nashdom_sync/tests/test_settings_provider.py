from pathlib import Path
from typing import Optional, Tuple

import pytest
import tomli
from nashdom_sync.settings import (
    BrowserSettings,
    ConfigurationError,
    ConfigurationOverlapError,
    SettingsProvider,
    SyncSettings,
)
from nashdom_sync.settings.provider import (
    _merge_settings,  # pyright: ignore[reportPrivateUsage]
)
from pydantic import ValidationError
from runtime_files import RuntimePaths

VALID_APP_CONFIG = """
[browser]
headless = false
""".strip()

VALID_PATHS_CONFIG = """
[browser]
browser_path = "drivers/chrome/chrome-win/chrome.exe"
driver_path = "drivers/chrome/chromedriver_win32/chromedriver.exe"
""".strip()


def _provider(
    tmp_path: Path,
    app_config: Optional[str] = VALID_APP_CONFIG,
    paths_config: Optional[str] = VALID_PATHS_CONFIG,
) -> Tuple[SettingsProvider, Path]:
    repo_root = (tmp_path / "repository").resolve()
    config_root = repo_root / "config"
    program_data_root = (tmp_path / "program-data").resolve()
    config_root.mkdir(parents=True)
    program_data_root.mkdir()

    if app_config is not None:
        (config_root / "sync.toml").write_text(app_config, encoding="utf-8")
    if paths_config is not None:
        (program_data_root / "sync.paths.toml").write_text(
            paths_config,
            encoding="utf-8",
        )

    paths = RuntimePaths(
        repo_root=repo_root,
        program_data_root=program_data_root,
    )
    return SettingsProvider(paths), program_data_root


def test_provide_merges_sources_and_resolves_nonexistent_browser_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, program_data_root = _provider(tmp_path)
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    settings = provider.provide()

    expected_browser_path = program_data_root / "drivers" / "chrome" / "chrome-win" / "chrome.exe"
    expected_driver_path = (
        program_data_root / "drivers" / "chrome" / "chromedriver_win32" / "chromedriver.exe"
    )
    assert isinstance(settings, SyncSettings)
    assert isinstance(settings.browser, BrowserSettings)
    assert settings.browser.headless is False
    assert settings.browser.browser_path == expected_browser_path
    assert settings.browser.driver_path == expected_driver_path
    assert not expected_browser_path.exists()
    assert not expected_driver_path.exists()


def test_provide_rejects_overlap_without_silent_override(tmp_path: Path) -> None:
    provider, _ = _provider(
        tmp_path,
        paths_config="""
[browser]
headless = true
browser_path = "drivers/chrome.exe"
driver_path = "drivers/chromedriver.exe"
""".strip(),
    )

    with pytest.raises(ConfigurationOverlapError) as exc_info:
        provider.provide()

    assert "Параметр browser.headless определён одновременно" in str(exc_info.value)
    assert "sync.toml" in str(exc_info.value)
    assert "sync.paths.toml" in str(exc_info.value)


@pytest.mark.parametrize("missing_source", ["sync.toml", "sync.paths.toml"])
def test_provide_reports_missing_configuration_file(
    tmp_path: Path,
    missing_source: str,
) -> None:
    provider, _ = _provider(
        tmp_path,
        app_config=None if missing_source == "sync.toml" else VALID_APP_CONFIG,
        paths_config=None if missing_source == "sync.paths.toml" else VALID_PATHS_CONFIG,
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "Не найден файл конфигурации синхронизации" in str(exc_info.value)
    assert missing_source in str(exc_info.value)


@pytest.mark.parametrize("invalid_source", ["sync.toml", "sync.paths.toml"])
def test_provide_wraps_invalid_toml_with_parser_cause(
    tmp_path: Path,
    invalid_source: str,
) -> None:
    invalid_toml = "[browser\nheadless = false"
    provider, _ = _provider(
        tmp_path,
        app_config=invalid_toml if invalid_source == "sync.toml" else VALID_APP_CONFIG,
        paths_config=(invalid_toml if invalid_source == "sync.paths.toml" else VALID_PATHS_CONFIG),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "Не удалось прочитать TOML-файл настроек" in str(exc_info.value)
    assert invalid_source in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, tomli.TOMLDecodeError)


def test_provide_wraps_missing_required_parameter_validation(tmp_path: Path) -> None:
    provider, _ = _provider(
        tmp_path,
        paths_config="""
[browser]
browser_path = "drivers/chrome.exe"
""".strip(),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "не прошла валидацию" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert "driver_path" in str(exc_info.value)


def test_provide_requires_strict_boolean(tmp_path: Path) -> None:
    provider, _ = _provider(
        tmp_path,
        app_config='[browser]\nheadless = "false"',
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert "headless" in str(exc_info.value)


def test_provide_forbids_unknown_fields(tmp_path: Path) -> None:
    provider, _ = _provider(
        tmp_path,
        app_config="""
[browser]
headless = false
headles = false
""".strip(),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert "headles" in str(exc_info.value)
    assert "extra fields not permitted" in str(exc_info.value)


def test_provide_rejects_absolute_machine_path(tmp_path: Path) -> None:
    absolute_path = (tmp_path / "outside" / "chrome.exe").resolve().as_posix()
    provider, _ = _provider(
        tmp_path,
        paths_config=f"""
[browser]
browser_path = "{absolute_path}"
driver_path = "drivers/chromedriver.exe"
""".strip(),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "Не удалось разрешить путь browser.browser_path" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_provide_rejects_program_data_traversal(tmp_path: Path) -> None:
    provider, _ = _provider(
        tmp_path,
        paths_config="""
[browser]
browser_path = "../outside/chrome.exe"
driver_path = "drivers/chromedriver.exe"
""".strip(),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "Не удалось разрешить путь browser.browser_path" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_recursive_merge_combines_nested_tables_without_mutating_sources() -> None:
    first = {"browser": {"options": {"headless": False}}}
    second = {"browser": {"options": {"locale": "ru"}}}

    merged = _merge_settings(first, second)

    assert merged == {"browser": {"options": {"headless": False, "locale": "ru"}}}
    assert first == {"browser": {"options": {"headless": False}}}
    assert second == {"browser": {"options": {"locale": "ru"}}}


def test_recursive_merge_reports_full_nested_overlap_path() -> None:
    first = {"browser": {"options": {"headless": False}}}
    second = {"browser": {"options": {"headless": True}}}

    with pytest.raises(
        ConfigurationOverlapError,
        match=r"browser\.options\.headless",
    ):
        _merge_settings(first, second)


def test_configuration_overlap_error_is_configuration_error() -> None:
    assert issubclass(ConfigurationOverlapError, ConfigurationError)
