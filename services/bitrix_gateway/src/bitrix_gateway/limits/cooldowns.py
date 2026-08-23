import asyncio
import time
from typing import Dict


class MethodCooldownRegistry:
    def __init__(self) -> None:
        self._blocked_until: Dict[str, float] = {}

    async def wait_turn(self, method: str) -> None:
        while True:
            blocked_until = self._blocked_until.get(method)

            if blocked_until is None:
                return

            delay = blocked_until - time.monotonic()

            if delay <= 0:
                self._blocked_until.pop(method, None)
                return

            await asyncio.sleep(delay)

    def set_cooldown(self, method: str, duration: float) -> None:
        if duration < 0:
            raise ValueError("Cooldown duration cannot be negative")

        if duration == 0:
            return

        blocked_until = time.monotonic() + duration
        current = self._blocked_until.get(method)

        if current is None or blocked_until > current:
            self._blocked_until[method] = blocked_until