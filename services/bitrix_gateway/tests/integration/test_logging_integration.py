from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Tuple, Type, cast

import httpx
import pytest
from bitrix_gateway.app import create_app
from bitrix_gateway.bootstrap import GatewayRuntime
from bitrix_gateway.dispatch.dispatcher import RequestDispatcher
from bitrix_gateway.dispatch.queue import InMemoryJobQueue
from bitrix_gateway.execution.executor import RequestExecutor
from bitrix_gateway.execution.http_transport import HttpBitrixTransport
from bitrix_gateway.http_api.api import GatewayHttpApi
from bitrix_gateway.limits.controller import BitrixApiLimitController
from bitrix_gateway.limits.cooldowns import MethodCooldownRegistry
from bitrix_gateway.limits.rate_limiter import RateLimiter
from fastapi import FastAPI
from platform_logging import LoggingConfig, LoggingSession, configure_logging
from runtime_files import RuntimePaths

ResponseHandler = Callable[[httpx.Request], httpx.Response]
SECRET_TOKEN = "SUPER_SECRET_TOKEN"
WEBHOOK_URL = f"https://example.invalid/rest/50/{SECRET_TOKEN}"


@dataclass(frozen=True)
class LoggedGateway:
    runtime: GatewayRuntime
    app: FastAPI
    logging_session: LoggingSession


def _assemble_logged_gateway(
    tmp_path: Path,
    handler: ResponseHandler,
    *,
    level: str,
    log_payloads: bool,
    max_attempts: int = 1,
) -> LoggedGateway:
    paths = RuntimePaths(
        repo_root=tmp_path.resolve(),
        program_data_root=(tmp_path / "program-data").resolve(),
    )
    logging_session = configure_logging(
        service_name="bitrix_gateway",
        logger_name="bitrix_gateway",
        paths=paths,
        config=LoggingConfig(
            level=level,
            console=False,
            log_payloads=log_payloads,
            max_bytes=100_000,
            backup_count=1,
        ),
    )
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=1.0,
    )
    transport = HttpBitrixTransport(http_client, WEBHOOK_URL)
    limits = BitrixApiLimitController(
        rate_limiter=RateLimiter(min_interval=0.001),
        cooldowns=MethodCooldownRegistry(),
    )
    executor = RequestExecutor(
        transport=transport,
        limits=limits,
        max_attempts=max_attempts,
        retry_delay=0.0,
    )
    dispatcher = RequestDispatcher(
        queue=InMemoryJobQueue(max_size=10),
        executor=executor,
    )
    api = GatewayHttpApi(
        dispatcher=dispatcher,
        request_timeout=2.0,
        log_payloads=log_payloads,
    )
    runtime = GatewayRuntime(
        http_client=http_client,
        dispatcher=dispatcher,
        api=api,
        logging_session=logging_session,
    )
    return LoggedGateway(
        runtime=runtime,
        app=create_app(runtime),
        logging_session=logging_session,
    )


def _post_and_read_log(
    tmp_path: Path,
    handler: ResponseHandler,
    *,
    level: str,
    log_payloads: bool,
    payload: Dict[str, Any],
    retry_policy: str = "safe",
    max_attempts: int = 1,
) -> Tuple[httpx.Response, str]:
    async def scenario() -> Tuple[httpx.Response, LoggingSession]:
        assembled = _assemble_logged_gateway(
            tmp_path,
            handler,
            level=level,
            log_payloads=log_payloads,
            max_attempts=max_attempts,
        )
        transport = httpx.ASGITransport(app=assembled.app)
        async with assembled.app.router.lifespan_context(assembled.app):
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    "/call",
                    json={
                        "method": "crm.item.list",
                        "payload": payload,
                        "retry_policy": retry_policy,
                    },
                )
        return response, assembled.logging_session

    response, logging_session = asyncio.run(scenario())
    logger = logging.getLogger(logging_session.logger_name)
    for log_handler in logger.handlers:
        log_handler.flush()
    return response, logging_session.log_file.read_text(encoding="utf-8")


def _success_handler(request: httpx.Request) -> httpx.Response:
    assert request.method == "POST"
    return httpx.Response(
        200,
        json={"result": {"items": [{"id": 1, "title": "Тест"}]}},
    )


