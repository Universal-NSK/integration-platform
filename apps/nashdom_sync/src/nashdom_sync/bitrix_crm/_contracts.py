from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class RetryPolicy(Enum):
    """Определяет допустимость повторов на стороне Gateway."""

    SAFE = "safe"
    NEVER = "never"


class GatewayExecutionStatus(Enum):
    """Описывает результат выполнения запроса Gateway."""

    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GatewayCallResult:
    """Хранит локальное представление HTTP-контракта Gateway."""

    status: GatewayExecutionStatus
    data: Optional[Dict[str, Any]]
    http_status: Optional[int]
    error_code: Optional[str]
    error_message: Optional[str]
    attempt_count: int
