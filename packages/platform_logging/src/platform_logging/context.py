from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Union, cast

from platform_logging.config import coerce_level
from platform_logging.formatter import (
    CONTEXT_ATTRIBUTE,
    DETAILS_ATTRIBUTE,
    EVENT_ATTRIBUTE,
)
from platform_logging.serialization import serialize_payload

LoggerLike = Union[logging.Logger, "logging.LoggerAdapter[logging.Logger]"]


def with_context(
    logger: logging.Logger,
    **fields: Any,
) -> logging.LoggerAdapter[logging.Logger]:
    """Bind context fields to an ordinary stdlib logger."""
    return logging.LoggerAdapter(logger, {CONTEXT_ATTRIBUTE: dict(fields)})


def _adapter_context(
    logger: logging.LoggerAdapter[logging.Logger],
) -> Mapping[str, Any]:
    if logger.extra is None:
        return {}
    value = logger.extra.get(CONTEXT_ATTRIBUTE)
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _require_nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _write_event(
    logger: LoggerLike,
    level: Union[int, str],
    event: str,
    details: Mapping[str, Any],
) -> None:
    event_value = _require_nonempty_string(event, "event")

    extra: Dict[str, Any] = {
        EVENT_ATTRIBUTE: event_value,
        DETAILS_ATTRIBUTE: dict(details),
    }

    resolved_level = coerce_level(level)
    if isinstance(logger, logging.LoggerAdapter):
        extra[CONTEXT_ATTRIBUTE] = dict(_adapter_context(logger))
        logger.logger.log(resolved_level, event_value, extra=extra)
        return

    logger.log(resolved_level, event_value, extra=extra)


def log_event(
    logger: LoggerLike,
    level: Union[int, str],
    event: str,
    **details: Any,
) -> None:
    """Write a structured operational event through a Logger or LoggerAdapter."""
    _write_event(logger, level, event, details)


def log_payload(
    logger: LoggerLike,
    level: Union[int, str],
    event: str,
    payload: Any,
    *,
    enabled: bool,
    field_name: str = "payload",
    **details: Any,
) -> None:
    """Explicitly log one complete payload or response as compact UTF-8 JSON.

    Business payloads and responses are permitted. Webhook URLs, secret config,
    and full Bitrix request URLs must never be passed to this helper.
    """
    if not enabled:
        return
    field_name_value = _require_nonempty_string(field_name, "field_name")

    payload_details = dict(details)
    payload_details[field_name_value] = serialize_payload(payload)
    _write_event(logger, level, event, payload_details)
