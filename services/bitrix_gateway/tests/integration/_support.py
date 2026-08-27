from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

import httpx
from bitrix_gateway.app import create_app
from bitrix_gateway.bootstrap import GatewayRuntime
from bitrix_gateway.contracts.models import TransportResult
from bitrix_gateway.dispatch.dispatcher import RequestDispatcher
from bitrix_gateway.dispatch.queue import InMemoryJobQueue
from bitrix_gateway.execution.executor import RequestExecutor
from bitrix_gateway.execution.transport import TransportError
from bitrix_gateway.http_api.api import GatewayHttpApi
from bitrix_gateway.limits.controller import BitrixApiLimitController
from bitrix_gateway.limits.cooldowns import MethodCooldownRegistry
from bitrix_gateway.limits.rate_limiter import RateLimiter
from bitrix_gateway.settings.models import GatewaySecrets, GatewaySettings
from fastapi import FastAPI
from platform_logging import LoggingConfig, configure_logging
from runtime_files import RuntimePaths

FAKE_WEBHOOK_URL = "https://example.invalid/rest/test/fake-secret"


def valid_settings_data(*, log_payloads: bool = False) -> Dict[str, Any]:
    return {
        "bitrix": {"request_timeout": 5.0},
        "limits": {"min_interval": 0.001},
        "execution": {"max_attempts": 2, "retry_delay": 0.0},
        "queue": {"max_size": 10},
        "http": {"request_timeout": 2.0},
        "server": {"host": "127.0.0.1", "port": 8765},
        "logging": {
            "level": "INFO",
            "console": False,
            "log_payloads": log_payloads,
            "max_bytes": 100000,
            "backup_count": 1,
        },
    }


def valid_settings(*, log_payloads: bool = False) -> GatewaySettings:
    return GatewaySettings.parse_obj(valid_settings_data(log_payloads=log_payloads))


def valid_secrets() -> GatewaySecrets:
    return GatewaySecrets.parse_obj({"bitrix": {"webhook_url": FAKE_WEBHOOK_URL}})


class FakeBitrixTransport:
    def __init__(
        self,
        outcome: Union[TransportResult, TransportError],
        *,
        webhook_url: str = FAKE_WEBHOOK_URL,
    ) -> None:
        self.outcome = outcome
        self.webhook_url = webhook_url
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def call(
        self,
        method: str,
        payload: Dict[str, Any],
    ) -> TransportResult:
        self.calls.append((method, payload))

        if isinstance(self.outcome, TransportError):
            raise self.outcome

        return self.outcome


@dataclass(frozen=True)
class AssembledGateway:
    runtime: GatewayRuntime
    app: FastAPI
    transport: FakeBitrixTransport


def assemble_gateway(
    tmp_path: Path,
    outcome: Union[TransportResult, TransportError],
    *,
    log_payloads: bool = False,
) -> AssembledGateway:
    paths = RuntimePaths(
        repo_root=tmp_path.resolve(),
        program_data_root=(tmp_path / "program-data").resolve(),
    )
    logging_session = configure_logging(
        service_name="bitrix_gateway",
        logger_name="bitrix_gateway",
        paths=paths,
        config=LoggingConfig(
            level="INFO",
            console=False,
            log_payloads=log_payloads,
            max_bytes=100000,
            backup_count=1,
        ),
    )
    http_client = httpx.AsyncClient()
    transport = FakeBitrixTransport(outcome)
    limits = BitrixApiLimitController(
        rate_limiter=RateLimiter(min_interval=0.001),
        cooldowns=MethodCooldownRegistry(),
    )
    executor = RequestExecutor(
        transport=transport,
        limits=limits,
        max_attempts=2,
        retry_delay=0.0,
    )
    dispatcher = RequestDispatcher(
        queue=InMemoryJobQueue(max_size=10),
        executor=executor,
    )
    api = GatewayHttpApi(
        dispatcher=dispatcher,
        request_timeout=2.0,
        log_payloads=logging_session.config.log_payloads,
    )
    runtime = GatewayRuntime(
        http_client=http_client,
        dispatcher=dispatcher,
        api=api,
        logging_session=logging_session,
    )
    return AssembledGateway(
        runtime=runtime,
        app=create_app(runtime),
        transport=transport,
    )


def read_log(runtime: GatewayRuntime) -> str:
    logger = logging.getLogger(runtime.logging_session.logger_name)
    for handler in logger.handlers:
        handler.flush()
    return runtime.logging_session.log_file.read_text(encoding="utf-8")
