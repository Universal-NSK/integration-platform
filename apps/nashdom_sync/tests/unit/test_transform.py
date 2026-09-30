# pyright: reportPrivateUsage=false
import json
import logging
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, cast
from unittest.mock import Mock

import pytest
from nashdom_sync.contracts import (
    AddressFieldsBindings,
    CommissioningPeriod,
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
    ExistingCrmCompanyGroup,
    ExistingCrmDeveloper,
    ExistingCrmEntities,
    ExistingCrmLead,
    ExtractedCompanyGroup,
    ExtractedDeveloper,
    ExtractedObject,
    ExtractedObjectTypeEnum,
    ExtractResult,
    LeadFieldsBindings,
    MultiFieldFieldsBindings,
    RegionSettings,
    RequisiteFieldsBindings,
)
from nashdom_sync.contracts.transform import (
    AddAddressCommand,
    AddItemCommand,
    AddRequisiteCommand,
    CrmCommand,
    PlannedOperation,
    RuntimeBinding,
    SyncPlan,
    TransformResult,
)
from nashdom_sync.transform import (
    SyncPlanTransformer,
    SyncPlanValidationError,
    SyncPlanValidator,
    TransformError,
    TransformInputError,
    TransformService,
)
from platform_logging.formatter import DETAILS_ATTRIBUTE, EVENT_ATTRIBUTE


def context() -> CrmContext:
    # Нестандартные ID и имена полей проверяют отсутствие жёстко заданных привязок CRM.
    return CrmContext(
        CrmStructure(
            CrmEntityTypeId(101, 104, 105, 108),
            CrmEntityFields(
                LeadFieldsBindings(
                    "building",
                    "location",
                    "published",
                    "kind",
                    "period",
                    "parent",
                    "lead_title",
                    "lead_manager",
                    "company_ref",
                    "lead_source",
                ),
                DeveloperFieldsBindings(
                    "contact",
                    "company_title",
                    "company_manager",
                    "company_type",
                    "sector",
                    "multi",
                ),
                CompanyGroupFieldsBindings(
                    "group_source", "group_title", "source", "group_manager"
                ),
                RequisiteFieldsBindings(
                    "owner_type", "owner", "preset", "card", "short", "full", "inn", "kpp", "ogrn"
                ),
                AddressFieldsBindings("address_type", "owner_type", "owner", "address"),
                MultiFieldFieldsBindings("use", "text", "channel"),
            ),
        ),
        CrmReferences(
            "SOURCE",
            CrmBuildingType("RES", "NONRES"),
            "SECTOR",
            "TYPE",
            17,
            CrmAddressType(31, 36),
            CrmMultiField("BUSINESS", "TEL", "MAIL", "SITE"),
        ),
        ExistingCrmEntities((), (), ()),
        (CrmEmployee("default", 7), CrmEmployee("regional", 9)),
    )


def settings() -> RegionSettings:
    return RegionSettings(default_assigned_by_name="default", assignment={22: "regional"})


def source() -> ExtractResult:
    return ExtractResult(
        [
            ExtractedObject(
                1,
                "Title",
                "Object address",
                22,
                date(2026, 8, 21),
                CommissioningPeriod(2028, 4),
                ExtractedObjectTypeEnum.RESIDENTIAL,
                10,
                20,
            )
        ],
        [
            ExtractedDeveloper(
                10,
                "Short",
                "Full company name",
                "00123",
                "00456",
                "00789",
                22,
                "Legal address",
                "Actual address",
                "Contact person",
                "+70000000000",
                "mail@example.invalid",
                "https://example.invalid",
                20,
            )
        ],
        [ExtractedCompanyGroup(20, "Group")],
    )


def plan(data: ExtractResult, crm: CrmContext) -> SyncPlan:
    return TransformService().transform(data, crm, settings()).plan


@pytest.mark.parametrize(
    "dto",
    [
        AddItemCommand(1, {}),
        AddRequisiteCommand({}),
        AddAddressCommand({}),
        RuntimeBinding("target", "source"),
        PlannedOperation("id", AddItemCommand(1, {})),
        SyncPlan(()),
        TransformResult(SyncPlan(())),
    ],
)
def test_frozen_contracts(dto: Any) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(dto, fields(dto)[0].name, None)


