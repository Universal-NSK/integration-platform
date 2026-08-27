import asyncio
import logging
import time
from typing import Dict

from platform_logging import log_event

logger = logging.getLogger(__name__)


class MethodCooldownRegistry:
    """Хранит независимые периоды блокировки для методов Bitrix24."""

    def __init__(self) -> None:
        self._blocked_until: Dict[str, float] = {}

    async def wait_turn(self, method: str) -> None:
        """Дождаться окончания действующей блокировки указанного метода."""

        while True:
            blocked_until = self._blocked_until.get(method)

            if blocked_until is None:
                return

            delay = blocked_until - time.monotonic()

            if delay <= 0:
                self._blocked_until.pop(method, None)
                return

            log_event(
                logger,
                logging.DEBUG,
                "method_cooldown_wait",
                method=method,
                wait_seconds=delay,
            )
            await asyncio.sleep(delay)

    def set_cooldown(self, method: str, duration: float) -> None:
        """Установить или продлить блокировку метода, не сокращая текущую."""

        if duration < 0:
            raise ValueError("duration периода блокировки не может быть отрицательным")

        if duration == 0:
            return

        blocked_until = time.monotonic() + duration
        current = self._blocked_until.get(method)

        if current is None or blocked_until > current:
            self._blocked_until[method] = blocked_until
            log_event(
                logger,
                logging.DEBUG,
                "method_cooldown_set",
                method=method,
                duration=duration,
                reset_at=blocked_until,
            )
