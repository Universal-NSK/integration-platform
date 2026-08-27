from bitrix_gateway.limits.cooldowns import MethodCooldownRegistry
from bitrix_gateway.limits.rate_limiter import RateLimiter


class BitrixApiLimitController:
    """Последовательно применяет cooldown метода и общий rate limit."""

    def __init__(
        self,
        rate_limiter: RateLimiter,
        cooldowns: MethodCooldownRegistry,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._cooldowns = cooldowns

    async def wait_turn(self, method: str) -> None:
        """Дождаться допуска запроса по обоим видам ограничений."""

        await self._cooldowns.wait_turn(method)
        await self._rate_limiter.wait_turn()

    def set_cooldown(self, method: str, duration: float) -> None:
        """Передать блокировку метода в реестр cooldown."""

        self._cooldowns.set_cooldown(method, duration)
