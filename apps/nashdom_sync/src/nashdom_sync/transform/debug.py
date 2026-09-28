"""Просмотр готового SyncPlan по явному вызову, без исполнения и логирования.

Данные команд выводятся полностью и должны быть сериализуемы в JSON, как команды CRM.
Дерево служит только для отображения. Связи и зависимости определяются самим планом.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from nashdom_sync.contracts import CrmStructure
from nashdom_sync.contracts.transform import (
    AddAddressCommand,
    AddItemCommand,
    AddRequisiteCommand,
    PlannedOperation,
    SyncPlan,
)


def _operation(op: PlannedOperation) -> str:
    bindings = "; ".join(f"{b.field} <- {b.source_operation_id}" for b in op.bindings)
    dependencies = "; ".join(op.dependencies)
    command = op.command
    payload = json.dumps(dict(command.fields), ensure_ascii=False, sort_keys=True)
    entity = (
        f"entity_type_id={command.entity_type_id}, " if isinstance(command, AddItemCommand) else ""
    )
    return (
        f"[{op.operation_id}][привязки: {bindings or '-'}]"
        f"[зависимости: {dependencies or '-'}]"
        f"[команда: {type(command).__name__}({entity}fields={payload})]"
    )


def _children() -> List["_Node"]:
    return []


@dataclass
class _Node:
    label: str
    children: List["_Node"] = field(default_factory=_children)


class _Tree:
    def __init__(self, plan: SyncPlan, structure: CrmStructure) -> None:
        self.plan = plan
        self.structure = structure
        self.nodes = {op.operation_id: _Node(_operation(op)) for op in plan.operations}
        self.operations = {op.operation_id: op for op in plan.operations}
        self.existing: Dict[Tuple[str, int], _Node] = {}
        self.roots: List[_Node] = []
        self.placed: Set[int] = set()
        self.slots: Dict[Tuple[int, int], _Node] = {}
        self.ungrouped = _Node("[без группы]")

    def _place(self, node: _Node, parent: Optional[_Node] = None) -> None:
        if id(node) not in self.placed:
            (self.roots if parent is None else parent.children).append(node)
            self.placed.add(id(node))

    def _kind(self, op: PlannedOperation, kind: str) -> bool:
        command = op.command
        if kind == "requisite":
            return isinstance(command, AddRequisiteCommand)
        types = self.structure.entity_types
        expected = {"company": types.company, "group": types.company_group, "lead": types.lead}
        return isinstance(command, AddItemCommand) and command.entity_type_id == expected[kind]

    def _parent(self, op: PlannedOperation, name: str, kind: str) -> Optional[_Node]:
        for binding in op.bindings:
            if binding.field == name:
                producer = self.operations.get(binding.source_operation_id)
                if producer is not None and self._kind(producer, kind):
                    return self.nodes[producer.operation_id]
                return None
        value = op.command.fields.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            key = (kind, value)
            if key not in self.existing:
                labels = {
                    "company": "существующая компания",
                    "group": "существующая группа",
                    "requisite": "существующие реквизиты",
                }
                self.existing[key] = _Node(f"[{labels[kind]} crm_id={value}]")
            return self.existing[key]
        return None

    def _company_slot(self, company: _Node, group: _Node) -> _Node:
        key = (id(group), id(company))
        if key not in self.slots:
            if id(company) in self.placed:
                # Сама операция и её ветка создания выводятся только один раз.
                label = company.label.split("][привязки:", 1)[0]
                if not label.endswith("]"):
                    label += "]"
                slot = _Node(f"[ссылка на {label}; визуальная группировка по лидам]")
            else:
                slot = company
            self._place(slot, group)
            self.slots[key] = slot
        return self.slots[key]

    def build(self) -> List[_Node]:
        fields = self.structure.entity_fields
        # Сначала собираем реальные ветки принадлежности, затем группируем лиды для отображения.
        for op in self.plan.operations:
            parent = None
            if isinstance(op.command, AddRequisiteCommand):
                parent = self._parent(op, fields.requisite.entity_id_to_bind, "company")
            elif isinstance(op.command, AddAddressCommand):
                parent = self._parent(op, fields.address.entity_id_to_bind, "requisite")
            if parent is not None:
                self._place(self.nodes[op.operation_id], parent)
        for op in self.plan.operations:
            if self._kind(op, "lead"):
                group = self._parent(op, fields.lead.company_group_bitrix_id, "group")
                if group is None:
                    group = self.ungrouped
                self._place(group)
                company = self._parent(op, fields.lead.company_id, "company")
                parent = self._company_slot(company, group) if company is not None else group
                self._place(self.nodes[op.operation_id], parent)
        # Сохраняем неиспользованные операции создания и владельцев с явными ID даже без лидов.
        for node in list(self.nodes.values()) + list(self.existing.values()):
            self._place(node)
        return self.roots


def _render(nodes: List[_Node], prefix: str = "", roots: bool = True) -> List[str]:
    lines: List[str] = []
    for index, node in enumerate(nodes):
        last = index == len(nodes) - 1
        lines.append(prefix + ("" if roots else "└── " if last else "├── ") + node.label)
        child_prefix = prefix + ("" if roots else "    " if last else "│   ")
        lines.extend(_render(node.children, child_prefix, False))
    return lines


def format_sync_plan(plan: SyncPlan, structure: CrmStructure, mode: str = "flat") -> str:
    """Вернуть полные данные команд без изменения входов, ввода-вывода и логирования.

    Режим flat сохраняет порядок исполнения. Режим tree использует поля и связи
    готового плана; компания под группой — только визуальная группировка по лидам.
    Общая операция создания компании выводится один раз, в остальных ветках — ссылки.
    Неизвестный режим вызывает ValueError; несовместимые с JSON данные — ошибку кодировщика.
    """
    if mode == "flat":
        return "\n".join(_operation(op) for op in plan.operations)
    if mode == "tree":
        legend = (
            "Визуальная группировка по лидам: группа -> компания не является связью CRM "
            "или зависимостью исполнения. Порядок исполнения показан в режиме flat."
        )
        return "\n".join([legend] + _render(_Tree(plan, structure).build()))
    raise ValueError(f"Неизвестный режим отладочного вывода SyncPlan: {mode!r}")
