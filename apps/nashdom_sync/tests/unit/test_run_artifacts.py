import json
import logging
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict

import pytest
import runtime_files.paths as paths_module
from nashdom_sync.contracts import (
    CommissioningPeriod,
    ExistingCrmCompanyGroup,
    ExistingCrmDeveloper,
    ExistingCrmEntities,
    ExistingCrmLead,
    ExtractedObjectTypeEnum,
    ExtractResult,
    LoadResult,
    OperationResult,
    OperationStatus,
)
from nashdom_sync.contracts.transform import SyncPlan
from nashdom_sync.run_artifacts import RunArtifactError, RunArtifactStore, RunStage, RunStatus
from nashdom_sync.run_artifacts import store as store_module
from platform_logging import LoggingConfig, configure_logging
from runtime_files import RuntimePaths
from test_transform import context, source
from test_transform_debug import sample


def _json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_shared_run_directory_and_full_round_trips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = datetime(2026, 9, 28, 20, 15, 3)
    monkeypatch.setattr(paths_module, "_current_time", lambda: started)
    paths = RuntimePaths(tmp_path, tmp_path / "program-data")
    run_dir = paths.create_run_dir("nashdom_sync")
    logger = logging.getLogger("nashdom_sync")
    old_level, old_propagate, old_disabled = logger.level, logger.propagate, logger.disabled
    session = configure_logging(
        "nashdom_sync",
        "nashdom_sync",
        run_dir,
        LoggingConfig("INFO", False, True, 100_000, 2),
    )
    logger = logging.getLogger("nashdom_sync")
    try:
        logger.info("Начало запуска")
        store = RunArtifactStore.start(run_dir)
        original = source()
        result = replace(
            original,
            objects=[
                replace(
                    original.objects[0],
                    commissioning_period=CommissioningPeriod(2028, 4, date(2028, 12, 3)),
                ),
                replace(
                    original.objects[0],
                    id=2,
                    company_group_id=None,
                    object_type=ExtractedObjectTypeEnum.NON_RESIDENTIAL,
                ),
            ],
        )
        crm = replace(
            context(),
            existing=ExistingCrmEntities(
                (ExistingCrmLead(1, 11),),
                (ExistingCrmDeveloper("00123", 12),),
                (ExistingCrmCompanyGroup(20, 13),),
            ),
        )
        plan = sample()
        store.save_extract_result(result)
        store.save_crm_context(crm)
        store.save_sync_plan(plan)
        assert store.load_extract_result() == result
        assert store.load_crm_context() == crm
        assert store.load_sync_plan() == plan
        assert isinstance(store.load_crm_context().managers, tuple)
        with pytest.raises(FrozenInstanceError):
            setattr(
                store.load_crm_context().structure,
                fields(store.load_crm_context().structure)[0].name,
                None,
            )
        assert store.get_run_dir() == run_dir
        assert run_dir == tmp_path / "program-data" / "nashdom_sync" / "2026-09-28_20-15-03"
        assert list(run_dir.parent.iterdir()) == [run_dir]
        assert {p.name for p in run_dir.iterdir()} == {
            "nashdom_sync.log",
            "run.json",
            "extract_result.json",
            "crm_context.json",
            "sync_plan.json",
        }
        extract_json = _json(run_dir / "extract_result.json")
        assert extract_json["schema_version"] == 1
        assert extract_json["data"]["objects"][0]["commissioning_period"] == {
            "year": 2028,
            "quarter": 4,
            "exact_date": "2028-12-03",
        }
        commands = _json(run_dir / "sync_plan.json")["data"]["operations"]
        assert [op["command"]["type"] for op in commands] == [
            "add_item",
            "add_item",
            "add_requisite",
            "add_address",
            "add_address",
            "add_item",
        ]
        # Идентификаторы намеренно не совпадают с типами команд.
        assert commands[2]["operation_id"] == "R"
        assert "Группа" in (run_dir / "sync_plan.json").read_text(encoding="utf-8")
        before = (run_dir / "sync_plan.json").read_bytes()
        store.save_sync_plan(plan)
        assert (run_dir / "sync_plan.json").read_bytes() == before
        for handler in logger.handlers:
            handler.flush()
        log = session.log_file.read_text(encoding="utf-8")
        assert len(log.splitlines()) == 1
        assert "Начало запуска" in log
        for private in ("00123", "+70000000000", "mail@example.invalid", "Группа"):
            assert private not in log
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "_platform_logging_owned", False):
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(old_level)
        logger.propagate = old_propagate
        logger.disabled = old_disabled


