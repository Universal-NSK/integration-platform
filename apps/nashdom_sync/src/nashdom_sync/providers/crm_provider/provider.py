import logging
import math
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple, cast

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


@dataclass
class _ExistingLoadStats:
    received: int = 0
    indexed: int = 0
    skipped_empty: int = 0
    duplicate_source_ids: int = 0


@dataclass
class _CrmProviderRunStats:
    leads: _ExistingLoadStats = dataclass_field(default_factory=_ExistingLoadStats)
    developers: _ExistingLoadStats = dataclass_field(default_factory=_ExistingLoadStats)
    company_groups: _ExistingLoadStats = dataclass_field(default_factory=_ExistingLoadStats)
    managers_resolved: int = 0
    structure_duration_seconds: float = 0.0
    references_duration_seconds: float = 0.0
    existing_duration_seconds: float = 0.0
    managers_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0

    def log_fields(self) -> Dict[str, Any]:
        fields: Dict[str, Any] = {
            "managers_resolved": self.managers_resolved,
            "structure_duration_seconds": self.structure_duration_seconds,
            "references_duration_seconds": self.references_duration_seconds,
            "existing_duration_seconds": self.existing_duration_seconds,
            "managers_duration_seconds": self.managers_duration_seconds,
            "total_duration_seconds": self.total_duration_seconds,
            # Number of extra lead records skipped, not distinct duplicated keys.
            "lead_duplicate_source_ids": self.leads.duplicate_source_ids,
        }
        for name, stats in (
            ("leads", self.leads),
            ("developers", self.developers),
            ("company_groups", self.company_groups),
        ):
            fields.update(
                {
                    f"{name}_received": stats.received,
                    f"{name}_indexed": stats.indexed,
                    f"{name}_skipped_empty": stats.skipped_empty,
                }
            )
        return fields


