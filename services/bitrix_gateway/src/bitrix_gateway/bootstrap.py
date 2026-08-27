from dataclasses import dataclass

import httpx
from platform_logging import (
    LoggingConfig,
    LoggingSession,
    configure_logging,
)
from runtime_files import RuntimePaths

from bitrix_gateway.dispatch.dispatcher import RequestDispatcher
from bitrix_gateway.dispatch.queue import InMemoryJobQueue
from bitrix_gateway.execution.executor import RequestExecutor
from bitrix_gateway.execution.http_transport import HttpBitrixTransport
from bitrix_gateway.http_api.api import GatewayHttpApi
from bitrix_gateway.limits.controller import BitrixApiLimitController
from bitrix_gateway.limits.cooldowns import MethodCooldownRegistry
from bitrix_gateway.limits.rate_limiter import RateLimiter
from bitrix_gateway.settings.models import (
    GatewaySecrets,
    GatewaySettings,
)


@dataclass(frozen=True)
class GatewayRuntime:
    http_client: httpx.AsyncClient
    dispatcher: RequestDispatcher
    api: GatewayHttpApi
    logging_session: LoggingSession


def build_rate_limiter(settings: GatewaySettings) -> RateLimiter:
    return RateLimiter(
        min_interval=settings.limits.min_interval,
    )


def build_runtime(
    settings: GatewaySettings,
    secrets: GatewaySecrets,
    paths: RuntimePaths,
) -> GatewayRuntime:
    logging_session = configure_logging(
        service_name="bitrix_gateway",
        logger_name="bitrix_gateway",
        paths=paths,
        config=LoggingConfig(
            level=settings.logging.level,
            console=settings.logging.console,
            log_payloads=settings.logging.log_payloads,
            max_bytes=settings.logging.max_bytes,
            backup_count=settings.logging.backup_count,
        ),
    )

    http_client = httpx.AsyncClient(
        timeout=settings.bitrix.request_timeout,
    )

    rate_limiter = build_rate_limiter(settings)

    cooldowns = MethodCooldownRegistry()

    limits = BitrixApiLimitController(
        rate_limiter=rate_limiter,
        cooldowns=cooldowns,
    )

    transport = HttpBitrixTransport(
        client=http_client,
        base_url=secrets.bitrix.webhook_url,
    )

    executor = RequestExecutor(
        transport=transport,
        limits=limits,
        max_attempts=settings.execution.max_attempts,
        retry_delay=settings.execution.retry_delay,
    )

    queue = InMemoryJobQueue(
        max_size=settings.queue.max_size,
    )

    dispatcher = RequestDispatcher(
        queue=queue,
        executor=executor,
    )

    api = GatewayHttpApi(
        dispatcher=dispatcher,
        request_timeout=settings.http.request_timeout,
        log_payloads=logging_session.config.log_payloads,
    )

    return GatewayRuntime(
        http_client=http_client,
        dispatcher=dispatcher,
        api=api,
        logging_session=logging_session,
    )
