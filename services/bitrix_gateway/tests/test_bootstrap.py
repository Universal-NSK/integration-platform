from bitrix_gateway.bootstrap import build_rate_limiter
from bitrix_gateway.settings.models import GatewaySettings


def test_build_rate_limiter() -> None:
    settings = GatewaySettings.parse_obj(
        {
            "limits": {
                "min_interval": 0.5,
            }
        }
    )
    rate_limiter = build_rate_limiter(settings)

    assert rate_limiter.get_min_interval == 0.5
