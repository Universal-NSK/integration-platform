"""Declarative, sequential write plan; no CRM client dependencies."""

from dataclasses import dataclass
from typing import Any, Mapping, Tuple, Union


@dataclass(frozen=True)
class AddItemCommand:
    entity_type_id: int
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class AddRequisiteCommand:
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class AddAddressCommand:
    fields: Mapping[str, Any]


CrmCommand = Union[AddItemCommand, AddRequisiteCommand, AddAddressCommand]


@dataclass(frozen=True)
class RuntimeBinding:
    field: str
    source_operation_id: str


@dataclass(frozen=True)
class PlannedOperation:
    operation_id: str
    command: CrmCommand
    bindings: Tuple[RuntimeBinding, ...] = ()
    dependencies: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SyncPlan:
    operations: Tuple[PlannedOperation, ...]


@dataclass(frozen=True)
class TransformResult:
    plan: SyncPlan
