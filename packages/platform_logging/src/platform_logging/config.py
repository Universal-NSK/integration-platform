import logging
from dataclasses import dataclass
from typing import Union

_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.FATAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "WARN": logging.WARN,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def resolve_level(level: object) -> int:
    """Resolve a standard logging level name."""
    if not isinstance(level, str) or not level.strip():
        raise ValueError("level must be a non-empty logging level name")

    value = _LEVELS.get(level.strip().upper())
    if value is None:
        raise ValueError(f"Unknown logging level: {level!r}")

    return value


def coerce_level(level: Union[int, str]) -> int:
    if isinstance(level, bool):
        raise ValueError("level must be an integer or logging level name")
    if isinstance(level, int):
        return level
    return resolve_level(level)


@dataclass(frozen=True)
class LoggingConfig:
    """Explicit settings shared by the file and optional console handlers."""

    level: str
    console: bool
    log_payloads: bool
    max_bytes: int
    backup_count: int

    def __post_init__(self) -> None:
        resolve_level(self.level)
        _require_bool(self.console, "console")
        _require_bool(self.log_payloads, "log_payloads")
        max_bytes = _require_int(self.max_bytes, "max_bytes")
        backup_count = _require_int(self.backup_count, "backup_count")

        if max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero")
        if backup_count < 0:
            raise ValueError("backup_count must be zero or greater")


def _require_bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a bool")


def _require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value
