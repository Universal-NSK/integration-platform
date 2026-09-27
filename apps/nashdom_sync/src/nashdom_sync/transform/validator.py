from typing import Mapping, Set, Tuple, cast

from nashdom_sync.contracts import CrmStructure
from nashdom_sync.contracts.transform import (
    AddAddressCommand,
    AddItemCommand,
    AddRequisiteCommand,
    PlannedOperation,
    SyncPlan,
)
from nashdom_sync.transform.exceptions import SyncPlanValidationError


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SyncPlanValidationError(message)


class SyncPlanValidator:
    """Validate against resolved CRM field names, without any CRM calls.

    Structure is supplied locally by the service: entity IDs and even standard
    field bindings belong to CrmContext, not to the plan's operation names.
    """

    def __init__(self, structure: CrmStructure) -> None:
        self._structure = structure

    def validate(self, plan: SyncPlan) -> None:
        operations = plan.operations
        self._validate_operation_ids(operations)
        self._validate_commands(operations)
        self._validate_bindings(operations)
        self._validate_dependencies(operations)
        self._validate_execution_order(operations)

    def _validate_operation_ids(self, operations: Tuple[PlannedOperation, ...]) -> None:
        seen: Set[str] = set()
        for op in operations:
            _require(_text(op.operation_id), "Empty operation ID")
            _require(op.operation_id not in seen, "Duplicate operation ID")
            seen.add(op.operation_id)

    def _validate_commands(self, operations: Tuple[PlannedOperation, ...]) -> None:
        fields = self._structure.entity_fields
        for op in operations:
            command = op.command
            _require(
                isinstance(
                    cast(object, command), (AddItemCommand, AddRequisiteCommand, AddAddressCommand)
                ),
                "Unsupported command",
            )
            _require(
                isinstance(cast(object, command.fields), Mapping),
                "Command fields must be a mapping",
            )
            _require(all(_text(key) for key in command.fields), "Invalid command field name")
            if isinstance(command, AddItemCommand):
                _require(_positive_id(command.entity_type_id), "Invalid item entity type ID")
                entity_types = self._structure.entity_types
                _require(
                    command.entity_type_id
                    in (entity_types.lead, entity_types.company, entity_types.company_group),
                    "Unsupported item entity type ID",
                )
                if command.entity_type_id == self._structure.entity_types.lead:
                    self._require_reference(op, fields.lead.company_id)
                    group_field = fields.lead.company_group_bitrix_id
                    if group_field in command.fields or any(
                        b.field == group_field for b in op.bindings
                    ):
                        self._require_reference(op, group_field)
            elif isinstance(command, AddRequisiteCommand):
                self._require_reference(op, fields.requisite.entity_id_to_bind)
                _require(
                    command.fields.get(fields.requisite.entity_type_id)
                    == self._structure.entity_types.company,
                    "Invalid requisite owner type",
                )
                _require(
                    _positive_id(command.fields.get(fields.requisite.preset_id)),
                    "Invalid requisite preset",
                )
            else:
                self._require_reference(op, fields.address.entity_id_to_bind)
                _require(
                    command.fields.get(fields.address.entity_type_id_to_bind)
                    == self._structure.entity_types.requisite,
                    "Invalid address owner type",
                )
                _require(
                    _positive_id(command.fields.get(fields.address.address_type_id)),
                    "Invalid address type",
                )

    @staticmethod
    def _require_reference(op: PlannedOperation, field: str) -> None:
        literal = field in op.command.fields
        bindings = sum(binding.field == field for binding in op.bindings)
        _require(
            int(literal) + bindings == 1, "Required reference must have one literal or binding"
        )
        if literal:
            _require(_positive_id(op.command.fields[field]), "Invalid literal reference ID")

    def _validate_bindings(self, operations: Tuple[PlannedOperation, ...]) -> None:
        by_id = {op.operation_id: op for op in operations}
        for op in operations:
            seen: Set[str] = set()
            for binding in op.bindings:
                _require(
                    _text(binding.field) and _text(binding.source_operation_id), "Empty binding"
                )
                _require(binding.field not in seen, "Duplicate binding field")
                _require(binding.field not in op.command.fields, "Literal and binding conflict")
                _require(binding.source_operation_id in by_id, "Unknown binding source")
                self._validate_binding_source(op, binding.field, by_id[binding.source_operation_id])
                seen.add(binding.field)

    def _validate_binding_source(
        self, consumer: PlannedOperation, field: str, producer: PlannedOperation
    ) -> None:
        fields = self._structure.entity_fields
        entity_types = self._structure.entity_types
        command = consumer.command
        source = producer.command
        if isinstance(command, AddAddressCommand) and field == fields.address.entity_id_to_bind:
            _require(isinstance(source, AddRequisiteCommand), "Binding source must create a requisite")
            return

        expected_entity_type = None
        if isinstance(command, AddRequisiteCommand) and field == fields.requisite.entity_id_to_bind:
            expected_entity_type = entity_types.company
        elif isinstance(command, AddItemCommand) and command.entity_type_id == entity_types.lead:
            if field == fields.lead.company_id:
                expected_entity_type = entity_types.company
            elif field == fields.lead.company_group_bitrix_id:
                expected_entity_type = entity_types.company_group
        if expected_entity_type is not None:
            _require(
                isinstance(source, AddItemCommand) and source.entity_type_id == expected_entity_type,
                "Binding source must create the required item entity type",
            )

    def _validate_dependencies(self, operations: Tuple[PlannedOperation, ...]) -> None:
        ids = {op.operation_id for op in operations}
        for op in operations:
            seen: Set[str] = set()
            for dependency in op.dependencies:
                _require(_text(dependency) and dependency in ids, "Unknown dependency")
                _require(dependency != op.operation_id, "Self dependency")
                _require(dependency not in seen, "Duplicate dependency")
                seen.add(dependency)

    def _validate_execution_order(self, operations: Tuple[PlannedOperation, ...]) -> None:
        earlier: Set[str] = set()
        for op in operations:
            sources = (
                tuple(binding.source_operation_id for binding in op.bindings) + op.dependencies
            )
            _require(
                all(source in earlier for source in sources),
                "Reference must point to an earlier operation",
            )
            earlier.add(op.operation_id)
