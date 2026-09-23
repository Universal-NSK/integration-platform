"""Неизменяемый контекст CRM для последующих стадий синхронизации."""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class LeadFieldsBindings:
    source_building_id: str
    address: str
    publication_date: str
    building_type: str
    commissioning_period: str
    company_group_bitrix_id: str
    title: str = "title"
    assigned_by_id: str = "assignedById"
    company_id: str = "companyId"
    source_id: str = "sourceId"


@dataclass(frozen=True)
class DeveloperFieldsBindings:
    contact_name: str
    source_developer_id: str
    title: str = "title"
    assigned_by_id: str = "assignedById"
    company_type: str = "typeId"
    industry: str = "industry"
    multifield: str = "fm"


@dataclass(frozen=True)
class CompanyGroupFieldsBindings:
    source_company_group_id: str
    title: str = "title"
    source_id: str = "sourceId"
    assigned_by_id: str = "assignedById"


@dataclass(frozen=True)
class RequisiteFieldsBindings:
    entity_type_id: str = "ENTITY_TYPE_ID"
    entity_id_to_bind: str = "ENTITY_ID"
    preset_id: str = "PRESET_ID"
    card_name: str = "NAME"
    details_name: str = "RQ_COMPANY_NAME"
    full_name: str = "RQ_COMPANY_FULL_NAME"
    inn: str = "RQ_INN"
    kpp: str = "RQ_KPP"
    ogrn: str = "RQ_OGRN"


@dataclass(frozen=True)
class AddressFieldsBindings:
    address_type_id: str = "TYPE_ID"
    entity_type_id_to_bind: str = "ENTITY_TYPE_ID"
    entity_id_to_bind: str = "ENTITY_ID"
    address: str = "ADDRESS_2"


@dataclass(frozen=True)
class MultiFieldFieldsBindings:
    value_type: str = "valueType"
    value: str = "value"
    type_id: str = "typeId"


@dataclass(frozen=True)
class CrmEntityTypeId:
    lead: int
    company: int
    company_group: int
    requisite: int


@dataclass(frozen=True)
class CrmEntityFields:
    lead: LeadFieldsBindings
    developer: DeveloperFieldsBindings
    company_group: CompanyGroupFieldsBindings
    requisite: RequisiteFieldsBindings
    address: AddressFieldsBindings
    multifield: MultiFieldFieldsBindings


@dataclass(frozen=True)
class CrmStructure:
    entity_types: CrmEntityTypeId
    entity_fields: CrmEntityFields


@dataclass(frozen=True)
class ExistingCrmEntity:
    source_id: int
    crm_id: int


@dataclass(frozen=True)
class ExistingCrmEntities:
    leads: Tuple[ExistingCrmEntity, ...]
    developers: Tuple[ExistingCrmEntity, ...]
    company_groups: Tuple[ExistingCrmEntity, ...]


@dataclass(frozen=True)
class CrmEmployee:
    configured_name: str
    crm_id: int


@dataclass(frozen=True)
class CrmAddressType:
    actual: int
    legal: int


@dataclass(frozen=True)
class CrmMultiField:
    value_type: str = "WORK"
    phone_type_id: str = "PHONE"
    email_type_id: str = "EMAIL"
    web_type_id: str = "WEB"


@dataclass(frozen=True)
class CrmBuildingType:
    residential: str = "Жилое"
    non_residential: str = "Нежилое"


@dataclass(frozen=True)
class CrmReferences:
    source_id: str
    building_type: CrmBuildingType
    developer_industry_id: str
    developer_company_type_id: str
    organization_requisite_preset_id: int
    address_types: CrmAddressType
    multifield: CrmMultiField


@dataclass(frozen=True)
class CrmContext:
    structure: CrmStructure
    references: CrmReferences
    existing: ExistingCrmEntities
    managers: Tuple[CrmEmployee, ...]
