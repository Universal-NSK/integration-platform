from bitrix_gateway.limits.rate_limiter import RateLimiter
from bitrix_gateway.settings.models import GatewaySettings


def build_rate_limiter(settings: GatewaySettings) -> RateLimiter:
    return RateLimiter(
        min_interval=settings.limits.min_interval,
    )