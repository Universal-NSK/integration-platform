import asyncio

import pytest
from bitrix_gateway.bootstrap import build_rate_limiter
from bitrix_gateway.main import main
from bitrix_gateway.settings.models import GatewaySettings


def test_build_rate_limiter() -> None:
    settings = GatewaySettings.parse_obj(
        {
            "bitrix": {"request_timeout": 5.0},
            "limits": {
                "min_interval": 0.5,
            },
            "execution": {"max_attempts": 2, "retry_delay": 0.0},
            "queue": {"max_size": 10},
            "http": {"request_timeout": 10.0},
            "server": {"host": "127.0.0.1", "port": 8765},
            "logging": {
                "level": "INFO",
                "console": False,
                "log_payloads": False,
                "max_bytes": 10000,
                "backup_count": 1,
            },
        }
    )

    async def scenario() -> float:
        rate_limiter = build_rate_limiter(settings)
        return rate_limiter.get_min_interval

    assert asyncio.run(scenario()) == 0.5

def test_main_suppresses_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_keyboard_interrupt(coro: object) -> None:
        if hasattr(coro, "close"):
            coro.close() # type: ignore

        raise KeyboardInterrupt

    monkeypatch.setattr(
        asyncio,
        "run",
        raise_keyboard_interrupt,
    )

    main()
