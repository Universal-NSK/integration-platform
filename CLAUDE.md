# CLAUDE.md

Руководство для Claude Code по работе с этим репозиторием.

## Назначение

ETL-синхронизация: раз в неделю (воскресенье, запуск внешним планировщиком Windows) приложение
`nashdom_sync` забирает с портала наш.дом.рф объекты строительства, застройщиков и группы компаний,
сверяет с CRM Bitrix24, строит план создания сущностей и выполняет его через локальный сервис
`bitrix_gateway`, который соблюдает rate limit Bitrix24. Шлюз работает постоянно (служба Windows).

## Окружение и ограничения

- **Python 3.8 строго** (`>=3.8,<3.9`), целевая ОС — Windows, в т.ч. старые (Server 2008 R2).
  Не использовать синтаксис/stdlib новее 3.8: `X | Y`, `list[int]`, `match`, `str.removeprefix` и т.п.
  Типы — через `typing` (`List`, `Dict`, `Optional`, `Tuple`).
- **pydantic 1.10** (не v2): `validator`, `parse_obj`, `.dict()`, `class Config`.
- uv workspace: члены `apps/*`, `services/*`, `packages/*`, зависимости закреплены в `uv.lock`.
- pyright `strict`, ruff (line-length 100, правила E4/E7/E9/F/I/B).

## Структура

```
apps/nashdom_sync/        ETL-приложение (точка входа nashdom_sync.main:main)
services/bitrix_gateway/  FastAPI-шлюз к Bitrix24 (bitrix_gateway:main), 127.0.0.1:8765
packages/runtime_files/   RuntimePaths: корень репо (маркер .projectroot), ProgramData, run-каталоги
packages/platform_logging/ структурное логирование: configure_logging, log_event, log_payload
config/                   публичные TOML (gateway.toml, sync.toml, sync.region_slugs.toml)
deploy/                   .cmd-скрипты установки/запуска, WinSW-служба шлюза, requirements с хешами
docs/                     C4 L1–L4 (draw.io XML без расширения), запросы.md (методы Bitrix и примеры),
                          nashdom-sync-data-extraction.md (исследование портала)
```

## Конфигурация

`RuntimePaths` различает два источника:
- `config/<name>` в репозитории — несекретное;
- `%PROGRAMDATA%\Universal\IntegrationPlatform\<name>` — приватное, вне Git.

**Не читать и не выводить содержимое приватных файлов** (`bitrix.secrets.toml` содержит webhook URL
с токеном). Структуру полей брать из pydantic-моделей в коде.

Sync собирает настройки в `providers/settings_provider/provider.py`: `sync.toml` + приватные
`sync.browser.toml`, `sync.extract.toml`, `sync.manager-region.toml`, `sync.execution.toml`.
Слияние глубокое, **перекрытие одного ключа в двух файлах — ошибка** (`ConfigurationOverlapError`).
Итог валидируется `contracts/settings.py::SyncSettings` (`extra=forbid`, strict-типы).
`extract.nashdom.regions` не задаётся вручную — вычисляется из `region.assignment` ∩ регионов со slug
в `sync.region_slugs.toml`. `execution.load_enabled=false` — прогон без записи в CRM; тогда при
наличии `crm_context.json` в ProgramData CRM-контекст берётся из кеша.

Шлюз: `config/gateway.toml` (`GatewaySettings`) + `bitrix.secrets.toml` (`GatewaySecrets`).

## Архитектура nashdom_sync

