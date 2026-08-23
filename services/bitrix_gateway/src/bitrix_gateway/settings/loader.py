import json
from pathlib import Path
from typing import Any

from bitrix_gateway.settings.models import GatewaySettings


def load_settings(path: Path) -> GatewaySettings:
    with path.open("r", encoding="utf-8") as file:
        raw_config: Any = json.load(file)

    return GatewaySettings.parse_obj(raw_config)
