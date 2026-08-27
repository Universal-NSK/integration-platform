import json
import re
from dataclasses import dataclass
from typing import Any

_SIMPLE_VALUE = re.compile(r'^[^\s|=",{}\[\]]+$')


@dataclass(frozen=True)
class SerializedValue:
    text: str


def compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def serialize_payload(value: Any) -> SerializedValue:
    """Serialize a payload without allowing serialization errors to escape."""
    try:
        return SerializedValue(compact_json(value))
    except Exception as exc:
        marker = {
            "_platform_logging_error": "payload_not_json_serializable",
            "error_type": type(exc).__name__,
            "object_type": f"{type(value).__module__}.{type(value).__name__}",
        }
        return SerializedValue(compact_json(marker))


def format_value(value: Any) -> str:
    if isinstance(value, SerializedValue):
        return value.text

    if isinstance(value, str):
        if _SIMPLE_VALUE.fullmatch(value):
            return value
        return compact_json(value)

    try:
        return compact_json(value)
    except Exception:
        try:
            representation = repr(value)
        except Exception:
            representation = f"<unrepresentable {type(value).__name__}>"
        return compact_json(representation)
