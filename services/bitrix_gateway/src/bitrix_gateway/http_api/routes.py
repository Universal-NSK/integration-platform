from fastapi import APIRouter

from bitrix_gateway.http_api.api import GatewayHttpApi
from bitrix_gateway.http_api.models import (
    CallRequest,
    CallResponse,
    HealthResponse,
)


def create_router(
    api: GatewayHttpApi,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/call",
        response_model=CallResponse,
    )
    async def call(
        request: CallRequest,
    ) -> CallResponse:
        return await api.call(request)

    @router.get(
        "/health",
        response_model=HealthResponse,
    )
    async def health() -> HealthResponse:
        return await api.health()

    _ = call, health
    return router
