import logging
from pathlib import Path

from platform_logging import LoggingConfig, configure_logging, log_event, with_context
from runtime_files import RuntimePaths


def test_context_is_bound_per_adapter_and_children_share_service_file(tmp_path: Path) -> None:
    paths = RuntimePaths(
        repo_root=tmp_path / "repository",
        program_data_root=tmp_path / "program-data",
    )
    config = LoggingConfig(
        level="INFO",
        console=False,
        log_payloads=True,
        max_bytes=100_000,
        backup_count=1,
    )
    session = configure_logging("context", "test.context", paths, config)
    first = with_context(
        logging.getLogger("test.context.dispatch"),
        job_id="job-a",
        method="crm.company.add",
        attempt=1,
        source="etl-a",
    )
    second = with_context(
        logging.getLogger("test.context.execution"),
        job_id="job-b",
        method="crm.contact.update",
        attempt=2,
    )

    log_event(first, logging.INFO, "first_job", queue_size=1)
    log_event(second, logging.INFO, "second_job", queue_size=2)
    log_event(logging.getLogger("test.context.transport"), logging.INFO, "child_event")
    for handler in logging.getLogger("test.context").handlers:
        handler.flush()

    lines = session.log_file.read_text(encoding="utf-8").splitlines()
    first_line = next(line for line in lines if "first_job" in line)
    second_line = next(line for line in lines if "second_job" in line)
    child_line = next(line for line in lines if "child_event" in line)

    assert "job_id=job-a" in first_line
    assert "method=crm.company.add" in first_line
    assert "attempt=1" in first_line
    assert "source=etl-a" in first_line
    assert "queue_size=1" in first_line
    assert "job-b" not in first_line

    assert "job_id=job-b" in second_line
    assert "method=crm.contact.update" in second_line
    assert "attempt=2" in second_line
    assert "job-a" not in second_line

    assert "test.context.transport" in child_line
    assert " | - | child_event | -" in child_line
