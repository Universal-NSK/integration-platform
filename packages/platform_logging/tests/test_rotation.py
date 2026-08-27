import logging
from pathlib import Path

from platform_logging import LoggingConfig, configure_logging, log_event
from runtime_files import RuntimePaths


def test_size_rotation_creates_and_limits_backups(tmp_path: Path) -> None:
    paths = RuntimePaths(
        repo_root=tmp_path / "repository",
        program_data_root=tmp_path / "program-data",
    )
    config = LoggingConfig(
        level="INFO",
        console=False,
        log_payloads=True,
        max_bytes=220,
        backup_count=2,
    )
    session = configure_logging("rotation", "test.rotation", paths, config)
    logger = logging.getLogger("test.rotation")

    for index in range(12):
        log_event(logger, logging.INFO, "rotation_event", index=index, value="x" * 80)
    for handler in logger.handlers:
        handler.flush()

    backups = sorted(session.log_file.parent.glob(f"{session.log_file.name}.*"))
    assert session.log_file.is_file()
    assert (session.log_file.parent / f"{session.log_file.name}.1").is_file()
    assert len(backups) == config.backup_count
    assert {path.suffix for path in backups} == {".1", ".2"}
