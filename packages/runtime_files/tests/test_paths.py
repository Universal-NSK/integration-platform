from pathlib import Path

import pytest
from runtime_files import RuntimePaths


def test_config_file_is_resolved_from_repo_root(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repository"

    paths = RuntimePaths(
        repo_root=repo_root,
        program_data_root=tmp_path / "program-data",
    )

    result = paths.config_file("gateway.toml")

    assert result == (repo_root / "config" / "gateway.toml")


def test_program_data_file_uses_explicit_root(
    tmp_path: Path,
) -> None:
    program_data_root = tmp_path / "Universal" / "IntegrationPlatform"

    paths = RuntimePaths(
        repo_root=tmp_path / "repository",
        program_data_root=program_data_root,
    )

    result = paths.program_data_file("bitrix.secrets.toml")

    assert result == (program_data_root / "bitrix.secrets.toml")


def test_program_data_dir_uses_explicit_root(
    tmp_path: Path,
) -> None:
    program_data_root = tmp_path / "Universal" / "IntegrationPlatform"
    paths = RuntimePaths(
        repo_root=tmp_path / "repository",
        program_data_root=program_data_root,
    )

    result = paths.program_data_dir("logs")

    assert result == (program_data_root / "logs")


def test_program_data_path_resolves_nested_relative_path(
    tmp_path: Path,
) -> None:
    program_data_root = tmp_path / "Universal" / "IntegrationPlatform"
    paths = RuntimePaths(
        repo_root=tmp_path / "repository",
        program_data_root=program_data_root,
    )

    result = paths.program_data_path(
        Path("drivers/chrome/chrome.exe"),
    )

    assert result == program_data_root / "drivers" / "chrome" / "chrome.exe"


@pytest.mark.parametrize(
    "relative_path",
    [
        Path("."),
        Path(".."),
        Path("../outside.exe"),
        Path("drivers/../../outside.exe"),
    ],
)
def test_program_data_path_rejects_root_and_traversal(
    tmp_path: Path,
    relative_path: Path,
) -> None:
    paths = RuntimePaths(
        repo_root=tmp_path / "repository",
        program_data_root=tmp_path / "program-data",
    )

    with pytest.raises(ValueError):
        paths.program_data_path(relative_path)


def test_program_data_path_rejects_absolute_path(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(
        repo_root=tmp_path / "repository",
        program_data_root=tmp_path / "program-data",
    )

    with pytest.raises(ValueError):
        paths.program_data_path(tmp_path / "outside.exe")


def test_program_data_file_uses_windows_programdata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PROGRAMDATA",
        str(tmp_path),
    )

    paths = RuntimePaths(
        repo_root=tmp_path / "repository",
    )

    result = paths.program_data_file("bitrix.secrets.toml")

    assert result == (tmp_path / "Universal" / "IntegrationPlatform" / "bitrix.secrets.toml")


def test_relative_repo_root_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="repo_root must be an absolute path",
    ):
        RuntimePaths(
            repo_root=Path("repository"),
        )


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../gateway.toml",
        "config/gateway.toml",
        r"config\gateway.toml",
    ],
)
def test_file_name_must_not_be_a_path(
    tmp_path: Path,
    name: str,
) -> None:
    paths = RuntimePaths(
        repo_root=tmp_path,
        program_data_root=tmp_path,
    )

    with pytest.raises(ValueError):
        paths.config_file(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../logs",
        "data/logs",
        r"data\logs",
    ],
)
def test_program_data_dir_name_must_be_one_path_segment(
    tmp_path: Path,
    name: str,
) -> None:
    paths = RuntimePaths(
        repo_root=tmp_path,
        program_data_root=tmp_path,
    )

    with pytest.raises(ValueError):
        paths.program_data_dir(name)
