import asyncio
import logging
from datetime import datetime
from pathlib import Path

import pytest
import runtime_files.paths as paths_module
from bitrix_gateway.bootstrap import build_runtime
from bitrix_gateway.settings.models import GatewaySettings
from runtime_files import RuntimePaths

from ._support import valid_secrets, valid_settings_data


def test_gateway_run_directory_and_rotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paths_module, "_current_time", lambda: datetime(2026, 9, 28, 20, 10, 11))
    paths = RuntimePaths(tmp_path, tmp_path / "program-data")
    run_dir = paths.create_run_dir("bitrix_gateway")
    data = valid_settings_data()
    data["logging"]["max_bytes"] = 220
    data["logging"]["backup_count"] = 2

    async def scenario() -> None:
        runtime = build_runtime(GatewaySettings.parse_obj(data), valid_secrets(), run_dir)
        try:
            assert runtime.logging_session.log_file == (
                tmp_path
                / "program-data"
                / "bitrix_gateway"
                / "2026-09-28_20-10-11"
                / "bitrix_gateway.log"
            )
            logger = logging.getLogger("bitrix_gateway")
            for index in range(15):
                logger.info("Проверка ротации %s: %s", index, "я" * 80)
            for handler in logger.handlers:
                handler.flush()
            assert {p.name for p in run_dir.iterdir()} == {
                "bitrix_gateway.log",
                "bitrix_gateway.log.1",
                "bitrix_gateway.log.2",
            }
            assert list(run_dir.parent.iterdir()) == [run_dir]
            assert "Проверка ротации 14" in runtime.logging_session.log_file.read_text(
                encoding="utf-8",
            )
        finally:
            await runtime.http_client.aclose()

    asyncio.run(scenario())
