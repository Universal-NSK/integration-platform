import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from platform_logging import log_event

from bitrix_gateway.bootstrap import GatewayRuntime
from bitrix_gateway.http_api.routes import create_router

logger = logging.getLogger(__name__)


def create_app(
    runtime: GatewayRuntime,
) -> FastAPI:
    """Создать FastAPI-приложение поверх готового runtime Gateway."""

    @asynccontextmanager  # type: ignore
    async def lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        """Запустить worker и закрыть ресурсы в принятом простом lifecycle."""

        del app

        log_event(
            logger,
            logging.INFO,
            "gateway_starting",
        )

        worker = asyncio.create_task(
            runtime.dispatcher.run(),
            name="bitrix-gateway-dispatcher",
        )

        log_event(
            logger,
            logging.INFO,
            "gateway_ready",
        )

        try:
            yield
        finally:
            log_event(
                logger,
                logging.INFO,
                "gateway_stopping",
            )

            worker.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await worker

            await runtime.http_client.aclose()

            log_event(
                logger,
                logging.INFO,
                "gateway_stopped",
            )

    app = FastAPI(
        title="Bitrix Gateway",
        lifespan=lifespan,
    )

    app.include_router(create_router(runtime.api))

    return app
