from pathlib import Path
from typing import Tuple

import pytest
import tomli
from bitrix_gateway.settings.loader import load_secrets, load_settings
from bitrix_gateway.settings.models import GatewaySecrets, GatewaySettings
from pydantic import ValidationError
from runtime_files import RuntimeFileNotFoundError, RuntimePaths

VALID_CONFIG = """
[bitrix]
request_timeout = 5.0

[limits]
min_interval = 0.001

[execution]
max_attempts = 2
retry_delay = 0.0

[queue]
max_size = 10

[http]
request_timeout = 2.0

[server]
host = "127.0.0.1"
port = 8765

[logging]
level = "INFO"
console = false
log_payloads = true
max_bytes = 100000
backup_count = 1
""".strip()

VALID_SECRETS = """
[bitrix]
webhook_url = "https://example.invalid/rest/test/fake-secret"
""".strip()


def _runtime_files(tmp_path: Path) -> Tuple[Path, Path, Path]:
    repo_root = tmp_path / "repo"
    start = repo_root / "services" / "bitrix_gateway" / "entry.py"
    program_data_root = tmp_path / "program-data"

    start.parent.mkdir(parents=True)
    start.write_text("", encoding="utf-8")
    (repo_root / ".projectroot").write_text("", encoding="utf-8")
    (repo_root / "config").mkdir()
    program_data_root.mkdir()

    (repo_root / "config" / "gateway.toml").write_text(
        VALID_CONFIG,
        encoding="utf-8",
    )
    (program_data_root / "bitrix.secrets.toml").write_text(
        VALID_SECRETS,
        encoding="utf-8",
    )
    return repo_root, start, program_data_root


def test_runtime_paths_load_complete_config_and_separate_secrets_without_cwd_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root, start, program_data_root = _runtime_files(tmp_path)
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    paths = RuntimePaths.from_project(
        start=start,
        program_data_root=program_data_root.resolve(),
    )
    config_path = paths.config_file("gateway.toml")
    secrets_path = paths.program_data_file("bitrix.secrets.toml")
    settings = load_settings(config_path)
    secrets = load_secrets(secrets_path)

    assert config_path == repo_root.resolve() / "config" / "gateway.toml"
    assert secrets_path == program_data_root.resolve() / "bitrix.secrets.toml"
    assert config_path.parent != secrets_path.parent
    assert isinstance(settings, GatewaySettings)
    assert settings.server.port == 8765
    assert settings.logging.log_payloads is True
    assert isinstance(secrets, GatewaySecrets)
    assert secrets.bitrix.webhook_url == "https://example.invalid/rest/test/fake-secret"


@pytest.mark.parametrize("missing_file", ["config", "secrets"])
def test_missing_runtime_file_has_clear_path_aware_error(
    tmp_path: Path,
    missing_file: str,
) -> None:
    _, start, program_data_root = _runtime_files(tmp_path)
    paths = RuntimePaths.from_project(
        start=start,
        program_data_root=program_data_root.resolve(),
    )

    if missing_file == "config":
        missing_path = paths.config_file("gateway.toml")
        missing_path.unlink()
        loader = load_settings
    else:
        missing_path = paths.program_data_file("bitrix.secrets.toml")
        missing_path.unlink()
        loader = load_secrets

    with pytest.raises(RuntimeFileNotFoundError) as exc_info:
        loader(missing_path)

    assert str(missing_path) in str(exc_info.value)
    assert "Runtime file not found" in str(exc_info.value)


def test_invalid_toml_fails_loading(tmp_path: Path) -> None:
    invalid_path = tmp_path / "gateway.toml"
    invalid_path.write_text("[bitrix\nrequest_timeout = 5.0", encoding="utf-8")

    with pytest.raises(tomli.TOMLDecodeError):
        load_settings(invalid_path)


def test_missing_required_settings_fail_validation(tmp_path: Path) -> None:
    incomplete_path = tmp_path / "gateway.toml"
    incomplete_path.write_text(
        "[limits]\nmin_interval = 0.001\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_settings(incomplete_path)
