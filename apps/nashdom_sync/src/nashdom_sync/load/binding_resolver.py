"""Подстановка полученных CRM ID в новую команду без изменения плана."""

from typing import Mapping, cast

from nashdom_sync.contracts import (
    AddAddressCommand,
    AddItemCommand,
    AddRequisiteCommand,
    CrmCommand,
    OperationResult,
    OperationStatus,
    PlannedOperation,
)

from .exceptions import LoadInvariantError


class RuntimeBindingResolver:
    def resolve(
        self, operation: PlannedOperation, results: Mapping[str, OperationResult]
    ) -> CrmCommand:
        command = operation.command
        if not isinstance(
            cast(object, command), (AddItemCommand, AddRequisiteCommand, AddAddressCommand)
        ):
            raise LoadInvariantError(
                f"Получен неподдерживаемый тип CRM-команды: {type(command).__name__}"
            )
        resolved_fields = dict(command.fields)
        for binding in operation.bindings:
            source_id = binding.source_operation_id
            source = results.get(source_id)
            if source is None:
                raise LoadInvariantError(
                    f"Операция {operation.operation_id} ссылается на отсутствующий результат "
                    f"{source_id} для поля {binding.field}"
                )
            if source.status is not OperationStatus.SUCCESS:
                raise LoadInvariantError(
                    f"Операция {operation.operation_id} ожидает успешный результат "
                    f"{source_id} для поля {binding.field}"
                )
            if source.crm_id is None:
                raise LoadInvariantError(
                    f"Операция {operation.operation_id} ожидает CRM ID от {source_id}, "
                    f"но успешный результат не содержит crm_id для поля {binding.field}"
                )
            resolved_fields[binding.field] = source.crm_id
        if isinstance(command, AddItemCommand):
            return AddItemCommand(command.entity_type_id, resolved_fields)
        if isinstance(command, AddRequisiteCommand):
            return AddRequisiteCommand(resolved_fields)
        return AddAddressCommand(resolved_fields)
