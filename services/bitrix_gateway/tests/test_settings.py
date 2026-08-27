from pathlib import Path

from bitrix_gateway.settings.loader import load_settings


def test_load_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "gateway.toml"

    config_path.write_text(
        """
        [bitrix]
        request_timeout = 5.0

        [limits]
        min_interval = 0.5

        [execution]
        max_attempts = 2
        retry_delay = 0.0

        [queue]
        max_size = 10

        [http]
        request_timeout = 10.0

        [server]
        host = "127.0.0.1"
        port = 8765

        [logging]
        level = "INFO"
        console = false
        log_payloads = false
        max_bytes = 10000
        backup_count = 1
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.limits.min_interval == 0.5
