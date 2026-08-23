import asyncio
from typing import Any, Callable, Dict

import httpx
import pytest
from bitrix_gateway.contracts.models import TransportResult
from bitrix_gateway.execution.http_transport import HttpBitrixTransport
from bitrix_gateway.execution.transport import BitrixTransport, TransportError

ResponseHandler = Callable[[httpx.Request], httpx.Response]
ErrorFactory = Callable[[httpx.Request], httpx.RequestError]


def _as_bitrix_transport(transport: HttpBitrixTransport) -> BitrixTransport:
    """Keep structural Protocol compatibility covered by Pyright."""
    return transport


def _call_transport(
    handler: ResponseHandler,
    *,
    method: str = "crm.item.list",
) -> TransportResult:
    async def scenario() -> TransportResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = _as_bitrix_transport(
                HttpBitrixTransport(client, "https://example.test/rest")
            )
            return await transport.call(method, {"entityTypeId": 2})

    return asyncio.run(scenario())


def _call_transport_error(handler: ResponseHandler) -> TransportError:
    async def scenario() -> TransportError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = HttpBitrixTransport(client, "https://example.test/rest")
            try:
                await transport.call("crm.item.list", {"entityTypeId": 2})
            except TransportError as exc:
                return exc
        raise AssertionError("TransportError was not raised")

    return asyncio.run(scenario())


def _connect_error(request: httpx.Request) -> httpx.RequestError:
    return httpx.ConnectError("connection failed", request=request)


def _connect_timeout(request: httpx.Request) -> httpx.RequestError:
    return httpx.ConnectTimeout("connection timed out", request=request)


def _pool_timeout(request: httpx.Request) -> httpx.RequestError:
    return httpx.PoolTimeout("pool timed out", request=request)


def test_success_keeps_complete_bitrix_body_and_operating_reset_at() -> None:
    body: Dict[str, Any] = {
        "result": {"items": [{"id": 1}]},
        "next": 50,
        "total": 1576,
        "time": {
            "duration": 0.2,
            "operating_reset_at": 1787492641,
            "operating": 2.8,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/crm.item.list")
        return httpx.Response(200, json=body)

    result = _call_transport(handler)

    assert result == TransportResult(
        data=body,
        http_status=200,
        error_code=None,
        error_message=None,
        operating_reset_at=1787492641.0,
    )


def test_bitrix_api_error_is_normalized_without_raising_for_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": "ENTITY_TYPE_NOT_SUPPORTED",
                "error_description": "CRM entity is not supported",
            },
        )

    result = _call_transport(handler)

    assert result == TransportResult(
        data=None,
        http_status=400,
        error_code="ENTITY_TYPE_NOT_SUPPORTED",
        error_message="CRM entity is not supported",
        operating_reset_at=None,
    )


@pytest.mark.parametrize(
    "body",
    [
        {"result": []},
        {"result": [], "time": {}},
    ],
)
def test_missing_operating_reset_at_is_none(body: Dict[str, Any]) -> None:
    result = _call_transport(lambda request: httpx.Response(200, json=body))

    assert result.operating_reset_at is None
    assert result.data == body


@pytest.mark.parametrize(
    "error_factory",
    [_connect_error, _connect_timeout, _pool_timeout],
)
def test_definitely_unsent_request_errors_have_certain_outcome(
    error_factory: ErrorFactory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_factory(request)

    error = _call_transport_error(handler)

    assert error.outcome_uncertain is False


def test_other_request_errors_have_uncertain_outcome() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response timed out", request=request)

    error = _call_transport_error(handler)

    assert error.outcome_uncertain is True


def test_invalid_json_raises_uncertain_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            content=b"not-json",
            headers={"content-type": "application/json"},
        )

    error = _call_transport_error(handler)

    assert error.outcome_uncertain is True
    assert "invalid JSON" in str(error)
    assert "502" in str(error)


@pytest.mark.parametrize("root", [[], "unexpected", 42])
def test_unexpected_json_root_raises_uncertain_transport_error(root: Any) -> None:
    error = _call_transport_error(lambda request: httpx.Response(200, json=root))

    assert error.outcome_uncertain is True
    assert "unexpected root type" in str(error)
