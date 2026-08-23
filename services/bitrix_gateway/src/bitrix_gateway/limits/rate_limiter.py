import asyncio
import time


class RateLimiter:
    def __init__(self, min_interval: float) -> None:
        if min_interval <= 0:
            raise ValueError("min_interval must be greater than zero")

        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_start_ts = 0.0

    @property
    def get_min_interval(self) -> float:
        return self._min_interval

    async def wait_turn(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_start_ts
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_start_ts = time.monotonic()
