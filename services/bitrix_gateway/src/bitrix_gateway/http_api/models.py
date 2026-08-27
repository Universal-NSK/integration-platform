from typing import Any, Dict, Optional, cast

from pydantic import BaseModel, Field, validator  # pyright: ignore[reportUnknownVariableType]

from bitrix_gateway.contracts.models import (
    ExecutionStatus,
    RetryPolicy,
)


class CallRequest(BaseModel):
    method: str = Field(..., min_length=1)
    payload: Dict[str, Any]
    retry_policy: RetryPolicy

    @validator("payload", pre=True)  # pyright: ignore[reportUntypedFunctionDecorator]
    def payload_must_be_object(cls, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("payload must be an object")
        return cast(Dict[str, Any], value)

    class Config:
        extra = "forbid"


class CallResponse(BaseModel):
    status: ExecutionStatus
    data: Optional[Any] = None
    http_status: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    attempt_count: int

    class Config:
        extra = "forbid"


class HealthResponse(BaseModel):
    status: str
    queue_size: int = Field(..., ge=0)

    class Config:
        extra = "forbid"
