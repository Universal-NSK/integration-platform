from pathlib import Path

import pytest
from runtime_files import ProjectRootNotFoundError, find_project_root


def add_marker(directory: Path) -> None:
    (directory / ".projectroot").touch()


def test_marker_is_found_in_start_directory(tmp_path: Path) -> None:
    add_marker(tmp_path)

    assert find_project_root(tmp_path) == tmp_path.resolve()


def test_marker_is_found_multiple_levels_above_start(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    start = repository / "services" / "gateway"
    start.mkdir(parents=True)
    add_marker(repository)

    assert find_project_root(start) == repository.resolve()


def test_start_can_point_to_a_file(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    source_file = repository / "src" / "bootstrap.py"
    source_file.parent.mkdir(parents=True)
    source_file.touch()
    add_marker(repository)

    assert find_project_root(source_file) == repository.resolve()


def test_search_does_not_depend_on_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    start = repository / "packages" / "runtime_files"
    unrelated_cwd = tmp_path / "unrelated"
    start.mkdir(parents=True)
    unrelated_cwd.mkdir()
    add_marker(repository)
    monkeypatch.chdir(unrelated_cwd)

    assert find_project_root(start) == repository.resolve()


def test_absolute_fallback_is_returned_when_marker_is_missing(tmp_path: Path) -> None:
    start = tmp_path / "unmarked" / "nested"
    fallback = tmp_path / "installed-repository"
    start.mkdir(parents=True)

    assert find_project_root(start, fallback_root=fallback) == fallback


def test_fallback_is_not_used_when_marker_is_found(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    start = repository / "service"
    fallback = tmp_path / "fallback"
    start.mkdir(parents=True)
    add_marker(repository)

    assert find_project_root(start, fallback_root=fallback) == repository.resolve()


def test_relative_fallback_is_rejected_when_marker_is_missing(tmp_path: Path) -> None:
    start = tmp_path / "unmarked"
    start.mkdir()

    with pytest.raises(
        ValueError,
        match="fallback_root must be an absolute path",
    ):
        find_project_root(start, fallback_root=Path("relative-repository"))


def test_missing_marker_without_fallback_raises_project_error(tmp_path: Path) -> None:
    start = tmp_path / "unmarked"
    start.mkdir()

    with pytest.raises(ProjectRootNotFoundError) as exc_info:
        find_project_root(start)

    assert exc_info.value.path == start.resolve()


def test_search_stops_at_filesystem_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filesystem_root = Path(tmp_path.anchor)

    def marker_is_not_a_file(self: Path) -> bool:
        return False

    monkeypatch.setattr(Path, "is_file", marker_is_not_a_file)

    with pytest.raises(ProjectRootNotFoundError):
        find_project_root(filesystem_root)


def test_runtime_paths_from_project_uses_resolved_root(tmp_path: Path) -> None:
    from runtime_files import RuntimePaths

    repository = tmp_path / "repository"
    start = repository / "service"
    program_data_root = tmp_path / "program-data"
    start.mkdir(parents=True)
    add_marker(repository)

    paths = RuntimePaths.from_project(
        start=start,
        fallback_root=tmp_path / "unused-fallback",
        program_data_root=program_data_root,
    )

    assert paths.config_file("gateway.toml") == repository / "config" / "gateway.toml"
    assert paths.program_data_file("secrets.toml") == program_data_root / "secrets.toml"
