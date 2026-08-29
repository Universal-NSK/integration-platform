import os
from pathlib import Path
from typing import Optional

from runtime_files.project import find_project_root


class RuntimePaths:
    def __init__(
        self,
        repo_root: Path,
        program_data_root: Optional[Path] = None,
    ) -> None:
        self._repo_root = self._require_absolute(
            repo_root,
            "repo_root",
        )

        if program_data_root is None:
            self._program_data_root = self._default_program_data_root()
        else:
            self._program_data_root = self._require_absolute(
                program_data_root,
                "program_data_root",
            )

    @classmethod
    def from_project(
        cls,
        start: Path,
        fallback_root: Optional[Path] = None,
        program_data_root: Optional[Path] = None,
    ) -> "RuntimePaths":
        return cls(
            repo_root=find_project_root(
                start=start,
                fallback_root=fallback_root,
            ),
            program_data_root=program_data_root,
        )

    def config_file(
        self,
        name: str,
    ) -> Path:
        self._validate_file_name(name)

        return self._repo_root / "config" / name

    def program_data_file(
        self,
        name: str,
    ) -> Path:
        self._validate_file_name(name)

        return self._program_data_root / name

    def program_data_dir(
        self,
        name: str,
    ) -> Path:
        """Return a direct child directory of the Integration Platform data root."""
        self._validate_directory_name(name)

        return self._program_data_root / name

    def program_data_path(
        self,
        relative_path: Path,
    ) -> Path:
        """Разрешить вложенный путь внутри корня ProgramData платформы."""
        if relative_path.is_absolute():
            raise ValueError("Expected a relative ProgramData path")

        root = self._program_data_root.resolve()
        candidate = (root / relative_path).resolve()

        if candidate == root:
            raise ValueError("Expected a child path inside ProgramData root")

        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("ProgramData path must stay inside its root") from exc

        return candidate

    @staticmethod
    def _default_program_data_root() -> Path:
        program_data = os.environ.get("PROGRAMDATA")

        if not program_data:
            raise RuntimeError("PROGRAMDATA environment variable is not set")

        root = Path(program_data)

        if not root.is_absolute():
            raise RuntimeError("PROGRAMDATA must contain an absolute path")

        return root / "Universal" / "IntegrationPlatform"

    @staticmethod
    def _require_absolute(
        path: Path,
        parameter_name: str,
    ) -> Path:
        if not path.is_absolute():
            raise ValueError(f"{parameter_name} must be an absolute path")

        return path

    @staticmethod
    def _validate_file_name(
        name: str,
    ) -> None:
        if not name:
            raise ValueError("File name cannot be empty")

        if name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError("Expected a file name, not a path")

    @staticmethod
    def _validate_directory_name(
        name: str,
    ) -> None:
        if not name:
            raise ValueError("Directory name cannot be empty")

        if name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError("Expected a directory name, not a path")
