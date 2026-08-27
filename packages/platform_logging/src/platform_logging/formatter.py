import logging
import re
import time
from typing import Any, Mapping, cast

from platform_logging.serialization import format_value

CONTEXT_ATTRIBUTE = "_platform_logging_context"
DETAILS_ATTRIBUTE = "_platform_logging_details"
EVENT_ATTRIBUTE = "_platform_logging_event"

_SIMPLE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def _record_mapping(record: logging.LogRecord, attribute: str) -> Mapping[str, Any]:
    value = record.__dict__.get(attribute)
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _format_key(key: str) -> str:
    if _SIMPLE_KEY.fullmatch(key):
        return key
    return format_value(key)


def _format_fields(fields: Mapping[str, Any]) -> str:
    if not fields:
        return "-"

    return " ".join(
        f"{_format_key(key)}={format_value(value)}" for key, value in sorted(fields.items())
    )


class StructuredFormatter(logging.Formatter):
    """Format operational records as stable, human-readable structured lines."""

    converter = time.localtime

    def format(self, record: logging.LogRecord) -> str:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", self.converter(record.created))
        timestamp = f"{timestamp}.{int(record.msecs):03d}"

        event_value = record.__dict__.get(EVENT_ATTRIBUTE, record.getMessage())
        event = format_value(event_value)
        context = _format_fields(_record_mapping(record, CONTEXT_ATTRIBUTE))
        details = _format_fields(_record_mapping(record, DETAILS_ATTRIBUTE))
        logger_name = format_value(record.name)

        line = f"{timestamp} | {record.levelname} | {logger_name} | {context} | {event} | {details}"

        exception_text = record.exc_text
        if record.exc_info is not None and exception_text is None:
            exception_text = self.formatException(record.exc_info)
        if exception_text:
            line = f"{line}\n{exception_text}"
        if record.stack_info:
            line = f"{line}\n{self.formatStack(record.stack_info)}"

        return line
