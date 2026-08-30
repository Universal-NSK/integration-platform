from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, cast

import tomli
from pydantic import BaseModel, StrictInt, StrictStr, ValidationError
from runtime_files import (
    RuntimeFileNotFoundError,
    RuntimeFileReadError,
    RuntimePaths,
    read_text,
)

from nashdom_sync.contracts import NashDomRegion, RegionSettings, SyncSettings
from nashdom_sync.providers.settings_provider.exceptions import (
    ConfigurationError,
    ConfigurationOverlapError,
)

_APP_CONFIG_NAME = "sync.toml"
_PATHS_CONFIG_NAME = "sync.paths.toml"
_REGION_SLUGS_CONFIG_NAME = "sync.region_slugs.toml"
_REGION_CATALOG_KEY = "_region_catalog"
_PATH_FIELDS = ("browser_path", "driver_path")


class _StrictInputModel(BaseModel):
    class Config:
        allow_mutation = False
        extra = "forbid"


class _CatalogRegion(_StrictInputModel):
    code: StrictInt
    name: StrictStr
    slug: Optional[StrictStr] = None


class _RegionCatalog(_StrictInputModel):
    regions: Tuple[_CatalogRegion, ...]


class _RegionPostProcessingInput(_StrictInputModel):
    region: RegionSettings
    region_catalog: _RegionCatalog