def test_all_six_indexes() -> None:
    crm = replace(
        context(),
        existing=ExistingCrmEntities(
            (ExistingCrmLead(1, 11),),
            (ExistingCrmDeveloper("00123", 12),),
            (ExistingCrmCompanyGroup(20, 13),),
        ),
    )
    data = source()
    indexes = SyncPlanTransformer()._build_indexes(data, crm)
    assert indexes.developers_by_id == {10: data.developers[0]}
    assert indexes.company_groups_by_id == {20: data.company_groups[0]}
    assert indexes.existing_leads_by_source_id == {1: 11}
    assert indexes.existing_developers_by_inn == {"00123": 12}
    assert indexes.existing_company_groups_by_source_id == {20: 13}
    assert indexes.managers_by_name == {"default": 7, "regional": 9}


@pytest.mark.parametrize(
    "duplicate", ["objects", "developers", "groups", "leads", "inn", "crm_groups", "managers"]
)
def test_duplicate_inputs(duplicate: str) -> None:
    data, crm = source(), context()
    if duplicate == "objects":
        data = replace(data, objects=data.objects * 2)
    elif duplicate == "developers":
        data = replace(data, developers=data.developers * 2)
    elif duplicate == "groups":
        data = replace(data, company_groups=data.company_groups * 2)
    elif duplicate == "managers":
        crm = replace(crm, managers=crm.managers * 2)
    elif duplicate == "leads":
        crm = replace(
            crm,
            existing=replace(crm.existing, leads=(ExistingCrmLead(1, 2), ExistingCrmLead(1, 3))),
        )
    elif duplicate == "inn":
        crm = replace(
            crm,
            existing=replace(
                crm.existing,
                developers=(ExistingCrmDeveloper("00123", 2), ExistingCrmDeveloper("00123", 3)),
            ),
        )
    else:
        crm = replace(
            crm,
            existing=replace(
                crm.existing,
                company_groups=(ExistingCrmCompanyGroup(20, 2), ExistingCrmCompanyGroup(20, 3)),
            ),
        )
    with pytest.raises(TransformInputError):
        plan(data, crm)


@pytest.mark.parametrize("missing", ["developer", "group", "default", "regional"])
def test_missing_required_input(missing: str) -> None:
    data, crm = source(), context()
    if missing == "developer":
        data = replace(data, developers=[])
    elif missing == "group":
        data = replace(data, company_groups=[])
    else:
        crm = replace(crm, managers=tuple(m for m in crm.managers if m.configured_name != missing))
    with pytest.raises(TransformInputError):
        plan(data, crm)


@pytest.mark.parametrize("company_exists", [False, True])
@pytest.mark.parametrize("group_exists", [False, True])
def test_existing_new_combinations(company_exists: bool, group_exists: bool) -> None:
    crm = context()
    crm = replace(
        crm,
        existing=replace(
            crm.existing,
            developers=(ExistingCrmDeveloper("00123", 1000),) if company_exists else (),
            company_groups=(ExistingCrmCompanyGroup(20, 2000),) if group_exists else (),
        ),
    )
    result = plan(source(), crm)
    expected = (
        ([] if group_exists else ["group:20"])
        + (
            []
            if company_exists
            else [
                "company:10",
                "requisite:10",
                "address:10:actual",
                "address:10:legal",
            ]
        )
        + ["lead:1"]
    )
    assert [op.operation_id for op in result.operations] == expected
    lead = result.operations[-1]
    assert (lead.command.fields.get("company_ref") == 1000) == company_exists
    assert (lead.command.fields.get("parent") == 2000) == group_exists
    assert lead.bindings == tuple(
        ([] if company_exists else [RuntimeBinding("company_ref", "company:10")])
        + ([] if group_exists else [RuntimeBinding("parent", "group:20")])
    )
    assert lead.dependencies == (
        ()
        if company_exists
        else (
            "requisite:10",
            "address:10:actual",
            "address:10:legal",
        )
    )


def test_existing_leads_do_not_create_parents() -> None:
    crm = replace(context(), existing=ExistingCrmEntities((ExistingCrmLead(1, 100),), (), ()))
    # Для пропущенных объектов поиск родителей не требуется.
    assert plan(replace(source(), developers=[], company_groups=[]), crm).operations == ()


