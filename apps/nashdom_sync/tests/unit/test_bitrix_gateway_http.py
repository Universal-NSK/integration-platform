import json
import traceback
from typing import Any, Callable, Dict

import httpx
import pytest
from nashdom_sync.bitrix_crm import BitrixGatewayError, ClientBitrixCRM
from nashdom_sync.bitrix_crm._contracts import GatewayExecutionStatus, RetryPolicy
from nashdom_sync.bitrix_crm._gateway import GatewayHttpClient


def wire(**changes: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "status": "success",
        "data": {"result": {"ID": "1"}},
        "http_status": 200,
        "error_code": None,
        "error_message": None,
        "attempt_count": 1,
    }
    body.update(changes)
    return body


def install_http(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.Client:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://fake/gateway/")

    def constructor(**kwargs: Any) -> httpx.Client:
        return client

    monkeypatch.setattr("nashdom_sync.bitrix_crm._gateway.httpx.Client", constructor)
    return client


@pytest.mark.parametrize("policy", [RetryPolicy.SAFE, RetryPolicy.NEVER])
@pytest.mark.parametrize("status", list(GatewayExecutionStatus))
def test_http_contract(
    monkeypatch: pytest.MonkeyPatch,
    policy: RetryPolicy,
    status: GatewayExecutionStatus,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/gateway/call"
        assert json.loads(request.content) == {
            "method": "profile",
            "payload": {"x": 1},
            "retry_policy": policy.value,
        }
        return httpx.Response(200, json=wire(status=status.value))

    http = install_http(monkeypatch, handler)
    gateway = GatewayHttpClient("http://fake/gateway/", 3.0)
    try:
        result = gateway.call("profile", {"x": 1}, policy)
        assert result.status is status
        assert result.data == {"result": {"ID": "1"}}
        assert result.attempt_count == 1
    finally:
        gateway.close()
        gateway.close()
    assert http.is_closed


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        wire(status="bad"),
        wire(status=[]),
        wire(data=[]),
        wire(data=None),
        wire(http_status=True),
        wire(http_status="200"),
        wire(http_status=999),
        wire(attempt_count=True),
        wire(attempt_count=0),
        wire(attempt_count="1"),
        wire(error_code=1),
        wire(error_message={}),
        wire(extra=True),
    ],
)
def test_invalid_contract(monkeypatch: pytest.MonkeyPatch, body: Any) -> None:
    install_http(monkeypatch, lambda _: httpx.Response(200, json=body))
    gateway = GatewayHttpClient("http://fake", 3.0)
    try:
        with pytest.raises(BitrixGatewayError):
            gateway.call("profile", {}, RetryPolicy.SAFE)
    finally:
        gateway.close()


@pytest.mark.parametrize("failure", ["connect", "timeout", "http", "json", "redirect"])
def test_transport_errors_hide_url_and_body(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "connect":
            raise httpx.ConnectError("https://secret.invalid/token", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("token=private", request=request)
        if failure == "http":
            return httpx.Response(503, text="token=private")
        if failure == "redirect":
            return httpx.Response(307, headers={"location": "https://secret.invalid/token"})
        return httpx.Response(200, text="token=private")

    install_http(monkeypatch, handler)
    gateway = GatewayHttpClient("http://fake", 3.0)
    try:
        with pytest.raises(BitrixGatewayError) as exc:
            gateway.call("profile", {}, RetryPolicy.SAFE)
        rendered = "".join(
            traceback.format_exception(type(exc.value), exc.value, exc.value.__traceback__)
        )
        assert "secret.invalid" not in rendered and "token=private" not in rendered
        assert calls == 1
    finally:
        gateway.close()


def test_high_level_close_closes_owned_http(monkeypatch: pytest.MonkeyPatch) -> None:
    http = install_http(monkeypatch, lambda _: httpx.Response(200, json=wire()))
    client = ClientBitrixCRM("http://fake", 3.0)
    assert client.profile() == {"ID": "1"}
    client.close()
    client.close()
    assert http.is_closed
    with pytest.raises(BitrixGatewayError):
        client.profile()
