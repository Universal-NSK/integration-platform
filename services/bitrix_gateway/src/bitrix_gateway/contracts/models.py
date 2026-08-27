from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class RetryPolicy(Enum):
    """Определяет допустимость повторного выполнения запроса."""

    SAFE = "safe"
    NEVER = "never"


class ExecutionStatus(Enum):
    """Описывает нормализованный итог выполнения запроса Gateway."""

    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GatewayRequest:
    """Содержит запрос к Bitrix24 и выбранную политику повторов."""

    method: str
    payload: Dict[str, Any]
    retry_policy: RetryPolicy


@dataclass(frozen=True)
class GatewayResult:
    """Представляет итог Gateway с сохранением диагностических данных."""

    status: ExecutionStatus
    data: Optional[Dict[str, Any]]
    http_status: Optional[int]
    error_code: Optional[str]
    error_message: Optional[str]
    attempt_count: int


@dataclass(frozen=True)
class TransportResult:
    """Хранит нормализованный HTTP-ответ транспортного слоя Bitrix24."""

    data: Optional[Dict[str, Any]]
    http_status: int
    error_code: Optional[str]
    error_message: Optional[str]
    operating_reset_at: Optional[float]
