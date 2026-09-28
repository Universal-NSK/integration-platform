from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest
import runtime_files.paths as paths_module
from runtime_files import RuntimePaths


def test_run_path_timestamp_collisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths_module, "_current_time", lambda: datetime(2026, 9, 28, 20, 15, 3))
    paths = RuntimePaths(tmp_path, tmp_path / "program-data")
    runs = [paths.create_run_dir("nashdom_sync") for _ in range(3)]
    assert [run.name for run in runs] == [
        "2026-09-28_20-15-03",
        "2026-09-28_20-15-03_2",
        "2026-09-28_20-15-03_3",
    ]
    assert all(run.is_dir() and run.is_absolute() for run in runs)
    assert runs[0].parent == tmp_path / "program-data" / "nashdom_sync"


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../escape",
        "a/b",
        "a\\b",
        "C:escape",
        "C:\\escape",
        "/absolute",
        "bad.",
        "bad ",
        "bad:name",
        "a*",
        "a?",
        "a\x00",
        "CON",
        "nul.log",
        "COM1",
        "LPT9.txt",
        "a\n",
        "CONIN$",
    ],
)
def test_unsafe_container(tmp_path: Path, name: str) -> None:
    paths = RuntimePaths(tmp_path, tmp_path / "program-data")
    with pytest.raises(ValueError, match="container_name"):
        paths.create_run_dir(name)
    assert not (tmp_path / "program-data").exists()


def test_concurrent_runs_are_distinct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths_module, "_current_time", lambda: datetime(2026, 9, 28))
    paths = RuntimePaths(tmp_path, tmp_path / "data")
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(paths.create_run_dir, ["nashdom_sync"] * 8))
    assert len(set(runs)) == 8
    assert all(run.is_dir() for run in runs)


def test_existing_file_collision_is_not_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paths_module, "_current_time", lambda: datetime(2026, 9, 28))
    paths = RuntimePaths(tmp_path, tmp_path / "data")
    container = paths.program_data_dir("nashdom_sync")
    container.mkdir(parents=True)
    existing = container / "2026-09-28_00-00-00"
    existing.write_text("Сохранить", encoding="utf-8")
    assert paths.create_run_dir("nashdom_sync").name == "2026-09-28_00-00-00_2"
    assert existing.read_text(encoding="utf-8") == "Сохранить"


def test_container_cannot_resolve_outside_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = RuntimePaths(tmp_path, tmp_path / "data")
    original = Path.resolve

    def resolve(path: Path, strict: bool = False) -> Path:
        if path.name == "nashdom_sync":
            return tmp_path / "outside"
        return original(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="внутри"):
        paths.create_run_dir("nashdom_sync")
