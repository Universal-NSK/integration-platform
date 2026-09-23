import logging
import math
import re
from typing import Any, Dict, List, Tuple, cast

from platform_logging import log_event

from nashdom_sync.bitrix_crm import ClientBitrixCRM
from nashdom_sync.bitrix_crm.exceptions import BitrixClientError, BitrixGatewayError
from nashdom_sync.contracts.crm import (
    AddressFieldsBindings,
    CompanyGroupFieldsBindings,
    CrmAddressType,
    CrmBuildingType,
    CrmContext,
    CrmEmployee,
    CrmEntityFields,
    CrmEntityTypeId,
    CrmMultiField,
    CrmReferences,
    CrmStructure,
    DeveloperFieldsBindings,
    ExistingCrmEntities,
    ExistingCrmEntity,
    LeadFieldsBindings,
    MultiFieldFieldsBindings,
    RequisiteFieldsBindings,
)
from nashdom_sync.contracts.settings import BitrixClientSettings, RegionSettings

from .exceptions import (
    CrmAmbiguousSemanticError,
    CrmInvalidDataError,
    CrmMissingSemanticError,
    CrmProviderError,
)
from .fields import COMPANY_GROUP_FIELDS, DEVELOPER_FIELDS, LEAD_FIELDS, FieldSpec

logger = logging.getLogger(__name__)


