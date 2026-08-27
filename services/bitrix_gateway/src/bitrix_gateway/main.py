import asyncio
import logging
from pathlib import Path

import uvicorn
from platform_logging import log_event
from runtime_files import RuntimePaths

from bitrix_gateway.app import create_app
from bitrix_gateway.bootstrap import build_runtime
from bitrix_gateway.settings.loader import (
    load_secrets,
    load_settings,
)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


async def _run() -> None:
    paths = RuntimePaths.from_project(
        start=Path(__file__),
    )

    settings = load_settings(
        paths.config_file("gateway.toml"),
    )

    secrets = load_secrets(
        paths.program_data_file(
            "bitrix.secrets.toml",
        ),
    )

    # ВАЖНО:
    # runtime создаётся уже внутри активного event loop.
    runtime = build_runtime(
        settings=settings,
        secrets=secrets,
        paths=paths,
    )

    app = create_app(runtime)

    logger = logging.getLogger(
        "bitrix_gateway",
    )

    log_event(
        logger,
        logging.INFO,
        "server_starting",
        host=settings.server.host,
        port=settings.server.port,
    )

    config = uvicorn.Config(
        app=app,
        host=settings.server.host,
        port=settings.server.port,
        workers=1,
    )

    server = uvicorn.Server(config)

    await server.serve()
