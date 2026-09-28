# Артефакты запуска

Владелец запуска один раз вызывает `RuntimePaths.create_run_dir("nashdom_sync")`
и передаёт полученный `Path` в `configure_logging` и `RunArtifactStore.start`.
Store не создаёт каталог и не выбирает ProgramData. Конфиги и секреты не переносятся.

```text
C:\ProgramData\Universal\IntegrationPlatform\
├── nashdom_sync\
│   └── YYYY-MM-DD_HH-MM-SS\
│       ├── nashdom_sync.log
│       ├── nashdom_sync.log.1
│       ├── run.json
│       ├── extract_result.json
│       ├── crm_context.json
│       └── sync_plan.json
└── bitrix_gateway\
    └── YYYY-MM-DD_HH-MM-SS\
        ├── bitrix_gateway.log
        └── bitrix_gateway.log.1
```

Суффиксы `_2`, `_3` различают запуски в одну секунду. Backup-файлы появляются
только после ротации. Gateway создаёт каталог на один старт процесса.

`start(run_dir)` записывает `run.json`: `schema_version=1`, `run_id=run_dir.name`,
`status=RUNNING`, `stage=INITIALIZATION`, `started_at` (локальное время с часовым поясом),
`finished_at=null`, `error_type=null`. Манифест хранится напрямую, без `data`.
Статусы: `RUNNING`, `COMPLETED`, `FAILED`; стадии: `INITIALIZATION`, `CRM_CONTEXT`,
`EXTRACT`, `TRANSFORM`, `LOAD`. Dataclass манифеста неизменяемый.

API: `save_extract_result` / `load_extract_result`, `save_crm_context` /
`load_crm_context`, `save_sync_plan` / `load_sync_plan`, `get_run_dir`,
`mark_stage(stage)`, `mark_completed()`, `mark_failed(stage, error_type)`.
Завершение сохраняет текущую стадию, ошибочное завершение — указанную стадию
и имя типа ошибки. `error_type` должен содержать имя класса, без текста ошибки и PII.

Все snapshots используют `{"schema_version": 1, "data": {...}}`.
Поля DTO сохраняются по именам; даты — ISO, enum — значения, кортежи — JSON-массивы
с восстановлением по контракту DTO. `CommissioningPeriod` сохраняется объектом
с `year`, `quarter`, `exact_date`, включая `null`. Поля команд должны содержать
JSON-совместимые значения. Команда имеет явный `type`: `add_item`,
`add_requisite` или `add_address`; `operation_id` не определяет её тип.
Неизвестные версии схемы, типы команд и некорректные структуры отвергаются.

Запись: временный файл в том же каталоге, полный UTF-8 JSON с `ensure_ascii=False`,
отступом 2, сортировкой ключей, `flush`, `fsync`, затем `os.replace`.
При ошибке временный файл удаляется по возможности; старый целевой файл сохраняется.
Манифест в памяти меняется только после успешной записи. Повторный `start`
инициализирует манифест заново: для каждого запуска требуется новый каталог.
Один store предназначен для последовательного использования владельцем запуска.

Ошибки оборачиваются в `RunArtifactError` с исходной причиной, без payload
в сообщении хранилища. Снимки содержат полные диагностические данные и PII;
store не отправляет их в лог. Retention и ACL здесь не реализованы.
