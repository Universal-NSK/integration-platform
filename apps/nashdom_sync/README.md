# NashDom Sync

## Синхронный Bitrix CRM client

```python
from nashdom_sync.bitrix_crm import ClientBitrixCRM

client = ClientBitrixCRM(gateway_url="http://bitrix-gateway:8000", timeout=30.0)
try:
    companies = client.list_items(4, filter_={"title": "Компания"}, select=["id", "title"])
finally:
    client.close()
```

`gateway_url` — базовый адрес HTTP Gateway, не Bitrix webhook. Клиент сам создаёт
и закрывает внутренний `GatewayHttpClient`, владеющий синхронным `httpx.Client`.
DTO и enums находятся в этом приложении; production-код не импортирует Gateway.

Публичные методы:

- `profile() -> Dict[str, Any]`
- `list_items(entity_type_id: int, *, filter_=None, select=None) -> List[Dict[str, Any]]`
- `get_item_fields(entity_type_id: int) -> Dict[str, Any]`
- `list_statuses(entity_id: str) -> List[Dict[str, Any]]`
- `list_users(*, filter_=None) -> List[Dict[str, Any]]`
- `list_requisite_presets() -> List[Dict[str, Any]]`
- `list_requisites(*, filter_=None) -> List[Dict[str, Any]]`
- `list_addresses(*, filter_=None) -> List[Dict[str, Any]]`
- `get_address_fields() -> Dict[str, Any]`
- `list_address_types() -> List[Dict[str, Any]]`
- `list_owner_types() -> List[Dict[str, Any]]`
- `add_item(entity_type_id: int, fields: Dict[str, Any]) -> int`
- `add_requisite(fields: Dict[str, Any]) -> int`
- `add_address(fields: Dict[str, Any]) -> None`
- `close() -> None`

Фильтры имеют тип `Optional[Dict[str, Any]]`, `select` — `Optional[List[str]]`.
Чтение использует `SAFE`, создание — `NEVER`. Локальных повторов HTTP-запроса нет:
политика исполняется только Gateway. `FAILED` преобразуется в
`BitrixRequestFailedError`, `UNKNOWN` — в `BitrixRequestUnknownError`; последний
не означает доказанную неудачу записи и не разрешает повторить её автоматически.
Сбой HTTP Gateway, некорректный JSON или ответ — `BitrixGatewayError`.

Сообщения исключений включают метод, статус, HTTP-код, допустимый код ошибки и
число попыток. Произвольный `error_message` сервера скрывается целиком, поскольку
может содержать секреты или отражённый payload; нестандартный `error_code` также
скрывается. Клиент не логирует payload и не выводит URL из исключений HTTPX.

Пагинация скрыта: верхнеуровневый `next` из Bitrix `data` передаётся как `start`.
Отсутствие `next` завершает обход; `total` не используется для вычисления курсора.
Нецелый, неположительный либо не возрастающий курсор вызывает ошибку.
`crm.item.list` разбирается через `result.items`, остальные постраничные методы —
через `result`. Справочники `crm.enum.*` возвращают весь `result` без пагинации.
`get_item_fields` возвращает `result.fields`, `get_address_fields` — `result`.

Поля передаются без переименования и нормализации: используйте `ADDRESS_2` для
строки адреса, а ИНН/КПП/ОГРН передавайте строками, сохраняя ведущие нули.
`user.get` получает фильтр под ключом `FILTER`, остальные методы — `filter`.
Формы `user.get` и `crm.item.fields` дополнительно сверены с документацией:

- https://apidocs.bitrix24.ru/api-reference/user/user-get.html
- https://apidocs.bitrix24.ru/api-reference/crm/universal/crm-item-fields.html

## Тесты и граница реального Bitrix

Из корня workspace, в окружении Python 3.8 со всеми workspace packages:

```powershell
.venv/Scripts/python.exe -m pytest apps/nashdom_sync/tests/unit
.venv/Scripts/python.exe -m pytest apps/nashdom_sync/tests -m gateway_integration
.venv/Scripts/python.exe -m pytest -m "not bitrix_live and not nashdom_live and not browser"
.venv/Scripts/pyright.exe --pythonpath .venv/Scripts/python.exe
```

Unit-тесты блокируют реальные соединения и используют fake Gateway/MockTransport.
`gateway_integration` поднимает настоящий FastAPI Gateway на случайном loopback
порту; Dispatcher, Executor, RateLimiter настоящие, Bitrix transport всегда fake.
Production transport и внешние соединения заблокированы. Production secrets не
используются. Создание CRM-объектов проверяется только на этих двух уровнях.