def test_shared_parents_and_stable_sorted_order() -> None:
    data = source()
    data = replace(
        data,
        objects=[replace(data.objects[0], id=3), data.objects[0], replace(data.objects[0], id=2)],
    )
    result = plan(data, context())
    assert [op.operation_id for op in result.operations] == [
        "group:20",
        "company:10",
        "requisite:10",
        "address:10:actual",
        "address:10:legal",
        "lead:1",
        "lead:2",
        "lead:3",
    ]
    assert result == plan(replace(data, objects=list(reversed(data.objects))), context())


def test_identity_is_inn_not_source_metadata_or_name() -> None:
    crm = replace(
        context(), existing=ExistingCrmEntities((), (ExistingCrmDeveloper("00123", 400),), ())
    )
    data = source()
    data = replace(
        data,
        developers=[replace(data.developers[0], id=99, short_name="Changed")],
        objects=[replace(data.objects[0], developer_id=99)],
    )
    assert [op.operation_id for op in plan(data, crm).operations] == ["group:20", "lead:1"]
    data = replace(data, developers=[replace(data.developers[0], inn="different")])
    assert "company:99" in [op.operation_id for op in plan(data, crm).operations]


def test_branch_payloads_bindings_and_managers() -> None:
    result = plan(source(), context())
    group, company, requisite, actual, legal, lead = result.operations
    assert group.command == AddItemCommand(
        105, {"group_title": "Group", "group_source": 20, "source": "SOURCE", "group_manager": 7}
    )
    assert company.command == AddItemCommand(
        104,
        {
            "company_title": "Short",
            "company_manager": 9,
            "company_type": "TYPE",
            "sector": "SECTOR",
            "contact": "Contact person",
            "multi": [
                {"use": "BUSINESS", "channel": channel, "text": value}
                for channel, value in (
                    ("TEL", "+70000000000"),
                    ("MAIL", "mail@example.invalid"),
                    ("SITE", "https://example.invalid"),
                )
            ],
        },
    )
    assert requisite.command == AddRequisiteCommand(
        {
            "owner_type": 104,
            "preset": 17,
            "card": "Short",
            "short": "Short",
            "full": "Full company name",
            "inn": "00123",
            "kpp": "00456",
            "ogrn": "00789",
        }
    )
    assert requisite.bindings == (RuntimeBinding("owner", "company:10"),)
    for op, type_id, value in ((actual, 31, "Actual address"), (legal, 36, "Legal address")):
        assert op.command == AddAddressCommand(
            {"address_type": type_id, "owner_type": 108, "address": value}
        )
        assert op.bindings == (RuntimeBinding("owner", "requisite:10"),)
    assert lead.command.fields == {
        "building": 1,
        "lead_title": "Title",
        "location": "Object address",
        "published": "2026-08-21",
        "period": "2028, квартал 4",
        "kind": "RES",
        "lead_source": "SOURCE",
        "lead_manager": 9,
    }


def test_no_object_group_does_not_invent_fallback_and_optional_url() -> None:
    data = source()
    data = replace(
        data,
        objects=[
            replace(
                data.objects[0],
                company_group_id=None,
                region_id=23,
                object_type=ExtractedObjectTypeEnum.NON_RESIDENTIAL,
            )
        ],
        developers=[replace(data.developers[0], url=None, region_id=23)],
    )
    result = plan(data, context())
    assert result.operations[0].operation_id == "company:10"
    assert result.operations[0].command.fields["company_manager"] == 7
    assert len(result.operations[0].command.fields["multi"]) == 2
    assert result.operations[-1].command.fields["lead_manager"] == 7
    assert result.operations[-1].command.fields["kind"] == "NONRES"
    assert "parent" not in result.operations[-1].command.fields
    assert all(b.field != "parent" for b in result.operations[-1].bindings)


@pytest.mark.parametrize(
    "case", ["duplicate_inn", "conflicting_developer_group", "conflicting_object_groups"]
)
def test_ambiguous_source_inputs(case: str) -> None:
    data = source()
    if case == "duplicate_inn":
        data = replace(
            data,
            objects=data.objects + [replace(data.objects[0], id=2, developer_id=11)],
            developers=data.developers + [replace(data.developers[0], id=11)],
        )
    elif case == "conflicting_developer_group":
        data = replace(data, developers=[replace(data.developers[0], company_group_id=99)])
    else:
        data = replace(
            data,
            developers=[replace(data.developers[0], company_group_id=None)],
            objects=data.objects + [replace(data.objects[0], id=2, company_group_id=99)],
        )
    with pytest.raises(TransformInputError):
        plan(data, context())


