import asyncio
import time

import pytest
from bitrix_gateway.limits.cooldowns import MethodCooldownRegistry


def test_method_without_cooldown_does_not_wait() -> None:
    async def scenario() -> None:
        registry = MethodCooldownRegistry()

        await registry.wait_turn("crm.lead.add")

    asyncio.run(scenario())


def test_cooldown_delays_method() -> None:
    async def scenario() -> None:
        registry = MethodCooldownRegistry()
        registry.set_cooldown("crm.lead.add", 0.05)

        started_at = time.monotonic()
        await registry.wait_turn("crm.lead.add")
        elapsed = time.monotonic() - started_at

        assert elapsed >= 0.04

    asyncio.run(scenario())


def test_cooldown_does_not_block_other_methods() -> None:
    async def scenario() -> None:
        registry = MethodCooldownRegistry()
        registry.set_cooldown("crm.lead.add", 0.1)

        started_at = time.monotonic()
        await registry.wait_turn("crm.company.get")
        elapsed = time.monotonic() - started_at

        assert elapsed < 0.05

    asyncio.run(scenario())


def test_longer_cooldown_extends_existing_cooldown() -> None:
    async def scenario() -> None:
        registry = MethodCooldownRegistry()
        method = "crm.lead.add"

        registry.set_cooldown(method, 0.05)

        async def extend_cooldown() -> None:
            await asyncio.sleep(0.02)
            registry.set_cooldown(method, 0.08)

        task = asyncio.create_task(extend_cooldown())

        started_at = time.monotonic()
        await registry.wait_turn(method)
        elapsed = time.monotonic() - started_at

        await task

        assert elapsed >= 0.09

    asyncio.run(scenario())


def test_negative_cooldown_is_rejected() -> None:
    registry = MethodCooldownRegistry()

    with pytest.raises(ValueError):
        registry.set_cooldown("crm.lead.add", -1.0)