Live-тесты находятся в `tests/live/test_bitrix_readonly.py`, содержат только
`profile`, `crm.enum.ownertype`, `crm.item.fields`. По умолчанию они пропускаются.
Даже при `RUN_BITRIX_LIVE=1` обычный pytest пропускает их: требуется также точный
выбор `-m bitrix_live` и `BITRIX_GATEWAY_URL`. Конфигурация и secrets автоматически
не читаются. Запуск разрешён только после явного согласия пользователя.
Live-write тестов нет. В рамках реализации live-тесты не выполнялись.

## Подтверждённые расхождения с L4

Архитектура и композиция сохранены; диаграмма не изменялась. По подтверждению
пользователя исправлены устаревшие сигнатуры:

- `plofile` → `profile`;
- `_list_items` → публичный `list_items`;
- `filter` → `filter_`;
- `list_statuses(entity_type_id: int)` → `list_statuses(entity_id: str)`;
- `list_requisites(*, entity_type_id: int)` → `list_requisites(*, filter_=None)`;
- `list_address_type` → `list_address_types`;
- `list_addresses` принимает keyword-only `filter_` по заданию;
- `GatewayHttpClient.call` возвращает `GatewayCallResult`, а private
  `ClientBitrixCRM._call` возвращает `data` или выбрасывает исключение;
- добавлен private helper `_call_all_pages`.


## CrmProvider

`CrmProvider(bitrix_client_settings: BitrixClientSettings)` из
`nashdom_sync.providers.crm_provider` предоставляет единственный публичный метод
`provide(region_settings: RegionSettings) -> CrmContext`. Каждый вызов создаёт
принадлежащий Provider клиент и закрывает его в `finally`; повторные последовательные
вызовы допустимы. Один экземпляр не предназначен для конкурентных вызовов.
Контракты — frozen dataclass в `contracts/crm.py`.

`providers/crm_provider/fields.py` содержит FieldSpec и точные метаданные восьми
полей, предоставленные владельцем портала 24.09.2026. Основной поиск — exact title.
При нескольких совпадениях upperName проверяется только среди них; при отсутствии
title — среди всех полей. Только уникальный fallback успешен и пишет WARNING
`crm_field_upper_name_fallback` через platform_logging с причиной `title_missing`
или `title_ambiguous`, без данных записей и секретов. Адрес лида — пользовательское
поле «Адрес», адрес реквизитов — системный ADDRESS_2.

SPA «Группа компаний» разрешается по NAME из существующего `list_owner_types()`.
Этот метод возвращает именно entityTypeId, включая SPA:
https://apidocs.bitrix24.ru/api-reference/crm/auxiliary/enum/crm-enum-owner-type.html
Дополнительный crm.type.list не требуется. Стандартные типы — lead=1, company=4,
requisite=8. Справочники соответствуют `docs/запросы.md`; для SOURCE, INDUSTRY и
COMPANY_TYPE используется STATUS_ID, а не ID записи справочника. «Жилое»/«Нежилое»
передаются строками: поле «Тип объекта» имеет type=string.

Клиент дополнен только `search_users(query: str) -> List[Dict[str, Any]]`:
user.search с FILTER[FIND], полной пагинацией и SAFE retry.
https://apidocs.bitrix24.ru/api-reference/user/user-search.html
Менеджер сопоставляется по LAST_NAME NAME SECOND_NAME с нормализацией пробелов и
регистра, без fuzzy matching. При наличии ACTIVE и USER_TYPE исключаются неактивные
и не-employee. configured_name сохраняется для Transform; одинаковые строки
конфигурации запрашиваются один раз.

Existing содержит все записи выбранных типов. Отсутствующие source ID не
отфильтровываются: по контракту это ошибка. Целочисленные double (42.0/"42.00")
нормализуются, дробные ID, bool и повторные source ID отклоняются.

Доменные ошибки: CrmProviderError, CrmMissingSemanticError,
CrmAmbiguousSemanticError, CrmInvalidDataError. Обязательная стадия либо успешна
полностью, либо provide поднимает ошибку; частичный контекст не возвращается.
Тесты Provider находятся в tests/unit/test_crm_provider.py; сеть в unit-тестах
блокируется общей fixture. Transform, Load и C4 не изменены.
