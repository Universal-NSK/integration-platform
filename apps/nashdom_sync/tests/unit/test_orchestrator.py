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
from nashdom_sync.contracts import SyncSettings
from nashdom_sync.contracts.transform import SyncPlan, TransformResult
from nashdom_sync.extract import ExtractError
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
            "logging": {
                "level": "DEBUG",
                "console": False,
                "log_payloads": True,
                "max_bytes": 123456,
                "backup_count": 2,
            },
            "browser": {
                "headless": True,
                "browser_path": tmp_path / "chrome.exe",
                "driver_path": tmp_path / "driver.exe",
            },
            "bitrix": {"gateway_url": "http://example.invalid", "timeout": 2},
            "extract": {"nashdom": {"objects_to_parse_count": 1, "regions": []}},
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
    }
    assert run.manifest()["status"] == "COMPLETED"
    assert run.manifest()["stage"] == "TRANSFORM"
    assert run.manifest()["error_type"] is None
    assert run.manifest()["finished_at"] is not None
    expected = [("sync_started", "INITIALIZATION")]
    for stage in ("INITIALIZATION", "CRM_CONTEXT", "EXTRACT", "TRANSFORM"):
        expected.extend([("stage_started", stage), ("stage_completed", stage)])
    expected.append(("sync_completed", "TRANSFORM"))
    assert run.events == expected
    assert [call.args[0] for call in run.store.mark_stage.call_args_list] == [
        RunStage.CRM_CONTEXT,
        RunStage.EXTRACT,
        RunStage.TRANSFORM,
    ]
    run.driver.quit.assert_called_once_with()
    for constructor in run.constructors.values():
        constructor.assert_called_once()
    run.constructors["SettingsProvider"].assert_called_once_with(run.paths)
    run.constructors["CrmProvider"].assert_called_once_with(run.settings.bitrix)
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
    ["SettingsProvider", "BrowserProvider", "ExtractService", "TransformService", "CrmProvider"],
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
    if stage != "TRANSFORM":
        run.constructors["TransformService"].return_value.transform.assert_not_called()
    if component in ("CrmProvider", "BrowserProvider"):
        run.constructors["ExtractService"].return_value.extract.assert_not_called()
        run.driver.quit.assert_not_called()
    else:
        run.driver.quit.assert_called_once_with()
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
        ("mark_completed", "TRANSFORM"),
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
    if stage == "CRM_CONTEXT":
        run.constructors["BrowserProvider"].return_value.provide.assert_not_called()
    if stage != "TRANSFORM":
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


@pytest.mark.parametrize("stage", [RunStage.CRM_CONTEXT, RunStage.EXTRACT, RunStage.TRANSFORM])
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
