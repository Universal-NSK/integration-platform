"""Состояние диагностического снимка одного запуска синхронизации."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RunStage(str, Enum):
    INITIALIZATION = "INITIALIZATION"
    CRM_CONTEXT = "CRM_CONTEXT"
    EXTRACT = "EXTRACT"
    TRANSFORM = "TRANSFORM"
    LOAD = "LOAD"


@dataclass(frozen=True)
class RunManifest:
    schema_version: int
    run_id: str
    status: RunStatus
    stage: RunStage
    started_at: datetime
    finished_at: Optional[datetime]
    error_type: Optional[str]
