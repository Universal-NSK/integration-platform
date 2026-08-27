import asyncio
import logging
import time
from typing import Dict, Optional

from platform_logging import log_event, with_context

from bitrix_gateway.contracts.models import (
    ExecutionStatus,
    GatewayRequest,
    GatewayResult,
    RetryPolicy,
    TransportResult,
)
from bitrix_gateway.execution.transport import (
    BitrixTransport,
    TransportError,
)
from bitrix_gateway.limits.controller import (
    BitrixApiLimitController,
)

logger = logging.getLogger(__name__)


class RequestExecutor:
    """Выполняет запрос с учётом лимитов, retry и семантики UNKNOWN."""

    _QUERY_LIMIT_ERROR = "QUERY_LIMIT_EXCEEDED"
    _OPERATION_LIMIT_ERROR = "OPERATION_TIME_LIMIT"

    def __init__(
        self,
        transport: BitrixTransport,
        limits: BitrixApiLimitController,
        max_attempts: int,
        retry_delay: float,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts должен быть не меньше 1")

        if retry_delay < 0:
            raise ValueError("retry_delay не может быть отрицательным")

        self._transport = transport
        self._limits = limits
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay

        self._operating_reset_at: Dict[str, float] = {}

    async def execute(
        self,
        request: GatewayRequest,
    ) -> GatewayResult:
        """Выполнить запрос, безопасно повторяя только политику SAFE."""

        log_event(
            logger,
            logging.DEBUG,
            "execution_started",
            method=request.method,
            retry_policy=request.retry_policy.value,
            max_attempts=self._max_attempts,
        )

        for attempt in range(1, self._max_attempts + 1):
            log_event(
                logger,
                logging.DEBUG,
                "execution_attempt_started",
                method=request.method,
                attempt=attempt,
            )
            await self._limits.wait_turn(request.method)

            try:
                result = await self._transport.call(
                    request.method,
                    request.payload,
                )
            except TransportError as exc:
                transport_result = await self._handle_transport_error(
                    request=request,
                    error=exc,
                    attempt=attempt,
                )

                if transport_result is not None:
                    return self._complete(
                        request=request,
                        result=transport_result,
                    )

                continue

            self._remember_operating_reset(
                request.method,
                result,
            )

            if self._is_success(result):
                log_event(
                    logger,
                    logging.DEBUG,
                    "execution_attempt_succeeded",
                    method=request.method,
                    attempt=attempt,
                    http_status=result.http_status,
                )
                return self._complete(
                    request=request,
                    result=self._success_result(
                        result=result,
                        attempt=attempt,
                    ),
                )

            log_event(
                logger,
                logging.DEBUG,
                "execution_attempt_failed",
                method=request.method,
                attempt=attempt,
                http_status=result.http_status,
                error_code=result.error_code,
            )

            if result.error_code == self._OPERATION_LIMIT_ERROR:
                self._apply_method_cooldown(request.method)

                return self._complete(
                    request=request,
                    result=self._failed_result(
                        result=result,
                        attempt=attempt,
                    ),
                )

            if self._should_retry_response(
                request=request,
                result=result,
                attempt=attempt,
            ):
                await self._wait_before_retry(
                    request=request,
                    attempt=attempt,
                    reason="bitrix_response",
                    error_code=result.error_code,
                )
                continue

            if self._is_uncertain_response(
                request=request,
                result=result,
            ):
                return self._complete(
                    request=request,
                    result=self._unknown_result(
                        result=result,
                        attempt=attempt,
                    ),
                )

            return self._complete(
                request=request,
                result=self._failed_result(
                    result=result,
                    attempt=attempt,
                ),
            )

        raise RuntimeError("RequestExecutor достиг недостижимого состояния")

    async def _handle_transport_error(
        self,
        request: GatewayRequest,
        error: TransportError,
        attempt: int,
    ) -> Optional[GatewayResult]:
        """Применить retry или определить FAILED/UNKNOWN по факту отправки."""

        if request.retry_policy is RetryPolicy.SAFE and attempt < self._max_attempts:
            log_event(
                logger,
                logging.DEBUG,
                "execution_attempt_failed",
                method=request.method,
                attempt=attempt,
                error_code="TRANSPORT_ERROR",
                outcome_uncertain=error.outcome_uncertain,
            )
            await self._wait_before_retry(
                request=request,
                attempt=attempt,
                reason="transport_error",
                error_code="TRANSPORT_ERROR",
            )
            return None

        status = ExecutionStatus.FAILED

        if request.retry_policy is RetryPolicy.NEVER and error.outcome_uncertain:
            status = ExecutionStatus.UNKNOWN

        cause = error.__cause__
        exception_type = type(cause).__name__ if cause is not None else type(error).__name__
        safe_error = TransportError(
            str(error),
            outcome_uncertain=error.outcome_uncertain,
        )
        safe_logger = with_context(
            logger,
            method=request.method,
            attempt=attempt,
            exception_type=exception_type,
            error_message=str(error),
            outcome_uncertain=error.outcome_uncertain,
        )
        safe_logger.error(
            "execution_transport_failed",
            exc_info=(TransportError, safe_error, error.__traceback__),
        )

        return GatewayResult(
            status=status,
            data=None,
            http_status=None,
            error_code="TRANSPORT_ERROR",
            error_message=str(error),
            attempt_count=attempt,
        )

    async def _wait_before_retry(
        self,
        *,
        request: GatewayRequest,
        attempt: int,
        reason: str,
        error_code: Optional[str],
    ) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "execution_retry_scheduled",
            method=request.method,
            attempt=attempt,
            next_attempt=attempt + 1,
            retry_delay=self._retry_delay,
            reason=reason,
            error_code=error_code,
        )
        if self._retry_delay > 0:
            log_event(
                logger,
                logging.DEBUG,
                "execution_retry_wait",
                method=request.method,
                attempt=attempt,
                wait_seconds=self._retry_delay,
            )
        await asyncio.sleep(self._retry_delay)

    @staticmethod
    def _complete(
        *,
        request: GatewayRequest,
        result: GatewayResult,
    ) -> GatewayResult:
        log_event(
            logger,
            logging.DEBUG,
            "execution_completed",
            method=request.method,
            status=result.status.value,
            attempt_count=result.attempt_count,
        )
        return result

    def _remember_operating_reset(
        self,
        method: str,
        result: TransportResult,
    ) -> None:
        if result.operating_reset_at is None:
            return

        self._operating_reset_at[method] = result.operating_reset_at

    def _apply_method_cooldown(
        self,
        method: str,
    ) -> None:
        """Вычислить cooldown по последнему reset_at конкретного метода."""

        reset_at = self._operating_reset_at.get(method)

        if reset_at is None:
            return

        duration = reset_at - time.time()

        if duration <= 0:
            return

        self._limits.set_cooldown(
            method,
            duration,
        )

    def _should_retry_response(
        self,
        request: GatewayRequest,
        result: TransportResult,
        attempt: int,
    ) -> bool:
        if request.retry_policy is not RetryPolicy.SAFE:
            return False

        if attempt >= self._max_attempts:
            return False

        if result.error_code == self._QUERY_LIMIT_ERROR:
            return True

        return result.http_status >= 500

    @staticmethod
    def _is_success(
        result: TransportResult,
    ) -> bool:
        return 200 <= result.http_status < 300 and result.error_code is None

    @classmethod
    def _is_uncertain_response(
        cls,
        request: GatewayRequest,
        result: TransportResult,
    ) -> bool:
        """Определить ответ, после которого результат NEVER нельзя доказать."""

        if request.retry_policy is not RetryPolicy.NEVER:
            return False

        if result.http_status < 500:
            return False

        if result.error_code in {
            cls._QUERY_LIMIT_ERROR,
            cls._OPERATION_LIMIT_ERROR,
        }:
            return False

        return True

    @staticmethod
    def _success_result(
        result: TransportResult,
        attempt: int,
    ) -> GatewayResult:
        return GatewayResult(
            status=ExecutionStatus.SUCCESS,
            data=result.data,
            http_status=result.http_status,
            error_code=None,
            error_message=None,
            attempt_count=attempt,
        )

    @staticmethod
    def _failed_result(
        result: TransportResult,
        attempt: int,
    ) -> GatewayResult:
        return GatewayResult(
            status=ExecutionStatus.FAILED,
            data=None,
            http_status=result.http_status,
            error_code=result.error_code,
            error_message=result.error_message,
            attempt_count=attempt,
        )

    @staticmethod
    def _unknown_result(
        result: TransportResult,
        attempt: int,
    ) -> GatewayResult:
        return GatewayResult(
            status=ExecutionStatus.UNKNOWN,
            data=None,
            http_status=result.http_status,
            error_code=result.error_code,
            error_message=result.error_message,
            attempt_count=attempt,
        )
