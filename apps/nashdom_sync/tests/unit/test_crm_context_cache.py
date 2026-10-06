"""Проверки кеша без обращений к CRM."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from nashdom_sync.providers.crm_context_cache import CrmContextCache, CrmContextCacheError
from nashdom_sync.run_artifacts import RunArtifactStore
from test_transform import context


def test_missing(tmp_path: Path) -> None:
    cache = CrmContextCache(tmp_path / "crm_context.json")
    assert not cache.exists()
    with pytest.raises(CrmContextCacheError) as caught:
        cache.load()
    assert isinstance(caught.value.__cause__, FileNotFoundError)


def test_round_trip(tmp_path: Path) -> None:
    store = RunArtifactStore.start(tmp_path)
    expected = context()
    store.save_crm_context(expected)
    path = tmp_path / "crm_context.json"
    before = path.read_bytes()
    cache = CrmContextCache(path)
    assert cache.exists()
    assert cache.load() == expected
    target = tmp_path / "new-run"
    target.mkdir()
    current = RunArtifactStore.start(target)
    current.save_crm_context(cache.load())
    assert current.load_crm_context() == expected
    assert (target / path.name).read_bytes() == before


@pytest.mark.parametrize("payload", [
    "SECRET_PAYLOAD",
    '{"schema_version": 2, "data": "SECRET_PAYLOAD"}',
    '{"schema_version": true, "data": "SECRET_PAYLOAD"}',
    '{"data": "SECRET_PAYLOAD"}',
    '{"schema_version": 1, "data": {}, "secret": "SECRET_PAYLOAD"}',
    '{"schema_version": 1, "data": {"secret": "SECRET_PAYLOAD"}}',
    '[]',
    '{"schema_version": 1, "data": NaN}',
])
def test_invalid(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "crm_context.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(CrmContextCacheError) as caught:
        CrmContextCache(path).load()
    assert caught.value.__cause__ is not None
    assert "SECRET_PAYLOAD" not in str(caught.value)
    assert str(caught.value) == "Не удалось прочитать кеш CRM context"


def test_read_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    error = PermissionError("SECRET_PAYLOAD")
    monkeypatch.setattr(Path, "open", Mock(side_effect=error))
    with pytest.raises(CrmContextCacheError) as caught:
        CrmContextCache(tmp_path / "crm_context.json").load()
    assert caught.value.__cause__ is error
    assert "SECRET_PAYLOAD" not in str(caught.value)


def test_exists_access_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    error = PermissionError("SECRET_PAYLOAD")
    monkeypatch.setattr(Path, "stat", Mock(side_effect=error))
    with pytest.raises(CrmContextCacheError) as caught:
        CrmContextCache(tmp_path / "crm_context.json").exists()
    assert caught.value.__cause__ is error
    assert "SECRET_PAYLOAD" not in str(caught.value)
