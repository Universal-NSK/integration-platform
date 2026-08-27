import asyncio
import logging

from fastapi import HTTPException
from platform_logging import log_event, log_payload

from bitrix_gateway.contracts.models import GatewayRequest
from bitrix_gateway.dispatch.dispatcher import RequestDispatcher
from bitrix_gateway.dispatch.queue import QueueFullError
from bitrix_gateway.http_api.models import (
    CallRequest,
    CallResponse,
    HealthResponse,
)

logger = logging.getLogger(__name__)


class GatewayHttpApi:
    """Преобразует HTTP-модели в контракт Dispatcher и обратно."""

    def __init__(
        self,
        dispatcher: RequestDispatcher,
        request_timeout: float,
        log_payloads: bool = False,
    ) -> None:
        if request_timeout <= 0:
            raise ValueError("request_timeout должен быть больше нуля")

        self._dispatcher = dispatcher
        self._request_timeout = request_timeout
        self._log_payloads = log_payloads

    async def call(
        self,
        request: CallRequest,
    ) -> CallResponse:
        """Выполнить вызов в пределах общего тайм-аута HTTP API."""

        log_event(
            logger,
            logging.INFO,
            "gateway_call_request",
            method=request.method,
            retry_policy=request.retry_policy.value,
        )
        log_payload(
            logger,
            logging.INFO,
            "gateway_call_request_payload",
            request.payload,
            enabled=self._log_payloads,
            method=request.method,
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
            log_event(
                logger,
                logging.WARNING,
                "gateway_call_rejected",
                method=request.method,
                http_status=503,
                error_code="QUEUE_FULL",
            )
            raise HTTPException(
                status_code=503,
                detail="Очередь заданий Gateway переполнена",
            ) from exc
        except asyncio.TimeoutError as exc:
            log_event(
                logger,
                logging.WARNING,
                "gateway_call_timed_out",
                method=request.method,
                http_status=504,
            )
            raise HTTPException(
                status_code=504,
                detail="Истекло время ожидания ответа Gateway",
            ) from exc
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "gateway_call_failed",
                method=request.method,
                exception_type=type(exc).__name__,
            )
            raise

        response = CallResponse(
            status=result.status,
            data=result.data,
            http_status=result.http_status,
            error_code=result.error_code,
            error_message=result.error_message,
            attempt_count=result.attempt_count,
        )

        log_event(
            logger,
            logging.INFO,
            "gateway_call_response",
            method=request.method,
            status=result.status.value,
            http_status=result.http_status,
            error_code=result.error_code,
            attempt_count=result.attempt_count,
        )
        log_payload(
            logger,
            logging.INFO,
            "gateway_call_response_payload",
            result.data,
            enabled=self._log_payloads,
            field_name="response",
            method=request.method,
        )

        return response

    async def health(self) -> HealthResponse:
        """Вернуть состояние процесса без обращения к Bitrix24."""

        return HealthResponse(
            status="ok",
            queue_size=self._dispatcher.queue_size(),
        )
