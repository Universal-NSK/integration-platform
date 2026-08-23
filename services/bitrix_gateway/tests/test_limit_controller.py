import asyncio
from typing import List

from bitrix_gateway.limits.controller import BitrixApiLimitController
from bitrix_gateway.limits.cooldowns import MethodCooldownRegistry
from bitrix_gateway.limits.rate_limiter import RateLimiter


class RecordingRateLimiter(RateLimiter):
    def __init__(self, calls: List[str]) -> None:
        super().__init__(min_interval=1.0)
        self._calls = calls

    async def wait_turn(self) -> None:
        self._calls.append("rate")


class RecordingCooldownRegistry(MethodCooldownRegistry):
    def __init__(self, calls: List[str]) -> None:
        super().__init__()
        self._calls = calls

    async def wait_turn(self, method: str) -> None:
        self._calls.append(f"cooldown:{method}")


def test_wait_turn_checks_method_cooldown_before_rate_limit() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        controller = BitrixApiLimitController(
            rate_limiter=RecordingRateLimiter(calls),
            cooldowns=RecordingCooldownRegistry(calls),
        )

        await controller.wait_turn("crm.lead.add")

        assert calls == [
            "cooldown:crm.lead.add",
            "rate",
        ]

    asyncio.run(scenario())