@pytest.mark.parametrize(
    "case",
    [
        "empty_id",
        "duplicate_id",
        "unknown_source",
        "future_source",
        "self_binding",
        "empty_binding",
        "empty_source",
        "duplicate_field",
        "literal_binding",
        "unknown_dependency",
        "self_dependency",
        "future_dependency",
        "duplicate_dependency",
        "missing_company",
        "missing_requisite_owner",
        "missing_address_owner",
        "bad_command",
        "bad_fields",
        "bad_entity_id",
        "bool_entity_id",
        "bad_literal_id",
        "bad_preset",
        "bad_address_type",
        "bad_requisite_type",
        "bad_address_owner_type",
    ],
)
def test_validator_rejects_invalid_plans(case: str) -> None:
    crm = context()
    ops = list(plan(source(), crm).operations)
    lead = ops[-1]
    if case == "empty_id":
        ops[-1] = replace(lead, operation_id=" ")
    elif case == "duplicate_id":
        ops.append(lead)
    elif case in ("unknown_source", "future_source", "self_binding", "empty_source"):
        target = {
            "unknown_source": "missing",
            "future_source": "later",
            "self_binding": "lead:1",
            "empty_source": "",
        }[case]
        ops[-1] = replace(lead, bindings=(RuntimeBinding("company_ref", target),))
        if case == "future_source":
            ops.append(PlannedOperation("later", AddItemCommand(104, {})))
    elif case == "empty_binding":
        ops[-1] = replace(lead, bindings=lead.bindings + (RuntimeBinding("", "company:10"),))
    elif case == "duplicate_field":
        ops[-1] = replace(lead, bindings=lead.bindings + (lead.bindings[-1],))
    elif case == "literal_binding":
        ops[-1] = replace(lead, command=AddItemCommand(101, dict(lead.command.fields, parent=999)))
    elif case in (
        "unknown_dependency",
        "self_dependency",
        "future_dependency",
        "duplicate_dependency",
    ):
        deps = {
            "unknown_dependency": ("missing",),
            "self_dependency": ("lead:1",),
            "future_dependency": ("later",),
            "duplicate_dependency": ("group:20", "group:20"),
        }
        ops[-1] = replace(lead, dependencies=deps[case])
        if case == "future_dependency":
            ops.append(PlannedOperation("later", AddItemCommand(104, {})))
    elif case.startswith("missing_"):
        index = {"missing_company": -1, "missing_requisite_owner": 2, "missing_address_owner": 3}[
            case
        ]
        ops[index] = replace(ops[index], bindings=())
    elif case == "bad_command":
        ops[0] = replace(ops[0], command=cast(Any, object()))
    elif case == "bad_fields":
        ops[0] = replace(ops[0], command=AddItemCommand(105, cast(Any, [])))
    elif case in ("bad_entity_id", "bool_entity_id"):
        ops[0] = replace(ops[0], command=AddItemCommand(0 if case == "bad_entity_id" else True, {}))
    elif case == "bad_literal_id":
        ops[-1] = replace(lead, command=AddItemCommand(101, {"company_ref": 0}), bindings=())
    else:
        index, key = {
            "bad_preset": (2, "preset"),
            "bad_address_type": (3, "address_type"),
            "bad_requisite_type": (2, "owner_type"),
            "bad_address_owner_type": (3, "owner_type"),
        }[case]
        payload = dict(ops[index].command.fields)
        payload[key] = 0
        command = AddRequisiteCommand(payload) if index == 2 else AddAddressCommand(payload)
        ops[index] = replace(ops[index], command=command)
    with pytest.raises(SyncPlanValidationError):
        SyncPlanValidator(crm.structure).validate(SyncPlan(tuple(ops)))


