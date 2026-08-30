from pathlib import Path
from typing import Any, Dict, Mapping, Tuple, cast

from pydantic import (
    BaseModel,
    StrictBool,
    StrictInt,
    StrictStr,
    validator,  # pyright: ignore[reportUnknownVariableType]
)


class _StrictSettingsModel(BaseModel):
    class Config:
        allow_mutation = False
        extra = "forbid"


class BrowserSettings(_StrictSettingsModel):
    """Настройки запуска браузера для синхронизации."""

    headless: StrictBool
    browser_path: Path
    driver_path: Path


class NashDomRegion(_StrictSettingsModel):
    """Регион NashDom, подготовленный для извлечения объявлений."""

    code: StrictInt
    name: StrictStr
    slug: StrictStr


class NashDomExtractSettings(_StrictSettingsModel):
    """Настройки извлечения объявлений из NashDom."""

    objects_to_parse_count: StrictInt
    regions: Tuple[NashDomRegion, ...]

    @validator(  # pyright: ignore[reportUntypedFunctionDecorator]
        "objects_to_parse_count"
    )
    def _require_positive_objects_to_parse_count(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("objects_to_parse_count должен быть положительным")
        return value


class ExtractionSettings(_StrictSettingsModel):
    """Настройки извлечения данных из внешних источников."""

    nashdom: NashDomExtractSettings


class RegionSettings(_StrictSettingsModel):
    """Настройки назначения ответственных по регионам."""

    default_assigned_by_id: StrictInt
    assignment: Dict[int, StrictInt]

    @validator("assignment", pre=True)  # pyright: ignore[reportUntypedFunctionDecorator]
    def _convert_assignment_keys(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        converted: Dict[int, Any] = {}
        for raw_code, assigned_by_id in cast(Mapping[Any, Any], value).items():
            if isinstance(raw_code, bool):
                raise ValueError("код региона должен быть целым числом")

            if isinstance(raw_code, int):
                code = raw_code
            elif isinstance(raw_code, str) and raw_code.isdecimal():
                code = int(raw_code)
            else:
                raise ValueError("код региона должен быть целым числом")

            if code in converted:
                raise ValueError(f"код региона {code} указан несколько раз")
            converted[code] = assigned_by_id

        return converted


class SyncSettings(_StrictSettingsModel):
    """Единая проверенная конфигурация синхронизации."""

    browser: BrowserSettings
    extract: ExtractionSettings
    region: RegionSettings
