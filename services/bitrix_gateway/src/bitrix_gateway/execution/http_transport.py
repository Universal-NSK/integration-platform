from typing import Any, Dict, Optional, cast

import httpx

from bitrix_gateway.contracts.models import TransportResult
from bitrix_gateway.execution.transport import TransportError


class HttpBitrixTransport:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def call(
        self,
        method: str,
        payload: Dict[str, Any],
    ) -> TransportResult:
        url = f"{self._base_url}/{method}"

        try:
            response = await self._client.post(
                url,
                json=payload,
            )
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.PoolTimeout,
        ) as exc:
            raise TransportError(
                str(exc),
                outcome_uncertain=False,
            ) from exc
        except httpx.RequestError as exc:
            raise TransportError(
                str(exc),
                outcome_uncertain=True,
            ) from exc

        try:
            raw_body = response.json()
        except ValueError as exc:
            raise TransportError(
                f"Bitrix returned invalid JSON with HTTP status {response.status_code}",
                outcome_uncertain=True,
            ) from exc

        if not isinstance(raw_body, dict):
            raise TransportError(
                "Bitrix returned JSON with unexpected root type",
                outcome_uncertain=True,
            )

        body = cast(Dict[str, Any], raw_body)

        error_code = self._read_string(body, "error")
        error_message = self._read_string(
            body,
            "error_description",
        )

        operating_reset_at = self._read_operating_reset_at(body)

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
