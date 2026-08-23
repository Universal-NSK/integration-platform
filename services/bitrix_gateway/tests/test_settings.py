from pathlib import Path

from bitrix_gateway.settings.loader import load_settings


def test_load_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "gateway.json"

    config_path.write_text(
        """
        {
          "limits": {
            "min_interval": 0.5
          }
        }
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.limits.min_interval == 0.5