class CrmProvider:
    """Готовит полный контекст; владеет отдельным клиентом на каждый provide()."""

    def __init__(self, bitrix_client_settings: BitrixClientSettings) -> None:
        self._settings = bitrix_client_settings
        self._client: ClientBitrixCRM
        self._stage = "client.create"
        self._stats = _CrmProviderRunStats()

    def provide(self, region_settings: RegionSettings) -> CrmContext:
        """Подготовить контекст целиком и закрыть HTTP-ресурсы, в том числе при ошибке."""
        total_started_at = perf_counter()
        self._stage = "client.create"
        stats = self._stats = _CrmProviderRunStats()
        log_event(
            logger,
            logging.INFO,
            "crm_provider_started",
            configured_managers_count=len(
                {
                    region_settings.default_assigned_by_name,
                    *region_settings.assignment.values(),
                }
            ),
            region_assignment_count=len(region_settings.assignment),
        )
        stage_started_at = total_started_at
        phase = "client"
        try:
            self._client = ClientBitrixCRM(
                gateway_url=self._settings.gateway_url, timeout=self._settings.timeout
            )
            try:
                phase = "structure"
                self._stage = phase
                stage_started_at = perf_counter()
                structure = self._build_structure()
                stats.structure_duration_seconds = perf_counter() - stage_started_at
                log_event(
                    logger,
                    logging.INFO,
                    "crm_structure_built",
                    lead_entity_type_id=structure.entity_types.lead,
                    company_entity_type_id=structure.entity_types.company,
                    company_group_entity_type_id=structure.entity_types.company_group,
                    requisite_entity_type_id=structure.entity_types.requisite,
                    duration_seconds=stats.structure_duration_seconds,
                )

                phase = "references"
                self._stage = phase
                stage_started_at = perf_counter()
                references = self._build_references()
                stats.references_duration_seconds = perf_counter() - stage_started_at
                log_event(
                    logger,
                    logging.INFO,
                    "crm_references_built",
                    source_id=references.source_id,
                    developer_industry_id=references.developer_industry_id,
                    developer_company_type_id=references.developer_company_type_id,
                    requisite_preset_id=references.organization_requisite_preset_id,
                    actual_address_type_id=references.address_types.actual,
                    legal_address_type_id=references.address_types.legal,
                    duration_seconds=stats.references_duration_seconds,
                )

                phase = "existing"
                self._stage = phase
                stage_started_at = perf_counter()
                existing = self._build_existing(structure)
                stats.existing_duration_seconds = perf_counter() - stage_started_at
                log_event(
                    logger,
                    logging.INFO,
                    "crm_existing_loaded",
                    leads=len(existing.leads),
                    developers=len(existing.developers),
                    company_groups=len(existing.company_groups),
                    leads_skipped_empty=stats.leads.skipped_empty,
                    developers_skipped_empty=stats.developers.skipped_empty,
                    company_groups_skipped_empty=stats.company_groups.skipped_empty,
                    lead_duplicate_source_ids=stats.leads.duplicate_source_ids,
                    duration_seconds=stats.existing_duration_seconds,
                )

                phase = "managers"
                self._stage = phase
                stage_started_at = perf_counter()
                managers = self._build_managers(region_settings)
                stats.managers_duration_seconds = perf_counter() - stage_started_at
                log_event(
                    logger,
                    logging.INFO,
                    "crm_managers_resolved",
                    managers=len(managers),
                    duration_seconds=stats.managers_duration_seconds,
                )
                self._stage = "context"
                result = CrmContext(structure, references, existing, managers)
                self._stage = "client.close"
            finally:
                try:
                    self._client.close()
                except Exception:
                    self._stage = "client.close"
                    raise
        except Exception as exc:
            failed_at = perf_counter()
            stats.total_duration_seconds = failed_at - total_started_at
            if self._stage.startswith(phase):
                duration = failed_at - stage_started_at
                if phase == "structure":
                    stats.structure_duration_seconds = duration
                elif phase == "references":
                    stats.references_duration_seconds = duration
                elif phase == "existing":
                    stats.existing_duration_seconds = duration
                elif phase == "managers":
                    stats.managers_duration_seconds = duration
            log_event(
                logger,
                logging.ERROR,
                "crm_provider_failed",
                stage=self._stage,
                elapsed_seconds=stats.total_duration_seconds,
                exception_type=type(exc).__name__,
                error=str(exc),
                **stats.log_fields(),
            )
            if isinstance(exc, BitrixGatewayError):
                raise CrmProviderError(
                    "CRM: недоступен Gateway или нарушен контракт ответа"
                ) from exc
            if isinstance(exc, BitrixClientError):
                raise CrmProviderError("CRM: не удалось прочитать обязательные данные") from exc
            raise
        stats.total_duration_seconds = perf_counter() - total_started_at
        log_event(logger, logging.INFO, "crm_provider_completed", **stats.log_fields())
        return result

    def _build_structure(self) -> CrmStructure:
        self._stage = "structure.entity_types"
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
        self._stage = "structure.lead_fields"
        lead = self._build_lead_fields(
            self._client.get_item_fields(entity_type_ids.lead),
            entity_type_ids.company_group,
        )
        self._stage = "structure.developer_fields"
        developer = self._build_developer_fields(
            self._client.get_item_fields(entity_type_ids.company)
        )
        self._stage = "structure.company_group_fields"
        company_group = self._build_company_group_fields(
            self._client.get_item_fields(entity_type_ids.company_group)
        )
        return CrmEntityFields(
            lead=lead,
            developer=developer,
            company_group=company_group,
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
        self._stage = "references.source"
        source = self._unique(self._client.list_statuses("SOURCE"), "NAME", "наш.дом.рф")
        source_id = self._status_id(source, "SOURCE")
        self._stage = "references.industry"
        industry = self._unique(self._client.list_statuses("INDUSTRY"), "NAME", "Застройщик")
        industry_id = self._status_id(industry, "INDUSTRY")
        self._stage = "references.company_type"
        company_type = self._unique(self._client.list_statuses("COMPANY_TYPE"), "NAME", "Партнер")
        company_type_id = self._status_id(company_type, "COMPANY_TYPE")
        self._stage = "references.requisite_preset"
        preset = self._unique(self._client.list_requisite_presets(), "NAME", "Организация")
        preset_id = self._id(preset.get("ID"), "Организация")
        self._stage = "references.address_types"
        addresses = self._client.list_address_types()
        actual = self._unique(addresses, "NAME", "Фактический адрес")
        legal = self._unique(addresses, "NAME", "Юридический адрес")
        return CrmReferences(
            source_id=source_id,
            building_type=CrmBuildingType(),
            developer_industry_id=industry_id,
            developer_company_type_id=company_type_id,
            organization_requisite_preset_id=preset_id,
            address_types=CrmAddressType(
                actual=self._id(actual.get("ID"), "Фактический адрес"),
                legal=self._id(legal.get("ID"), "Юридический адрес"),
            ),
            multifield=CrmMultiField(),
        )

    def _build_existing(self, structure: CrmStructure) -> ExistingCrmEntities:
        types, fields = structure.entity_types, structure.entity_fields
        self._stage = "existing.leads"
        leads = self._load_existing_entities(
            types.lead,
            fields.lead.source_building_id,
            allow_duplicates=True,
            stats=self._stats.leads,
        )
        self._stage = "existing.developers"
        developers = self._load_existing_entities(
            types.company,
            fields.developer.source_developer_id,
            stats=self._stats.developers,
        )
        self._stage = "existing.company_groups"
        company_groups = self._load_existing_entities(
            types.company_group,
            fields.company_group.source_company_group_id,
            stats=self._stats.company_groups,
        )
        return ExistingCrmEntities(
            leads=leads, developers=developers, company_groups=company_groups
        )

    def _load_existing_entities(
        self,
        entity_type_id: int,
        source_id_field: str,
        *,
        allow_duplicates: bool = False,
        stats: Optional[_ExistingLoadStats] = None,
    ) -> Tuple[ExistingCrmEntity, ...]:
        if stats is None:
            stats = _ExistingLoadStats()
        records = self._client.list_items(entity_type_id, select=["id", source_id_field])
        stats.received = len(records)
        result: List[ExistingCrmEntity] = []
        seen: Dict[int, int] = {}
        for index, record in enumerate(records):
            context = f"entityTypeId={entity_type_id}, запись {index}"
            crm_id = self._id(record.get("id"), f"{context}, id")
            context += f", crm_id={crm_id}"
            if source_id_field not in record:
                raise CrmInvalidDataError(f"CRM {context}: отсутствует поле {source_id_field}")
            raw_source_id = record[source_id_field]
            # В CRM есть записи без связи с источником; в индекс соответствий они не входят.
            if raw_source_id is None or (
                isinstance(raw_source_id, str) and not raw_source_id.strip()
            ):
                stats.skipped_empty += 1
                continue
            source_id = self._id(
                raw_source_id,
                f"{context}, {source_id_field}",
                source=True,
            )
            if source_id in seen:
                if allow_duplicates:
                    stats.duplicate_source_ids += 1
                    # Для лидов нужен факт существования; сохраняем первую запись ответа CRM.
                    continue
                raise CrmInvalidDataError(
                    f"CRM entityTypeId={entity_type_id}: повтор source_id={source_id}, "
                    f"crm_id={seen[source_id]} и {crm_id}"
                )
            seen[source_id] = crm_id
            result.append(ExistingCrmEntity(source_id, crm_id))
            stats.indexed += 1
        return tuple(result)

    def _build_managers(self, region_settings: RegionSettings) -> Tuple[CrmEmployee, ...]:
        # Сохраняем исходные configured_name для последующего точного связывания в Transform.
        names = dict.fromkeys(
            [
                region_settings.default_assigned_by_name,
                *region_settings.assignment.values(),
            ]
        )
        managers: List[CrmEmployee] = []
        for name in names:
            self._stage = f"managers.{name}"
            managers.append(self._resolve_manager(name))
            self._stats.managers_resolved = len(managers)
        return tuple(managers)

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.split()).casefold()

    def _resolve_manager(self, name: str) -> CrmEmployee:
        matches: List[Dict[str, Any]] = []
        for candidate in self._client.search_users(name):
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
            last_name, first_name, second_name = parts
            if not first_name.strip() or not last_name.strip():
                continue
            # Только точные варианты имени: отчество можно опустить, порядок — поменять.
            variants = (
                f"{first_name} {last_name}",
                f"{last_name} {first_name}",
                f"{last_name} {first_name} {second_name}",
                f"{first_name} {second_name} {last_name}",
            )
            if self._normalize_name(name) in {
                self._normalize_name(variant) for variant in variants
            }:
                matches.append(candidate)
        if not matches:
            raise CrmMissingSemanticError(
                f'CRM manager "{name}": совпадение имени и фамилии не найдено'
            )
        if len(matches) != 1:
            raise CrmAmbiguousSemanticError(f'CRM manager "{name}": неоднозначное имя и фамилия')
        return CrmEmployee(name, self._id(matches[0].get("ID"), "user.search ID"))
