from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, cast

import pytest
from bitrix_gateway.contracts.models import (
    ExecutionStatus,
    GatewayRequest,
    GatewayResult,
    RetryPolicy,
)
from bitrix_gateway.dispatch.dispatcher import RequestDispatcher
from bitrix_gateway.dispatch.queue import QueueFullError
from bitrix_gateway.http_api.api import GatewayHttpApi
from bitrix_gateway.http_api.routes import create_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeDispatcher:
    def __init__(
        self,
        *,
        result: Optional[GatewayResult] = None,
        error: Optional[Exception] = None,
        block: bool = False,
        queue_size: int = 0,
    ) -> None:
        self.result = result
        self.error = error
        self.block = block
        self.queue_size_value = queue_size
        self.submitted: List[GatewayRequest] = []
        self.queue_size_calls = 0

    async def submit(self, request: GatewayRequest) -> GatewayResult:
        self.submitted.append(request)

        if self.error is not None:
            raise self.error

        if self.block:
            pending: asyncio.Future[GatewayResult] = asyncio.get_running_loop().create_future()
            return await pending

        if self.result is None:
            raise AssertionError("FakeDispatcher requires a result")

        return self.result

    def queue_size(self) -> int:
        self.queue_size_calls += 1
        return self.queue_size_value


def _result(
    *,
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
    data: Optional[Dict[str, Any]] = None,
    http_status: Optional[int] = 200,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    attempt_count: int = 1,
) -> GatewayResult:
    return GatewayResult(
        status=status,
        data=data,
        http_status=http_status,
        error_code=error_code,
        error_message=error_message,
        attempt_count=attempt_count,
    )


def _client(
    dispatcher: FakeDispatcher,
    *,
    request_timeout: float = 1.0,
    raise_server_exceptions: bool = True,
) -> TestClient:
    api = GatewayHttpApi(
        dispatcher=cast(RequestDispatcher, dispatcher),
        request_timeout=request_timeout,
    )
    app = FastAPI()
    app.include_router(create_router(api))
    return TestClient(
        app,
        raise_server_exceptions=raise_server_exceptions,
    )


def test_call_accepts_request_and_maps_complete_success_result() -> None:
    data = {
        "result": [{"id": "1", "title": "Lead"}],
        "next": 50,
        "total": 125,
        "time": {"duration": 0.25, "processing": 0.1},
    }
    dispatcher = FakeDispatcher(
        result=_result(
            data=data,
            http_status=200,
            attempt_count=2,
        )
    )

    with _client(dispatcher) as client:
        response = client.post(
            "/call",
            json={
                "method": "crm.item.list",
                "payload": {
                    "entityTypeId": 1,
                    "filter": {">ID": 10},
                    "select": ["id", "title"],
                },
                "retry_policy": "safe",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "data": data,
        "http_status": 200,
        "error_code": None,
        "error_message": None,
        "attempt_count": 2,
    }
    assert dispatcher.submitted == [
        GatewayRequest(
            method="crm.item.list",
            payload={
                "entityTypeId": 1,
                "filter": {">ID": 10},
                "select": ["id", "title"],
            },
            retry_policy=RetryPolicy.SAFE,
        )
    ]
    assert type(dispatcher.submitted[0]) is GatewayRequest


@pytest.mark.parametrize(
    ("invalid_field", "request_body"),
    [
        (
            "method",
            {"method": "", "payload": {}, "retry_policy": "safe"},
        ),
        (
            "retry_policy",
            {"method": "crm.item.list", "payload": {}, "retry_policy": "sometimes"},
        ),
        (
            "payload",
            {"method": "crm.item.list", "payload": [], "retry_policy": "safe"},
        ),
        (
            "unexpected",
            {
                "method": "crm.item.list",
                "payload": {},
                "retry_policy": "safe",
                "unexpected": True,
            },
        ),
    ],
)
def test_call_rejects_invalid_http_request(
    invalid_field: str,
    request_body: Dict[str, object],
) -> None:
    dispatcher = FakeDispatcher(result=_result())

    with _client(dispatcher) as client:
        response = client.post("/call", json=request_body)

    assert response.status_code == 422
    assert any(error["loc"][-1] == invalid_field for error in response.json()["detail"])
    assert dispatcher.submitted == []


@pytest.mark.parametrize(
    "result",
    [
        _result(
            status=ExecutionStatus.FAILED,
            data={"error": "ERROR_CORE"},
            http_status=400,
            error_code="ERROR_CORE",
            error_message="Invalid request",
        ),
        _result(
            status=ExecutionStatus.UNKNOWN,
            data=None,
            http_status=None,
            error_code="CONNECTION_LOST",
            error_message="Outcome is unknown",
            attempt_count=3,
        ),
    ],
)
def test_bitrix_failure_is_returned_as_normal_gateway_response(
    result: GatewayResult,
) -> None:
    dispatcher = FakeDispatcher(result=result)

    with _client(dispatcher) as client:
        response = client.post(
            "/call",
            json={
                "method": "crm.item.add",
                "payload": {"fields": {"title": "Lead"}},
                "retry_policy": "never",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": result.status.value,
        "data": result.data,
        "http_status": result.http_status,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "attempt_count": result.attempt_count,
    }


def test_queue_full_is_gateway_503() -> None:
    dispatcher = FakeDispatcher(error=QueueFullError("queue is full"))

    with _client(dispatcher) as client:
        response = client.post(
            "/call",
            json={
                "method": "crm.item.list",
                "payload": {},
                "retry_policy": "safe",
            },
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Gateway queue is full"}


def test_request_timeout_limits_entire_dispatcher_submission() -> None:
    dispatcher = FakeDispatcher(block=True)

    with _client(dispatcher, request_timeout=0.001) as client:
        response = client.post(
            "/call",
            json={
                "method": "crm.item.list",
                "payload": {},
                "retry_policy": "safe",
            },
        )

    assert response.status_code == 504
    assert response.json() == {"detail": "Gateway request timed out"}
    assert len(dispatcher.submitted) == 1


def test_unexpected_dispatcher_error_uses_standard_gateway_500() -> None:
    dispatcher = FakeDispatcher(error=RuntimeError("unexpected dispatcher failure"))

    with _client(dispatcher, raise_server_exceptions=False) as client:
        response = client.post(
            "/call",
            json={
                "method": "crm.item.list",
                "payload": {},
                "retry_policy": "safe",
            },
        )

    assert response.status_code == 500
    assert response.text == "Internal Server Error"


@pytest.mark.parametrize("queue_size", [0, 7])
def test_health_reports_dispatcher_queue_size(queue_size: int) -> None:
    dispatcher = FakeDispatcher(queue_size=queue_size)

    with _client(dispatcher) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "queue_size": queue_size}
    assert dispatcher.queue_size_calls == 1
    assert dispatcher.submitted == []