def reference_commands(crm: CrmContext) -> Dict[str, CrmCommand]:
    fields = crm.structure.entity_fields
    types = crm.structure.entity_types
    return {
        "company": AddItemCommand(types.company, {}),
        "group": AddItemCommand(types.company_group, {}),
        "lead": AddItemCommand(
            types.lead, {fields.lead.company_id: 700, fields.lead.company_group_bitrix_id: 800}
        ),
        "requisite": AddRequisiteCommand(
            {
                fields.requisite.entity_id_to_bind: 700,
                fields.requisite.entity_type_id: types.company,
                fields.requisite.preset_id: crm.references.organization_requisite_preset_id,
            }
        ),
        "address": AddAddressCommand(
            {
                fields.address.entity_id_to_bind: 900,
                fields.address.entity_type_id_to_bind: types.requisite,
                fields.address.address_type_id: crm.references.address_types.actual,
            }
        ),
    }


@pytest.mark.parametrize("producer_kind", ["company", "group", "lead", "requisite", "address"])
@pytest.mark.parametrize("reference", ["requisite", "address", "lead_company", "lead_group"])
def test_validator_binding_producer_compatibility(reference: str, producer_kind: str) -> None:
    crm = context()
    fields = crm.structure.entity_fields
    consumer_kind, field, expected_producer = {
        "requisite": ("requisite", fields.requisite.entity_id_to_bind, "company"),
        "address": ("address", fields.address.entity_id_to_bind, "requisite"),
        "lead_company": ("lead", fields.lead.company_id, "company"),
        "lead_group": ("lead", fields.lead.company_group_bitrix_id, "group"),
    }[reference]
    commands = reference_commands(crm)
    command = commands[consumer_kind]
    payload = dict(command.fields)
    del payload[field]
    # ID намеренно не раскрывают тип: совместимость проверяется по команде-источнику.
    producer = PlannedOperation("first", commands[producer_kind])
    consumer = PlannedOperation(
        "second", replace(command, fields=payload), (RuntimeBinding(field, "first"),)
    )
    candidate = SyncPlan((producer, consumer))
    validator = SyncPlanValidator(crm.structure)
    if producer_kind == expected_producer:
        validator.validate(candidate)
    else:
        with pytest.raises(SyncPlanValidationError, match="Источник привязки должен создавать"):
            validator.validate(candidate)


@pytest.mark.parametrize("consumer_kind", ["requisite", "address", "lead"])
def test_validator_accepts_literal_references(consumer_kind: str) -> None:
    crm = context()
    command = reference_commands(crm)[consumer_kind]
    SyncPlanValidator(crm.structure).validate(SyncPlan((PlannedOperation("only", command),)))


@pytest.mark.parametrize("entity_kind", ["unknown", "requisite"])
def test_validator_rejects_unsupported_item_entity_type(entity_kind: str) -> None:
    crm = context()
    types = crm.structure.entity_types
    entity_type_id = (
        types.requisite
        if entity_kind == "requisite"
        else max(types.lead, types.company, types.company_group, types.requisite) + 1
    )
    candidate = SyncPlan((PlannedOperation("only", AddItemCommand(entity_type_id, {})),))
    with pytest.raises(SyncPlanValidationError, match="Неподдерживаемый ID типа сущности элемента"):
        SyncPlanValidator(crm.structure).validate(candidate)


