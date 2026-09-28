"""Обратимое представление DTO с явным типом команды и проверкой структуры."""

from collections.abc import Mapping as MappingOrigin
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from nashdom_sync.contracts.transform import (
    AddAddressCommand,
    AddItemCommand,
    AddRequisiteCommand,
    CrmCommand,
)

T = TypeVar("T")
_COMMAND_TYPES: Dict[str, Type[CrmCommand]] = {
    "add_item": AddItemCommand,
    "add_requisite": AddRequisiteCommand,
    "add_address": AddAddressCommand,
}


def encode(value: Any) -> Any:
    """Сохранить поля DTO без потери точной даты CommissioningPeriod."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        result = {field.name: encode(getattr(value, field.name)) for field in fields(value)}
        for tag, command_type in _COMMAND_TYPES.items():
            if type(value) is command_type:
                result["type"] = tag
                break
        return result
    if isinstance(value, Mapping):
        mapping = cast(Mapping[Any, Any], value)
        if any(not isinstance(key, str) for key in mapping):
            raise ValueError("Ключи JSON должны быть строками")
        return {key: encode(item) for key, item in mapping.items()}
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in cast(Tuple[Any, ...], value)]
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError("Неподдерживаемый тип данных артефакта")


def decode(model: Type[T], data: Any) -> T:
    """Восстановить DTO по его объявленному контракту."""
    return cast(T, _decode(model, data))


def _decode(model: Any, data: Any) -> Any:
    if model is Any:
        return data
    origin = get_origin(model)
    args = get_args(model)
    if model == CrmCommand:
        if not isinstance(data, dict):
            raise ValueError("Ожидался объект команды")
        command = dict(cast(Dict[str, Any], data))
        tag = command.pop("type", None)
        if not isinstance(tag, str) or tag not in _COMMAND_TYPES:
            raise ValueError("Неизвестный или отсутствующий тип команды")
        return _decode(_COMMAND_TYPES[tag], command)
    if origin is Union and type(None) in args:
        if data is None:
            return None
        return _decode(next(arg for arg in args if arg is not type(None)), data)
    if origin in (list, tuple):
        if not isinstance(data, list):
            raise ValueError("Ожидался массив данных")
        items = [_decode(args[0], item) for item in cast(List[Any], data)]
        return tuple(items) if origin is tuple else items
    if origin is MappingOrigin:
        if not isinstance(data, dict):
            raise ValueError("Ожидался объект полей команды")
        return {
            _decode(args[0], key): _decode(args[1], item)
            for key, item in cast(Dict[str, Any], data).items()
        }
    if model in (datetime, date):
        if not isinstance(data, str):
            raise ValueError("Ожидалась дата в формате ISO")
        try:
            return model.fromisoformat(data)
        except ValueError:
            raise ValueError("Некорректная дата в артефакте") from None
    if isinstance(model, type) and issubclass(model, Enum):
        for member in model:
            if member.value == data:
                return member
        raise ValueError("Неизвестное значение перечисления")
    if isinstance(model, type) and is_dataclass(model):
        if not isinstance(data, dict):
            raise ValueError("Ожидался объект DTO")
        mapping = cast(Dict[str, Any], data)
        hints = get_type_hints(model)
        if set(mapping) != {field.name for field in fields(model)}:
            raise ValueError("Набор полей DTO не соответствует контракту")
        return model(**{name: _decode(hints[name], item) for name, item in mapping.items()})
    if model in (str, int, float, bool) and type(data) is model:
        return data
    raise ValueError("Тип поля не соответствует контракту артефакта")
