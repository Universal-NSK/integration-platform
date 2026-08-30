from pathlib import Path
from typing import Optional, Tuple, Union

import pytest
import tomli
from nashdom_sync.contracts import (
    BrowserSettings,
    ExtractionSettings,
    NashDomExtractSettings,
    NashDomRegion,
    RegionSettings,
    SyncSettings,
)
from nashdom_sync.providers.settings_provider import (
    ConfigurationError,
    ConfigurationOverlapError,
    SettingsProvider,
)
from pydantic import ValidationError
from runtime_files import RuntimeFileReadError, RuntimePaths

VALID_APP_CONFIG = """
[browser]
headless = false

[extract.nashdom]
objects_to_parse_count = 35

[region]
default_assigned_by_id = 12

[region.assignment]
4 = 28
22 = 12
""".strip()

VALID_PATHS_CONFIG = """
[browser]
browser_path = "drivers/chrome/chrome-win/chrome.exe"
driver_path = "drivers/chrome/chromedriver_win32/chromedriver.exe"
""".strip()

VALID_REGION_CATALOG = """
[[regions]]
code = 1
name = "Республика Адыгея"

[[regions]]
code = 4
name = "Республика Алтай"
slug = "республика-алтай"

[[regions]]
code = 22
name = "Алтайский край"
""".strip()


def _provider(
    tmp_path: Path,
    app_config: Optional[Union[str, bytes]] = VALID_APP_CONFIG,
    paths_config: Optional[Union[str, bytes]] = VALID_PATHS_CONFIG,
    region_catalog: Optional[Union[str, bytes]] = VALID_REGION_CATALOG,
) -> Tuple[SettingsProvider, Path]:
    repo_root = (tmp_path / "repository").resolve()
    config_root = repo_root / "config"
    program_data_root = (tmp_path / "program-data").resolve()
    config_root.mkdir(parents=True)
    program_data_root.mkdir()

    if app_config is not None:
        app_config_path = config_root / "sync.toml"
        if isinstance(app_config, bytes):
            app_config_path.write_bytes(app_config)
        else:
            app_config_path.write_text(app_config, encoding="utf-8")
    if paths_config is not None:
        paths_config_path = program_data_root / "sync.paths.toml"
        if isinstance(paths_config, bytes):
            paths_config_path.write_bytes(paths_config)
        else:
            paths_config_path.write_text(paths_config, encoding="utf-8")
    if region_catalog is not None:
        region_catalog_path = config_root / "sync.region_slugs.toml"
        if isinstance(region_catalog, bytes):
            region_catalog_path.write_bytes(region_catalog)
        else:
            region_catalog_path.write_text(region_catalog, encoding="utf-8")

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
    assert isinstance(settings.extract, ExtractionSettings)
    assert isinstance(settings.extract.nashdom, NashDomExtractSettings)
    assert settings.extract.nashdom.objects_to_parse_count == 35
    assert settings.extract.nashdom.regions == (
        NashDomRegion(
            code=4,
            name="Республика Алтай",
            slug="республика-алтай",
        ),
    )
    assert isinstance(settings.region, RegionSettings)
    assert settings.region.default_assigned_by_id == 12
    assert settings.region.assignment == {4: 28, 22: 12}


def test_provide_keeps_assignment_region_without_slug_out_of_extract(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)

    settings = provider.provide()

    assert 22 in settings.region.assignment
    assert [region.code for region in settings.extract.nashdom.regions] == [4]


def test_provide_builds_region_intersection_in_catalog_order(tmp_path: Path) -> None:
    provider, _ = _provider(
        tmp_path,
        region_catalog="""
[[regions]]
code = 22
name = "Алтайский край"
slug = "алтайский-край"

[[regions]]
code = 1
name = "Республика Адыгея"
slug = "республика-адыгея"

[[regions]]
code = 4
name = "Республика Алтай"
slug = "республика-алтай"
""".strip(),
    )

    settings = provider.provide()

    assert [region.code for region in settings.extract.nashdom.regions] == [22, 4]


def test_provide_rejects_assignment_region_missing_from_catalog(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path, app_config=f"{VALID_APP_CONFIG}\n99 = 34")

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "отсутствующие в sync.region_slugs.toml: 99" in str(exc_info.value)


