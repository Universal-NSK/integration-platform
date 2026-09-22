import logging
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple, Union

import httpx
import pytest
import uvicorn
from bitrix_gateway.app import create_app
from bitrix_gateway.bootstrap import GatewayRuntime
from bitrix_gateway.contracts.models import TransportResult
from bitrix_gateway.dispatch.dispatcher import RequestDispatcher
from bitrix_gateway.dispatch.queue import InMemoryJobQueue
from bitrix_gateway.execution.executor import RequestExecutor
from bitrix_gateway.execution.http_transport import HttpBitrixTransport
from bitrix_gateway.execution.transport import TransportError
from bitrix_gateway.http_api.api import GatewayHttpApi
from bitrix_gateway.limits.controller import BitrixApiLimitController
from bitrix_gateway.limits.cooldowns import MethodCooldownRegistry
from bitrix_gateway.limits.rate_limiter import RateLimiter
from fastapi import FastAPI
from nashdom_sync.bitrix_crm import (
    BitrixRequestFailedError,
    BitrixRequestUnknownError,
    ClientBitrixCRM,
)
from platform_logging import LoggingConfig, configure_logging
from runtime_files import RuntimePaths

pytestmark = pytest.mark.gateway_integration


class FakeBitrixTransport:
    def __init__(self) -> None:
        self.outcomes: List[Union[TransportResult, TransportError]] = []
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def call(self, method: str, payload: Dict[str, Any]) -> TransportResult:
        self.calls.append((method, payload))
        assert self.outcomes, "Не задан fake-ответ: реальный Bitrix недоступен"
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, TransportError):
            raise outcome
        return outcome


@dataclass
class LocalGateway:
    client: ClientBitrixCRM
    transport: FakeBitrixTransport


@pytest.fixture
def local_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LocalGateway]:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Production Bitrix transport запрещён")

    # Защита даже при ошибочной замене fake-транспорта в сборке.
    monkeypatch.setattr(HttpBitrixTransport, "call", blocked)
    original_connect = socket.socket.connect

    def loopback_only(sock: socket.socket, address: Any) -> None:
        assert address[0] in ("127.0.0.1", "::1"), "Разрешён только loopback"
        original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    paths = RuntimePaths(
        repo_root=tmp_path.resolve(), program_data_root=(tmp_path / "data").resolve()
    )
    session = configure_logging(
        service_name="bitrix_gateway",
        logger_name="bitrix_gateway",
        paths=paths,
        config=LoggingConfig(
            level="ERROR", console=False, log_payloads=False, max_bytes=100000, backup_count=1
        ),
    )
    fake = FakeBitrixTransport()
    # Этот ресурс требуется lifecycle Gateway, но не имеет сетевого транспорта.
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(blocked))

    def create_test_app() -> FastAPI:
        # Python 3.8 привязывает asyncio.Queue к текущему loop при создании.
        executor = RequestExecutor(
            transport=fake,
            limits=BitrixApiLimitController(
                rate_limiter=RateLimiter(min_interval=0.001),
                cooldowns=MethodCooldownRegistry(),
            ),
            max_attempts=2,
            retry_delay=0.0,
        )
        dispatcher = RequestDispatcher(queue=InMemoryJobQueue(max_size=10), executor=executor)
        runtime = GatewayRuntime(
            http_client=http_client,
            dispatcher=dispatcher,
            api=GatewayHttpApi(dispatcher=dispatcher, request_timeout=3.0),
            logging_session=session,
        )
        return create_app(runtime)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_test_app,
            factory=True,
            log_config=None,
            access_log=False,
            lifespan="on",
        )
    )
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    client = ClientBitrixCRM(gateway_url="http://127.0.0.1:{}".format(port), timeout=5.0)
    try:
        deadline = time.monotonic() + 5.0
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "Локальный тестовый Gateway не запустился"
        yield LocalGateway(client, fake)
    finally:
        client.close()
        server.should_exit = True
        worker.join(timeout=5.0)
        listener.close()
        logger = logging.getLogger(session.logger_name)
        for handler in list(logger.handlers):
            if getattr(handler, "_platform_logging_owned", False):
                logger.removeHandler(handler)
                handler.close()
        assert not worker.is_alive(), "Тестовый Gateway не завершился"
        assert http_client.is_closed


def reply(result: Any, **extra: Any) -> TransportResult:
    return TransportResult({"result": result, **extra}, 200, None, None, None)


def test_pagination_through_http_gateway(local_gateway: LocalGateway) -> None:
    local_gateway.transport.outcomes.extend(
        [
            reply({"items": [{"id": i} for i in range(50)]}, next=50, total=51),
            reply({"items": [{"id": 50}]}, total=51),
        ]
    )
    assert len(local_gateway.client.list_items(4, select=["id"])) == 51
    assert local_gateway.transport.calls == [
        ("crm.item.list", {"entityTypeId": 4, "select": ["id"]}),
        ("crm.item.list", {"entityTypeId": 4, "select": ["id"], "start": 50}),
    ]


def test_safe_retries_inside_gateway(local_gateway: LocalGateway) -> None:
    local_gateway.transport.outcomes.extend(
        [
            TransportError("Fake disconnect", outcome_uncertain=True),
            reply({"ID": "1"}),
        ]
    )
    assert local_gateway.client.profile() == {"ID": "1"}
    assert local_gateway.transport.calls == [("profile", {}), ("profile", {})]


def test_write_success_only_with_fake_transport(local_gateway: LocalGateway) -> None:
    local_gateway.transport.outcomes.extend([reply({"item": {"id": 7}}), reply(8), reply(True)])
    assert local_gateway.client.add_item(4, {"title": "Fake"}) == 7
    assert local_gateway.client.add_requisite({"RQ_INN": "001"}) == 8
    assert local_gateway.client.add_address({"ADDRESS_2": "Fake address"}) is None
    assert local_gateway.transport.calls == [
        ("crm.item.add", {"entityTypeId": 4, "fields": {"title": "Fake"}}),
        ("crm.requisite.add", {"fields": {"RQ_INN": "001"}}),
        ("crm.address.add", {"fields": {"ADDRESS_2": "Fake address"}}),
    ]


@pytest.mark.parametrize("method", ["item", "requisite", "address"])
def test_never_becomes_unknown_without_retry(local_gateway: LocalGateway, method: str) -> None:
    local_gateway.transport.outcomes.append(
        TransportError("Fake disconnect", outcome_uncertain=True)
    )
    with pytest.raises(BitrixRequestUnknownError, match="TRANSPORT_ERROR"):
        if method == "item":
            local_gateway.client.add_item(4, {})
        elif method == "requisite":
            local_gateway.client.add_requisite({})
        else:
            local_gateway.client.add_address({})
    assert len(local_gateway.transport.calls) == 1


def test_failed_is_distinct_from_unknown(local_gateway: LocalGateway) -> None:
    local_gateway.transport.outcomes.append(
        TransportResult(None, 400, "ACCESS_DENIED", "Fake denied", None),
    )
    with pytest.raises(BitrixRequestFailedError, match="ACCESS_DENIED"):
        local_gateway.client.profile()
    assert len(local_gateway.transport.calls) == 1
