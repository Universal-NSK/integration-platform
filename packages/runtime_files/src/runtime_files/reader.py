from pathlib import Path

from runtime_files.errors import (
    RuntimeFileNotFoundError,
    RuntimeFileReadError,
)


def read_text(
    path: Path,
) -> str:
    try:
        return path.read_text(
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise RuntimeFileNotFoundError(path) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeFileReadError(
            path,
            str(exc),
        ) from exc