def test_service_validation_error_propagates_and_logs_safely(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import nashdom_sync.transform.service as service_module

    caplog.set_level(logging.INFO)
    bad = SyncPlan((PlannedOperation("lead:1", AddItemCommand(101, {})),))
    transformer = Mock(return_value=bad)
    monkeypatch.setattr(service_module.SyncPlanTransformer, "transform", transformer)
    with pytest.raises(TransformError):
        plan(source(), context())
    assert transformer.call_count == 1
    events = [getattr(r, EVENT_ATTRIBUTE) for r in caplog.records]
    assert events == ["transform_started", "transform_failed"]
    details = getattr(caplog.records[-1], DETAILS_ATTRIBUTE)
    assert details["stage"] == "validation"
    assert details["exception_type"] == "SyncPlanValidationError"
    assert "error" not in details


def test_service_safe_success_and_input_failure_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    result = plan(source(), context())
    assert isinstance(result, SyncPlan)
    details = getattr(caplog.records[-1], DETAILS_ATTRIBUTE)
    assert {k: details[k] for k in ("new_leads", "new_groups", "new_companies", "operations")} == {
        "new_leads": 1,
        "new_groups": 1,
        "new_companies": 1,
        "operations": 6,
    }
    assert all(isinstance(v, (int, float)) for v in details.values())
    caplog.clear()
    with pytest.raises(TransformInputError):
        plan(replace(source(), developers=[]), context())
    details = getattr(caplog.records[-1], DETAILS_ATTRIBUTE)
    assert details["exception_type"] == "TransformInputError"
    assert details["stage"] == "building"


def test_representative_local_samples() -> None:
    repo = Path(__file__).resolve().parents[4]
    paths = [
        repo / "temp" / (name + ".json") for name in ("objects", "developers", "company_groups")
    ]
    snapshot = repo / "crm_context.snapshot.json"
    if not all(path.exists() for path in paths + [snapshot]):
        pytest.skip("Необязательные локальные примеры не хранятся в репозитории")
    rows = [
        cast(List[Dict[str, Any]], json.loads(path.read_text(encoding="utf-8"))) for path in paths
    ]
    objects: List[ExtractedObject] = []
    for row in rows[0]:
        payload = dict(row)
        year, quarter = payload["commissioning_period"].split(", квартал ")
        payload["commissioning_period"] = CommissioningPeriod(int(year), int(quarter))
        payload["publication_date"] = date.fromisoformat(payload["publication_date"])
        payload["object_type"] = ExtractedObjectTypeEnum(payload["object_type"])
        objects.append(ExtractedObject(**payload))
    data = ExtractResult(
        objects,
        [ExtractedDeveloper(**r) for r in rows[1]],
        [ExtractedCompanyGroup(**r) for r in rows[2]],
    )
    raw: Dict[str, Any] = json.loads(snapshot.read_text(encoding="utf-8"))
    ef, refs, existing = raw["structure"]["entity_fields"], raw["references"], raw["existing"]
    crm = CrmContext(
        CrmStructure(
            CrmEntityTypeId(**raw["structure"]["entity_types"]),
            CrmEntityFields(
                LeadFieldsBindings(**ef["lead"]),
                # Исторический локальный snapshot может содержать удалённый binding.
                DeveloperFieldsBindings(
                    **{
                        key: value
                        for key, value in ef["developer"].items()
                        if key != "source_developer_id"
                    }
                ),
                CompanyGroupFieldsBindings(**ef["company_group"]),
                RequisiteFieldsBindings(**ef["requisite"]),
                AddressFieldsBindings(**ef["address"]),
                MultiFieldFieldsBindings(**ef["multifield"]),
            ),
        ),
        CrmReferences(
            **dict(
                refs,
                building_type=CrmBuildingType(**refs["building_type"]),
                address_types=CrmAddressType(**refs["address_types"]),
                multifield=CrmMultiField(**refs["multifield"]),
            )
        ),
        ExistingCrmEntities(
            tuple(ExistingCrmLead(**r) for r in existing["leads"]),
            tuple(ExistingCrmDeveloper(**r) for r in existing["developers"]),
            tuple(ExistingCrmCompanyGroup(**r) for r in existing["company_groups"]),
        ),
        tuple(CrmEmployee(**r) for r in raw["managers"]),
    )
    region = RegionSettings(default_assigned_by_name=crm.managers[0].configured_name, assignment={})
    result = TransformService().transform(data, crm, region).plan
    SyncPlanValidator(crm.structure).validate(result)
    ids = {op.operation_id for op in result.operations}
    new_objects = [
        obj for obj in objects if obj.id not in {lead.source_id for lead in crm.existing.leads}
    ]
    assert sum(op.operation_id.startswith("lead:") for op in result.operations) == len(new_objects)
    required = {obj.developer_id for obj in new_objects}
    new_devs = {
        dev.id
        for dev in data.developers
        if dev.id in required and dev.inn not in {dev.inn for dev in crm.existing.developers}
    }
    assert {
        op.operation_id for op in result.operations if op.operation_id.startswith("company:")
    } == {f"company:{key}" for key in new_devs}
    for key in new_devs:
        assert {f"requisite:{key}", f"address:{key}:actual", f"address:{key}:legal"} <= ids
    assert result == TransformService().transform(data, crm, region).plan
