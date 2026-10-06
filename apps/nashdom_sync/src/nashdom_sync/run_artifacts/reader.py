"""Общее чтение типизированного конверта артефакта."""

import json
from pathlib import Path
from typing import Any, Dict, Type, TypeVar, cast

from nashdom_sync.run_artifacts.serialization import decode

T = TypeVar("T")


def _reject_constant(value: str) -> None:
    raise ValueError("Нечисловые константы JSON запрещены")


def read_typed_artifact(path: Path, model: Type[T]) -> T:
    """Прочитать и проверить конверт и восстановить DTO без изменения схемы."""
    with (path).open("r", encoding="utf-8") as stream:
        raw: Any = json.load(stream, parse_constant=_reject_constant)
    if not isinstance(raw, dict):
        raise ValueError("Ожидался JSON-конверт артефакта")
    envelope = cast(Dict[str, Any], raw)
    if (
        set(envelope) != {"schema_version", "data"}
        or type(envelope["schema_version"]) is not int
        or envelope["schema_version"] != 1
    ):
        raise ValueError("Неподдерживаемая схема артефакта")
    return decode(model, envelope["data"])
