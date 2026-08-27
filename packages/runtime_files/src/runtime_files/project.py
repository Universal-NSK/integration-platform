from pathlib import Path
from typing import Optional

from runtime_files.errors import ProjectRootNotFoundError

_PROJECT_ROOT_MARKER = ".projectroot"


def find_project_root(
    start: Path,
    fallback_root: Optional[Path] = None,
) -> Path:
    """Find the marked project root above start or return an explicit fallback."""
    resolved_start = start.resolve()
    current = resolved_start.parent if resolved_start.is_file() else resolved_start

    while True:
        if (current / _PROJECT_ROOT_MARKER).is_file():
            return current

        if current.parent == current:
            break

        current = current.parent

    if fallback_root is not None:
        if not fallback_root.is_absolute():
            raise ValueError("fallback_root must be an absolute path")
        return fallback_root

    raise ProjectRootNotFoundError(resolved_start)
