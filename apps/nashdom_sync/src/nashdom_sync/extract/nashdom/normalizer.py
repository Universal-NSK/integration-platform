import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, cast

from nashdom_sync.contracts import (
    CommissioningPeriod,
    ExtractedObject,
    ExtractedObjectTypeEnum,
)
from nashdom_sync.extract.exceptions import NashDomNormalizationError

_SourcePath = Tuple[str, ...]
_SourcePaths = Tuple[_SourcePath, ...]
_ValueNormalizer = Callable[[Any], Any]

_OBJECT_ID_PATHS: _SourcePaths = (("objId",),)
_TITLE_PATHS: _SourcePaths = (("objCommercNm",),)
_ADDRESS_PATHS: _SourcePaths = (("objAddr",),)
_REGION_ID_PATHS: _SourcePaths = (("rpdRegionCd",),)
_PUBLICATION_DATE_PATHS: _SourcePaths = (
    ("publicationDate",),
    ("objPublDt",),
)
_COMMISSIONING_PERIOD_PATHS: _SourcePaths = (("objReady100PercDt",),)
_OBJECT_TYPE_PATHS: _SourcePaths = (("buildType",),)
_DEVELOPER_ID_PATHS: _SourcePaths = (("developer", "devId"),)
_COMPANY_GROUP_ID_PATHS: _SourcePaths = (("developer", "companyGroup"),)

_QUARTER_PATTERN = re.compile(r"^(I|II|III|IV)\s+кв\.\s+(\d{4})$")
_ROMAN_QUARTERS = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
}
_MISSING = object()


