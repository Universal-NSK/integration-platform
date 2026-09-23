"""Метаданные crm.item.fields, предоставленные владельцем портала 24.09.2026."""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class FieldSpec:
    title: str
    fallback_upper_name: Optional[str] = None


LEAD_FIELDS: Dict[str, FieldSpec] = {
    "source_building_id": FieldSpec("ID объекта (Из источника)", "UF_CRM_1754293174"),
    "address": FieldSpec("Адрес", "UF_CRM_1790173341"),
    "publication_date": FieldSpec("Дата публикации объекта", "UF_CRM_1754445745"),
    "building_type": FieldSpec("Тип объекта", "UF_CRM_1754445977"),
    "commissioning_period": FieldSpec("Ввод в эксплуатацию", "UF_CRM_1754445867"),
}

DEVELOPER_FIELDS: Dict[str, FieldSpec] = {
    "contact_name": FieldSpec("ЛПР", "UF_CRM_1754447476814"),
    "source_developer_id": FieldSpec("ID компании (Из источника)", "UF_CRM_1777639761"),
}

COMPANY_GROUP_FIELDS: Dict[str, FieldSpec] = {
    "source_company_group_id": FieldSpec("ID (из источника)", "UF_CRM_10_1789999470"),
}
