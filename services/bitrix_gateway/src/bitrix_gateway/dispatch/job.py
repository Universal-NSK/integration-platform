from dataclasses import dataclass
from datetime import datetime

from bitrix_gateway.contracts.models import GatewayRequest


@dataclass(frozen=True)
class GatewayJob:
    """Связывает запрос с внутренним идентификатором и временем постановки."""

    id: str
    request: GatewayRequest
    created_at: datetime
