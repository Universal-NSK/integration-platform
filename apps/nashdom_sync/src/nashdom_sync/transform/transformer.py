from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence, Set, Tuple, TypeVar

from nashdom_sync.contracts import (
    CrmContext,
    ExtractedCompanyGroup,
    ExtractedDeveloper,
    ExtractedObject,
    ExtractedObjectTypeEnum,
    ExtractResult,
    RegionSettings,
)
from nashdom_sync.contracts.transform import (
    AddAddressCommand,
    AddItemCommand,
    AddRequisiteCommand,
    PlannedOperation,
    RuntimeBinding,
    SyncPlan,
)
from nashdom_sync.transform.exceptions import TransformInputError

K = TypeVar("K")
V = TypeVar("V")
T = TypeVar("T")


def _index(items: Iterable[T], key: Callable[[T], K], value: Callable[[T], V]) -> Dict[K, V]:
    result: Dict[K, V] = {}
    for item in items:
        item_key = key(item)
        if item_key in result:
            # Не включаем естественные ключи (в частности ИНН или имена сотрудников) в ошибки.
            raise TransformInputError("Повторяющийся ключ индекса входных данных")
        result[item_key] = value(item)
    return result


@dataclass(frozen=True)
class _TransformIndexes:
    developers_by_id: Mapping[int, ExtractedDeveloper]
    company_groups_by_id: Mapping[int, ExtractedCompanyGroup]
    existing_leads_by_source_id: Mapping[int, int]
    existing_developers_by_inn: Mapping[str, int]
    existing_company_groups_by_source_id: Mapping[int, int]
    managers_by_name: Mapping[str, int]