def test_empty_round_trips(tmp_path: Path) -> None:
    store = RunArtifactStore.start(tmp_path)
    store.save_extract_result(ExtractResult([], [], []))
    store.save_sync_plan(SyncPlan(()))
    assert store.load_extract_result() == ExtractResult([], [], [])
    assert store.load_sync_plan() == SyncPlan(())


def test_manifest_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started, finished = datetime(2026, 9, 28, 12), datetime(2026, 9, 28, 13)
    monkeypatch.setattr(store_module, "_current_time", lambda: started)
    store = RunArtifactStore.start(tmp_path)
    assert _json(tmp_path / "run.json") == {
        "schema_version": 1,
        "run_id": tmp_path.name,
        "status": "RUNNING",
        "stage": "INITIALIZATION",
        "started_at": started.isoformat(),
        "finished_at": None,
        "error_type": None,
    }
    for stage in RunStage:
        store.mark_stage(stage)
        manifest = _json(tmp_path / "run.json")
        assert manifest["stage"] == stage.value
        assert manifest["status"] == RunStatus.RUNNING.value
        assert manifest["finished_at"] is None
    monkeypatch.setattr(store_module, "_current_time", lambda: finished)
    store.mark_completed()
    manifest = _json(tmp_path / "run.json")
    assert manifest["status"] == "COMPLETED"
    assert manifest["finished_at"] == finished.isoformat()
    assert manifest["started_at"] == started.isoformat()
    assert manifest["error_type"] is None
    store.mark_failed(RunStage.EXTRACT, "ExtractError")
    manifest = _json(tmp_path / "run.json")
    assert manifest["status"] == "FAILED"
    assert manifest["stage"] == "EXTRACT"
    assert manifest["error_type"] == "ExtractError"
    assert manifest["finished_at"] == finished.isoformat()


@pytest.mark.parametrize("as_file", [False, True])
def test_start_requires_existing_directory(tmp_path: Path, as_file: bool) -> None:
    run_dir = tmp_path / "invalid"
    if as_file:
        run_dir.touch()
    with pytest.raises(RunArtifactError) as error:
        RunArtifactStore.start(run_dir)
    assert error.value.__cause__ is not None
    assert not run_dir.is_dir()


@pytest.mark.parametrize("failure", ["replace", "fsync", "dump"])
def test_atomic_failure_preserves_target_and_cleans_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    store = RunArtifactStore.start(tmp_path)
    store.save_sync_plan(sample())
    before = (tmp_path / "sync_plan.json").read_bytes()

    def fail(*args: Any, **kwargs: Any) -> None:
        if failure == "dump":
            args[1].write("{частичная запись")
        raise OSError("Тестовый сбой записи")

    target = store_module.json if failure == "dump" else store_module.os
    monkeypatch.setattr(target, failure, fail)
    with pytest.raises(RunArtifactError) as error:
        store.save_sync_plan(SyncPlan(()))
    assert error.value.__cause__ is not None
    assert (tmp_path / "sync_plan.json").read_bytes() == before
    assert {p.name for p in tmp_path.iterdir()} == {"run.json", "sync_plan.json"}


def test_failed_manifest_write_does_not_advance_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RunArtifactStore.start(tmp_path)
    before = (tmp_path / "run.json").read_bytes()

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("Тестовый сбой замены")

    with monkeypatch.context() as patch:
        patch.setattr(store_module.os, "replace", fail)
        with pytest.raises(RunArtifactError):
            store.mark_failed(RunStage.TRANSFORM, "TransformError")
    assert (tmp_path / "run.json").read_bytes() == before
    store.mark_stage(RunStage.CRM_CONTEXT)
    manifest = _json(tmp_path / "run.json")
    assert manifest["status"] == "RUNNING"
    assert manifest["error_type"] is None
    assert manifest["finished_at"] is None


