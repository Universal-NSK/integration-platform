import asyncio
from pathlib import Path
from typing import Any, Dict, Tuple, Union, cast

import httpx
from bitrix_gateway.contracts.models import TransportResult
from bitrix_gateway.execution.transport import TransportError

from ._support import (
    FAKE_WEBHOOK_URL,
    AssembledGateway,
    assemble_gateway,
    read_log,
)


async def _post_call(
    assembled: AssembledGateway,
    request_body: Dict[str, Any],
) -> httpx.Response:
    transport = httpx.ASGITransport(app=assembled.app)
    async with assembled.app.router.lifespan_context(assembled.app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post("/call", json=request_body)


async def _assemble_and_post(
    tmp_path: Path,
    outcome: Union[TransportResult, TransportError],
    request_body: Dict[str, Any],
    *,
    log_payloads: bool = False,
) -> Tuple[AssembledGateway, httpx.Response]:
    assembled = assemble_gateway(
        tmp_path,
        outcome,
        log_payloads=log_payloads,
    )
    response = await _post_call(assembled, request_body)
    return assembled, response


def test_call_success_preserves_exact_method_payload_and_complete_response(
    tmp_path: Path,
) -> None:
    response_data = {
        "result": {"item": {"id": 42, "title": "Тест"}},
        "time": {"duration": 0.25, "processing": 0.1},
        "total": 1,
    }
    payload = {
        "entityTypeId": 2,
        "fields": {"TITLE": "Тест"},
    }

    assembled, response = asyncio.run(
        _assemble_and_post(
            tmp_path,
            TransportResult(
                data=response_data,
                http_status=200,
                error_code=None,
                error_message=None,
                operating_reset_at=None,
            ),
            {
                "method": "crm.item.add",
                "payload": payload,
                "retry_policy": "never",
            },
            log_payloads=True,
        )
    )

    assert response.status_code == 200
    assert cast(Dict[str, Any], response.json()) == {
        "status": "success",
        "data": response_data,
        "http_status": 200,
        "error_code": None,
        "error_message": None,
        "attempt_count": 1,
    }
    assert assembled.transport.calls == [("crm.item.add", payload)]
    assert assembled.runtime.http_client.is_closed is True

    log_text = read_log(assembled.runtime)
    assert "gateway_call_request_payload" in log_text
    assert 'payload={"entityTypeId":2,"fields":{"TITLE":"Тест"}}' in log_text
    assert "gateway_call_response_payload" in log_text
    assert "Тест" in log_text
    assert FAKE_WEBHOOK_URL not in log_text
    assert "fake-secret" not in log_text


def test_ordinary_bitrix_error_remains_http_200_failed_response(tmp_path: Path) -> None:
    _, response = asyncio.run(
        _assemble_and_post(
            tmp_path,
            TransportResult(
                data=None,
                http_status=400,
                error_code="ENTITY_TYPE_NOT_SUPPORTED",
                error_message="Entity type is not supported",
                operating_reset_at=None,
            ),
            {
                "method": "crm.item.add",
                "payload": {"entityTypeId": -1, "fields": {}},
                "retry_policy": "never",
            },
        )
    )

    body = cast(Dict[str, Any], response.json())
    assert response.status_code == 200
    assert body["status"] == "failed"
    assert body["http_status"] == 400
    assert body["error_code"] == "ENTITY_TYPE_NOT_SUPPORTED"
    assert body["attempt_count"] == 1


def test_uncertain_transport_error_with_never_policy_is_unknown(tmp_path: Path) -> None:
    _, response = asyncio.run(
        _assemble_and_post(
            tmp_path,
            TransportError(
                "Connection lost after request was sent",
                outcome_uncertain=True,
            ),
            {
                "method": "crm.item.add",
                "payload": {"entityTypeId": 2, "fields": {"TITLE": "Тест"}},
                "retry_policy": "never",
            },
        )
    )

    body = cast(Dict[str, Any], response.json())
    assert response.status_code == 200
    assert body["status"] == "unknown"
    assert body["http_status"] is None
    assert body["error_code"] == "TRANSPORT_ERROR"
    assert body["attempt_count"] == 1
