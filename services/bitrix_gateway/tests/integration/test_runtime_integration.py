import asyncio
from pathlib import Path

import httpx
from bitrix_gateway.bootstrap import build_runtime
from bitrix_gateway.dispatch.dispatcher import RequestDispatcher
from bitrix_gateway.http_api.api import GatewayHttpApi
from runtime_files import RuntimePaths

from ._support import valid_secrets, valid_settings


def test_build_runtime_composes_real_gateway_and_creates_log_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        program_data_root = (tmp_path / "program-data").resolve()
        paths = RuntimePaths(
            repo_root=tmp_path.resolve(),
            program_data_root=program_data_root,
        )

        runtime = build_runtime(
            settings=valid_settings(),
            secrets=valid_secrets(),
            paths=paths,
        )

        try:
            assert isinstance(runtime.http_client, httpx.AsyncClient)
            assert runtime.http_client.is_closed is False
            assert isinstance(runtime.dispatcher, RequestDispatcher)
            assert isinstance(runtime.api, GatewayHttpApi)
            assert runtime.logging_session.log_file.is_file()
            assert runtime.logging_session.log_file.parent == (
                program_data_root / "logs" / "bitrix_gateway"
            )
        finally:
            await runtime.http_client.aclose()

        assert runtime.http_client.is_closed is True

    asyncio.run(scenario())
