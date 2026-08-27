import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List

import platform_logging.setup as platform_setup
import pytest
from platform_logging import LoggingConfig, configure_logging, log_event
from runtime_files import RuntimePaths


def _paths(tmp_path: Path) -> RuntimePaths:
    return RuntimePaths(
        repo_root=tmp_path / "repository",
        program_data_root=tmp_path / "program-data",
    )


def _config(*, console: bool = False) -> LoggingConfig:
    return LoggingConfig(
        level="INFO",
        console=console,
        log_payloads=True,
        max_bytes=100_000,
        backup_count=2,
    )


def _flush(logger_name: str) -> None:
    for handler in logging.getLogger(logger_name).handlers:
        handler.flush()


def _handler_kind(handler: logging.Handler) -> str:
    return str(handler.__dict__.get("_platform_logging_kind"))


def test_log_directory_and_collision_safe_name_are_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime(2026, 8, 27, 20, 31, 14)
    monkeypatch.setattr(platform_setup, "_current_time", lambda: started_at)
    paths = _paths(tmp_path)

    first = configure_logging("bitrix_gateway", "test.naming", paths, _config())
    second = configure_logging("bitrix_gateway", "test.naming", paths, _config())

    expected_dir = tmp_path / "program-data" / "logs" / "bitrix_gateway"
    assert first.log_file.parent == expected_dir
    assert first.log_file.name == "bitrix_gateway_2026-08-27_20-31-14.log"
    assert second.log_file.name == "bitrix_gateway_2026-08-27_20-31-14_2.log"
    assert first.log_file.is_file()
    assert second.log_file.is_file()
    assert re.fullmatch(
        r"bitrix_gateway_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:_\d+)?\.log",
        second.log_file.name,
    )


def test_standard_and_structured_events_are_utf8_single_lines(tmp_path: Path) -> None:
    session = configure_logging("basic_service", "test.basic", _paths(tmp_path), _config())
    logger = logging.getLogger("test.basic")

    logger.info("gateway_started")
    log_event(
        logger,
        logging.INFO,
        "request_succeeded",
        metadata={"ids": [1, 2]},
        note="первая строка\nвторая строка",
        title="ООО Ромашка",
    )
    _flush("test.basic")

    lines = session.log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert " | INFO | test.basic | - | gateway_started | -" in lines[0]
    assert "request_succeeded" in lines[1]
    assert 'metadata={"ids":[1,2]}' in lines[1]
    assert 'note="первая строка\\nвторая строка"' in lines[1]
    assert 'title="ООО Ромашка"' in lines[1]
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \|", lines[0])


def test_console_handler_is_optional(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("console_on", "test.console_on", _paths(tmp_path), _config(console=True))
    capsys.readouterr()

    log_event(logging.getLogger("test.console_on"), "INFO", "console_event")
    _flush("test.console_on")

    captured = capsys.readouterr()
    assert " | INFO | test.console_on | - | console_event | -" in captured.err


def test_console_false_adds_no_package_console_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("console_off", "test.console_off", _paths(tmp_path), _config())
    capsys.readouterr()

    log_event(logging.getLogger("test.console_off"), logging.INFO, "file_only_event")
    _flush("test.console_off")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_reconfigure_replaces_owned_handlers_without_duplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        platform_setup,
        "_current_time",
        lambda: datetime(2026, 8, 27, 20, 31, 14),
    )
    config = _config(console=True)
    first = configure_logging("reconfigure", "test.reconfigure", _paths(tmp_path), config)
    logger = logging.getLogger("test.reconfigure")
    old_file_handler = next(
        handler
        for handler in logger.handlers
        if getattr(handler, "_platform_logging_kind", None) == "file"
    )

    second = configure_logging("reconfigure", "test.reconfigure", _paths(tmp_path), config)
    owned_kinds: List[str] = [
        _handler_kind(handler)
        for handler in logger.handlers
        if getattr(handler, "_platform_logging_owned", False) is True
    ]

    assert sorted(owned_kinds) == ["console", "file"]
    assert old_file_handler not in logger.handlers
    assert getattr(old_file_handler, "stream", None) is None

    log_event(logger, logging.INFO, "configured_once")
    _flush("test.reconfigure")

    assert first.log_file.read_text(encoding="utf-8") == ""
    assert second.log_file.read_text(encoding="utf-8").count("configured_once") == 1


