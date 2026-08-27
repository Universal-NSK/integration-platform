from pathlib import Path
from typing import Any, Dict

import tomli
from runtime_files import read_text

from bitrix_gateway.settings.models import (
    GatewaySecrets,
    GatewaySettings,
)


def _load_toml(path: Path) -> Dict[str, Any]:
    content = read_text(path)
    raw = tomli.loads(content)

    return raw


def load_settings(path: Path) -> GatewaySettings:
    return GatewaySettings.parse_obj(_load_toml(path))


def load_secrets(path: Path) -> GatewaySecrets:
    return GatewaySecrets.parse_obj(_load_toml(path))