class SyncPlanTransformer:
    """Построить детерминированный план по возрастанию исходных ID внутри каждой фазы."""

    def transform(
        self,
        extract_result: ExtractResult,
        crm_context: CrmContext,
        region_settings: RegionSettings,
    ) -> SyncPlan:
        indexes = self._build_indexes(extract_result, crm_context)
        # Проверяем все настроенные имена, включая неиспользованные назначения по регионам.
        self._resolve_default_manager_id(region_settings, indexes)
        for region_id in region_settings.assignment:
            self._resolve_region_manager_id(region_id, region_settings, indexes)
        objects = self._select_new_objects(extract_result.objects, indexes)
        developers = self._collect_required_developers(objects, indexes)
        groups = self._collect_required_company_groups(objects, indexes)
        return SyncPlan(
            self._build_company_group_operations(groups, indexes, crm_context, region_settings)
            + self._build_developer_operations(developers, indexes, crm_context, region_settings)
            + self._build_lead_operations(objects, indexes, crm_context, region_settings)
        )

    def _build_indexes(
        self, extract_result: ExtractResult, crm_context: CrmContext
    ) -> _TransformIndexes:
        return _TransformIndexes(
            _index(extract_result.developers, lambda x: x.id, lambda x: x),
            _index(extract_result.company_groups, lambda x: x.id, lambda x: x),
            _index(crm_context.existing.leads, lambda x: x.source_id, lambda x: x.crm_id),
            _index(crm_context.existing.developers, lambda x: x.inn, lambda x: x.crm_id),
            _index(crm_context.existing.company_groups, lambda x: x.source_id, lambda x: x.crm_id),
            _index(crm_context.managers, lambda x: x.configured_name, lambda x: x.crm_id),
        )

    def _select_new_objects(
        self,
        objects: Sequence[ExtractedObject],
        indexes: _TransformIndexes,
    ) -> Tuple[ExtractedObject, ...]:
        unique = _index(objects, lambda x: x.id, lambda x: x)
        return tuple(
            unique[key] for key in sorted(unique) if key not in indexes.existing_leads_by_source_id
        )

    def _collect_required_developers(
        self,
        objects: Tuple[ExtractedObject, ...],
        indexes: _TransformIndexes,
    ) -> Tuple[ExtractedDeveloper, ...]:
        required = sorted({obj.developer_id for obj in objects})
        if any(key not in indexes.developers_by_id for key in required):
            raise TransformInputError("Отсутствует необходимый застройщик")
        developers = tuple(indexes.developers_by_id[key] for key in required)
        # Разные исходные ID при одном естественном ключе создают неоднозначность:
        # не создаём дубликаты компаний и не выбираем произвольно данные или ответственного.
        _index(developers, lambda x: x.inn, lambda x: x)
        return developers

    def _collect_required_company_groups(
        self,
        objects: Tuple[ExtractedObject, ...],
        indexes: _TransformIndexes,
    ) -> Tuple[ExtractedCompanyGroup, ...]:
        required: Set[int] = set()
        developer_groups: Dict[int, int] = {}
        for obj in objects:
            group_id = obj.company_group_id
            if group_id is None:
                continue
            developer = indexes.developers_by_id.get(obj.developer_id)
            if developer is None:
                raise TransformInputError("Отсутствует необходимый застройщик")
            if developer.company_group_id is not None and developer.company_group_id != group_id:
                raise TransformInputError("Группы объекта и застройщика не совпадают")
            if (
                obj.developer_id in developer_groups
                and developer_groups[obj.developer_id] != group_id
            ):
                raise TransformInputError("У объектов одного застройщика указаны разные группы")
            developer_groups[obj.developer_id] = group_id
            required.add(group_id)
        if any(key not in indexes.company_groups_by_id for key in required):
            raise TransformInputError("Отсутствует необходимая группа компаний")
        return tuple(indexes.company_groups_by_id[key] for key in sorted(required))

    def _build_company_group_operations(
        self,
        company_groups: Tuple[ExtractedCompanyGroup, ...],
        indexes: _TransformIndexes,
        crm_context: CrmContext,
        region_settings: RegionSettings,
    ) -> Tuple[PlannedOperation, ...]:
        fields = crm_context.structure.entity_fields.company_group
        return tuple(
            PlannedOperation(
                f"group:{group.id}",
                AddItemCommand(
                    crm_context.structure.entity_types.company_group,
                    {
                        fields.title: group.name,
                        fields.source_company_group_id: group.id,
                        fields.source_id: crm_context.references.source_id,
                        fields.assigned_by_id: self._resolve_default_manager_id(
                            region_settings, indexes
                        ),
                    },
                ),
            )
            for group in company_groups
            if group.id not in indexes.existing_company_groups_by_source_id
        )

    def _build_developer_operations(
        self,
        developers: Tuple[ExtractedDeveloper, ...],
        indexes: _TransformIndexes,
        crm_context: CrmContext,
        region_settings: RegionSettings,
    ) -> Tuple[PlannedOperation, ...]:
        operations: List[PlannedOperation] = []
        structure, refs = crm_context.structure, crm_context.references
        fields, mf = structure.entity_fields.developer, structure.entity_fields.multifield
        req, address = structure.entity_fields.requisite, structure.entity_fields.address
        for developer in developers:
            if developer.inn in indexes.existing_developers_by_inn:
                continue
            company_id, requisite_id = f"company:{developer.id}", f"requisite:{developer.id}"
            multifields = [
                {mf.value_type: refs.multifield.value_type, mf.type_id: type_id, mf.value: value}
                for type_id, value in (
                    (refs.multifield.phone_type_id, developer.phone),
                    (refs.multifield.email_type_id, developer.email),
                    (refs.multifield.web_type_id, developer.url),
                )
                if value is not None
            ]
            operations.append(
                PlannedOperation(
                    company_id,
                    AddItemCommand(
                        structure.entity_types.company,
                        {
                            fields.title: developer.short_name,
                            fields.assigned_by_id: self._resolve_region_manager_id(
                                developer.region_id, region_settings, indexes
                            ),
                            fields.company_type: refs.developer_company_type_id,
                            fields.industry: refs.developer_industry_id,
                            fields.contact_name: developer.contact_name,
                            fields.source_developer_id: developer.id,
                            fields.multifield: multifields,
                        },
                    ),
                )
            )
            operations.append(
                PlannedOperation(
                    requisite_id,
                    AddRequisiteCommand(
                        {
                            req.entity_type_id: structure.entity_types.company,
                            req.preset_id: refs.organization_requisite_preset_id,
                            req.card_name: developer.short_name,
                            req.details_name: developer.short_name,
                            req.full_name: developer.full_name,
                            req.inn: developer.inn,
                            req.kpp: developer.kpp,
                            req.ogrn: developer.ogrn,
                        },
                    ),
                    (RuntimeBinding(req.entity_id_to_bind, company_id),),
                )
            )
            for kind, type_id, value in (
                ("actual", refs.address_types.actual, developer.fact_address),
                ("legal", refs.address_types.legal, developer.legal_address),
            ):
                operations.append(
                    PlannedOperation(
                        f"address:{developer.id}:{kind}",
                        AddAddressCommand(
                            {
                                address.address_type_id: type_id,
                                address.entity_type_id_to_bind: structure.entity_types.requisite,
                                address.address: value,
                            },
                        ),
                        (RuntimeBinding(address.entity_id_to_bind, requisite_id),),
                    )
                )
        return tuple(operations)

    def _build_lead_operations(
        self,
        objects: Tuple[ExtractedObject, ...],
        indexes: _TransformIndexes,
        crm_context: CrmContext,
        region_settings: RegionSettings,
    ) -> Tuple[PlannedOperation, ...]:
        operations: List[PlannedOperation] = []
        fields, refs = crm_context.structure.entity_fields.lead, crm_context.references
        for obj in objects:
            developer = indexes.developers_by_id[obj.developer_id]
            if obj.object_type == ExtractedObjectTypeEnum.RESIDENTIAL:
                building_type = refs.building_type.residential
            elif obj.object_type == ExtractedObjectTypeEnum.NON_RESIDENTIAL:
                building_type = refs.building_type.non_residential
            else:
                raise TransformInputError("Неподдерживаемый тип объекта")
            payload: Dict[str, Any] = {
                fields.source_building_id: obj.id,
                fields.title: obj.title,
                fields.address: obj.address,
                fields.publication_date: obj.publication_date.isoformat(),
                fields.commissioning_period: str(obj.commissioning_period),
                fields.building_type: building_type,
                fields.source_id: refs.source_id,
                fields.assigned_by_id: self._resolve_region_manager_id(
                    obj.region_id, region_settings, indexes
                ),
            }
            bindings: List[RuntimeBinding] = []
            dependencies: Tuple[str, ...] = ()
            if developer.inn in indexes.existing_developers_by_inn:
                payload[fields.company_id] = indexes.existing_developers_by_inn[developer.inn]
            else:
                bindings.append(RuntimeBinding(fields.company_id, f"company:{developer.id}"))
                dependencies = (
                    f"requisite:{developer.id}",
                    f"address:{developer.id}:actual",
                    f"address:{developer.id}:legal",
                )
            if obj.company_group_id is not None:
                group_id = obj.company_group_id
                if group_id in indexes.existing_company_groups_by_source_id:
                    payload[fields.company_group_bitrix_id] = (
                        indexes.existing_company_groups_by_source_id[group_id]
                    )
                else:
                    bindings.append(
                        RuntimeBinding(fields.company_group_bitrix_id, f"group:{group_id}")
                    )
            operations.append(
                PlannedOperation(
                    f"lead:{obj.id}",
                    AddItemCommand(
                        crm_context.structure.entity_types.lead,
                        payload,
                    ),
                    tuple(bindings),
                    dependencies,
                )
            )
        return tuple(operations)

    def _resolve_region_manager_id(
        self,
        region_id: int,
        region_settings: RegionSettings,
        indexes: _TransformIndexes,
    ) -> int:
        name = region_settings.assignment.get(region_id, region_settings.default_assigned_by_name)
        if name not in indexes.managers_by_name:
            raise TransformInputError("Не найден ответственный для региона")
        return indexes.managers_by_name[name]

    def _resolve_default_manager_id(
        self, region_settings: RegionSettings, indexes: _TransformIndexes
    ) -> int:
        name = region_settings.default_assigned_by_name
        if name not in indexes.managers_by_name:
            raise TransformInputError("Не найден ответственный по умолчанию")
        return indexes.managers_by_name[name]