def test_info_keeps_boundary_events_and_disables_internal_debug_and_payloads(
    tmp_path: Path,
) -> None:
    marker = "НЕ_ЛОГИРОВАТЬ"
    response, log_text = _post_and_read_log(
        tmp_path,
        _success_handler,
        level="INFO",
        log_payloads=False,
        payload={"entityTypeId": 1, "marker": marker},
    )

    assert response.status_code == 200
    assert "gateway_call_request" in log_text
    assert "gateway_call_response" in log_text
    assert "dispatcher_job_enqueued" not in log_text
    assert "execution_attempt_started" not in log_text
    assert "transport_request_started" not in log_text
    assert "gateway_call_request_payload" not in log_text
    assert "gateway_call_response_payload" not in log_text
    assert marker not in log_text


def test_debug_records_complete_dispatch_executor_transport_pipeline(tmp_path: Path) -> None:
    response, log_text = _post_and_read_log(
        tmp_path,
        _success_handler,
        level="DEBUG",
        log_payloads=False,
        payload={"entityTypeId": 1},
    )

    assert response.status_code == 200
    for event in (
        "dispatcher_job_enqueued",
        "dispatcher_job_dequeued",
        "execution_started",
        "execution_attempt_started",
        "transport_request_started",
        "transport_response_received",
        "transport_response_parsed",
        "execution_attempt_succeeded",
        "execution_completed",
        "dispatcher_job_completed",
    ):
        assert event in log_text
    assert "job_id=" in log_text
    assert WEBHOOK_URL not in log_text
    assert SECRET_TOKEN not in log_text


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_httpx_exception_is_russian_nonempty_and_redacted_with_safe_traceback(
    tmp_path: Path,
    error_type: Type[httpx.RequestError],
) -> None:
    full_url = f"{WEBHOOK_URL}/crm.item.list"

    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type(
            f"connection failed for {request.url}",
            request=request,
        )

    response, log_text = _post_and_read_log(
        tmp_path,
        handler,
        level="DEBUG",
        log_payloads=False,
        payload={"entityTypeId": 1},
    )

    body = cast(Dict[str, Any], response.json())
    assert response.status_code == 200
    assert body["status"] == "failed"
    assert body["error_code"] == "TRANSPORT_ERROR"
    assert body["error_message"] == f"Ошибка транспорта Bitrix24: {error_type.__name__}"
    assert "transport_request_failed" in log_text
    assert "execution_transport_failed" in log_text
    assert f"exception_type={error_type.__name__}" in log_text
    assert "Traceback (most recent call last):" in log_text
    assert " | ERROR | " in log_text
    assert WEBHOOK_URL not in log_text
    assert full_url not in log_text
    assert SECRET_TOKEN not in log_text


def test_retry_logs_decision_and_attempts_while_info_stays_compact(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("временный сбой соединения", request=request)
        return httpx.Response(200, json={"result": {"items": []}})

    response, log_text = _post_and_read_log(
        tmp_path,
        handler,
        level="DEBUG",
        log_payloads=False,
        max_attempts=2,
        payload={"entityTypeId": 1},
    )

    body = cast(Dict[str, Any], response.json())
    assert body["status"] == "success"
    assert body["attempt_count"] == 2
    assert calls == 2
    assert "execution_retry_scheduled" in log_text
    assert "attempt=1" in log_text
    assert "next_attempt=2" in log_text
    assert "attempt=2" in log_text

    info_lines = [line for line in log_text.splitlines() if " | INFO | " in line]
    info_text = "\n".join(info_lines)
    assert "gateway_call_request" in info_text
    assert "gateway_call_response" in info_text
    assert "execution_retry_scheduled" not in info_text
    assert "transport_request_started" not in info_text


def test_enabled_payload_audit_is_separate_compact_utf8_json(tmp_path: Path) -> None:
    response, log_text = _post_and_read_log(
        tmp_path,
        _success_handler,
        level="INFO",
        log_payloads=True,
        payload={"entityTypeId": 1, "title": "Русский текст"},
    )

    assert response.status_code == 200
    assert "gateway_call_request_payload" in log_text
    assert 'payload={"entityTypeId":1,"title":"Русский текст"}' in log_text
    assert "gateway_call_response_payload" in log_text
    assert "Тест" in log_text
    assert "\\u0420" not in log_text
    assert WEBHOOK_URL not in log_text
    assert SECRET_TOKEN not in log_text
