import logging
import re
from typing import Any, Dict, NoReturn, Optional, Tuple, cast
from urllib.parse import urlsplit

import httpx
from platform_logging import log_event, with_context

from bitrix_gateway.contracts.models import TransportResult
from bitrix_gateway.execution.transport import TransportError

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)


class HttpBitrixTransport:
    """Выполняет HTTP-вызовы Bitrix24 без повторов и ограничения частоты."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._secret_fragments = self._collect_secret_fragments(self._base_url)

    async def call(
        self,
        method: str,
        payload: Dict[str, Any],
    ) -> TransportResult:
        """Выполнить запрос и нормализовать HTTP-ответ или транспортный сбой."""

        url = f"{self._base_url}/{method}"

        log_event(
            logger,
            logging.DEBUG,
            "transport_request_started",
            method=method,
        )

        try:
            response = await self._client.post(
                url,
                json=payload,
            )
        except httpx.RequestError as exc:
            outcome_uncertain = not isinstance(
                exc,
                (
                    httpx.ConnectError,
                    httpx.ConnectTimeout,
                    httpx.PoolTimeout,
                ),
            )
            self._raise_transport_error(
                method=method,
                error=exc,
                outcome_uncertain=outcome_uncertain,
            )

        log_event(
            logger,
            logging.DEBUG,
            "transport_response_received",
            method=method,
            http_status=response.status_code,
        )

        try:
            raw_body = response.json()
        except ValueError as exc:
            message = f"Bitrix24 вернул некорректный JSON, HTTP статус {response.status_code}"
            log_event(
                logger,
                logging.WARNING,
                "transport_response_invalid_json",
                method=method,
                http_status=response.status_code,
                exception_type=type(exc).__name__,
            )
            raise TransportError(
                message,
                outcome_uncertain=True,
            ) from exc

        if not isinstance(raw_body, dict):
            log_event(
                logger,
                logging.WARNING,
                "transport_response_unexpected_root",
                method=method,
                http_status=response.status_code,
                root_type=type(raw_body).__name__,
            )
            raise TransportError(
                "Bitrix24 вернул JSON с неожиданным типом корневого объекта",
                outcome_uncertain=True,
            )

        body = cast(Dict[str, Any], raw_body)

        error_code = self._read_string(body, "error")
        error_message = self._read_string(
            body,
            "error_description",
        )

        operating_reset_at = self._read_operating_reset_at(body)

        log_event(
            logger,
            logging.DEBUG,
            "transport_response_parsed",
            method=method,
            http_status=response.status_code,
            bitrix_error_code=error_code,
        )

        if error_code is not None:
            return TransportResult(
                data=None,
                http_status=response.status_code,
                error_code=error_code,
                error_message=error_message,
                operating_reset_at=operating_reset_at,
            )

        return TransportResult(
            data=body,
            http_status=response.status_code,
            error_code=None,
            error_message=None,
            operating_reset_at=operating_reset_at,
        )

    @staticmethod
    def _collect_secret_fragments(base_url: str) -> Tuple[str, ...]:
        """Выделить части webhook, по которым можно обнаружить утечку в сообщении."""

        parsed = urlsplit(base_url)
        path_parts = [part for part in parsed.path.split("/") if part]
        candidates = [base_url]
        if path_parts:
            candidates.append(path_parts[-1])
        if parsed.query:
            candidates.append(parsed.query)
        return tuple(value for value in candidates if len(value) >= 4)

    def _safe_exception_message(self, error: httpx.RequestError) -> str:
        """Сформировать русское сообщение без URL и частей webhook-токена."""

        exception_type = type(error).__name__
        detail = " ".join(str(error).split())
        contains_secret = any(fragment in detail for fragment in self._secret_fragments)

        if not detail or contains_secret or _URL_PATTERN.search(detail):
            return f"Ошибка транспорта Bitrix24: {exception_type}"

        return f"Ошибка транспорта Bitrix24: {exception_type} — {detail}"

    def _raise_transport_error(
        self,
        *,
        method: str,
        error: httpx.RequestError,
        outcome_uncertain: bool,
    ) -> NoReturn:
        """Записать очищенный traceback и поднять нормализованную ошибку транспорта."""

        message = self._safe_exception_message(error)
        transport_error = TransportError(
            message,
            outcome_uncertain=outcome_uncertain,
        )
        safe_logger = with_context(
            logger,
            method=method,
            exception_type=type(error).__name__,
            exception_message=message,
            outcome_uncertain=outcome_uncertain,
        )
        safe_logger.debug(
            "transport_request_failed",
            exc_info=(TransportError, transport_error, error.__traceback__),
        )
        raise transport_error from error

    @staticmethod
    def _read_string(
        body: Dict[str, Any],
        key: str,
    ) -> Optional[str]:
        value = body.get(key)

        if value is None:
            return None

        return str(value)

    @staticmethod
    def _read_operating_reset_at(
        body: Dict[str, Any],
    ) -> Optional[float]:
        time_data = body.get("time")

        if not isinstance(time_data, dict):
            return None

        reset_at = time_data.get("operating_reset_at")  # type: ignore

        if isinstance(reset_at, (int, float)):
            return float(reset_at)

        return None
