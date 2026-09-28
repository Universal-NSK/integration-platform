# platform-logging

`platform_logging` настраивает стандартный `logging` для одного пространства имён.
Вызывающая сторона создаёт каталог запуска и передаёт его в логгер:

```python
from pathlib import Path

from platform_logging import LoggingConfig, configure_logging
from runtime_files import RuntimePaths

paths = RuntimePaths.from_project(start=Path(__file__))
run_dir = paths.create_run_dir("bitrix_gateway")
session = configure_logging(
    service_name="bitrix_gateway",
    logger_name="bitrix_gateway",
    run_dir=run_dir,
    config=LoggingConfig(
        level="INFO", console=True, log_payloads=False,
        max_bytes=10_000_000, backup_count=5,
    ),
)
```

`run_dir` должен существовать и быть каталогом. Логгер пишет UTF-8 в
`run_dir / "bitrix_gateway.log"`; ротация создаёт рядом `.log.1`, `.log.2` и т. д.
Логгер не выбирает ProgramData и не создаёт каталог запуска.
За timestamp `YYYY-MM-DD_HH-MM-SS` и коллизии `_2`, `_3` отвечает `RuntimePaths`.

Повторная настройка заменяет и закрывает только обработчики `platform_logging`.
При передаче того же каталога запись продолжается в том же файле.
Сторонние обработчики и корневой логгер сохраняются; `propagate = False`
изолирует выбранное пространство имён. Консоль использует тот же StructuredFormatter.

`log_event`, `with_context` и `log_payload` сохраняют прежние API.
Логирование payload включается явно; нельзя передавать секреты, webhook URL
или полные URL запросов Bitrix. Диагностические snapshots `RunArtifactStore`
сохраняются отдельно и автоматически в лог не попадают.
