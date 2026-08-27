import asyncio

from fastapi import HTTPException

from bitrix_gateway.contracts.models import GatewayRequest
from bitrix_gateway.dispatch.dispatcher import RequestDispatcher
from bitrix_gateway.dispatch.queue import QueueFullError
from bitrix_gateway.http_api.models import (
    CallRequest,
    CallResponse,
    HealthResponse,
)


class GatewayHttpApi:
    def __init__(
        self,
        dispatcher: RequestDispatcher,
        request_timeout: float,
    ) -> None:
        if request_timeout <= 0:
            raise ValueError("request_timeout must be greater than zero")

        self._dispatcher = dispatcher
        self._request_timeout = request_timeout

    async def call(
        self,
        request: CallRequest,
    ) -> CallResponse:
        gateway_request = GatewayRequest(
            method=request.method,
            payload=request.payload,
            retry_policy=request.retry_policy,
        )

        try:
            result = await asyncio.wait_for(
                self._dispatcher.submit(gateway_request),
                timeout=self._request_timeout,
            )
        except QueueFullError as exc:
            raise HTTPException(
                status_code=503,
                detail="Gateway queue is full",
            ) from exc
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail="Gateway request timed out",
            ) from exc

        return CallResponse(
            status=result.status,
            data=result.data,
            http_status=result.http_status,
            error_code=result.error_code,
            error_message=result.error_message,
            attempt_count=result.attempt_count,
        )

    async def health(self) -> HealthResponse:
        return HealthResponse(
            status="ok",
            queue_size=self._dispatcher.queue_size(),
        )
