from pathlib import Path
from typing import Any, Dict, Mapping, Tuple, cast

from pydantic import (
    BaseModel,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    validator,  # pyright: ignore[reportUnknownVariableType]
)


class _StrictSettingsModel(BaseModel):
    class Config:
        allow_mutation = False
        extra = "forbid"


class ExecutionSettings(_StrictSettingsModel):
    """Настройки выполнения этапов синхронизации."""

    load_enabled: StrictBool


class BrowserSettings(_StrictSettingsModel):
    """Настройки запуска браузера для синхронизации."""

    headless: StrictBool
    browser_path: Path
    driver_path: Path
    page_load_timeout_seconds: StrictFloat
    script_timeout_seconds: StrictFloat
    page_load_strategy: StrictStr
    disable_images: StrictBool
    window_width: StrictInt
    window_height: StrictInt
    launch_max_attempts: StrictInt
    launch_retry_delay_seconds: StrictFloat
    extract_session_max_attempts: StrictInt
    extract_session_retry_delay_seconds: StrictFloat

    @validator("launch_max_attempts", "extract_session_max_attempts")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _positive_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("attempts must be positive")
        return value

    @validator("launch_retry_delay_seconds", "extract_session_retry_delay_seconds")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _nonnegative_delay(cls, value: float) -> float:
        if not value >= 0 or value == float("inf"):
            raise ValueError("delay must be finite and nonnegative")
        return value

    @validator(
        "page_load_timeout_seconds", "script_timeout_seconds", "window_width", "window_height"
    )  # pyright: ignore[reportUntypedFunctionDecorator]
    def _positive_browser_value(cls, value: float) -> float:
        if not value > 0 or value == float("inf"):
            raise ValueError("value must be finite and positive")
        return value

    @validator("page_load_strategy")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _valid_strategy(cls, value: str) -> str:
        if value not in ("normal", "eager", "none"):
            raise ValueError("invalid page load strategy")
        return value


class BitrixClientSettings(_StrictSettingsModel):
    """Настройки HTTP-клиента Bitrix Gateway."""

    gateway_url: StrictStr
    timeout: float

    @validator("gateway_url")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _require_gateway_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("gateway_url не должен быть пустым")
        return value

    @validator("timeout")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _require_positive_timeout(cls, value: float) -> float:
        if not value > 0:
            raise ValueError("timeout должен быть положительным")
        return value


class NashDomRegion(_StrictSettingsModel):
    """Регион NashDom, подготовленный для извлечения объявлений."""

    code: StrictInt
    name: StrictStr
    slug: StrictStr


class NashDomExtractSettings(_StrictSettingsModel):
    """Настройки извлечения объявлений из NashDom."""

    objects_to_parse_count: StrictInt
    regions: Tuple[NashDomRegion, ...]
    element_wait_timeout_seconds: StrictFloat
    navigation_max_attempts: StrictInt
    navigation_retry_delay_seconds: StrictFloat

    @validator("element_wait_timeout_seconds", "navigation_max_attempts")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _positive_policy_value(cls, value: float) -> float:
        if not value > 0 or value == float("inf"):
            raise ValueError("value must be finite and positive")
        return value

    @validator("navigation_retry_delay_seconds")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _nonnegative_delay(cls, value: float) -> float:
        if not value >= 0 or value == float("inf"):
            raise ValueError("delay must be finite and nonnegative")
        return value

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

    default_assigned_by_name: StrictStr
    assignment: Dict[int, StrictStr]

    @validator("default_assigned_by_name")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _require_default_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("имя ответственного не должно быть пустым")
        return value

    @validator("assignment", each_item=True)  # pyright: ignore[reportUntypedFunctionDecorator]
    def _require_assignment_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("имя ответственного не должно быть пустым")
        return value

    @validator("assignment", pre=True)  # pyright: ignore[reportUntypedFunctionDecorator]
    def _convert_assignment_keys(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        converted: Dict[int, Any] = {}
        for raw_code, assigned_by_name in cast(Mapping[Any, Any], value).items():
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
            converted[code] = assigned_by_name

        return converted


class LoggingSettings(_StrictSettingsModel):
    """Настройки структурированного логирования синхронизации."""

    level: StrictStr
    console: StrictBool
    log_payloads: StrictBool
    max_bytes: StrictInt
    backup_count: StrictInt

    @validator("level")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _require_level(cls, value: str) -> str:
        if value.strip().upper() not in {
            "CRITICAL",
            "FATAL",
            "ERROR",
            "WARNING",
            "WARN",
            "INFO",
            "DEBUG",
            "NOTSET",
        }:
            raise ValueError("level должен быть допустимым именем уровня логирования")
        return value

    @validator("max_bytes")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _require_positive_max_bytes(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_bytes должен быть положительным")
        return value

    @validator("backup_count")  # pyright: ignore[reportUntypedFunctionDecorator]
    def _require_nonnegative_backup_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("backup_count не должен быть отрицательным")
        return value


class SyncSettings(_StrictSettingsModel):
    """Единая проверенная конфигурация синхронизации."""

    logging: LoggingSettings
    execution: ExecutionSettings
    browser: BrowserSettings
    bitrix: BitrixClientSettings
    extract: ExtractionSettings
    region: RegionSettings
