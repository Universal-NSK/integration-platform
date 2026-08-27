import asyncio
import logging

from fastapi import HTTPException
from platform_logging import log_payload

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
        log_payloads: bool = False,
    ) -> None:
        if request_timeout <= 0:
            raise ValueError("request_timeout must be greater than zero")

        self._dispatcher = dispatcher
        self._request_timeout = request_timeout
        self._log_payloads = log_payloads
        self._logger = logging.getLogger("bitrix_gateway")

    async def call(
        self,
        request: CallRequest,
    ) -> CallResponse:
        log_payload(
            self._logger,
            logging.INFO,
            "gateway_call_request",
            request.payload,
            enabled=self._log_payloads,
            method=request.method,
            retry_policy=request.retry_policy.value,
        )

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

        response = CallResponse(
            status=result.status,
            data=result.data,
            http_status=result.http_status,
            error_code=result.error_code,
            error_message=result.error_message,
            attempt_count=result.attempt_count,
        )

        log_payload(
            self._logger,
            logging.INFO,
            "gateway_call_response",
            result.data,
            enabled=self._log_payloads,
            field_name="response",
            method=request.method,
            status=result.status.value,
            http_status=result.http_status,
            error_code=result.error_code,
            attempt_count=result.attempt_count,
        )

        return response

    async def health(self) -> HealthResponse:
        return HealthResponse(
            status="ok",
            queue_size=self._dispatcher.queue_size(),
        )
