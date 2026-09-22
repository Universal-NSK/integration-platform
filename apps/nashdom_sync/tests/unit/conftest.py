import socket
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit-тесты клиента никогда не открывают реальные соединения."""

    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Реальная сеть запрещена в unit-тестах")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
