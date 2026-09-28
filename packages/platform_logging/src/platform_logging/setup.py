import logging
import re
import threading
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List

from platform_logging.config import LoggingConfig, resolve_level
from platform_logging.formatter import StructuredFormatter

_SAFE_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
_SAFE_LOGGER_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_OWNED_MARKER = "_platform_logging_owned"
_HANDLER_KIND = "_platform_logging_kind"
_CONFIGURE_LOCK = threading.RLock()


@dataclass(frozen=True)
class LoggingSession:
    """Неизменяемое описание настроенной сессии логирования."""

    service_name: str
    logger_name: str
    log_file: Path
    config: LoggingConfig


def _validate_service_name(service_name: object) -> None:
    if not isinstance(service_name, str) or not _SAFE_SERVICE_NAME.fullmatch(service_name):
        raise ValueError("service_name должен быть безопасным сегментом имени файла")
    if service_name.endswith("."):
        raise ValueError("service_name не должен оканчиваться точкой")

    reserved_candidate = service_name.split(".", 1)[0].upper()
    if reserved_candidate in _WINDOWS_RESERVED_NAMES:
        raise ValueError("service_name зарезервирован в Windows")


def _validate_logger_name(logger_name: object) -> None:
    if not isinstance(logger_name, str) or not logger_name:
        raise ValueError("logger_name должен быть непустым пространством имён логгера")
    if any(not _SAFE_LOGGER_SEGMENT.fullmatch(segment) for segment in logger_name.split(".")):
        raise ValueError("logger_name должен содержать безопасные сегменты, разделённые точками")


def _mark_handler(handler: logging.Handler, kind: str) -> None:
    setattr(handler, _OWNED_MARKER, True)
    setattr(handler, _HANDLER_KIND, kind)


def _is_owned_handler(handler: logging.Handler) -> bool:
    return getattr(handler, _OWNED_MARKER, False) is True


def _build_handlers(log_file: Path, config: LoggingConfig) -> List[logging.Handler]:
    formatter = StructuredFormatter()
    handlers: List[logging.Handler] = []

    try:
        file_handler = RotatingFileHandler(
            filename=log_file,
            mode="a",
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
            delay=False,
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(resolve_level(config.level))
        _mark_handler(file_handler, "file")
        handlers.append(file_handler)

        if config.console:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            console_handler.setLevel(resolve_level(config.level))
            _mark_handler(console_handler, "console")
            handlers.append(console_handler)
    except BaseException:
        for handler in handlers:
            handler.close()
        raise

    return handlers


def configure_logging(
    service_name: str,
    logger_name: str,
    run_dir: Path,
    config: LoggingConfig,
) -> LoggingSession:
    """Настроить пространство логгера в готовом каталоге запуска.

    Повторная настройка заменяет и закрывает только собственные обработчики.
    Корневой логгер и сторонние обработчики остаются без изменений.
    """
    _validate_service_name(service_name)
    _validate_logger_name(logger_name)
    level = resolve_level(config.level)

    with _CONFIGURE_LOCK:
        if not run_dir.is_dir():
            raise ValueError("run_dir должен быть существующим каталогом")
        log_file = run_dir / f"{service_name}.log"
        new_handlers = _build_handlers(log_file, config)

        logger = logging.getLogger(logger_name)
        old_handlers = [handler for handler in logger.handlers if _is_owned_handler(handler)]

        for handler in old_handlers:
            logger.removeHandler(handler)
        for handler in new_handlers:
            logger.addHandler(handler)

        logger.setLevel(level)
        logger.propagate = False
        logger.disabled = False

        for handler in old_handlers:
            handler.close()

    return LoggingSession(
        service_name=service_name,
        logger_name=logger_name,
        log_file=log_file,
        config=config,
    )
