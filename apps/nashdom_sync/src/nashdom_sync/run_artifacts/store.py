"""Атомарное хранение снимков в готовом каталоге запуска без логирования PII."""

import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar, cast

from nashdom_sync.contracts.crm import CrmContext
from nashdom_sync.contracts.extract import ExtractResult
from nashdom_sync.contracts.transform import SyncPlan
from nashdom_sync.run_artifacts.contracts import RunManifest, RunStage, RunStatus
from nashdom_sync.run_artifacts.exceptions import RunArtifactError
from nashdom_sync.run_artifacts.serialization import decode, encode

T = TypeVar("T")


def _current_time() -> datetime:
    return datetime.now().astimezone()


def _reject_constant(value: str) -> None:
    raise ValueError("Нечисловые константы JSON запрещены")


class RunArtifactStore:
    """Хранилище одного запуска; каталог создаёт вызывающая сторона."""

    def __init__(self, run_dir: Path, manifest: RunManifest) -> None:
        self._run_dir = run_dir
        self._manifest = manifest

    @classmethod
    def start(cls, run_dir: Path) -> "RunArtifactStore":
        """Записать манифест только в ещё не инициализированный каталог запуска."""
        try:
            if not run_dir.is_dir():
                raise ValueError("run_dir должен быть существующим каталогом")
            if (run_dir / "run.json").exists():
                raise RunArtifactError("Каталог запуска уже инициализирован")
            manifest = RunManifest(
                schema_version=1,
                run_id=run_dir.name,
                status=RunStatus.RUNNING,
                stage=RunStage.INITIALIZATION,
                started_at=_current_time(),
                finished_at=None,
                error_type=None,
            )
            store = cls(run_dir, manifest)
            store._write_json("run.json", encode(manifest))
            return store
        except RunArtifactError:
            raise
        except Exception as exc:
            raise RunArtifactError("Не удалось начать хранение артефактов запуска") from exc

    def get_run_dir(self) -> Path:
        return self._run_dir

    def save_extract_result(self, result: ExtractResult) -> None:
        self._save("extract_result.json", result, ExtractResult)

    def load_extract_result(self) -> ExtractResult:
        return self._load("extract_result.json", ExtractResult)

    def save_crm_context(self, context: CrmContext) -> None:
        self._save("crm_context.json", context, CrmContext)

    def load_crm_context(self) -> CrmContext:
        return self._load("crm_context.json", CrmContext)

    def save_sync_plan(self, plan: SyncPlan) -> None:
        self._save("sync_plan.json", plan, SyncPlan)

    def load_sync_plan(self) -> SyncPlan:
        return self._load("sync_plan.json", SyncPlan)

    def mark_stage(self, stage: RunStage) -> None:
        self._update_manifest(replace(self._manifest, stage=stage))

    def mark_completed(self) -> None:
        self._update_manifest(
            replace(
                self._manifest,
                status=RunStatus.COMPLETED,
                finished_at=_current_time(),
                error_type=None,
            )
        )

    def mark_failed(self, stage: RunStage, error_type: str) -> None:
        """Записать тип ошибки; вызывающая сторона не должна передавать её payload."""
        self._update_manifest(
            replace(
                self._manifest,
                status=RunStatus.FAILED,
                stage=stage,
                finished_at=_current_time(),
                error_type=error_type,
            )
        )

    def _update_manifest(self, manifest: RunManifest) -> None:
        self._write_json("run.json", encode(manifest))
        self._manifest = manifest

    def _save(self, name: str, value: T, model: Type[T]) -> None:
        try:
            data = encode(value)
            if decode(model, data) != value:
                raise ValueError("Данные не поддерживают восстановление без потерь")
            self._write_json(name, {"schema_version": 1, "data": data})
        except RunArtifactError:
            raise
        except Exception as exc:
            raise RunArtifactError(f"Не удалось сохранить артефакт {name}") from exc

    def _load(self, name: str, model: Type[T]) -> T:
        try:
            with (self._run_dir / name).open("r", encoding="utf-8") as stream:
                raw: Any = json.load(stream, parse_constant=_reject_constant)
            if not isinstance(raw, dict):
                raise ValueError("Ожидался JSON-конверт артефакта")
            envelope = cast(Dict[str, Any], raw)
            if (
                set(envelope) != {"schema_version", "data"}
                or type(envelope["schema_version"]) is not int
                or envelope["schema_version"] != 1
            ):
                raise ValueError("Неподдерживаемая схема артефакта")
            return decode(model, envelope["data"])
        except Exception as exc:
            raise RunArtifactError(f"Не удалось прочитать артефакт {name}") from exc

    def _write_json(self, name: str, data: Any) -> None:
        temporary: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self._run_dir,
                prefix=f".{name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(
                    data, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(self._run_dir / name))
        except Exception as exc:
            raise RunArtifactError(f"Не удалось атомарно записать артефакт {name}") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass
