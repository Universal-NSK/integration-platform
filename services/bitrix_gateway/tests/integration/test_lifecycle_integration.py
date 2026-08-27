from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, cast

import httpx
import pytest
import uvicorn
from bitrix_gateway.app import create_app
from bitrix_gateway.bootstrap import GatewayRuntime, build_runtime
from bitrix_gateway.main import _run  # pyright: ignore[reportPrivateUsage]
from bitrix_gateway.settings.models import GatewaySecrets, GatewaySettings
from fastapi import FastAPI
from runtime_files import RuntimePaths

from ._support import read_log, valid_secrets, valid_settings

CONFIG_TOML = """
[bitrix]
request_timeout = 5.0

[limits]
min_interval = 0.001

[execution]
max_attempts = 2
retry_delay = 0.0

[queue]
max_size = 10

[http]
request_timeout = 2.0

[server]
host = "127.0.0.1"
port = 8765

[logging]
level = "INFO"
console = false
log_payloads = false
max_bytes = 100000
backup_count = 1
""".strip()

SECRETS_TOML = """
[bitrix]
webhook_url = "https://example.invalid/rest/test/fake-secret"
""".strip()


def test_empty_queue_worker_starts_once_and_shutdown_closes_same_loop_resources(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(
        repo_root=tmp_path.resolve(),
        program_data_root=(tmp_path / "program-data").resolve(),
    )

    async def scenario() -> GatewayRuntime:
        runtime = build_runtime(
            settings=valid_settings(),
            secrets=valid_secrets(),
            paths=paths,
        )
        app = create_app(runtime)
        transport = httpx.ASGITransport(app=app)

        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)
            workers = [
                task
                for task in asyncio.all_tasks()
                if task.get_name() == "bitrix-gateway-dispatcher"
            ]
            assert len(workers) == 1
            assert workers[0].done() is False
            assert runtime.dispatcher.queue_size() == 0

            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                response = await client.get("/health")

            assert response.status_code == 200
            assert response.json() == {"status": "ok", "queue_size": 0}
            assert runtime.http_client.is_closed is False

        assert runtime.http_client.is_closed is True
        return runtime

    runtime = asyncio.run(scenario())
    log_text = read_log(runtime)
    assert "gateway_starting" in log_text
    assert "gateway_ready" in log_text
    assert "gateway_stopping" in log_text
    assert "gateway_stopped" in log_text


@dataclass
class MainRunState:
    build_loop: Optional[asyncio.AbstractEventLoop] = None
    serve_loop: Optional[asyncio.AbstractEventLoop] = None
    runtime: Optional[GatewayRuntime] = None
    served: bool = False


def test_run_builds_runtime_and_awaits_uvicorn_server_inside_running_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = (tmp_path / "repo").resolve()
    program_data_root = (tmp_path / "program-data").resolve()
    (repo_root / "config").mkdir(parents=True)
    program_data_root.mkdir(parents=True)
    (repo_root / "config" / "gateway.toml").write_text(
        CONFIG_TOML,
        encoding="utf-8",
    )
    (program_data_root / "bitrix.secrets.toml").write_text(
        SECRETS_TOML,
        encoding="utf-8",
    )
    paths = RuntimePaths(
        repo_root=repo_root,
        program_data_root=program_data_root,
    )
    state = MainRunState()

    class TestRuntimePaths:
        @classmethod
        def from_project(cls, start: Path) -> RuntimePaths:
            del cls, start
            return paths

    def build_runtime_in_loop(
        settings: GatewaySettings,
        secrets: GatewaySecrets,
        paths: RuntimePaths,
    ) -> GatewayRuntime:
        state.build_loop = asyncio.get_running_loop()
        state.runtime = build_runtime(
            settings=settings,
            secrets=secrets,
            paths=paths,
        )
        return state.runtime

    class TestServer:
        def __init__(self, config: uvicorn.Config) -> None:
            self.config = config

        async def serve(self) -> None:
            state.serve_loop = asyncio.get_running_loop()
            app = cast(FastAPI, self.config.app)
            async with app.router.lifespan_context(app):
                await asyncio.sleep(0)
            state.served = True

    main_module = importlib.import_module("bitrix_gateway.main")
    monkeypatch.setattr(main_module, "RuntimePaths", TestRuntimePaths)
    monkeypatch.setattr(main_module, "build_runtime", build_runtime_in_loop)
    monkeypatch.setattr(uvicorn, "Server", TestServer)

    asyncio.run(_run())

    assert state.served is True
    assert state.build_loop is state.serve_loop
    assert state.runtime is not None
    assert state.runtime.http_client.is_closed is True
