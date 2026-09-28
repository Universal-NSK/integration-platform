import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from runtime_files.project import find_project_root


def _current_time() -> datetime:
    return datetime.now()


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
        """Вернуть непосредственный дочерний каталог корня данных платформы."""
        self._validate_directory_name(name)

        return self._program_data_root / name

    def create_run_dir(self, container_name: str) -> Path:
        """Создать отдельный каталог запуска внутри каталога контейнера."""
        if (
            not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", container_name)
            or container_name.endswith(".")
            or container_name.split(".", 1)[0].upper()
            in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
            | {f"COM{i}" for i in range(1, 10)}
            | {f"LPT{i}" for i in range(1, 10)}
        ):
            raise ValueError("container_name должен быть безопасным сегментом пути Windows")

        container_dir = self.program_data_path(Path(container_name))
        container_dir.mkdir(parents=True, exist_ok=True)
        timestamp = _current_time().strftime("%Y-%m-%d_%H-%M-%S")
        index = 1
        while True:
            suffix = "" if index == 1 else f"_{index}"
            run_dir = container_dir / f"{timestamp}{suffix}"
            try:
                run_dir.mkdir()
            except FileExistsError:
                index += 1
                continue
            return run_dir

    def program_data_path(
        self,
        relative_path: Path,
    ) -> Path:
        """Разрешить вложенный путь внутри корня ProgramData платформы."""
        if relative_path.is_absolute():
            raise ValueError("Ожидался относительный путь ProgramData")

        root = self._program_data_root.resolve()
        candidate = (root / relative_path).resolve()

        if candidate == root:
            raise ValueError("Ожидался дочерний путь внутри корня ProgramData")

        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("Путь ProgramData должен оставаться внутри своего корня") from exc

        return candidate

    @staticmethod
    def _default_program_data_root() -> Path:
        program_data = os.environ.get("PROGRAMDATA")

        if not program_data:
            raise RuntimeError("Переменная окружения PROGRAMDATA не задана")

        root = Path(program_data)

        if not root.is_absolute():
            raise RuntimeError("PROGRAMDATA должна содержать абсолютный путь")

        return root / "Universal" / "IntegrationPlatform"

    @staticmethod
    def _require_absolute(
        path: Path,
        parameter_name: str,
    ) -> Path:
        if not path.is_absolute():
            raise ValueError(f"{parameter_name} должен быть абсолютным путём")

        return path

    @staticmethod
    def _validate_file_name(
        name: str,
    ) -> None:
        if not name:
            raise ValueError("Имя файла не должно быть пустым")

        if name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError("Ожидалось имя файла, а не путь")

    @staticmethod
    def _validate_directory_name(
        name: str,
    ) -> None:
        if not name:
            raise ValueError("Имя каталога не должно быть пустым")

        if name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError("Ожидалось имя каталога, а не путь")
