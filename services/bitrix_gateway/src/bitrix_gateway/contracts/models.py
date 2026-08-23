from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class RetryPolicy(Enum):
    SAFE = "safe"
    NEVER = "never"


class ExecutionStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GatewayRequest:
    method: str
    payload: Dict[str, Any]
    retry_policy: RetryPolicy


@dataclass(frozen=True)
class GatewayResult:
    status: ExecutionStatus
    data: Optional[Dict[str, Any]]
    http_status: Optional[int]
    error_code: Optional[str]
    error_message: Optional[str]
    attempt_count: int


@dataclass(frozen=True)
class TransportResult:
    data: Optional[Dict[str, Any]]
    http_status: int
    error_code: Optional[str]
    error_message: Optional[str]
    operating_reset_at: Optional[float]
