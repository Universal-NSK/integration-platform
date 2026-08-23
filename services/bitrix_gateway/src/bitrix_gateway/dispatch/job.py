from dataclasses import dataclass
from datetime import datetime

from bitrix_gateway.contracts.models import GatewayRequest


@dataclass(frozen=True)
class GatewayJob:
    id: str
    request: GatewayRequest
    created_at: datetime