@pytest.mark.parametrize(
    "content",
    [
        "{",
        "[]",
        '{"schema_version": 2, "data": {}}',
        '{"schema_version": true, "data": {}}',
        '{"schema_version": 1, "data": {"operations": null}}',
        '{"schema_version": 1, "data": {"operations": [{"command": {"type": "private"}}]}}',
    ],
)
def test_bad_snapshot_is_wrapped_without_payload(tmp_path: Path, content: str) -> None:
    store = RunArtifactStore.start(tmp_path)
    (tmp_path / "sync_plan.json").write_text(content, encoding="utf-8")
    with pytest.raises(RunArtifactError) as error:
        store.load_sync_plan()
    assert error.value.__cause__ is not None
    assert "private" not in str(error.value)
    assert "sync_plan.json" in str(error.value)


def test_missing_snapshot_is_wrapped(tmp_path: Path) -> None:
    store = RunArtifactStore.start(tmp_path)
    with pytest.raises(RunArtifactError) as error:
        store.load_extract_result()
    assert isinstance(error.value.__cause__, FileNotFoundError)


@pytest.mark.parametrize("tag", [None, "unknown"])
def test_command_requires_discriminator(tmp_path: Path, tag: Any) -> None:
    store = RunArtifactStore.start(tmp_path)
    store.save_sync_plan(sample())
    data = _json(tmp_path / "sync_plan.json")
    command = data["data"]["operations"][0]["command"]
    if tag is None:
        del command["type"]
    else:
        command["type"] = tag
    (tmp_path / "sync_plan.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RunArtifactError):
        store.load_sync_plan()


def test_atomic_write_flushes_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_replace = store_module.os.replace
    original_fsync = store_module.os.fsync
    synced = False
    replaced = False

    def fsync(fd: int) -> None:
        nonlocal synced
        original_fsync(fd)
        synced = True

    def replace_file(source_path: str, target_path: str) -> None:
        nonlocal replaced
        assert synced
        temporary, target = Path(source_path), Path(target_path)
        assert temporary.parent == target.parent == tmp_path
        assert _json(temporary)["status"] == "RUNNING"
        original_replace(source_path, target_path)
        replaced = True

    monkeypatch.setattr(store_module.os, "fsync", fsync)
    monkeypatch.setattr(store_module.os, "replace", replace_file)
    RunArtifactStore.start(tmp_path)
    assert synced and replaced
    assert [p.name for p in tmp_path.iterdir()] == ["run.json"]


@pytest.mark.parametrize("failure", ["replace", "fsync", "dump"])
def test_start_write_failure_leaves_no_partial_manifest_and_allows_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        if failure == "dump":
            args[1].write("{частичная запись")
        raise OSError("Тестовый сбой записи")

    target = store_module.json if failure == "dump" else store_module.os
    with monkeypatch.context() as patch:
        patch.setattr(target, failure, fail)
        with pytest.raises(RunArtifactError):
            RunArtifactStore.start(tmp_path)
    assert list(tmp_path.iterdir()) == []

    store = RunArtifactStore.start(tmp_path)
    assert store.get_run_dir() == tmp_path
    assert _json(tmp_path / "run.json")["status"] == "RUNNING"
    assert [path.name for path in tmp_path.iterdir()] == ["run.json"]


def test_non_json_command_fields_cannot_silently_lose_type(tmp_path: Path) -> None:
    store = RunArtifactStore.start(tmp_path)
    plan = sample()
    first = plan.operations[0]
    changed = replace(first, command=replace(first.command, fields={"private": date(2026, 9, 28)}))
    with pytest.raises(RunArtifactError) as error:
        store.save_sync_plan(SyncPlan((changed,)))
    assert "private" not in str(error.value)
    assert not (tmp_path / "sync_plan.json").exists()


def test_start_in_empty_directory_creates_initial_manifest(tmp_path: Path) -> None:
    assert list(tmp_path.iterdir()) == []
    store = RunArtifactStore.start(tmp_path)
    assert store.get_run_dir() == tmp_path
    assert _json(tmp_path / "run.json")["status"] == "RUNNING"
    assert [path.name for path in tmp_path.iterdir()] == ["run.json"]


def test_repeated_start_preserves_manifest_bytes(tmp_path: Path) -> None:
    store = RunArtifactStore.start(tmp_path)
    store.mark_completed()
    manifest_path = tmp_path / "run.json"
    before = manifest_path.read_bytes()

    with pytest.raises(RunArtifactError) as error:
        RunArtifactStore.start(tmp_path)

    assert str(error.value) == "Каталог запуска уже инициализирован"
    assert manifest_path.read_bytes() == before
    assert [path.name for path in tmp_path.iterdir()] == ["run.json"]


@pytest.mark.parametrize("content", [b"", b"invalid JSON"])
def test_existing_manifest_is_rejected_regardless_of_content(
    tmp_path: Path,
    content: bytes,
) -> None:
    manifest_path = tmp_path / "run.json"
    manifest_path.write_bytes(content)

    with pytest.raises(RunArtifactError) as error:
        RunArtifactStore.start(tmp_path)

    assert str(error.value) == "Каталог запуска уже инициализирован"
    assert manifest_path.read_bytes() == content


def test_other_files_do_not_prevent_start(tmp_path: Path) -> None:
    other_file = tmp_path / "some_file.txt"
    other_file.write_text("Сохранить без изменений", encoding="utf-8")
    before = other_file.read_bytes()

    store = RunArtifactStore.start(tmp_path)

    assert store.get_run_dir() == tmp_path
    assert _json(tmp_path / "run.json")["status"] == "RUNNING"
    assert other_file.read_bytes() == before
    assert {path.name for path in tmp_path.iterdir()} == {"some_file.txt", "run.json"}


@pytest.mark.parametrize("empty", [False, True])
def test_load_result_round_trip(tmp_path: Path, empty: bool) -> None:
    result = (
        LoadResult(())
        if empty
        else LoadResult(
            (
                OperationResult("item", OperationStatus.SUCCESS, 123),
                OperationResult("address", OperationStatus.SUCCESS),
                OperationResult(
                    "failed", OperationStatus.FAILED, error_type="BitrixRequestFailedError"
                ),
                OperationResult(
                    "unknown", OperationStatus.UNKNOWN, error_type="BitrixRequestUnknownError"
                ),
                OperationResult(
                    "blocked", OperationStatus.BLOCKED, blocked_by=("unknown", "failed")
                ),
            )
        )
    )
    store = RunArtifactStore.start(tmp_path)
    store.save_load_result(result)
    restored = store.load_load_result()
    assert restored == result
    assert isinstance(restored.operations, tuple)
    for operation in restored.operations:
        assert isinstance(operation.status, OperationStatus)
        assert isinstance(operation.blocked_by, tuple)
    assert _json(tmp_path / "load_result.json")["schema_version"] == 1
    assert restored.is_successful is empty


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        "null",
        '{"schema_version": 2, "data": {"operations": []}}',
        '{"schema_version": 1, "data": {"operations": {}}}',
        '{"schema_version": 1, "data": {"operations": [{"operation_id": "a"}]}}',
    ],
)
def test_corrupt_load_result(tmp_path: Path, raw: str) -> None:
    store = RunArtifactStore.start(tmp_path)
    (tmp_path / "load_result.json").write_text(raw, encoding="utf-8")
    with pytest.raises(RunArtifactError, match="load_result.json"):
        store.load_load_result()


@pytest.mark.parametrize(
    "field, value",
    [
        ("status", "PENDING"),
        ("crm_id", "123"),
        ("blocked_by", [1]),
        ("error_type", 4),
    ],
)
def test_load_result_field_corruption(tmp_path: Path, field: str, value: Any) -> None:
    store = RunArtifactStore.start(tmp_path)
    store.save_load_result(LoadResult((OperationResult("a", OperationStatus.SUCCESS, 1),)))
    path = tmp_path / "load_result.json"
    raw = _json(path)
    raw["data"]["operations"][0][field] = value
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RunArtifactError):
        store.load_load_result()
