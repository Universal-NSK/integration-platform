"""Неизменяемые результаты последовательного выполнения плана синхронизации."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class OperationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    status: OperationStatus
    crm_id: Optional[int] = None
    error_type: Optional[str] = None
    blocked_by: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LoadResult:
    operations: Tuple[OperationResult, ...]

    @property
    def is_successful(self) -> bool:
        return all(result.status is OperationStatus.SUCCESS for result in self.operations)
