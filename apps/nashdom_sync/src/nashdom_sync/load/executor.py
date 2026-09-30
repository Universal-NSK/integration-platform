"""Последовательное выполнение плана с блокировкой непосредственных зависимостей."""

import logging
from time import perf_counter
from typing import Dict

from platform_logging import log_event

from nashdom_sync.bitrix_crm import BitrixRequestFailedError, BitrixRequestUnknownError
from nashdom_sync.contracts import LoadResult, OperationResult, OperationStatus, SyncPlan

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
            dependencies = tuple(
                dict.fromkeys(
                    operation.dependencies
                    + tuple(b.source_operation_id for b in operation.bindings)
                )
            )
            for dependency in dependencies:
                if dependency not in results:
                    raise LoadInvariantError(
                        f"Операция {operation_id} ссылается на отсутствующий результат {dependency}"
                    )
            blockers = tuple(
                dependency
                for dependency in dependencies
                if results[dependency].status is not OperationStatus.SUCCESS
            )
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
                except (BitrixRequestFailedError, BitrixRequestUnknownError) as exc:
                    status = (
                        OperationStatus.FAILED
                        if isinstance(exc, BitrixRequestFailedError)
                        else OperationStatus.UNKNOWN
                    )
                    error_type = (
                        "BitrixRequestFailedError"
                        if status is OperationStatus.FAILED
                        else "BitrixRequestUnknownError"
                    )
                    result = OperationResult(operation_id, status, error_type=error_type)
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