def test_foreign_handlers_are_preserved_during_reconfigure(tmp_path: Path) -> None:
    logger = logging.getLogger("test.foreign_handler")
    foreign_handler = logging.NullHandler()
    logger.addHandler(foreign_handler)

    try:
        configure_logging("foreign_handler", logger.name, _paths(tmp_path), _config())
        configure_logging("foreign_handler", logger.name, _paths(tmp_path), _config())

        assert foreign_handler in logger.handlers
    finally:
        logger.removeHandler(foreign_handler)
        foreign_handler.close()


def test_child_namespace_is_logged_but_external_namespace_is_isolated(tmp_path: Path) -> None:
    session = configure_logging("namespace", "test.namespace", _paths(tmp_path), _config())

    log_event(logging.getLogger("test.namespace.dispatch"), logging.INFO, "child_event")
    logging.getLogger("some_external_library").warning("external_event")
    _flush("test.namespace")

    content = session.log_file.read_text(encoding="utf-8")
    assert "test.namespace.dispatch" in content
    assert "child_event" in content
    assert "some_external_library" not in content
    assert "external_event" not in content


def test_root_logger_is_not_reconfigured(tmp_path: Path) -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    configure_logging("root_isolation", "test.root_isolation", _paths(tmp_path), _config())

    assert root_logger.handlers == original_handlers
    assert root_logger.level == original_level


def test_logger_exception_keeps_traceback(tmp_path: Path) -> None:
    session = configure_logging("traceback", "test.traceback", _paths(tmp_path), _config())
    logger = logging.getLogger("test.traceback")

    try:
        raise ValueError("broken payload")
    except ValueError:
        logger.exception("request_failed")
    _flush("test.traceback")

    content = session.log_file.read_text(encoding="utf-8")
    assert "request_failed" in content
    assert "Traceback (most recent call last):" in content
    assert "ValueError: broken payload" in content


@pytest.mark.parametrize("level", ["", "VERBOSE", "not-a-level"])
def test_invalid_logging_level_is_rejected(level: str) -> None:
    with pytest.raises(ValueError, match="level|logging level"):
        LoggingConfig(
            level=level,
            console=False,
            log_payloads=False,
            max_bytes=1,
            backup_count=0,
        )


@pytest.mark.parametrize("max_bytes", [0, -1])
def test_non_positive_max_bytes_is_rejected(max_bytes: int) -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        LoggingConfig(
            level="INFO",
            console=False,
            log_payloads=False,
            max_bytes=max_bytes,
            backup_count=0,
        )


def test_negative_backup_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="backup_count"):
        LoggingConfig(
            level="INFO",
            console=False,
            log_payloads=False,
            max_bytes=1,
            backup_count=-1,
        )


@pytest.mark.parametrize(
    "service_name",
    ["", ".", "..", "../service", r"data\service", "bad service", "CON"],
)
def test_unsafe_service_name_is_rejected(tmp_path: Path, service_name: str) -> None:
    with pytest.raises(ValueError, match="service_name"):
        configure_logging(service_name, "test.validation", _paths(tmp_path), _config())


@pytest.mark.parametrize(
    "logger_name",
    ["", ".root", "root.", "root..child", "bad/name", r"bad\name", "bad name"],
)
def test_unsafe_logger_name_is_rejected(tmp_path: Path, logger_name: str) -> None:
    with pytest.raises(ValueError, match="logger_name"):
        configure_logging("validation", logger_name, _paths(tmp_path), _config())
