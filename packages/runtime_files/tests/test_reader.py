from pathlib import Path

import pytest
from runtime_files import (
    RuntimeFileNotFoundError,
    RuntimeFileReadError,
    read_text,
)


def test_read_text_reads_utf8(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"

    path.write_text(
        'message = "Привет"',
        encoding="utf-8",
    )

    result = read_text(path)

    assert result == 'message = "Привет"'


def test_read_text_raises_runtime_file_not_found(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing.toml"

    with pytest.raises(RuntimeFileNotFoundError) as exc_info:
        read_text(path)

    assert exc_info.value.path == path


def test_read_text_wraps_os_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"

    def fail_read_text(
        self: Path,
        encoding: str,
    ) -> str:
        raise PermissionError("Access denied")

    monkeypatch.setattr(
        Path,
        "read_text",
        fail_read_text,
    )

    with pytest.raises(RuntimeFileReadError) as exc_info:
        read_text(path)

    assert exc_info.value.path == path


def test_read_text_wraps_unicode_decode_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"\xff")

    with pytest.raises(RuntimeFileReadError) as exc_info:
        read_text(path)

    assert exc_info.value.path == path
    assert isinstance(exc_info.value.__cause__, UnicodeDecodeError)
