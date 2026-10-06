"""Чтение кеша через общий контракт артефактов запуска."""

from pathlib import Path

from nashdom_sync.contracts.crm import CrmContext
from nashdom_sync.run_artifacts.reader import read_typed_artifact

from .exceptions import CrmContextCacheError


class CrmContextCache:
    """Кеш не обращается к CRM и не принимает решений о режиме запуска."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def exists(self) -> bool:
        """Проверить наличие; ошибки доступа не считать отсутствием кеша."""
        try:
            self._path.stat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CrmContextCacheError("Не удалось прочитать кеш CRM context") from exc
        return True

    def load(self) -> CrmContext:
        """Восстановить проверенный DTO; сохранить причину без payload в сообщении."""
        try:
            return read_typed_artifact(self._path, CrmContext)
        except Exception as exc:
            raise CrmContextCacheError("Не удалось прочитать кеш CRM context") from exc
