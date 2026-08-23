import asyncio
import time

from bitrix_gateway.limits.rate_limiter import RateLimiter


def test_wait_turn_respects_interval() -> None:
    async def scenario() -> None:
        limiter = RateLimiter(min_interval=0.1)
        await limiter.wait_turn()
        started_at = time.monotonic()
        await limiter.wait_turn()
        elapsed = time.monotonic() - started_at
        assert elapsed >= 0.09

    asyncio.run(scenario())