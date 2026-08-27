import asyncio
import logging
import time

from platform_logging import log_event

logger = logging.getLogger(__name__)


class RateLimiter:
    """Выдерживает минимальный интервал между началами запросов."""

    def __init__(self, min_interval: float) -> None:
        if min_interval <= 0:
            raise ValueError("min_interval должен быть больше нуля")

        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_start_ts = 0.0

    @property
    def get_min_interval(self) -> float:
        """Вернуть настроенный минимальный интервал в секундах."""

        return self._min_interval

    async def wait_turn(self) -> None:
        """Дождаться разрешённого момента и зафиксировать старт запроса."""

        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_start_ts
            if elapsed < self._min_interval:
                wait_seconds = self._min_interval - elapsed
                log_event(
                    logger,
                    logging.DEBUG,
                    "rate_limit_wait",
                    wait_seconds=wait_seconds,
                )
                await asyncio.sleep(wait_seconds)
            self._last_start_ts = time.monotonic()
