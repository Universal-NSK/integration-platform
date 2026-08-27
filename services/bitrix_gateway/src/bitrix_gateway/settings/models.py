from pydantic import BaseModel, Field


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class BitrixSettings(StrictModel):
    request_timeout: float = Field(..., gt=0)


class LimitSettings(StrictModel):
    min_interval: float = Field(..., gt=0)


class ExecutionSettings(StrictModel):
    max_attempts: int = Field(..., ge=1)
    retry_delay: float = Field(..., ge=0)


class QueueSettings(StrictModel):
    max_size: int = Field(..., ge=1)


class HttpSettings(StrictModel):
    request_timeout: float = Field(..., gt=0)


class ServerSettings(StrictModel):
    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)


class LoggingSettings(StrictModel):
    level: str = Field(..., min_length=1)
    console: bool
    log_payloads: bool
    max_bytes: int = Field(..., gt=0)
    backup_count: int = Field(..., ge=0)


class GatewaySettings(StrictModel):
    bitrix: BitrixSettings
    limits: LimitSettings
    execution: ExecutionSettings
    queue: QueueSettings
    http: HttpSettings
    server: ServerSettings
    logging: LoggingSettings


class BitrixSecrets(StrictModel):
    webhook_url: str = Field(..., min_length=1)


class GatewaySecrets(StrictModel):
    bitrix: BitrixSecrets