class NashDomDataNormalizer:
    """Приводит подтверждённые SSR/XHR-схемы NashDom к общим контрактам."""

    def normalize_objects(
        self,
        raw_objects: List[Dict[str, Any]],
    ) -> List[ExtractedObject]:
        """Нормализовать список raw-объектов одной source-схемы."""
        return [self._normalize_object(raw_object) for raw_object in raw_objects]

    def _normalize_object(self, raw_object: Dict[str, Any]) -> ExtractedObject:
        object_id = self._normalize_integer(
            self._resolve_value(
                raw_object,
                _OBJECT_ID_PATHS,
                "ID объекта",
                value_normalizer=self._normalize_integer,
            ),
            "ID объекта",
        )
        title = self._normalize_required_text(
            self._resolve_value(
                raw_object,
                _TITLE_PATHS,
                "название объекта",
                value_normalizer=self._normalize_required_text,
            ),
            "Название объекта",
        )
        address = self._normalize_required_text(
            self._resolve_value(
                raw_object,
                _ADDRESS_PATHS,
                "адрес объекта",
                value_normalizer=self._normalize_required_text,
            ),
            "Адрес объекта",
        )
        region_id = self._normalize_integer(
            self._resolve_value(
                raw_object,
                _REGION_ID_PATHS,
                "ID региона",
                value_normalizer=self._normalize_integer,
            ),
            "ID региона",
        )
        publication_date = self._normalize_publication_date(
            self._resolve_value(
                raw_object,
                _PUBLICATION_DATE_PATHS,
                "дата публикации",
                value_normalizer=self._normalize_publication_date,
            )
        )
        commissioning_period = self._normalize_commissioning_period(
            self._resolve_value(
                raw_object,
                _COMMISSIONING_PERIOD_PATHS,
                "период ввода",
                value_normalizer=self._normalize_commissioning_period,
            )
        )
        object_type = self._normalize_object_type(
            self._resolve_value(
                raw_object,
                _OBJECT_TYPE_PATHS,
                "тип объекта",
                value_normalizer=self._normalize_object_type,
            )
        )
        developer_id = self._normalize_integer(
            self._resolve_value(
                raw_object,
                _DEVELOPER_ID_PATHS,
                "ID застройщика",
                value_normalizer=self._normalize_integer,
            ),
            "ID застройщика",
        )
        raw_company_group_id = self._resolve_value(
            raw_object,
            _COMPANY_GROUP_ID_PATHS,
            "ID группы компаний",
            required=False,
            value_normalizer=self._normalize_integer,
        )
        company_group_id = (
            None
            if raw_company_group_id is None
            else self._normalize_integer(raw_company_group_id, "ID группы компаний")
        )

        try:
            return ExtractedObject(
                id=object_id,
                title=title,
                address=address,
                region_id=region_id,
                publication_date=publication_date,
                commissioning_period=commissioning_period,
                object_type=object_type,
                developer_id=developer_id,
                company_group_id=company_group_id,
            )
        except ValueError as exc:
            raise NashDomNormalizationError(
                f"Объект NashDom с ID {object_id} нарушает контракт: {exc}"
            ) from exc

    @staticmethod
    def _resolve_value(
        raw_object: Dict[str, Any],
        paths: _SourcePaths,
        field_name: str,
        *,
        required: bool = True,
        value_normalizer: Optional[_ValueNormalizer] = None,
    ) -> Any:
        values: List[Any] = []
        found_paths: List[str] = []

        for path in paths:
            value = NashDomDataNormalizer._read_path(raw_object, path)
            if value is _MISSING or value is None:
                continue
            values.append(value)
            found_paths.append(".".join(path))

        if not values:
            if required:
                expected_paths = ", ".join(".".join(path) for path in paths)
                raise NashDomNormalizationError(
                    f"Не найдено обязательное поле «{field_name}» "
                    f"по source-путям: {expected_paths}"
                )
            return None

        normalized_values = (
            [value_normalizer(value) for value in values]
            if value_normalizer is not None
            else values
        )
        first_value = normalized_values[0]
        if any(value != first_value for value in normalized_values[1:]):
            raise NashDomNormalizationError(
                f"Поле «{field_name}» содержит противоречивые значения "
                f"в source-путях: {', '.join(found_paths)}"
            )

        return values[0]

    @staticmethod
    def _read_path(raw_object: Dict[str, Any], path: _SourcePath) -> Any:
        current: Any = raw_object
        for part in path:
            if not isinstance(current, Mapping) or part not in current:
                return _MISSING
            current = cast(Mapping[str, Any], current)[part]
        return current

    @staticmethod
    def _normalize_integer(value: Any, field_name: str = "целочисленное поле") -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise NashDomNormalizationError(f"{field_name} должен быть целым числом")
        return value

    @staticmethod
    def _normalize_required_text(value: Any, field_name: str = "текстовое поле") -> str:
        if not isinstance(value, str) or not value.strip():
            raise NashDomNormalizationError(f"{field_name} не должно быть пустым")
        return value.strip()

    @staticmethod
    def _normalize_publication_date(value: Any) -> date:
        if not isinstance(value, str):
            raise NashDomNormalizationError("Дата публикации должна быть строкой")

        for date_format in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(value.strip(), date_format).date()
            except ValueError:
                continue

        raise NashDomNormalizationError(
            f"Неизвестный формат даты публикации: {value!r}"
        )

    @staticmethod
    def _normalize_commissioning_period(value: Any) -> CommissioningPeriod:
        if not isinstance(value, str):
            raise NashDomNormalizationError("Период ввода должен быть строкой")

        stripped_value = value.strip()
        try:
            exact_date = datetime.strptime(stripped_value, "%Y-%m-%d").date()
        except ValueError:
            exact_date = None

        if exact_date is not None:
            return CommissioningPeriod(
                year=exact_date.year,
                quarter=(exact_date.month - 1) // 3 + 1,
                exact_date=exact_date,
            )

        quarter_match = _QUARTER_PATTERN.fullmatch(stripped_value)
        if quarter_match is not None:
            return CommissioningPeriod(
                year=int(quarter_match.group(2)),
                quarter=_ROMAN_QUARTERS[quarter_match.group(1)],
            )

        raise NashDomNormalizationError(
            f"Неизвестный формат периода ввода: {value!r}"
        )

    @staticmethod
    def _normalize_object_type(value: Any) -> ExtractedObjectTypeEnum:
        if not isinstance(value, str):
            raise NashDomNormalizationError("Тип объекта должен быть строкой")

        try:
            return ExtractedObjectTypeEnum(value.strip())
        except ValueError as exc:
            raise NashDomNormalizationError(
                f"Неизвестный тип объекта NashDom: {value!r}"
            ) from exc
