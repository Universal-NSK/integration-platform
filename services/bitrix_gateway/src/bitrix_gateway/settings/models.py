from pydantic import BaseModel, Field


class StrictModel(BaseModel):
    """Запрещает неизвестные поля во всех моделях настроек Gateway."""

    class Config:
        extra = "forbid"


class BitrixSettings(StrictModel):
    """Задаёт параметры HTTP-взаимодействия с Bitrix24."""

    request_timeout: float = Field(..., gt=0)


class LimitSettings(StrictModel):
    """Задаёт глобальные ограничения частоты запросов к Bitrix24."""

    min_interval: float = Field(..., gt=0)


class ExecutionSettings(StrictModel):
    """Задаёт число попыток и паузу между повторными запросами."""

    max_attempts: int = Field(..., ge=1)
    retry_delay: float = Field(..., ge=0)


class QueueSettings(StrictModel):
    """Задаёт максимальную вместимость очереди Gateway."""

    max_size: int = Field(..., ge=1)


class HttpSettings(StrictModel):
    """Задаёт тайм-аут обработки входящего HTTP-запроса."""

    request_timeout: float = Field(..., gt=0)


class ServerSettings(StrictModel):
    """Задаёт адрес и порт локального HTTP-сервера."""

    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)


class LoggingSettings(StrictModel):
    """Задаёт уровень, вывод и ротацию журналов Gateway."""

    level: str = Field(..., min_length=1)
    console: bool
    log_payloads: bool
    max_bytes: int = Field(..., gt=0)
    backup_count: int = Field(..., ge=0)


class GatewaySettings(StrictModel):
    """Объединяет все несекретные настройки Gateway."""

    bitrix: BitrixSettings
    limits: LimitSettings
    execution: ExecutionSettings
    queue: QueueSettings
    http: HttpSettings
    server: ServerSettings
    logging: LoggingSettings


class BitrixSecrets(StrictModel):
    """Хранит секретные параметры подключения к Bitrix24."""

    webhook_url: str = Field(..., min_length=1)


class GatewaySecrets(StrictModel):
    """Объединяет секретные настройки Gateway."""

    bitrix: BitrixSecrets
