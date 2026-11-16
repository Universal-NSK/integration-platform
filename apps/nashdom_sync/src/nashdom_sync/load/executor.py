"""Последовательное выполнение плана с блокировкой непосредственных зависимостей."""

import logging
from time import perf_counter
from typing import Dict, Mapping, Tuple

from platform_logging import log_event

from nashdom_sync.bitrix_crm import (
    BitrixGatewayError,
    BitrixRequestFailedError,
    BitrixRequestUnknownError,
)
from nashdom_sync.contracts import (
    LoadResult,
    OperationResult,
    OperationStatus,
    PlannedOperation,
    SyncPlan,
)

from .binding_resolver import RuntimeBindingResolver
from .command_executor import CrmCommandExecutor
from .exceptions import LoadInvariantError

logger = logging.getLogger(__name__)


class SyncPlanExecutor:
    def __init__(
        self, binding_resolver: RuntimeBindingResolver, command_executor: CrmCommandExecutor
    ) -> None:
        self._binding_resolver = binding_resolver
        self._command_executor = command_executor

    def execute(self, plan: SyncPlan) -> LoadResult:
        results: Dict[str, OperationResult] = {}
        for operation in plan.operations:
            started = perf_counter()
            operation_id = operation.operation_id
            command_type = type(operation.command).__name__
            if operation_id in results:
                raise LoadInvariantError(f"Повторяющийся ID операции {operation_id}")
            blockers = self._find_blockers(operation, results)
            if blockers:
                result = OperationResult(operation_id, OperationStatus.BLOCKED, blocked_by=blockers)
                event = "load_operation_blocked"
            else:
                command = self._binding_resolver.resolve(operation, results)
                log_event(
                    logger,
                    logging.DEBUG,
                    "load_operation_started",
                    operation_id=operation_id,
                    command_type=command_type,
                )
                try:
                    crm_id = self._command_executor.execute(command)
                except _ERROR_STATUSES as exc:
                    result = OperationResult(
                        operation_id,
                        _status_for(exc),
                        error_type=type(exc).__name__,
                    )
                    event = "load_operation_failed"
                else:
                    result = OperationResult(operation_id, OperationStatus.SUCCESS, crm_id=crm_id)
                    event = "load_operation_completed"
            results[operation_id] = result
            log_event(
                logger,
                logging.DEBUG,
                event,
                operation_id=operation_id,
                command_type=command_type,
                status=result.status.value,
                error_type=result.error_type,
                duration_seconds=perf_counter() - started,
            )
        return LoadResult(tuple(results.values()))

    @staticmethod
    def _dependency_ids(operation: PlannedOperation) -> Tuple[str, ...]:
        """Явные зависимости и источники runtime-связей без повторов, в порядке появления."""
        return tuple(
            dict.fromkeys(
                operation.dependencies + tuple(b.source_operation_id for b in operation.bindings)
            )
        )

    @classmethod
    def _find_blockers(
        cls, operation: PlannedOperation, results: Mapping[str, OperationResult]
    ) -> Tuple[str, ...]:
        """Непосредственные зависимости, завершившиеся не SUCCESS.

        Зависимость без результата нарушает порядок плана и прерывает загрузку.
        """
        dependencies = cls._dependency_ids(operation)
        for dependency in dependencies:
            if dependency not in results:
                raise LoadInvariantError(
                    f"Операция {operation.operation_id} ссылается "
                    f"на отсутствующий результат {dependency}"
                )
        return tuple(
            dependency
            for dependency in dependencies
            if results[dependency].status is not OperationStatus.SUCCESS
        )


# Ошибки записи, после которых загрузка продолжается. BitrixGatewayError (504, обрыв,
# невалидный ответ) — исход записи неизвестен, поэтому UNKNOWN, как и BitrixRequestUnknownError.
_ERROR_STATUSES = (BitrixRequestFailedError, BitrixRequestUnknownError, BitrixGatewayError)


def _status_for(error: Exception) -> OperationStatus:
    if isinstance(error, BitrixRequestFailedError):
        return OperationStatus.FAILED
    return OperationStatus.UNKNOWN