class SettingsProvider:
    """Собирает и проверяет настройки синхронизации из runtime-файлов."""

    def __init__(self, paths: RuntimePaths) -> None:
        self._paths = paths

    def provide(self) -> SyncSettings:
        """Вернуть единую проверенную конфигурацию синхронизации."""
        app_settings = self._load_toml(self._paths.config_file(_APP_CONFIG_NAME))
        path_settings = self._load_toml(self._paths.program_data_file(_PATHS_CONFIG_NAME))
        region_catalog = self._load_toml(
            self._paths.config_file(_REGION_SLUGS_CONFIG_NAME)
        )
        merged_settings = self._merge_settings(app_settings, path_settings)
        resolved_settings = self._resolve_paths(merged_settings)
        resolved_settings[_REGION_CATALOG_KEY] = region_catalog

        try:
            processed_settings = self._post_process_settings(resolved_settings)
            return SyncSettings.parse_obj(processed_settings)
        except ValidationError as exc:
            raise ConfigurationError(self._format_validation_error(exc)) from exc

    def _post_process_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнить расширяемую последовательность преобразований настроек."""
        processors = (self._define_regions_to_parse,)

        for processor in processors:
            settings = processor(settings)

        return settings

    @staticmethod
    def _define_regions_to_parse(settings: Dict[str, Any]) -> Dict[str, Any]:
        """Добавить в Extract регионы со slug, назначенные в runtime-настройках."""
        source = _RegionPostProcessingInput.parse_obj(
            {
                "region": settings.get("region"),
                "region_catalog": settings.get(_REGION_CATALOG_KEY),
            }
        )

        catalog_by_code: Dict[int, _CatalogRegion] = {}
        for catalog_region in source.region_catalog.regions:
            if catalog_region.code in catalog_by_code:
                raise ConfigurationError(
                    "В sync.region_slugs.toml код региона "
                    f"{catalog_region.code} указан несколько раз"
                )
            catalog_by_code[catalog_region.code] = catalog_region

        unknown_codes = sorted(set(source.region.assignment) - set(catalog_by_code))
        if unknown_codes:
            formatted_codes = ", ".join(str(code) for code in unknown_codes)
            raise ConfigurationError(
                "В region.assignment указаны коды регионов, отсутствующие "
                f"в sync.region_slugs.toml: {formatted_codes}"
            )

        regions_to_parse: List[Dict[str, Any]] = []
        for catalog_region in source.region_catalog.regions:
            slug = catalog_region.slug
            if catalog_region.code not in source.region.assignment or not slug or not slug.strip():
                continue

            regions_to_parse.append(
                NashDomRegion(
                    code=catalog_region.code,
                    name=catalog_region.name,
                    slug=slug,
                ).dict()
            )

        processed_settings = dict(settings)
        processed_settings.pop(_REGION_CATALOG_KEY, None)
        extract_settings = processed_settings.get("extract")
        if not isinstance(extract_settings, Mapping):
            return processed_settings

        processed_extract = dict(cast(Mapping[str, Any], extract_settings))
        nashdom_settings = processed_extract.get("nashdom")
        if not isinstance(nashdom_settings, Mapping):
            return processed_settings

        processed_nashdom = dict(cast(Mapping[str, Any], nashdom_settings))
        if "regions" in processed_nashdom:
            raise ConfigurationError(
                "Параметр extract.nashdom.regions должен вычисляться из region.assignment "
                "и sync.region_slugs.toml"
            )

        processed_nashdom["regions"] = tuple(regions_to_parse)
        processed_extract["nashdom"] = processed_nashdom
        processed_settings["extract"] = processed_extract
        return processed_settings

    @staticmethod
    def _load_toml(path: Path) -> Dict[str, Any]:
        try:
            content = read_text(path)
        except RuntimeFileNotFoundError as exc:
            raise ConfigurationError(f"Не найден файл конфигурации синхронизации: {path}") from exc
        except RuntimeFileReadError as exc:
            raise ConfigurationError(
                f"Не удалось прочитать файл конфигурации синхронизации: {path}"
            ) from exc

        try:
            return tomli.loads(content)
        except tomli.TOMLDecodeError as exc:
            raise ConfigurationError(f"Не удалось прочитать TOML-файл настроек: {path}") from exc

    @staticmethod
    def _merge_settings(
        first: Mapping[str, Any],
        second: Mapping[str, Any],
        parent_path: Tuple[str, ...] = (),
    ) -> Dict[str, Any]:
        merged = dict(first)

        for key, second_value in second.items():
            current_path = parent_path + (key,)

            if key not in merged:
                merged[key] = second_value
                continue

            first_value = merged[key]
            if isinstance(first_value, Mapping) and isinstance(second_value, Mapping):
                merged[key] = SettingsProvider._merge_settings(
                    cast(Mapping[str, Any], first_value),
                    cast(Mapping[str, Any], second_value),
                    current_path,
                )
                continue

            raise ConfigurationOverlapError(".".join(current_path))

        return merged

    def _resolve_paths(self, settings: Mapping[str, Any]) -> Dict[str, Any]:
        resolved = dict(settings)
        browser_settings = resolved.get("browser")

        if not isinstance(browser_settings, Mapping):
            return resolved

        resolved_browser = dict(cast(Mapping[str, Any], browser_settings))
        for field_name in _PATH_FIELDS:
            raw_path = resolved_browser.get(field_name)
            if not isinstance(raw_path, str):
                continue

            try:
                resolved_browser[field_name] = self._paths.program_data_path(Path(raw_path))
            except (OSError, RuntimeError, ValueError) as exc:
                raise ConfigurationError(
                    f"Не удалось разрешить путь browser.{field_name} "
                    f"относительно ProgramData: {raw_path}"
                ) from exc

        resolved["browser"] = resolved_browser
        return resolved

    @staticmethod
    def _format_validation_error(exc: ValidationError) -> str:
        """Сформировать читаемое сообщение об ошибках валидации."""
        messages: List[str] = []

        for error in exc.errors():
            parameter_path = ".".join(str(part) for part in error["loc"])
            error_type = error["type"]

            if error_type == "value_error.missing":
                messages.append(
                    f"В конфигурации отсутствует обязательный параметр {parameter_path}"
                )
            elif error_type == "value_error.extra":
                messages.append(f"В конфигурации указан неизвестный параметр {parameter_path}")
            elif error_type == "value_error.strictbool" or error_type.startswith("type_error."):
                messages.append(f"Параметр {parameter_path} имеет недопустимое значение или тип")
            else:
                messages.append(
                    "Конфигурация синхронизации не прошла валидацию: "
                    f"некорректный параметр {parameter_path}"
                )

        return "; ".join(messages)
