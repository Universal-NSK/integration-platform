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
    """Проверить план по фактическим именам полей CRM без обращений к CRM.

    Сервис передаёт структуру локально: ID типов сущностей и привязки даже стандартных
    полей определяются CrmContext, а не именами операций плана.
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
            _require(_text(op.operation_id), "Пустой ID операции")
            _require(op.operation_id not in seen, "Повторяющийся ID операции")
            seen.add(op.operation_id)

    def _validate_commands(self, operations: Tuple[PlannedOperation, ...]) -> None:
        fields = self._structure.entity_fields
        for op in operations:
            command = op.command
            _require(
                isinstance(
                    cast(object, command), (AddItemCommand, AddRequisiteCommand, AddAddressCommand)
                ),
                "Неподдерживаемая команда",
            )
            _require(
                isinstance(cast(object, command.fields), Mapping),
                "Поля команды должны быть отображением ключей в значения",
            )
            _require(all(_text(key) for key in command.fields), "Некорректное имя поля команды")
            if isinstance(command, AddItemCommand):
                _require(
                    _positive_id(command.entity_type_id), "Некорректный ID типа сущности элемента"
                )
                entity_types = self._structure.entity_types
                _require(
                    command.entity_type_id
                    in (entity_types.lead, entity_types.company, entity_types.company_group),
                    "Неподдерживаемый ID типа сущности элемента",
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
                    "Некорректный тип владельца реквизитов",
                )
                _require(
                    _positive_id(command.fields.get(fields.requisite.preset_id)),
                    "Некорректный шаблон реквизитов",
                )
            else:
                self._require_reference(op, fields.address.entity_id_to_bind)
                _require(
                    command.fields.get(fields.address.entity_type_id_to_bind)
                    == self._structure.entity_types.requisite,
                    "Некорректный тип владельца адреса",
                )
                _require(
                    _positive_id(command.fields.get(fields.address.address_type_id)),
                    "Некорректный тип адреса",
                )

    @staticmethod
    def _require_reference(op: PlannedOperation, field: str) -> None:
        literal = field in op.command.fields
        bindings = sum(binding.field == field for binding in op.bindings)
        _require(
            int(literal) + bindings == 1,
            "Обязательная ссылка должна содержать либо явный ID, либо одну привязку",
        )
        if literal:
            _require(_positive_id(op.command.fields[field]), "Некорректный явный ID ссылки")

    def _validate_bindings(self, operations: Tuple[PlannedOperation, ...]) -> None:
        by_id = {op.operation_id: op for op in operations}
        for op in operations:
            seen: Set[str] = set()
            for binding in op.bindings:
                _require(
                    _text(binding.field) and _text(binding.source_operation_id), "Пустая привязка"
                )
                _require(binding.field not in seen, "Повторяющееся поле привязки")
                _require(
                    binding.field not in op.command.fields, "Конфликт явного значения и привязки"
                )
                _require(binding.source_operation_id in by_id, "Неизвестный источник привязки")
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
            _require(
                isinstance(source, AddRequisiteCommand),
                "Источник привязки должен создавать реквизиты",
            )
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
                isinstance(source, AddItemCommand)
                and source.entity_type_id == expected_entity_type,
                "Источник привязки должен создавать элемент требуемого типа сущности",
            )

    def _validate_dependencies(self, operations: Tuple[PlannedOperation, ...]) -> None:
        ids = {op.operation_id for op in operations}
        for op in operations:
            seen: Set[str] = set()
            for dependency in op.dependencies:
                _require(_text(dependency) and dependency in ids, "Неизвестная зависимость")
                _require(dependency != op.operation_id, "Операция зависит от самой себя")
                _require(dependency not in seen, "Повторяющаяся зависимость")
                seen.add(dependency)

    def _validate_execution_order(self, operations: Tuple[PlannedOperation, ...]) -> None:
        earlier: Set[str] = set()
        for op in operations:
            sources = (
                tuple(binding.source_operation_id for binding in op.bindings) + op.dependencies
            )
            _require(
                all(source in earlier for source in sources),
                "Ссылка должна указывать на предшествующую операцию",
            )
            earlier.add(op.operation_id)
