"""Shared configuration helpers for Python's standard :mod:`logging` package.

Payload and response bodies are logged only through an explicit ``log_payload``
call. Callers may pass business payloads and responses, but must never pass webhook
URLs, secret configuration, or full Bitrix request URLs to logging helpers.
"""

from platform_logging.config import LoggingConfig
from platform_logging.context import log_event, log_payload, with_context
from platform_logging.setup import LoggingSession, configure_logging

__all__ = [
    "LoggingConfig",
    "LoggingSession",
    "configure_logging",
    "log_event",
    "log_payload",
    "with_context",
]
