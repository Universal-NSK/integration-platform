"""Диспетчеризация команд без локальных повторов CRM-запросов."""

from typing import Optional, cast

from nashdom_sync.bitrix_crm import ClientBitrixCRM
from nashdom_sync.contracts import (
    AddAddressCommand,
    AddItemCommand,
    AddRequisiteCommand,
    CrmCommand,
)

from .exceptions import LoadInvariantError


class CrmCommandExecutor:
    def __init__(self, client: ClientBitrixCRM) -> None:
        self._client = client

    def execute(self, command: CrmCommand) -> Optional[int]:
        if isinstance(command, AddItemCommand):
            return self._client.add_item(command.entity_type_id, dict(command.fields))
        if isinstance(command, AddRequisiteCommand):
            return self._client.add_requisite(dict(command.fields))
        if isinstance(cast(object, command), AddAddressCommand):
            self._client.add_address(dict(command.fields))
            return None
        raise LoadInvariantError(
            f"Получен неподдерживаемый тип CRM-команды: {type(command).__name__}"
        )