class CrmProvider:
    """Готовит полный контекст; владеет отдельным клиентом на каждый provide()."""

    def __init__(self, bitrix_client_settings: BitrixClientSettings) -> None:
        self._settings = bitrix_client_settings
        self._client: ClientBitrixCRM

    def provide(self, region_settings: RegionSettings) -> CrmContext:
        """Подготовить контекст целиком и закрыть HTTP-ресурсы, в том числе при ошибке."""
        self._client = ClientBitrixCRM(
            gateway_url=self._settings.gateway_url, timeout=self._settings.timeout
        )
        try:
            structure = self._build_structure()
            references = self._build_references()
            existing = self._build_existing(structure)
            managers = self._build_managers(region_settings)
            return CrmContext(structure, references, existing, managers)
        except BitrixGatewayError as exc:
            raise CrmInvalidDataError(
                "CRM: недоступен Gateway или нарушен контракт ответа"
            ) from exc
        except BitrixClientError as exc:
            raise CrmProviderError("CRM: не удалось прочитать обязательные данные") from exc
        finally:
            self._client.close()

    def _build_structure(self) -> CrmStructure:
        entity_types = self._resolve_entity_type_ids()
        return CrmStructure(entity_types, self._resolve_entity_fields(entity_types))

    def _resolve_entity_type_ids(self) -> CrmEntityTypeId:
        group = self._unique(self._client.list_owner_types(), "NAME", "Группа компаний")
        return CrmEntityTypeId(
            lead=1,
            company=4,
            company_group=self._id(group.get("ID"), "entity type: Группа компаний"),
            requisite=8,
        )

    def _resolve_entity_fields(self, entity_type_ids: CrmEntityTypeId) -> CrmEntityFields:
        return CrmEntityFields(
            lead=self._build_lead_fields(
                self._client.get_item_fields(entity_type_ids.lead),
                entity_type_ids.company_group,
            ),
            developer=self._build_developer_fields(
                self._client.get_item_fields(entity_type_ids.company)
            ),
            company_group=self._build_company_group_fields(
                self._client.get_item_fields(entity_type_ids.company_group)
            ),
            requisite=RequisiteFieldsBindings(),
            address=AddressFieldsBindings(),
            multifield=MultiFieldFieldsBindings(),
        )

    def _build_lead_fields(
        self, raw_fields: Dict[str, Any], company_group_entity_type_id: int
    ) -> LeadFieldsBindings:
        resolved = self._resolve_fields(raw_fields, LEAD_FIELDS)
        return LeadFieldsBindings(
            company_group_bitrix_id=f"parentId{company_group_entity_type_id}",
            **resolved,
        )

    def _build_developer_fields(self, raw_fields: Dict[str, Any]) -> DeveloperFieldsBindings:
        return DeveloperFieldsBindings(**self._resolve_fields(raw_fields, DEVELOPER_FIELDS))

    def _build_company_group_fields(self, raw_fields: Dict[str, Any]) -> CompanyGroupFieldsBindings:
        return CompanyGroupFieldsBindings(**self._resolve_fields(raw_fields, COMPANY_GROUP_FIELDS))

    def _resolve_fields(
        self, raw_fields: Dict[str, Any], expected_fields: Dict[str, FieldSpec]
    ) -> Dict[str, str]:
        fields: Dict[str, Dict[str, Any]] = {}
        for key, metadata in raw_fields.items():
            if not key.strip() or not isinstance(metadata, dict):
                raise CrmInvalidDataError("crm.item.fields: некорректные метаданные поля")
            fields[key] = cast(Dict[str, Any], metadata)
        resolved: Dict[str, str] = {}
        for binding, spec in expected_fields.items():
            matches = [
                key for key, metadata in fields.items() if metadata.get("title") == spec.title
            ]
            if len(matches) == 1:
                resolved[binding] = matches[0]
                continue
            fallback = [
                key
                for key in (matches if matches else fields)
                if spec.fallback_upper_name is not None
                and fields[key].get("upperName") == spec.fallback_upper_name
            ]
            if len(fallback) == 1:
                resolved[binding] = fallback[0]
                log_event(
                    logger,
                    logging.WARNING,
                    "crm_field_upper_name_fallback",
                    title=spec.title,
                    reason="title_ambiguous" if matches else "title_missing",
                    upper_name=spec.fallback_upper_name,
                )
            elif matches or len(fallback) > 1:
                raise CrmAmbiguousSemanticError(
                    f'CRM field "{spec.title}": неоднозначное соответствие'
                )
            else:
                raise CrmMissingSemanticError(f'CRM field "{spec.title}": поле не найдено')
        return resolved

    @staticmethod
    def _unique(records: List[Dict[str, Any]], key: str, expected: str) -> Dict[str, Any]:
        matches = [record for record in records if record.get(key) == expected]
        if not matches:
            raise CrmMissingSemanticError(f'CRM {key}="{expected}": соответствие не найдено')
        if len(matches) != 1:
            raise CrmAmbiguousSemanticError(f'CRM {key}="{expected}": неоднозначное соответствие')
        return matches[0]

    @staticmethod
    def _id(value: Any, context: str, *, source: bool = False) -> int:
        # Пользовательские поля double могут вернуть 123.0 / "123.00".
        # Дробную часть не отбрасываем, bool и нечисловые значения не принимаем.
        if type(value) is int and value > 0:
            return value
        if isinstance(value, str):
            pattern = r"[0-9]+(?:\.0+)?" if source else r"[0-9]+"
            if re.fullmatch(pattern, value):
                number = int(value.split(".")[0])
                if number > 0:
                    return number
        if source and type(value) is float:
            if math.isfinite(value) and value.is_integer() and 0 < value < 2**53:
                return int(value)
        raise CrmInvalidDataError(f"CRM {context}: ожидался положительный целочисленный ID")

    @staticmethod
    def _status_id(record: Dict[str, Any], context: str) -> str:
        value: Any = record.get("STATUS_ID")
        if not isinstance(value, str) or not value.strip():
            raise CrmInvalidDataError(f"CRM {context}: отсутствует непустой STATUS_ID")
        return value

    def _build_references(self) -> CrmReferences:
        source = self._unique(self._client.list_statuses("SOURCE"), "NAME", "наш.дом.рф")
        industry = self._unique(self._client.list_statuses("INDUSTRY"), "NAME", "Застройщик")
        company_type = self._unique(self._client.list_statuses("COMPANY_TYPE"), "NAME", "Партнер")
        preset = self._unique(self._client.list_requisite_presets(), "NAME", "Организация")
        addresses = self._client.list_address_types()
        actual = self._unique(addresses, "NAME", "Фактический адрес")
        legal = self._unique(addresses, "NAME", "Юридический адрес")
        return CrmReferences(
            source_id=self._status_id(source, "SOURCE"),
            building_type=CrmBuildingType(),
            developer_industry_id=self._status_id(industry, "INDUSTRY"),
            developer_company_type_id=self._status_id(company_type, "COMPANY_TYPE"),
            organization_requisite_preset_id=self._id(preset.get("ID"), "Организация"),
            address_types=CrmAddressType(
                actual=self._id(actual.get("ID"), "Фактический адрес"),
                legal=self._id(legal.get("ID"), "Юридический адрес"),
            ),
            multifield=CrmMultiField(),
        )

    def _build_existing(self, structure: CrmStructure) -> ExistingCrmEntities:
        types, fields = structure.entity_types, structure.entity_fields
        return ExistingCrmEntities(
            leads=self._load_existing_entities(types.lead, fields.lead.source_building_id),
            developers=self._load_existing_entities(
                types.company, fields.developer.source_developer_id
            ),
            company_groups=self._load_existing_entities(
                types.company_group, fields.company_group.source_company_group_id
            ),
        )

    def _load_existing_entities(
        self, entity_type_id: int, source_id_field: str
    ) -> Tuple[ExistingCrmEntity, ...]:
        records = self._client.list_items(entity_type_id, select=["id", source_id_field])
        result: List[ExistingCrmEntity] = []
        seen: Dict[int, int] = {}
        for index, record in enumerate(records):
            context = f"entityTypeId={entity_type_id}, запись {index}"
            crm_id = self._id(record.get("id"), f"{context}, id")
            source_id = self._id(
                record.get(source_id_field),
                f"{context}, {source_id_field}",
                source=True,
            )
            if source_id in seen:
                raise CrmInvalidDataError(
                    f"CRM entityTypeId={entity_type_id}: повтор source_id={source_id}, "
                    f"crm_id={seen[source_id]} и {crm_id}"
                )
            seen[source_id] = crm_id
            result.append(ExistingCrmEntity(source_id, crm_id))
        return tuple(result)

    def _build_managers(self, region_settings: RegionSettings) -> Tuple[CrmEmployee, ...]:
        # Сохраняем исходные configured_name для последующего точного связывания в Transform.
        names = dict.fromkeys(
            [
                region_settings.default_assigned_by_name,
                *region_settings.assignment.values(),
            ]
        )
        return tuple(self._resolve_manager(name) for name in names)

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.split()).casefold()

    def _resolve_manager(self, name: str) -> CrmEmployee:
        matches: List[Dict[str, Any]] = []
        for candidate in self._client.search_users(name):
            if "ACTIVE" in candidate:
                active: Any = candidate["ACTIVE"]
                if active is False or active in ("N", "0", 0):
                    continue
                if not (active is True or active in ("Y", "1", 1)):
                    raise CrmInvalidDataError("CRM user.search: некорректный ACTIVE")
            if "USER_TYPE" in candidate and candidate["USER_TYPE"] != "employee":
                continue
            parts: List[str] = []
            for field in ("LAST_NAME", "NAME", "SECOND_NAME"):
                part: Any = candidate.get(field, "")
                if part is None:
                    part = ""
                if not isinstance(part, str):
                    raise CrmInvalidDataError(f"CRM user.search: некорректный {field}")
                parts.append(part)
            if self._normalize_name(" ".join(parts)) == self._normalize_name(name):
                matches.append(candidate)
        if not matches:
            raise CrmMissingSemanticError(f'CRM manager "{name}": точное ФИО не найдено')
        if len(matches) != 1:
            raise CrmAmbiguousSemanticError(f'CRM manager "{name}": неоднозначное ФИО')
        return CrmEmployee(name, self._id(matches[0].get("ID"), "user.search ID"))
