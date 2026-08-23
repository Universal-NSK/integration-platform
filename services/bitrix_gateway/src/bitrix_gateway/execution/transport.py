from typing import Any, Dict, Protocol

from bitrix_gateway.contracts.models import TransportResult


class TransportError(Exception):
    def __init__(
        self,
        message: str,
        *,
        outcome_uncertain: bool,
    ) -> None:
        super().__init__(message)
        self.outcome_uncertain = outcome_uncertain


class BitrixTransport(Protocol):
    async def call(
        self,
        method: str,
        payload: Dict[str, Any],
    ) -> TransportResult: ...