`SyncOrchestrator.run` последовательно проходит стадии (`RunStage`), каждая сохраняет артефакт
в run-каталог `%PROGRAMDATA%\...\nashdom_sync\<timestamp>\` (там же лог):

1. **CRM_CONTEXT** — `CrmProvider` читает из CRM структуру (entityTypeId, коды пользовательских
   полей), справочники, существующие сущности и менеджеров → `CrmContext` → `crm_context.json`.
2. **EXTRACT** — `BrowserProvider` (Selenium + Chrome) → `ExtractService`/`NashDomClient`:
   SSR-данные страниц + перехват XHR «Показать ещё» и fetch из контекста браузера; нормализация
   (`normalizer.py`) и валидация (`extract/validator.py`) → `extract_result.json`.
   При `BrowserSessionUnavailableError` сессия браузера перезапускается.
3. **TRANSFORM** — `SyncPlanTransformer` строит детерминированный `SyncPlan`: только **создание**
   отсутствующих сущностей (группы компаний → компании+реквизиты+адреса → лиды). Дедупликация:
   лиды и группы по source id, застройщики по ИНН из реквизитов. `SyncPlanValidator` проверяет план
   → `sync_plan.json`.
4. **LOAD** — `SyncPlanExecutor` выполняет операции по порядку. **Runtime bindings**: поле команды
   заполняется CRM ID, полученным предыдущей операцией (`RuntimeBinding(field, source_operation_id)`,
   подстановка в `RuntimeBindingResolver`). Неуспех зависимости → операция `BLOCKED`.
   Итог → `load_result.json`; не все `SUCCESS` → `LoadIncompleteError`.

`run.json` — манифест запуска (стадия, статус, тип ошибки). Контракты всех стадий — frozen
dataclass'ы в `contracts/`; сериализация/чтение артефактов — `run_artifacts/`.

Связь с CRM — только через `bitrix_crm.ClientBitrixCRM` (синхронный httpx → шлюз `/call`).
Чтение идёт с `retry_policy=safe`, запись (`add_*`) — `never`.

## Архитектура bitrix_gateway

`POST /call {method, payload, retry_policy}` → `GatewayHttpApi` → `RequestDispatcher`
(in-memory очередь, **один последовательный worker**) → `RequestExecutor` → `HttpBitrixTransport`.
`GET /health` — статус и размер очереди.
- `limits/`: глобальный минимальный интервал между запросами (`limits.min_interval`) и cooldown
  метода по `OPERATION_TIME_LIMIT`.
- Ретраи только для `safe`: `QUERY_LIMIT_EXCEEDED`, HTTP 5xx, транспортные ошибки (до
  `execution.max_attempts`). Для `never` повторов нет; 5xx/обрыв с неизвестным исходом → `status=unknown`.
- Ответ: `status` ∈ success/failed/unknown; очередь полна → 503, таймаут ожидания → 504.
- Секретные фрагменты webhook URL вырезаются из ошибок и логов — сохранять это свойство.

## Команды

Dev (uv):
```
uv sync --all-packages --group dev
uv run pytest -m "not bitrix_live and not nashdom_live and not browser"   # unit + gateway_integration
uv run pytest services/bitrix_gateway                                    # один член workspace
uv run ruff check . ; uv run pyright
```
Маркеры: `gateway_integration` (реальный HTTP шлюза, fake Bitrix), `bitrix_live` (read-only против
реального Bitrix, нужен запущенный шлюз), `browser` (Chrome/ChromeDriver), `nashdom_live` (живой сайт).
Live-тесты запускать только по явной просьбе.

Прод (Windows, из корня репо): `deploy\install-runtime.cmd "C:\...\python.exe"` → `.venv`;
`deploy\run-gateway.cmd` или служба `deploy\gateway-start.cmd` (WinSW, проверка `/health`);
`deploy\run-sync.cmd`. Тесты на сервере: `install-test.cmd` → `.venv-test`, `run-tests.cmd`.
После изменения зависимостей: `deploy\export-requirements.cmd` (обновляет requirements с хешами).

## Конвенции

- Docstrings, сообщения исключений и комментарии — на русском.
- Каждый модуль-пакет имеет свой `exceptions.py` с иерархией от базовой ошибки пакета.
- Логи только через `log_event(logger, level, "snake_case_event", **fields)`; payload — через
  `log_payload(..., enabled=config.log_payloads)`. Не логировать ИНН, имена, URL с токенами,
  тексты ошибок Bitrix (см. `client.py`: `error_message=[скрыто]`).
- Вторичные ошибки (закрытие ресурсов, диагностика) не должны подменять первичную:
  паттерн `with suppress(Exception)` + `raise`.
- Контракты неизменяемые (`@dataclass(frozen=True)`, pydantic `allow_mutation=False`).
- Файлы README в пакетах написаны автоматически и могут расходиться с кодом — источник истины код.
  Диаграммы L4 частично устарели (см. «Подтверждённые расхождения с L4» в `apps/nashdom_sync/README.md`).
