from pathlib import Path


class RuntimeFileError(Exception):
    """Base error for runtime file access."""

    def __init__(
        self,
        path: Path,
        message: str,
    ) -> None:
        self.path = path
        super().__init__(f"{message}: {path}")


class ProjectRootNotFoundError(RuntimeFileError):
    """Raised when the project root marker cannot be found."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            path,
            "Project root marker '.projectroot' not found from",
        )


class RuntimeFileNotFoundError(RuntimeFileError):
    def __init__(
        self,
        path: Path,
    ) -> None:
        super().__init__(
            path,
            "Runtime file not found",
        )


class RuntimeFileReadError(RuntimeFileError):
    def __init__(
        self,
        path: Path,
        reason: str,
    ) -> None:
        super().__init__(
            path,
            f"Failed to read runtime file ({reason})",
        )
