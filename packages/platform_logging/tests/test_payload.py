import logging
from pathlib import Path

from platform_logging import (
    LoggingConfig,
    configure_logging,
    log_event,
    log_payload,
    with_context,
)
from runtime_files import RuntimePaths


def _configure(tmp_path: Path, *, log_payloads: bool = True) -> Path:
    paths = RuntimePaths(
        repo_root=tmp_path / "repository",
        program_data_root=tmp_path / "program-data",
    )
    config = LoggingConfig(
        level="INFO",
        console=False,
        log_payloads=log_payloads,
        max_bytes=100_000,
        backup_count=1,
    )
    return configure_logging("payload", "test.payload", paths, config).log_file


def _flush() -> None:
    for handler in logging.getLogger("test.payload").handlers:
        handler.flush()


def test_nested_payload_is_complete_compact_utf8_json(tmp_path: Path) -> None:
    log_file = _configure(tmp_path)
    logger = with_context(logging.getLogger("test.payload.transport"), job_id="a812")
    payload = {
        "fields": {"TITLE": "ООО Ромашка", "INN": "123"},
        "items": [1, {"active": True, "tags": ["новый", "важный"]}],
    }

    log_payload(
        logger,
        logging.INFO,
        "request_payload",
        payload,
        enabled=True,
        direction="outgoing",
    )
    _flush()

    content = log_file.read_text(encoding="utf-8")
    assert "job_id=a812" in content
    assert "request_payload" in content
    assert "direction=outgoing" in content
    assert (
        'payload={"fields":{"TITLE":"ООО Ромашка","INN":"123"},'
        '"items":[1,{"active":true,"tags":["новый","важный"]}]}' in content
    )
    assert "\\u041e" not in content


def test_response_can_use_an_explicit_field_name(tmp_path: Path) -> None:
    log_file = _configure(tmp_path)

    log_payload(
        logging.getLogger("test.payload.transport"),
        "INFO",
        "response_payload",
        {"result": [7, 8], "status": "готово"},
        enabled=True,
        field_name="response",
    )
    _flush()

    content = log_file.read_text(encoding="utf-8")
    assert 'response={"result":[7,8],"status":"готово"}' in content


def test_disabled_payload_entry_is_skipped_but_events_continue(tmp_path: Path) -> None:
    log_file = _configure(tmp_path, log_payloads=False)
    logger = logging.getLogger("test.payload")

    log_payload(
        logger,
        logging.INFO,
        "request_payload",
        {"fields": {"TITLE": "Не писать"}},
        enabled=False,
    )
    log_event(logger, logging.INFO, "job_started")
    _flush()

    content = log_file.read_text(encoding="utf-8")
    assert "request_payload" not in content
    assert "Не писать" not in content
    assert "job_started" in content


def test_non_json_payload_never_raises_and_writes_safe_marker(tmp_path: Path) -> None:
    log_file = _configure(tmp_path)
    payload = {"valid": "data", "unsupported": {1, 2, 3}}

    log_payload(
        logging.getLogger("test.payload"),
        logging.INFO,
        "request_payload",
        payload,
        enabled=True,
    )
    _flush()

    content = log_file.read_text(encoding="utf-8")
    assert "request_payload" in content
    assert '"_platform_logging_error":"payload_not_json_serializable"' in content
    assert '"error_type":"TypeError"' in content
    assert '"object_type":"builtins.dict"' in content
    assert "{1, 2, 3}" not in content
