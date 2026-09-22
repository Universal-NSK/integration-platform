"""Публичный CRM-клиент; HTTP-адаптер и DTO остаются внутри пакета."""

from .client import ClientBitrixCRM
from .exceptions import (
    BitrixClientError,
    BitrixGatewayError,
    BitrixRequestFailedError,
    BitrixRequestUnknownError,
)

__all__ = [
    "ClientBitrixCRM",
    "BitrixClientError",
    "BitrixGatewayError",
    "BitrixRequestFailedError",
    "BitrixRequestUnknownError",
]
