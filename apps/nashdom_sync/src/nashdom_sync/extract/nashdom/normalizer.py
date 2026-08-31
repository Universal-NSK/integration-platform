import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, cast

from nashdom_sync.contracts import (
    CommissioningPeriod,
    ExtractedCompanyGroup,
    ExtractedDeveloper,
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
_OBJECT_DEVELOPER_ID_PATHS: _SourcePaths = (("developer", "devId"),)
_COMPANY_GROUP_ID_PATHS: _SourcePaths = (("developer", "companyGroup"),)

_DEVELOPER_ID_PATHS: _SourcePaths = (("devId",),)
_DEVELOPER_SHORT_NAME_PATHS: _SourcePaths = (("devShortCleanNm",),)
_DEVELOPER_FULL_NAME_PATHS: _SourcePaths = (("devFullCleanNm",),)
_DEVELOPER_INN_PATHS: _SourcePaths = (("devInn",),)
_DEVELOPER_KPP_PATHS: _SourcePaths = (("devKpp",),)
_DEVELOPER_OGRN_PATHS: _SourcePaths = (("devOgrn",),)
_DEVELOPER_REGION_ID_PATHS: _SourcePaths = (("devOrgRegRegionCd",),)
_DEVELOPER_LEGAL_ADDRESS_PATHS: _SourcePaths = (("devLegalAddr",),)
_DEVELOPER_FACT_ADDRESS_PATHS: _SourcePaths = (("devFactAddr",),)
_DEVELOPER_CONTACT_NAME_PATHS: _SourcePaths = (("devEmplMainFullNm",),)
_DEVELOPER_PHONE_PATHS: _SourcePaths = (("devPhoneNum",),)
_DEVELOPER_EMAIL_PATHS: _SourcePaths = (("devEmail",),)
_DEVELOPER_URL_PATHS: _SourcePaths = (("devSite",),)
_DEVELOPER_COMPANY_GROUP_ID_PATHS: _SourcePaths = (("companyGroupId",),)

_COMPANY_GROUP_ENTITY_ID_PATHS: _SourcePaths = (("devGroupId",),)
_COMPANY_GROUP_NAME_PATHS: _SourcePaths = (("name",),)

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

    def normalize_developers(
        self,
        raw_developers: List[Dict[str, Any]],
    ) -> List[ExtractedDeveloper]:
        """Нормализовать застройщиков из подтверждённой flat ERZ-схемы."""
        return [
            self._normalize_developer(raw_developer)
            for raw_developer in raw_developers
        ]

    def normalize_company_groups(
        self,
        raw_company_groups: List[Dict[str, Any]],
    ) -> List[ExtractedCompanyGroup]:
        """Нормализовать группы компаний из detail ERZ-схемы."""
        return [
            self._normalize_company_group(raw_company_group)
            for raw_company_group in raw_company_groups
        ]

    def _normalize_company_group(
        self,
        raw_company_group: Dict[str, Any],
    ) -> ExtractedCompanyGroup:
        company_group_id = self._normalize_integer(
            self._resolve_value(
                raw_company_group,
                _COMPANY_GROUP_ENTITY_ID_PATHS,
                "ID группы компаний",
                value_normalizer=self._normalize_integer,
            ),
            "ID группы компаний",
        )
        name = self._normalize_required_text(
            self._resolve_value(
                raw_company_group,
                _COMPANY_GROUP_NAME_PATHS,
                "название группы компаний",
                value_normalizer=self._normalize_required_text,
            ),
            "Название группы компаний",
        )

        try:
            return ExtractedCompanyGroup(id=company_group_id, name=name)
        except ValueError as exc:
            raise NashDomNormalizationError(
                f"Группа компаний NashDom с ID {company_group_id} "
                f"нарушает контракт: {exc}"
            ) from exc

    def _normalize_developer(
        self,
        raw_developer: Dict[str, Any],
    ) -> ExtractedDeveloper:
        developer_id = self._normalize_integer(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_ID_PATHS,
                "ID застройщика",
                value_normalizer=self._normalize_integer,
            ),
            "ID застройщика",
        )
        short_name = self._normalize_required_text(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_SHORT_NAME_PATHS,
                "краткое наименование застройщика",
                value_normalizer=self._normalize_required_text,
            ),
            "Краткое наименование застройщика",
        )
        full_name = self._normalize_required_text(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_FULL_NAME_PATHS,
                "полное наименование застройщика",
                value_normalizer=self._normalize_required_text,
            ),
            "Полное наименование застройщика",
        )
        inn = self._normalize_required_text(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_INN_PATHS,
                "ИНН застройщика",
                value_normalizer=self._normalize_required_text,
            ),
            "ИНН застройщика",
        )
        kpp = self._normalize_required_text(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_KPP_PATHS,
                "КПП застройщика",
                value_normalizer=self._normalize_required_text,
            ),
            "КПП застройщика",
        )
        ogrn = self._normalize_required_text(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_OGRN_PATHS,
                "ОГРН застройщика",
                value_normalizer=self._normalize_required_text,
            ),
            "ОГРН застройщика",
        )
        region_id = self._normalize_integer(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_REGION_ID_PATHS,
                "ID региона застройщика",
                value_normalizer=self._normalize_integer,
            ),
            "ID региона застройщика",
        )
        legal_address = self._normalize_required_text(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_LEGAL_ADDRESS_PATHS,
                "юридический адрес застройщика",
                value_normalizer=self._normalize_required_text,
            ),
            "Юридический адрес застройщика",
        )
        fact_address = self._normalize_required_text(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_FACT_ADDRESS_PATHS,
                "фактический адрес застройщика",
                value_normalizer=self._normalize_required_text,
            ),
            "Фактический адрес застройщика",
        )
        contact_name = self._normalize_required_text(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_CONTACT_NAME_PATHS,
                "контактное лицо застройщика",
                value_normalizer=self._normalize_required_text,
            ),
            "Контактное лицо застройщика",
        )
        phone = self._normalize_required_text(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_PHONE_PATHS,
                "телефон застройщика",
                value_normalizer=self._normalize_required_text,
            ),
            "Телефон застройщика",
        )
        email = self._normalize_required_text(
            self._resolve_value(
                raw_developer,
                _DEVELOPER_EMAIL_PATHS,
                "email застройщика",
                value_normalizer=self._normalize_required_text,
            ),
            "Email застройщика",
        )
        raw_url = self._resolve_value(
            raw_developer,
            _DEVELOPER_URL_PATHS,
            "URL застройщика",
            required=False,
            value_normalizer=self._normalize_optional_text,
        )
        url = None if raw_url is None else self._normalize_optional_text(raw_url)
        raw_company_group_id = self._resolve_value(
            raw_developer,
            _DEVELOPER_COMPANY_GROUP_ID_PATHS,
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
            return ExtractedDeveloper(
                id=developer_id,
                short_name=short_name,
                full_name=full_name,
                inn=inn,
                kpp=kpp,
                ogrn=ogrn,
                region_id=region_id,
                legal_address=legal_address,
                fact_address=fact_address,
                contact_name=contact_name,
                phone=phone,
                email=email,
                url=url,
                company_group_id=company_group_id,
            )
        except ValueError as exc:
            raise NashDomNormalizationError(
                f"Застройщик NashDom с ID {developer_id} нарушает контракт: {exc}"
            ) from exc

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
        address = self._normalize_required_text(
            self._resolve_value(
                raw_object,
                _ADDRESS_PATHS,
                "адрес объекта",
                value_normalizer=self._normalize_required_text,
            ),
            "Адрес объекта",
        )
        raw_title = self._resolve_value(
            raw_object,
            _TITLE_PATHS,
            "название объекта",
            required=False,
        )
        title = self._normalize_title(raw_title, address)
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
                _OBJECT_DEVELOPER_ID_PATHS,
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
    def _normalize_optional_text(value: Any) -> str:
        if not isinstance(value, str):
            raise NashDomNormalizationError("URL застройщика должен быть строкой")
        if not value.strip():
            raise NashDomNormalizationError("URL застройщика не должен быть пустым")
        return value.strip()

    @staticmethod
    def _normalize_title(value: Any, address: str) -> str:
        if value is None:
            return address
        if not isinstance(value, str):
            raise NashDomNormalizationError("Название объекта должно быть строкой")

        normalized_title = value.strip()
        return normalized_title or address

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
