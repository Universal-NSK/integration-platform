import asyncio
import time
from typing import Dict, Optional

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


class RequestExecutor:
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
            raise ValueError("max_attempts must be at least 1")

        if retry_delay < 0:
            raise ValueError("retry_delay cannot be negative")

        self._transport = transport
        self._limits = limits
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay

        self._operating_reset_at: Dict[str, float] = {}

    async def execute(
        self,
        request: GatewayRequest,
    ) -> GatewayResult:
        for attempt in range(1, self._max_attempts + 1):
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

                if transport_result is not None:  # type: ignore
                    return transport_result

                continue

            self._remember_operating_reset(
                request.method,
                result,
            )

            if self._is_success(result):
                return self._success_result(
                    result=result,
                    attempt=attempt,
                )

            if result.error_code == self._OPERATION_LIMIT_ERROR:
                self._apply_method_cooldown(request.method)

                return self._failed_result(
                    result=result,
                    attempt=attempt,
                )

            if self._should_retry_response(
                request=request,
                result=result,
                attempt=attempt,
            ):
                await asyncio.sleep(self._retry_delay)
                continue

            if self._is_uncertain_response(
                request=request,
                result=result,
            ):
                return self._unknown_result(
                    result=result,
                    attempt=attempt,
                )

            return self._failed_result(
                result=result,
                attempt=attempt,
            )

        raise RuntimeError("RequestExecutor reached unreachable state")

    async def _handle_transport_error(
        self,
        request: GatewayRequest,
        error: TransportError,
        attempt: int,
    ) -> Optional[GatewayResult]:
        if request.retry_policy is RetryPolicy.SAFE and attempt < self._max_attempts:
            await asyncio.sleep(self._retry_delay)
            return None

        status = ExecutionStatus.FAILED

        if request.retry_policy is RetryPolicy.NEVER and error.outcome_uncertain:
            status = ExecutionStatus.UNKNOWN

        return GatewayResult(
            status=status,
            data=None,
            http_status=None,
            error_code="TRANSPORT_ERROR",
            error_message=str(error),
            attempt_count=attempt,
        )

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