def test_provide_rejects_duplicate_region_code_in_catalog(tmp_path: Path) -> None:
    provider, _ = _provider(
        tmp_path,
        region_catalog="""
[[regions]]
code = 4
name = "Республика Алтай"
slug = "республика-алтай"

[[regions]]
code = 4
name = "Дубликат Республики Алтай"
slug = "дубликат"

[[regions]]
code = 22
name = "Алтайский край"
""".strip(),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "код региона 4 указан несколько раз" in str(exc_info.value)


@pytest.mark.parametrize("objects_to_parse_count", [0, -1])
def test_provide_requires_positive_objects_to_parse_count(
    tmp_path: Path,
    objects_to_parse_count: int,
) -> None:
    app_config = VALID_APP_CONFIG.replace(
        "objects_to_parse_count = 35",
        f"objects_to_parse_count = {objects_to_parse_count}",
    )
    provider, _ = _provider(tmp_path, app_config=app_config)

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert "extract.nashdom.objects_to_parse_count" in str(exc_info.value)


def test_provide_converts_numeric_assignment_keys_to_int(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)

    settings = provider.provide()

    assert settings.region.assignment == {4: 28, 22: 12}
    assert all(isinstance(code, int) for code in settings.region.assignment)


def test_provide_rejects_non_numeric_assignment_key(tmp_path: Path) -> None:
    provider, _ = _provider(
        tmp_path,
        app_config=f"{VALID_APP_CONFIG}\nnot_a_region_code = 34",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert "region.assignment" in str(exc_info.value)


def test_provide_rejects_raw_extract_regions(tmp_path: Path) -> None:
    app_config = VALID_APP_CONFIG.replace(
        "objects_to_parse_count = 35",
        "objects_to_parse_count = 35\nregions = []",
    )
    provider, _ = _provider(tmp_path, app_config=app_config)

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "extract.nashdom.regions должен вычисляться" in str(exc_info.value)


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


@pytest.mark.parametrize(
    "missing_source",
    ["sync.toml", "sync.paths.toml", "sync.region_slugs.toml"],
)
def test_provide_reports_missing_configuration_file(
    tmp_path: Path,
    missing_source: str,
) -> None:
    provider, _ = _provider(
        tmp_path,
        app_config=None if missing_source == "sync.toml" else VALID_APP_CONFIG,
        paths_config=None if missing_source == "sync.paths.toml" else VALID_PATHS_CONFIG,
        region_catalog=(
            None if missing_source == "sync.region_slugs.toml" else VALID_REGION_CATALOG
        ),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "Не найден файл конфигурации синхронизации" in str(exc_info.value)
    assert missing_source in str(exc_info.value)


@pytest.mark.parametrize(
    "invalid_source",
    ["sync.toml", "sync.paths.toml", "sync.region_slugs.toml"],
)
def test_provide_wraps_invalid_toml_with_parser_cause(
    tmp_path: Path,
    invalid_source: str,
) -> None:
    invalid_toml = "[browser\nheadless = false"
    provider, _ = _provider(
        tmp_path,
        app_config=invalid_toml if invalid_source == "sync.toml" else VALID_APP_CONFIG,
        paths_config=(invalid_toml if invalid_source == "sync.paths.toml" else VALID_PATHS_CONFIG),
        region_catalog=(
            invalid_toml
            if invalid_source == "sync.region_slugs.toml"
            else VALID_REGION_CATALOG
        ),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "Не удалось прочитать TOML-файл настроек" in str(exc_info.value)
    assert invalid_source in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, tomli.TOMLDecodeError)


@pytest.mark.parametrize(
    "invalid_source",
    ["sync.toml", "sync.paths.toml", "sync.region_slugs.toml"],
)
def test_provide_wraps_invalid_utf8_with_runtime_file_cause(
    tmp_path: Path,
    invalid_source: str,
) -> None:
    invalid_utf8 = b"\xff"
    provider, _ = _provider(
        tmp_path,
        app_config=invalid_utf8 if invalid_source == "sync.toml" else VALID_APP_CONFIG,
        paths_config=(invalid_utf8 if invalid_source == "sync.paths.toml" else VALID_PATHS_CONFIG),
        region_catalog=(
            invalid_utf8
            if invalid_source == "sync.region_slugs.toml"
            else VALID_REGION_CATALOG
        ),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert "Не удалось прочитать файл конфигурации синхронизации" in str(exc_info.value)
    assert invalid_source in str(exc_info.value)
    runtime_error = exc_info.value.__cause__
    assert isinstance(runtime_error, RuntimeFileReadError)
    assert isinstance(runtime_error.__cause__, UnicodeDecodeError)


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

    assert str(exc_info.value) == (
        "В конфигурации отсутствует обязательный параметр browser.driver_path"
    )
    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert "driver_path" in str(exc_info.value)


def test_provide_requires_strict_boolean(tmp_path: Path) -> None:
    provider, _ = _provider(
        tmp_path,
        app_config=VALID_APP_CONFIG.replace("headless = false", 'headless = "false"'),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert str(exc_info.value) == ("Параметр browser.headless имеет недопустимое значение или тип")


def test_provide_forbids_unknown_fields(tmp_path: Path) -> None:
    provider, _ = _provider(
        tmp_path,
        app_config=VALID_APP_CONFIG.replace(
            "headless = false",
            "headless = false\nheadles = false",
        ),
    )

    with pytest.raises(ConfigurationError) as exc_info:
        provider.provide()

    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert str(exc_info.value) == ("В конфигурации указан неизвестный параметр browser.headles")


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


def test_recursive_merge_combines_nested_tables_without_mutating_sources(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    first = {"browser": {"options": {"headless": False}}}
    second = {"browser": {"options": {"locale": "ru"}}}

    merged = provider._merge_settings(first, second)  # pyright: ignore[reportPrivateUsage]

    assert merged == {"browser": {"options": {"headless": False, "locale": "ru"}}}
    assert first == {"browser": {"options": {"headless": False}}}
    assert second == {"browser": {"options": {"locale": "ru"}}}


def test_recursive_merge_reports_full_nested_overlap_path(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    first = {"browser": {"options": {"headless": False}}}
    second = {"browser": {"options": {"headless": True}}}

    with pytest.raises(
        ConfigurationOverlapError,
        match=r"browser\.options\.headless",
    ):
        provider._merge_settings(first, second)  # pyright: ignore[reportPrivateUsage]


def test_configuration_overlap_error_is_configuration_error() -> None:
    assert issubclass(ConfigurationOverlapError, ConfigurationError)
