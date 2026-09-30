"""Владение CRM-клиентом на время одного полного выполнения плана."""

import logging
from contextlib import suppress
from time import perf_counter

from platform_logging import log_event

from nashdom_sync.bitrix_crm import ClientBitrixCRM
from nashdom_sync.contracts import BitrixClientSettings, LoadResult, OperationStatus, SyncPlan

from .binding_resolver import RuntimeBindingResolver
from .command_executor import CrmCommandExecutor
from .executor import SyncPlanExecutor

logger = logging.getLogger(__name__)


class LoadService:
    def __init__(self, bitrix_client_settings: BitrixClientSettings) -> None:
        self._settings = bitrix_client_settings

    def load(self, plan: SyncPlan) -> LoadResult:
        started = perf_counter()
        log_event(logger, logging.INFO, "load_started", operations=len(plan.operations))
        try:
            client = ClientBitrixCRM(
                gateway_url=self._settings.gateway_url, timeout=self._settings.timeout
            )
            try:
                executor = SyncPlanExecutor(RuntimeBindingResolver(), CrmCommandExecutor(client))
                result = executor.execute(plan)
            except BaseException:
                # Вторичная ошибка закрытия не должна подменять первичную ошибку выполнения.
                with suppress(Exception):
                    client.close()
                raise
            else:
                client.close()
        except Exception as exc:
            with suppress(Exception):
                log_event(
                    logger,
                    logging.ERROR,
                    "load_failed",
                    exception_type=type(exc).__name__,
                    operations=len(plan.operations),
                    duration_seconds=perf_counter() - started,
                )
            raise
        counts = {
            status.value.lower(): sum(item.status is status for item in result.operations)
            for status in OperationStatus
        }
        log_event(
            logger,
            logging.INFO,
            "load_completed",
            operations=len(result.operations),
            duration_seconds=perf_counter() - started,
            **counts,
        )
        return result
