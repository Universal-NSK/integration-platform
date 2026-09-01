from dataclasses import dataclass, fields
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, cast


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class BaseExtractedDataclass:
    """Базовая сериализация канонических данных Extract."""

    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать dataclass в устойчивое словарное представление."""
        return {
            model_field.name: self._serialize(getattr(self, model_field.name))
            for model_field in fields(self)
        }

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, CommissioningPeriod):
            return str(value)
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, BaseExtractedDataclass):
            return value.to_dict()
        if isinstance(value, list):
            items = cast(List[Any], value)
            return [BaseExtractedDataclass._serialize(item) for item in items]
        if isinstance(value, tuple):
            items = cast(Tuple[Any, ...], value)
            return tuple(BaseExtractedDataclass._serialize(item) for item in items)
        if isinstance(value, dict):
            mapping = cast(Dict[Any, Any], value)
            return {key: BaseExtractedDataclass._serialize(item) for key, item in mapping.items()}
        return value


@dataclass(frozen=True)
class CommissioningPeriod:
    """Год и квартал ввода объекта с опциональной точной датой."""

    year: int
    quarter: int
    exact_date: Optional[date] = None

    def __post_init__(self) -> None:
        if not _is_positive_integer(self.year):
            raise ValueError("Год ввода должен быть положительным целым числом")
        if not _is_positive_integer(self.quarter) or self.quarter > 4:
            raise ValueError("Квартал ввода должен быть целым числом от 1 до 4")
        if self.exact_date is None:
            return
        if self.exact_date.year != self.year:
            raise ValueError("Год точной даты ввода не совпадает с годом периода")

        exact_quarter = (self.exact_date.month - 1) // 3 + 1
        if exact_quarter != self.quarter:
            raise ValueError("Квартал точной даты ввода не совпадает с кварталом периода")

    def __str__(self) -> str:
        return f"{self.year}, квартал {self.quarter}"


class ExtractedObjectTypeEnum(str, Enum):
    """Канонический тип объекта строительства."""

    RESIDENTIAL = "Жилое"
    NON_RESIDENTIAL = "Нежилое"


@dataclass(frozen=True)
class ExtractedObject(BaseExtractedDataclass):
    """Канонический объект строительства из внешнего источника."""

    id: int
    title: str
    address: str
    region_id: int
    publication_date: date
    commissioning_period: CommissioningPeriod
    object_type: ExtractedObjectTypeEnum
    developer_id: int
    company_group_id: Optional[int]

    def __post_init__(self) -> None:
        if not _is_positive_integer(self.id):
            raise ValueError("ID объекта должен быть положительным целым числом")
        if not self.title.strip():
            raise ValueError("Название объекта не должно быть пустым")
        if not self.address.strip():
            raise ValueError("Адрес объекта не должен быть пустым")
        if not _is_positive_integer(self.region_id):
            raise ValueError("ID региона должен быть положительным целым числом")
        if not _is_positive_integer(self.developer_id):
            raise ValueError("ID застройщика должен быть положительным целым числом")
        if self.company_group_id is not None and not _is_positive_integer(self.company_group_id):
            raise ValueError("ID группы компаний должен быть положительным целым числом или None")


@dataclass(frozen=True)
class ExtractedDeveloper(BaseExtractedDataclass):
    """Канонический застройщик из внешнего источника."""

    id: int
    short_name: str
    full_name: str
    inn: str
    kpp: str
    ogrn: str
    region_id: int
    legal_address: str
    fact_address: str
    contact_name: str
    phone: str
    email: str
    url: Optional[str]
    company_group_id: Optional[int]

    def __post_init__(self) -> None:
        if not _is_positive_integer(self.id):
            raise ValueError("ID застройщика должен быть положительным целым числом")

        required_text_fields = (
            ("Краткое наименование застройщика", self.short_name),
            ("Полное наименование застройщика", self.full_name),
            ("ИНН застройщика", self.inn),
            ("КПП застройщика", self.kpp),
            ("ОГРН застройщика", self.ogrn),
            ("Юридический адрес застройщика", self.legal_address),
            ("Фактический адрес застройщика", self.fact_address),
            ("Контактное лицо застройщика", self.contact_name),
            ("Телефон застройщика", self.phone),
            ("Email застройщика", self.email),
        )
        for field_name, value in required_text_fields:
            if not _is_non_empty_string(value):
                raise ValueError(f"{field_name} не должно быть пустым")

        if not _is_positive_integer(self.region_id):
            raise ValueError("ID региона должен быть положительным целым числом")
        if self.url is not None and not _is_non_empty_string(self.url):
            raise ValueError("URL застройщика должен быть непустой строкой или None")
        if self.company_group_id is not None and not _is_positive_integer(self.company_group_id):
            raise ValueError("ID группы компаний должен быть положительным целым числом или None")


@dataclass(frozen=True)
class ExtractedCompanyGroup(BaseExtractedDataclass):
    """Каноническая группа компаний из внешнего источника."""

    id: int
    name: str

    def __post_init__(self) -> None:
        if not _is_positive_integer(self.id):
            raise ValueError("ID группы компаний должен быть положительным целым числом")
        if not _is_non_empty_string(self.name):
            raise ValueError("Название группы компаний не должно быть пустым")


@dataclass(frozen=True)
class ExtractResult(BaseExtractedDataclass):
    """Полный результат Extract."""

    objects: List[ExtractedObject]
    developers: List[ExtractedDeveloper]
    company_groups: List[ExtractedCompanyGroup]
