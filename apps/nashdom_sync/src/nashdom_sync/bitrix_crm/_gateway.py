from typing import Any, Dict, Optional, cast

import httpx

from ._contracts import GatewayCallResult, GatewayExecutionStatus, RetryPolicy
from .exceptions import BitrixGatewayError


class GatewayHttpClient:
    """Владеет синхронным HTTP-клиентом для внутреннего обращения к Gateway"""

    def __init__(self, base_url: str, timeout: float) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout, trust_env=False)

    def close(self) -> None:
        """Освободить соединения; повторное закрытие допустимо"""

        self._client.close()

    def call(
        self, method: str, payload: Dict[str, Any], retry_policy: RetryPolicy
    ) -> GatewayCallResult:
        """Выполнить один HTTP-запрос без локальных повторов и утечки URL"""

        try:
            response = self._client.post(
                "call",
                json={"method": method, "payload": payload, "retry_policy": retry_policy.value},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BitrixGatewayError(
                "Gateway вернул HTTP {}".format(exc.response.status_code)
            ) from None
        except (httpx.RequestError, httpx.InvalidURL, RuntimeError):
            raise BitrixGatewayError("Не удалось выполнить HTTP-запрос к Gateway") from None

        try:
            body: Any = response.json()
        except (ValueError, UnicodeError):
            raise BitrixGatewayError("Gateway вернул некорректный JSON") from None
        return self._parse_result(body)

    @staticmethod
    def _parse_result(body: Any) -> GatewayCallResult:
        """Проверить типы wire DTO без приведения строк, bool или чисел"""

        invalid = "Gateway вернул некорректный контракт ответа"
        if not isinstance(body, dict):
            raise BitrixGatewayError(invalid)
        value = cast(Dict[str, Any], body)
        if set(value) != {
            "status",
            "data",
            "http_status",
            "error_code",
            "error_message",
            "attempt_count",
        }:
            raise BitrixGatewayError(invalid)
        try:
            status = GatewayExecutionStatus(value["status"])
        except (ValueError, TypeError):
            raise BitrixGatewayError(invalid) from None
        data: Any = value["data"]
        http_status: Any = value["http_status"]
        attempt_count: Any = value["attempt_count"]
        if data is not None and not isinstance(data, dict):
            raise BitrixGatewayError(invalid)
        if status is GatewayExecutionStatus.SUCCESS and data is None:
            raise BitrixGatewayError(invalid)
        if http_status is not None and (
            type(http_status) is not int or not 100 <= http_status <= 599
        ):
            raise BitrixGatewayError(invalid)
        if type(attempt_count) is not int or attempt_count < 1:
            raise BitrixGatewayError(invalid)
        for key in ("error_code", "error_message"):
            if value[key] is not None and not isinstance(value[key], str):
                raise BitrixGatewayError(invalid)
        return GatewayCallResult(
            status=status,
            data=cast(Optional[Dict[str, Any]], data),
            http_status=http_status,
            error_code=value["error_code"],
            error_message=value["error_message"],
            attempt_count=attempt_count,
        )
