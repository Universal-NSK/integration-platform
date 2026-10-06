"""Проверки оркестрации с настоящими артефактами и подменёнными внешними сервисами."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple
from unittest.mock import Mock

import pytest
import tomli
from nashdom_sync import main as main_module
from nashdom_sync import orchestrator as module
from nashdom_sync.bitrix_crm import BitrixGatewayError, BitrixRequestFailedError, ClientBitrixCRM
from nashdom_sync.contracts import LoadResult, OperationResult, OperationStatus, SyncSettings
from nashdom_sync.contracts.transform import (
    AddItemCommand,
    PlannedOperation,
    RuntimeBinding,
    SyncPlan,
    TransformResult,
)
from nashdom_sync.extract import (
    BrowserSessionUnavailableError,
    ExtractError,
    NashDomClientError,
    SourceDataValidationError,
)
from nashdom_sync.load import LoadIncompleteError, LoadService
from nashdom_sync.load import service as load_module
from nashdom_sync.providers.browser_provider import (
    BrowserBinaryNotFoundError,
    BrowserLaunchError,
    DriverBinaryNotFoundError,
)
from nashdom_sync.providers.crm_provider import CrmProviderError
from nashdom_sync.providers.settings_provider import ConfigurationError, ConfigurationOverlapError
from nashdom_sync.run_artifacts import RunArtifactError, RunArtifactStore, RunStage
from nashdom_sync.transform import TransformError
from platform_logging import LoggingConfig, log_event
from runtime_files import RuntimePaths
from test_transform import context, source


@dataclass
class Run:
    paths: RuntimePaths
    settings: SyncSettings
    constructors: Dict[str, Mock]
    driver: Mock
    store: Mock
    events: List[Tuple[str, str]]
    configured: Mock

    @property
    def directory(self) -> Path:
        directories = list(self.paths.program_data_dir("nashdom_sync").iterdir())
        assert len(directories) == 1
        return directories[0]

    def manifest(self) -> Dict[str, Any]:
        return json.loads((self.directory / "run.json").read_text(encoding="utf-8"))

    def log(self) -> str:
        return (self.directory / "nashdom_sync.log").read_text(encoding="utf-8")

    def execute(self) -> None:
        module.SyncOrchestrator().run(self.paths)


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Run]:
    settings = SyncSettings.parse_obj(
        {
            "execution": {"load_enabled": True},
            "logging": {
                "level": "DEBUG",
                "console": False,
                "log_payloads": True,
                "max_bytes": 123456,
                "backup_count": 2,
            },
            "browser": {
                "headless": True,
                "page_load_timeout_seconds": 120.0,
                "script_timeout_seconds": 60.0,
                "page_load_strategy": "eager",
                "disable_images": True,
                "window_width": 1280,
                "window_height": 720,
                "launch_max_attempts": 3,
                "launch_retry_delay_seconds": 10.0,
                "extract_session_max_attempts": 2,
                "extract_session_retry_delay_seconds": 10.0,
                "browser_path": tmp_path / "chrome.exe",
                "driver_path": tmp_path / "driver.exe",
            },
            "bitrix": {"gateway_url": "http://example.invalid", "timeout": 2},
            "extract": {
                "nashdom": {
                    "objects_to_parse_count": 1,
                    "regions": [],
                    "element_wait_timeout_seconds": 60.0,
                    "navigation_max_attempts": 3,
                    "navigation_retry_delay_seconds": 10.0,
                }
            },
            "region": {"default_assigned_by_name": "Менеджер", "assignment": {}},
        }
    )
    constructors = {
        name: Mock()
        for name in (
            "SettingsProvider",
            "BrowserProvider",
            "ExtractService",
            "TransformService",
            "CrmProvider",
            "LoadService",
        )
    }
    for name, constructor in constructors.items():
        monkeypatch.setattr(module, name, constructor)
    constructors["SettingsProvider"].return_value.provide.return_value = settings
    constructors["CrmProvider"].return_value.provide.return_value = context()
    constructors["ExtractService"].return_value.extract.return_value = source()
    constructors["TransformService"].return_value.transform.return_value = TransformResult(
        SyncPlan(())
    )
    constructors["LoadService"].return_value.load.return_value = LoadResult(())
    driver = constructors["BrowserProvider"].return_value.provide.return_value
    store = Mock()
    start = RunArtifactStore.start

    def start_store(directory: Path) -> Mock:
        real = start(directory)
        for name in (
            "mark_stage",
            "mark_completed",
            "mark_failed",
            "save_crm_context",
            "save_extract_result",
            "save_sync_plan",
            "save_load_result",
        ):
            getattr(store, name).side_effect = getattr(real, name)
        return store

    monkeypatch.setattr(module, "RunArtifactStore", Mock(start=Mock(side_effect=start_store)))
    configured = Mock(wraps=module.configure_logging)
    monkeypatch.setattr(module, "configure_logging", configured)
    events: List[Tuple[str, str]] = []
    paths = RuntimePaths(tmp_path, tmp_path / "program-data")
    result = Run(paths, settings, constructors, driver, store, events, configured)
    logger = logging.getLogger("nashdom_sync")
    previous = logger.level, logger.propagate, logger.disabled

    def record(logger: logging.Logger, level: int, event: str, **details: Any) -> None:
        stage = details["stage"]
        events.append((event, stage))
        assert result.manifest()["stage"] == stage
        if event == "stage_completed":
            filename = {
                "CRM_CONTEXT": "crm_context.json",
                "EXTRACT": "extract_result.json",
                "TRANSFORM": "sync_plan.json",
                "LOAD": "load_result.json",
            }.get(stage)
            if filename is not None:
                assert (result.directory / filename).is_file()
        assert details["run_id"] == result.directory.name
        assert details["duration_seconds"] >= 0
        log_event(logger, level, event, **details)

    monkeypatch.setattr(module, "log_event", record)
    try:
        yield result
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "_platform_logging_owned", False):
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(previous[0])
        logger.propagate, logger.disabled = previous[1:]


def assert_failed(run: Run, stage: str, error: Exception) -> None:
    manifest = run.manifest()
    assert manifest["status"] == "FAILED"
    assert manifest["stage"] == stage
    assert manifest["error_type"] == type(error).__name__
    assert manifest["finished_at"] is not None


def test_happy_path(run: Run) -> None:
    def extract(*args: Any) -> Any:
        log_event(
            logging.getLogger("nashdom_sync.extract.service"), logging.INFO, "дочерний_extract"
        )
        return source_result

    source_result = run.constructors["ExtractService"].return_value.extract.return_value
    crm_result = run.constructors["CrmProvider"].return_value.provide.return_value
    run.constructors["ExtractService"].return_value.extract.side_effect = extract
    run.execute()
    assert {p.name for p in run.directory.iterdir()} == {
        "run.json",
        "nashdom_sync.log",
        "crm_context.json",
        "extract_result.json",
        "sync_plan.json",
        "load_result.json",
    }
    assert run.manifest()["status"] == "COMPLETED"
    assert run.manifest()["stage"] == "LOAD"
    assert run.manifest()["error_type"] is None
    assert run.manifest()["finished_at"] is not None
    expected = [("sync_started", "INITIALIZATION")]
    for stage in ("INITIALIZATION", "CRM_CONTEXT", "EXTRACT", "TRANSFORM", "LOAD"):
        expected.extend([("stage_started", stage), ("stage_completed", stage)])
    expected.append(("sync_completed", "LOAD"))
    expected.insert(4, ("crm_context_source", "CRM_CONTEXT"))
    assert run.events == expected
    assert [call.args[0] for call in run.store.mark_stage.call_args_list] == [
        RunStage.CRM_CONTEXT,
        RunStage.EXTRACT,
        RunStage.TRANSFORM,
        RunStage.LOAD,
    ]
    run.driver.quit.assert_called_once_with()
    for constructor in run.constructors.values():
        constructor.assert_called_once()
    run.constructors["SettingsProvider"].assert_called_once_with(run.paths)
    run.constructors["CrmProvider"].assert_called_once_with(run.settings.bitrix)
    run.constructors["LoadService"].assert_called_once_with(run.settings.bitrix)
    plan = run.constructors["TransformService"].return_value.transform.return_value.plan
    assert run.constructors["LoadService"].return_value.load.call_args.args[0] is plan
    run.store.save_load_result.assert_called_once_with(
        run.constructors["LoadService"].return_value.load.return_value
    )
    run.constructors["LoadService"].return_value.load.assert_called_once_with(plan)
    run.store.load_sync_plan.assert_not_called()
    run.constructors["CrmProvider"].return_value.provide.assert_called_once_with(
        run.settings.region
    )
    run.constructors["BrowserProvider"].return_value.provide.assert_called_once_with(
        run.settings.browser
    )
    run.constructors["ExtractService"].return_value.extract.assert_called_once_with(
        run.driver, run.settings.extract
    )
    args = run.constructors["TransformService"].return_value.transform.call_args.args
    assert args[0] is source_result
    assert args[1] is crm_result
    assert args[2] is run.settings.region
    assert run.store.save_extract_result.call_args.args[0] is source_result
    assert run.store.save_crm_context.call_args.args[0] is crm_result
    run.store.load_extract_result.assert_not_called()
    run.store.load_crm_context.assert_not_called()
    run.configured.assert_called_once_with(
        service_name="nashdom_sync",
        logger_name="nashdom_sync",
        run_dir=run.directory,
        config=LoggingConfig("DEBUG", False, True, 123456, 2),
    )
    text = run.log()
    assert "дочерний_extract" in text
    for event, stage in expected:
        assert any(event in line and "stage=" + stage in line for line in text.splitlines())
    for child in ("nashdom_sync.transform.service", "nashdom_sync.providers.crm_provider.provider"):
        log_event(logging.getLogger(child), logging.INFO, "дочерний_компонент")
        assert child in run.log()


@pytest.mark.parametrize(
    "error", [ConfigurationError("Секрет"), ConfigurationOverlapError("Секрет")]
)
def test_settings_failure(run: Run, error: Exception) -> None:
    run.constructors["SettingsProvider"].return_value.provide.side_effect = error
    with pytest.raises(type(error)) as caught:
        run.execute()
    assert caught.value is error
    assert_failed(run, "INITIALIZATION", error)
    assert not (run.directory / "nashdom_sync.log").exists()
    for name in ("BrowserProvider", "ExtractService", "TransformService"):
        run.constructors[name].assert_called_once_with()
        assert not run.constructors[name].return_value.mock_calls
    run.constructors["CrmProvider"].assert_not_called()


@pytest.mark.parametrize(
    "component",
    [
        "SettingsProvider",
        "BrowserProvider",
        "ExtractService",
        "TransformService",
        "CrmProvider",
        "LoadService",
    ],
)
def test_constructor_failure_is_initialization(run: Run, component: str) -> None:
    error = RuntimeError("Ошибка конструктора")
    run.constructors[component].side_effect = error
    with pytest.raises(RuntimeError) as caught:
        run.execute()
    assert caught.value is error
    assert_failed(run, "INITIALIZATION", error)
    run.constructors["CrmProvider"].return_value.provide.assert_not_called()
    run.constructors["BrowserProvider"].return_value.provide.assert_not_called()


@pytest.mark.parametrize(
    "component, method, stage, error",
    [
        ("CrmProvider", "provide", "CRM_CONTEXT", CrmProviderError("Секрет")),
        (
            "BrowserProvider",
            "provide",
            "EXTRACT",
            BrowserLaunchError(Path("секрет"), Path("секрет")),
        ),
        ("BrowserProvider", "provide", "EXTRACT", BrowserBinaryNotFoundError(Path("секрет"))),
        ("BrowserProvider", "provide", "EXTRACT", DriverBinaryNotFoundError(Path("секрет"))),
        ("ExtractService", "extract", "EXTRACT", ExtractError("Секрет")),
        ("TransformService", "transform", "TRANSFORM", TransformError("Секрет")),
    ],
)
def test_stage_failure(run: Run, component: str, method: str, stage: str, error: Exception) -> None:
    getattr(run.constructors[component].return_value, method).side_effect = error
    with pytest.raises(type(error)) as caught:
        run.execute()
    assert caught.value is error
    assert_failed(run, stage, error)
    assert ("stage_completed", stage) not in run.events
    if stage not in ("TRANSFORM", "LOAD"):
        run.constructors["TransformService"].return_value.transform.assert_not_called()
    if component in ("CrmProvider", "BrowserProvider"):
        run.constructors["ExtractService"].return_value.extract.assert_not_called()
        run.driver.quit.assert_not_called()
    else:
        run.driver.quit.assert_called_once_with()
    run.constructors["LoadService"].return_value.load.assert_not_called()
    assert not (run.directory / "sync_plan.json").exists()
    assert "sync_failed" in run.log()
    assert "exception_type=" + type(error).__name__ in run.log()
    assert "секрет" not in run.log().lower()


@pytest.mark.parametrize(
    "method, stage",
    [
        ("save_crm_context", "CRM_CONTEXT"),
        ("save_extract_result", "EXTRACT"),
        ("save_sync_plan", "TRANSFORM"),
        ("save_load_result", "LOAD"),
        ("mark_completed", "LOAD"),
    ],
)
def test_artifact_failure(
    run: Run, monkeypatch: pytest.MonkeyPatch, method: str, stage: str
) -> None:
    error = RunArtifactError("Ошибка сохранения")
    monkeypatch.setattr(RunArtifactStore, method, Mock(side_effect=error))
    with pytest.raises(RunArtifactError) as caught:
        run.execute()
    assert caught.value is error
    assert_failed(run, stage, error)
    if method != "mark_completed":
        assert ("stage_completed", stage) not in run.events
    if method != "mark_completed":
        run.store.mark_completed.assert_not_called()
    if stage != "LOAD":
        run.constructors["LoadService"].return_value.load.assert_not_called()
    if stage == "CRM_CONTEXT":
        run.constructors["BrowserProvider"].return_value.provide.assert_not_called()
    if stage not in ("TRANSFORM", "LOAD"):
        run.constructors["TransformService"].return_value.transform.assert_not_called()


@pytest.mark.parametrize("extract_fails", [False, True])
def test_quit_failure(run: Run, extract_fails: bool) -> None:
    cleanup_error = RuntimeError("Ошибка закрытия")
    extract_error = ExtractError("Ошибка извлечения")
    run.driver.quit.side_effect = cleanup_error
    if extract_fails:
        run.constructors["ExtractService"].return_value.extract.side_effect = extract_error
    expected = extract_error if extract_fails else cleanup_error
    with pytest.raises(type(expected)) as caught:
        run.execute()
    assert caught.value is expected
    assert_failed(run, "EXTRACT", expected)
    run.driver.quit.assert_called_once_with()
    run.constructors["TransformService"].return_value.transform.assert_not_called()
    assert not (run.directory / "extract_result.json").exists()


@pytest.mark.parametrize(
    "broken_log, broken_manifest", [(True, False), (False, True), (True, True)]
)
def test_secondary_failure(
    run: Run, monkeypatch: pytest.MonkeyPatch, broken_log: bool, broken_manifest: bool
) -> None:
    primary = TransformError("Первичная ошибка")
    run.constructors["TransformService"].return_value.transform.side_effect = primary
    original = module.log_event

    def fail_log(logger: logging.Logger, level: int, event: str, **details: Any) -> None:
        if event == "sync_failed" and broken_log:
            raise OSError("Ошибка диагностики")
        original(logger, level, event, **details)

    monkeypatch.setattr(module, "log_event", fail_log)
    if broken_manifest:
        monkeypatch.setattr(
            RunArtifactStore, "mark_failed", Mock(side_effect=OSError("Ошибка записи"))
        )
    with pytest.raises(TransformError) as caught:
        run.execute()
    assert caught.value is primary
    run.store.mark_failed.assert_called_once_with(RunStage.TRANSFORM, "TransformError")
    if not broken_manifest:
        assert_failed(run, "TRANSFORM", primary)
    if not broken_log:
        assert "sync_failed" in run.log()


def test_logging_setup_failure(run: Run) -> None:
    error = OSError("Ошибка файла")
    run.configured.side_effect = error
    with pytest.raises(module.LoggingInitializationError) as caught:
        run.execute()
    assert caught.value.__cause__ is error
    assert_failed(run, "INITIALIZATION", caught.value)
    run.constructors["CrmProvider"].assert_not_called()


@pytest.mark.parametrize(
    "stage", [RunStage.CRM_CONTEXT, RunStage.EXTRACT, RunStage.TRANSFORM, RunStage.LOAD]
)
def test_mark_stage_failure(run: Run, monkeypatch: pytest.MonkeyPatch, stage: RunStage) -> None:
    original = RunArtifactStore.mark_stage
    error = RunArtifactError("Ошибка перехода стадии")

    def mark(store: RunArtifactStore, target: RunStage) -> None:
        if target == stage:
            raise error
        original(store, target)

    monkeypatch.setattr(RunArtifactStore, "mark_stage", mark)
    with pytest.raises(RunArtifactError) as caught:
        run.execute()
    assert caught.value is error
    assert_failed(run, stage.value, error)
    assert ("stage_started", stage.value) not in run.events


def test_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = Mock()
    orchestrator = Mock()
    monkeypatch.setattr(main_module, "RuntimePaths", paths)
    monkeypatch.setattr(main_module, "SyncOrchestrator", orchestrator)
    main_module.main()
    paths.from_project.assert_called_once_with(start=Path(main_module.__file__))
    orchestrator.assert_called_once_with()
    orchestrator.return_value.run.assert_called_once_with(paths.from_project.return_value)
    project = Path(main_module.__file__).parents[2] / "pyproject.toml"
    assert tomli.loads(project.read_text(encoding="utf-8"))["project"]["scripts"] == {
        "nashdom-sync": "nashdom_sync.main:main"
    }


def test_components_created_before_settings_work(run: Run) -> None:
    def provide() -> SyncSettings:
        for name in ("SettingsProvider", "BrowserProvider", "ExtractService", "TransformService"):
            run.constructors[name].assert_called_once()
        run.constructors["CrmProvider"].assert_not_called()
        return run.settings

    run.constructors["SettingsProvider"].return_value.provide.side_effect = provide
    run.execute()


def test_run_directory_failure_preserves_original(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = OSError("Ошибка каталога")
    monkeypatch.setattr(run.paths, "create_run_dir", Mock(side_effect=error))
    with pytest.raises(OSError) as caught:
        run.execute()
    assert caught.value is error
    run.constructors["SettingsProvider"].assert_not_called()


def test_artifact_start_failure_preserves_original(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = RunArtifactError("Ошибка начала хранения")
    monkeypatch.setattr(module, "RunArtifactStore", Mock(start=Mock(side_effect=error)))
    with pytest.raises(RunArtifactError) as caught:
        run.execute()
    assert caught.value is error
    run.constructors["SettingsProvider"].assert_not_called()


def test_regular_log_failure_is_primary(run: Run, monkeypatch: pytest.MonkeyPatch) -> None:
    error = OSError("Ошибка записи события")
    original = module.log_event

    def write(logger: logging.Logger, level: int, event: str, **details: Any) -> None:
        if event == "stage_completed" and details["stage"] == "CRM_CONTEXT":
            raise error
        original(logger, level, event, **details)

    monkeypatch.setattr(module, "log_event", write)
    with pytest.raises(OSError) as caught:
        run.execute()
    assert caught.value is error
    assert_failed(run, "CRM_CONTEXT", error)
    run.constructors["BrowserProvider"].return_value.provide.assert_not_called()


@pytest.mark.parametrize(
    "status", [OperationStatus.FAILED, OperationStatus.UNKNOWN, OperationStatus.BLOCKED]
)
def test_partial_load_saved_before_failure(run: Run, status: OperationStatus) -> None:
    result = LoadResult((OperationResult("operation", status),))
    run.constructors["LoadService"].return_value.load.return_value = result
    with pytest.raises(LoadIncompleteError) as caught:
        run.execute()
    assert_failed(run, "LOAD", caught.value)
    store = RunArtifactStore(run.directory, Mock())
    assert store.load_load_result() == result
    assert run.store.save_load_result.call_args.args[0] is result
    names = [item[0] for item in run.store.mock_calls]
    assert names.index("save_load_result") < names.index("mark_failed")
    run.store.mark_completed.assert_not_called()
    assert ("stage_completed", "LOAD") not in run.events
    assert "Не все операции плана синхронизации выполнены успешно" == str(caught.value)


def test_load_infrastructure_failure(run: Run) -> None:
    error = BitrixGatewayError("Секретный payload")
    run.constructors["LoadService"].return_value.load.side_effect = error
    with pytest.raises(BitrixGatewayError) as caught:
        run.execute()
    assert caught.value is error
    assert_failed(run, "LOAD", error)
    assert not (run.directory / "load_result.json").exists()
    run.store.mark_completed.assert_not_called()
    assert "Секретный payload" not in run.log()


def test_load_constructed_in_initialization_and_called_only_in_load(run: Run) -> None:
    def create(settings: Any) -> Mock:
        assert run.manifest()["stage"] == "INITIALIZATION"
        assert settings is run.settings.bitrix
        return service

    def execute(plan: SyncPlan) -> LoadResult:
        assert run.manifest()["stage"] == "LOAD"
        assert (run.directory / "sync_plan.json").is_file()
        return LoadResult(())

    service = run.constructors["LoadService"].return_value
    service.load.side_effect = execute
    run.constructors["LoadService"].side_effect = create
    run.execute()


@pytest.mark.parametrize("outcome", ["empty", "success", "partial", "infrastructure"])
def test_orchestrator_with_real_load_and_fake_crm(
    run: Run, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    monkeypatch.setattr(module, "LoadService", LoadService)
    client = Mock(spec=ClientBitrixCRM)
    monkeypatch.setattr(load_module, "ClientBitrixCRM", Mock(return_value=client))
    secret = "Секретный адрес и телефон"
    command = AddItemCommand(4, {"TITLE": secret})
    plan = (
        SyncPlan(())
        if outcome == "empty"
        else SyncPlan(
            (
                PlannedOperation("first", command),
                PlannedOperation("dependent", command, (RuntimeBinding("OWNER", "first"),)),
                PlannedOperation("independent", command),
            )
        )
    )
    run.constructors["TransformService"].return_value.transform.return_value = TransformResult(plan)
    if outcome == "partial":
        client.add_item.side_effect = [BitrixRequestFailedError(secret), 303]
    elif outcome == "infrastructure":
        client.add_item.side_effect = BitrixGatewayError(secret)
    else:
        client.add_item.side_effect = [101, 202, 303]
    if outcome in ("empty", "success"):
        run.execute()
        assert run.manifest()["status"] == "COMPLETED"
    else:
        expected = LoadIncompleteError if outcome == "partial" else BitrixGatewayError
        with pytest.raises(expected) as caught:
            run.execute()
        assert_failed(run, "LOAD", caught.value)
        assert secret not in str(caught.value) if outcome == "partial" else True
    assert run.manifest()["stage"] == "LOAD"
    assert secret not in run.log()
    client.close.assert_called_once_with()
    if outcome == "infrastructure":
        assert not (run.directory / "load_result.json").exists()
        client.add_item.assert_called_once()
    else:
        saved = RunArtifactStore(run.directory, Mock()).load_load_result()
        assert tuple(r.operation_id for r in saved.operations) == tuple(
            op.operation_id for op in plan.operations
        )
        assert saved.is_successful is (outcome != "partial")
        if outcome == "partial":
            assert saved.operations[1].blocked_by == ("first",)
            assert client.add_item.call_count == 2
        elif outcome == "empty":
            client.add_item.assert_not_called()
        else:
            assert saved.operations[1].crm_id == 202
            assert client.add_item.call_args_list[1].args == (4, {"TITLE": secret, "OWNER": 101})


def test_load_result_save_failure_takes_priority_over_partial_result(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    run.constructors["LoadService"].return_value.load.return_value = LoadResult(
        (OperationResult("failed", OperationStatus.FAILED),)
    )
    error = RunArtifactError("Ошибка сохранения результата")
    monkeypatch.setattr(RunArtifactStore, "save_load_result", Mock(side_effect=error))
    with pytest.raises(RunArtifactError) as caught:
        run.execute()
    assert caught.value is error
    assert_failed(run, "LOAD", error)
    run.store.mark_completed.assert_not_called()


def test_load_disabled_runs_through_transform(run: Run) -> None:
    data = run.settings.dict()
    data["execution"] = {"load_enabled": False}
    run.settings = SyncSettings.parse_obj(data)
    run.constructors["SettingsProvider"].return_value.provide.return_value = run.settings
    run.constructors["LoadService"].side_effect = AssertionError("Load не должен создаваться")
    run.execute()

    assert {p.name for p in run.directory.iterdir()} == {
        "run.json", "nashdom_sync.log", "crm_context.json", "extract_result.json", "sync_plan.json"
    }
    assert not (run.directory / "load_result.json").exists()
    assert run.manifest()["status"] == "COMPLETED"
    assert run.manifest()["stage"] == "TRANSFORM"
    assert run.manifest()["finished_at"] is not None
    assert run.manifest()["error_type"] is None
    run.constructors["LoadService"].assert_not_called()
    run.constructors["LoadService"].return_value.load.assert_not_called()
    run.store.save_load_result.assert_not_called()
    run.store.mark_completed.assert_called_once_with()
    run.store.mark_failed.assert_not_called()
    run.constructors["CrmProvider"].return_value.provide.assert_called_once_with(run.settings.region)
    run.constructors["BrowserProvider"].return_value.provide.assert_called_once_with(
        run.settings.browser
    )
    run.constructors["ExtractService"].return_value.extract.assert_called_once_with(
        run.driver, run.settings.extract
    )
    source_result = run.constructors["ExtractService"].return_value.extract.return_value
    crm_result = run.constructors["CrmProvider"].return_value.provide.return_value
    run.constructors["TransformService"].return_value.transform.assert_called_once_with(
        source_result, crm_result, run.settings.region
    )
    run.store.save_crm_context.assert_called_once_with(crm_result)
    run.store.save_extract_result.assert_called_once_with(source_result)
    run.store.save_sync_plan.assert_called_once_with(
        run.constructors["TransformService"].return_value.transform.return_value.plan
    )
    run.driver.quit.assert_called_once_with()
    assert [call.args[0] for call in run.store.mark_stage.call_args_list] == [
        RunStage.CRM_CONTEXT, RunStage.EXTRACT, RunStage.TRANSFORM
    ]
    expected = [("sync_started", "INITIALIZATION")]
    for stage in ("INITIALIZATION", "CRM_CONTEXT", "EXTRACT", "TRANSFORM"):
        expected.extend([("stage_started", stage), ("stage_completed", stage)])
    expected.extend([("load_skipped", "TRANSFORM"), ("sync_completed", "TRANSFORM")])
    expected.insert(4, ("crm_context_source", "CRM_CONTEXT"))
    assert run.events == expected
    lines = run.log().splitlines()
    skipped = next(line for line in lines if "load_skipped" in line)
    assert "reason=disabled_by_configuration" in skipped
    assert "INFO" in skipped
    assert "stage=LOAD" not in run.log()


@pytest.mark.parametrize("enabled, cache_state", [
    (False, "valid"), (False, "missing"), (False, "invalid"),
    (True, "valid"), (True, "invalid"),
])
def test_crm_cache_policy(
    run: Run, monkeypatch: pytest.MonkeyPatch, enabled: bool, cache_state: str
) -> None:
    from nashdom_sync.providers.crm_context_cache import CrmContextCache, CrmContextCacheError
    from nashdom_sync.run_artifacts.serialization import encode

    data = run.settings.dict()
    data["execution"] = {"load_enabled": enabled}
    run.settings = SyncSettings.parse_obj(data)
    run.constructors["SettingsProvider"].return_value.provide.return_value = run.settings
    path = run.paths.program_data_file("crm_context.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = context()
    if cache_state != "missing":
        path.write_text(
            json.dumps({"schema_version": 1, "data": encode(expected)})
            if cache_state == "valid" else "SECRET_PAYLOAD",
            encoding="utf-8",
        )
    cache = CrmContextCache(path)
    spy = Mock(wraps=cache)
    constructor = Mock(return_value=spy)
    monkeypatch.setattr(module, "CrmContextCache", constructor)
    provider = run.constructors["CrmProvider"].return_value.provide
    if not enabled and cache_state == "invalid":
        with pytest.raises(CrmContextCacheError) as caught:
            run.execute()
        assert_failed(run, "CRM_CONTEXT", caught.value)
        assert caught.value.__cause__ is not None
        assert "SECRET_PAYLOAD" not in str(caught.value)
        assert "SECRET_PAYLOAD" not in run.log()
        provider.assert_not_called()
        spy.load.assert_called_once_with()
        run.store.save_crm_context.assert_not_called()
        return
    run.execute()
    constructor.assert_called_once_with(path)
    if enabled:
        spy.exists.assert_not_called()
        spy.load.assert_not_called()
    else:
        spy.exists.assert_called_once_with()
    if not enabled and cache_state == "valid":
        spy.load.assert_called_once_with()
        provider.assert_not_called()
        chosen = expected
        assert "source=cache" in run.log()
        assert "crm_provider_started" not in run.log()
        assert "crm_provider_completed" not in run.log()
    else:
        spy.load.assert_not_called()
        provider.assert_called_once_with(run.settings.region)
        chosen = provider.return_value
        assert "source=api" in run.log()
    run.store.save_crm_context.assert_called_once_with(chosen)
    assert RunArtifactStore(run.directory, Mock()).load_crm_context() == chosen
    envelope = json.loads((run.directory / "crm_context.json").read_text(encoding="utf-8"))
    assert envelope == {"schema_version": 1, "data": encode(chosen)}
    run.constructors["ExtractService"].return_value.extract.assert_called_once()
    run.constructors["TransformService"].return_value.transform.assert_called_once_with(
        run.constructors["ExtractService"].return_value.extract.return_value,
        chosen, run.settings.region,
    )
    assert run.manifest()["status"] == "COMPLETED"
    assert run.manifest()["stage"] == ("LOAD" if enabled else "TRANSFORM")
    assert ("crm_context_source", "CRM_CONTEXT") in run.events

@pytest.mark.parametrize("use_cache", [False, True])
def test_extract_session_restart(
    run: Run, monkeypatch: pytest.MonkeyPatch, use_cache: bool
) -> None:
    second = Mock()
    provide = run.constructors["BrowserProvider"].return_value.provide
    provide.side_effect = [run.driver, second]
    run.driver.quit.side_effect = RuntimeError("SECRET cleanup")
    pause = Mock()
    monkeypatch.setattr(module, "sleep", pause)
    cache = Mock()
    cache.exists.return_value = True
    cache.load.return_value = context()
    if use_cache:
        data = run.settings.dict()
        data["execution"] = {"load_enabled": False}
        run.settings = SyncSettings.parse_obj(data)
        run.constructors["SettingsProvider"].return_value.provide.return_value = run.settings
        monkeypatch.setattr(module, "CrmContextCache", Mock(return_value=cache))
    calls: List[Mock] = []

    def extract(driver: Any, settings: Any) -> Any:
        assert settings is run.settings.extract
        assert run.manifest()["stage"] == "EXTRACT"
        assert not (run.directory / "extract_result.json").exists()
        run.store.save_extract_result.assert_not_called()
        run.constructors["TransformService"].return_value.transform.assert_not_called()
        run.constructors["LoadService"].return_value.load.assert_not_called()
        calls.append(driver)
        if len(calls) == 1:
            raise BrowserSessionUnavailableError("SECRET failed session")
        return source()

    extract_mock = run.constructors["ExtractService"].return_value.extract
    extract_mock.side_effect = extract
    run.execute()
    assert calls == [run.driver, second]
    assert provide.call_count == extract_mock.call_count == 2
    run.driver.quit.assert_called_once_with()
    second.quit.assert_called_once_with()
    pause.assert_called_once_with(10.0)
    run.store.save_extract_result.assert_called_once_with(source())
    run.constructors["TransformService"].return_value.transform.assert_called_once()
    if use_cache:
        cache.exists.assert_called_once_with()
        cache.load.assert_called_once_with()
        run.constructors["CrmProvider"].return_value.provide.assert_not_called()
        run.constructors["LoadService"].assert_not_called()
    else:
        run.constructors["CrmProvider"].return_value.provide.assert_called_once()
        run.constructors["LoadService"].return_value.load.assert_called_once()
    assert run.events.count(("browser_session_restart", "EXTRACT")) == 1
    restart_line = next(line for line in run.log().splitlines() if "browser_session_restart" in line)
    for field in ("attempt=2", "max_attempts=2", "retry_delay_seconds=10.0", "reason=browser_session_unavailable"):
        assert field in restart_line
    assert "SECRET" not in run.log()
    assert run.manifest()["status"] == "COMPLETED"


def test_session_attempts_exhausted(run: Run, monkeypatch: pytest.MonkeyPatch) -> None:
    second = Mock()
    provide = run.constructors["BrowserProvider"].return_value.provide
    provide.side_effect = [run.driver, second]
    first_error = BrowserSessionUnavailableError("first")
    last_error = BrowserSessionUnavailableError("last")
    run.constructors["ExtractService"].return_value.extract.side_effect = [first_error, last_error]
    second.quit.side_effect = RuntimeError("cleanup")
    pause = Mock()
    monkeypatch.setattr(module, "sleep", pause)
    with pytest.raises(BrowserSessionUnavailableError) as caught:
        run.execute()
    assert caught.value is last_error
    assert_failed(run, "EXTRACT", last_error)
    assert provide.call_count == 2
    run.driver.quit.assert_called_once_with()
    second.quit.assert_called_once_with()
    pause.assert_called_once_with(10.0)
    run.constructors["TransformService"].return_value.transform.assert_not_called()
    run.constructors["LoadService"].return_value.load.assert_not_called()
    run.store.save_extract_result.assert_not_called()
    assert not (run.directory / "extract_result.json").exists()
    assert run.events.count(("browser_session_restart", "EXTRACT")) == 1


@pytest.mark.parametrize(
    "error", [NashDomClientError("contract"), SourceDataValidationError("missing region")]
)
def test_domain_failure_never_restarts_session(run: Run, error: Exception) -> None:
    run.constructors["ExtractService"].return_value.extract.side_effect = error
    with pytest.raises(type(error)) as caught:
        run.execute()
    assert caught.value is error
    assert_failed(run, "EXTRACT", error)
    run.constructors["BrowserProvider"].return_value.provide.assert_called_once()
    assert ("browser_session_restart", "EXTRACT") not in run.events


def test_launch_failure_is_not_retried_by_orchestrator(run: Run) -> None:
    error = BrowserLaunchError(Path("chrome"), Path("driver"))
    provide = run.constructors["BrowserProvider"].return_value.provide
    provide.side_effect = error
    with pytest.raises(BrowserLaunchError) as caught:
        run.execute()
    assert caught.value is error
    provide.assert_called_once()
    run.constructors["ExtractService"].return_value.extract.assert_not_called()
    assert_failed(run, "EXTRACT", error)



def test_one_configured_session_disables_restart(run: Run, monkeypatch: pytest.MonkeyPatch) -> None:
    data = run.settings.dict()
    data["browser"]["extract_session_max_attempts"] = 1
    run.settings = SyncSettings.parse_obj(data)
    run.constructors["SettingsProvider"].return_value.provide.return_value = run.settings
    pause = Mock()
    monkeypatch.setattr(module, "sleep", pause)
    error = BrowserSessionUnavailableError("failed")
    run.constructors["ExtractService"].return_value.extract.side_effect = error
    with pytest.raises(BrowserSessionUnavailableError) as caught:
        run.execute()
    assert caught.value is error
    run.constructors["BrowserProvider"].return_value.provide.assert_called_once()
    run.driver.quit.assert_called_once_with()
    pause.assert_not_called()
    assert ("browser_session_restart", "EXTRACT") not in run.events
    assert_failed(run, "EXTRACT", error)
