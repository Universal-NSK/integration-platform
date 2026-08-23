from bitrix_gateway.limits.cooldowns import MethodCooldownRegistry
from bitrix_gateway.limits.rate_limiter import RateLimiter


class BitrixApiLimitController:
    def __init__(
        self,
        rate_limiter: RateLimiter,
        cooldowns: MethodCooldownRegistry,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._cooldowns = cooldowns

    async def wait_turn(self, method: str) -> None:
        await self._cooldowns.wait_turn(method)
        await self._rate_limiter.wait_turn()

    def set_cooldown(self, method: str, duration: float) -> None:
        self._cooldowns.set_cooldown(method, duration)