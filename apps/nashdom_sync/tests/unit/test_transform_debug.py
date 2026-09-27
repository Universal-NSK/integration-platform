import copy
from dataclasses import replace

import pytest
from nashdom_sync.contracts.transform import (
    AddAddressCommand,
    AddItemCommand,
    AddRequisiteCommand,
    PlannedOperation,
    RuntimeBinding,
    SyncPlan,
)
from nashdom_sync.transform.debug import format_sync_plan
from test_transform import context


def sample() -> SyncPlan:
    # Произвольные ID намеренно исключают распознавание сущностей по префиксам операций.
    return SyncPlan(
        (
            PlannedOperation("G", AddItemCommand(105, {"title": "Группа"})),
            PlannedOperation("C", AddItemCommand(104, {"z": 2, "a": ["Компания"]})),
            PlannedOperation(
                "R",
                AddRequisiteCommand({"owner_type": 104, "preset": 17}),
                (RuntimeBinding("owner", "C"),),
            ),
            PlannedOperation(
                "A1", AddAddressCommand({"address_type": 31}), (RuntimeBinding("owner", "R"),)
            ),
            PlannedOperation(
                "A2", AddAddressCommand({"address_type": 36}), (RuntimeBinding("owner", "R"),)
            ),
            PlannedOperation(
                "L",
                AddItemCommand(101, {"title": "Lead"}),
                (RuntimeBinding("company_ref", "C"), RuntimeBinding("parent", "G")),
                ("A1", "A2"),
            ),
        )
    )


def test_flat_order_and_complete_payload() -> None:
    plan = sample()
    lines = format_sync_plan(plan, context().structure).splitlines()
    assert [line.split("]", 1)[0][1:] for line in lines] == [
        op.operation_id for op in plan.operations
    ]
    assert (
        '[команда: AddItemCommand(entity_type_id=104, fields={"a": ["Компания"], "z": 2})]'
        in lines[1]
    )
    assert "[привязки: company_ref <- C; parent <- G][зависимости: A1; A2]" in lines[5]
    assert "AddRequisiteCommand" in lines[2]
    assert "AddAddressCommand" in lines[3]
    assert "[привязки: -][зависимости: -]" in lines[0]


def test_tree_new_creation_branch() -> None:
    plan = sample()
    tree = format_sync_plan(plan, context().structure, "tree")
    assert "группа -> компания не является связью CRM" in tree
    for fragment in (
        "\n[G]",
        "\n└── [C]",
        "\n    ├── [R]",
        "\n    │   ├── [A1]",
        "\n    │   └── [A2]",
        "\n    └── [L]",
    ):
        assert fragment in tree
    for line in format_sync_plan(plan, context().structure).splitlines():
        assert line in tree


def test_existing_parents() -> None:
    plan = SyncPlan(
        (
            PlannedOperation(
                "literal",
                AddItemCommand(
                    101,
                    {
                        "company_ref": 4836,
                        "parent": 70,
                    },
                ),
            ),
        )
    )
    tree = format_sync_plan(plan, context().structure, "tree")
    assert (
        "\n[существующая группа crm_id=70]\n└── [существующая компания crm_id=4836]\n    └── [literal]"
        in tree
    )


@pytest.mark.parametrize("grouped", [False, True])
def test_shared_company_and_ungrouped_leads(grouped: bool) -> None:
    original = sample()
    lead = original.operations[-1]
    bindings = lead.bindings if grouped else lead.bindings[:1]
    plan = SyncPlan(
        original.operations
        + (
            replace(lead, operation_id="L2", bindings=bindings),
            replace(lead, operation_id="L3", bindings=bindings),
        )
    )
    tree = format_sync_plan(plan, context().structure, "tree")
    for op in plan.operations:
        assert tree.count(f"[{op.operation_id}][привязки:") == 1
    if grouped:
        assert "ссылка на" not in tree
    else:
        assert "[без группы]" in tree
        assert "[ссылка на [C]; визуальная группировка по лидам]" in tree


def test_multiple_groups_reference_single_create() -> None:
    original = sample()
    lead = original.operations[-1]
    second = replace(
        lead,
        operation_id="L2",
        bindings=lead.bindings[:1],
        command=AddItemCommand(101, {"parent": 99}),
    )
    plan = SyncPlan(original.operations + (second,))
    tree = format_sync_plan(plan, context().structure, "tree")
    assert "[существующая группа crm_id=99]\n└── [ссылка на [C]" in tree
    assert tree.count("[C][привязки:") == 1
    assert tree.count("[R][привязки:") == 1


def test_orphans_and_literal_ownership_are_preserved() -> None:
    plan = SyncPlan(
        (
            PlannedOperation("unused", AddItemCommand(105, {})),
            PlannedOperation("card", AddRequisiteCommand({"owner": 45})),
            PlannedOperation("address", AddAddressCommand({"owner": 67})),
        )
    )
    tree = format_sync_plan(plan, context().structure, "tree")
    assert "[существующая компания crm_id=45]\n└── [card]" in tree
    assert "[существующие реквизиты crm_id=67]\n└── [address]" in tree
    assert "\n[unused][привязки:" in tree


@pytest.mark.parametrize("mode", ["flat", "tree"])
def test_no_mutation_and_determinism(mode: str) -> None:
    plan = sample()
    structure = context().structure
    before = copy.deepcopy((plan, structure))
    result = format_sync_plan(plan, structure, mode)
    assert (plan, structure) == before
    assert result == format_sync_plan(plan, structure, mode)


def test_unknown_mode() -> None:
    with pytest.raises(ValueError, match="Неизвестный режим отладочного вывода SyncPlan"):
        format_sync_plan(sample(), context().structure, "unknown")


def test_empty_plan() -> None:
    assert format_sync_plan(SyncPlan(()), context().structure) == ""
    assert "Визуальная группировка" in format_sync_plan(SyncPlan(()), context().structure, "tree")
