# NashDom Sync: получение списка объектов с наш.дом.рф

Этот документ фиксирует проверенную основу для реализации `NashDomClient.get_objects()`. Его область — только transport/extraction: как получить список объектов в браузерной сессии. Нормализация полей, застройщики и группы компаний сюда намеренно не входят.

Ниже отдельно указаны **подтверждённые экспериментами наблюдения** и **принятые решения для production-прототипа**. Исследовательские файлы лежат в корневом `examples/`, который добавлен в `.gitignore`.

## Подтверждённые наблюдения

### Среда и владение браузером

- `BrowserProvider` создаёт Selenium Chrome `WebDriver` по проверенным настройкам.
- Жизненным циклом браузера владеет `Orchestrator`: создание драйвера оборачивается в `try/finally`, а `driver.quit()` вызывается в `finally`. `NashDomClient` не должен самостоятельно закрывать переданный ему драйвер.
- Production работает на Windows Server 2008 R2 с 4 GB RAM. Память Chrome/Selenium — критичный ресурс.
- Headless-режим ранее приводил к антибот-проверке. В production браузер запускается не headless; текущий `config/sync.toml` также содержит `headless = false`.
- Прямой HTTP-запрос к внутреннему API вне браузерного контекста вернул `403 Forbidden`.

### Два источника данных

Начальный SSR-снимок находится в:

```text
__NEXT_DATA__.props.pageProps.houses
```

На исследованной странице в нём было 20 объектов. После нажатия «Показать ещё» содержимое `__NEXT_DATA__` не изменилось: SHA-256 до и после клика совпал (`nextDataChanged = false`). Поэтому `__NEXT_DATA__` нельзя перечитывать для получения следующих порций.

Frontend получает следующие объекты настоящим XHR:

```text
GET /сервисы/api/kn/object
    ?offset=20
    &limit=20
    &sortField=objPublDt
    &sortType=desc
    &place=22
    &objStatus=0
```

Ответ имеет форму:

```json
{
  "data": {
    "list": [],
    "total": 123
  },
  "errcode": "0"
}
```

Форматы объектов в SSR и XHR различаются. Например, встречаются пары `publicationDate` / `objPublDt`, `status` / `objStatus`, `isGreenHouse` / `objGreenHouseFlg`; отличаются и представления некоторых значений. В выбранном способе получения итоговый список состоит только из raw XHR-объектов одной схемы. Окончательная нормализация A/B/будущих C/D в канонический контракт Z — отдельная задача.

### Interception и browser-context fetch

- До клика устанавливается JS monkeypatch для `XMLHttpRequest.prototype.open`, `setRequestHeader` и `send`.
- Перехватчик принимает только запросы, URL которых содержит `/api/kn/object`; посторонний трафик страницы игнорируется.
- Frontend сам устанавливает заголовок `Authorization`. Monkeypatch `setRequestHeader` позволяет перехватить его в памяти вместе с URL настоящего запроса.
- После одного настоящего XHR вызванный через Selenium `fetch()` в контексте той же страницы работает с перехваченным Authorization и в том же browser context/origin. Обычные browser credentials/cookies при их наличии обрабатываются самим браузером.
- Browser-context fetch с `offset=0&limit=20` вернул HTTP 200. Все 20 `objId` в том же порядке совпали с начальными SSR-объектами.
- Запрос с `limit=1000` был принят и вернул HTTP 200, но сервер отдал только 50 объектов. Это наблюдаемый server cap, а не рекомендуемый размер production-порции.
- Для Алтайского края (`place=22`, `objStatus=0`) API сообщил `total=123`. Через browser-context fetch получено 123/123 объекта порциями 50 + 50 + 23; все 123 `objId` уникальны, `complete=true`.

`Authorization` — чувствительное значение, получаемое из настоящего frontend-запроса. В production-коде его следует считать только runtime-данными: не сохранять в результаты, файлы, логи или исключения и отбрасывать после завершения сессии. Research outputs, HAR и дампы запросов из `examples/` не коммитить: ранние материалы могут содержать чувствительные заголовки. После завершения браузерной сессии значение должно быть отброшено.

### Кнопка «Показать ещё»

Наблюдавшийся DOM:

```html
<div class="Newbuildings__LoadMoreContainer-sc-1bou0u4-4 hGfGit">
  <button type="button" class="styles__ButtonWrapper-sc-40tof2-0 kYqzc Newbuildings__ButtonLoadMore-sc-1bou0u4-12 eDETjV">
    <div class="styles__ButtonContentWrapper-sc-40tof2-3 heLBAf">Показать ещё</div>
  </button>
</div>
```

На исследованной странице `button[class*="Newbuildings__ButtonLoadMore"]` нашёл ровно один элемент. У кнопки были только атрибуты `type="button"` и `class`; `id`, `data-testid` и `aria-label` отсутствовали. Полные styled-components-классы и их сгенерированные hash-части не являются стабильным контрактом.

fetch## Решения для production-прототипа

### Ограничение объёма и сетевой профиль

- Не требуется извлекать все объекты сайта. В конфигурации будет общий лимит `objects_limit` (ориентир: 120); точное место в `SyncSettings`/конфиге пока не закреплено.
- Один настоящий клик «Показать ещё» используется только как bootstrap: frontend формирует валидный XHR, из которого в памяти берутся URL, параметры и `Authorization`.
- Не нажимать кнопку многократно ради сбора данных. Каждый клик дорисовывает карточки и увеличивает потребление RAM; на production-сервере это уже проявлялось как проблема.
- После bootstrap весь нужный объём получать через browser-context fetch. DOM при этом не разрастается.
- Production batch size — 20, как у штатного frontend. Эксперимент с `limit=1000` и обнаруженный cap 50 остаются только research-фактами.
- Целевое количество: `target_count = min(objects_limit, api_total)`. Последнюю порцию можно запросить ровно на остаток.
- При `403`, `429`, challenge-странице или неожиданном не-JSON ответе не делать агрессивных retry. Прервать Extract и записать безопасную причину: статус/тип ошибки, endpoint без секретов, `offset`; не логировать `Authorization` и полный набор заголовков.

### Надёжный выбор и нажатие кнопки

Проверять локаторы по порядку, от наиболее структурного к наиболее общему:

1. CSS: `button[class*="Newbuildings__ButtonLoadMore"]`.
2. CSS: `div[class*="Newbuildings__LoadMoreContainer"] > button`.
3. Текстовый XPath по кнопке с `Показать ещё` или `Показать еще` — только последний fallback.

Для каждого локатора:

- 0 совпадений — перейти к следующему;
- ровно 1 элемент, который видим и разрешён, — выбрать его;
- больше 1 совпадения — считать выбор неоднозначным и завершить с ошибкой; не брать первый элемент молча.

После выбора локатора нужно заново получить элемент, дождаться `element_to_be_clickable`, выполнить `scrollIntoView({block: "center"})` и обычный Selenium `.click()`. JS click допустим только как fallback при технической невозможности native click, а не как основной путь.

Успех клика подтверждается не изменением DOM и не появлением карточек, а получением ожидаемого XHR `/api/kn/object`. Из-за возможного `StaleElementReferenceException` не хранить `WebElement` дольше необходимого: locator хранить можно, сам элемент лучше повторно найти непосредственно перед кликом.

## Рекомендуемая последовательность `get_objects()`

```text
Orchestrator:
    driver = BrowserProvider.provide(...)
    try:
        result = NashDomClient(driver).get_objects(objects_limit)
    finally:
        driver.quit()

NashDomClient.get_objects(objects_limit):
    открыть listing нужного региона и фильтра
    установить XHR interceptor до клика
    найти «Показать ещё» по fallback-стратегии
    выполнить один native click
    дождаться ожидаемого XHR /api/kn/object

    взять из него в память:
        API URL и query-параметры
        Authorization
        валидный response и API total

    target_count = min(objects_limit, API total)
    offset = 0
    objects = []

    while len(objects) < target_count:
        remaining = target_count - len(objects)
        limit = min(20, remaining)
        response = browser-context fetch(offset, limit, Authorization)

        проверить HTTP 200, errcode == "0", data.list и data.total
        прервать Extract на 403/429/challenge без агрессивных retry
        добавить raw XHR objects
        увеличить offset на фактический размер порции

    проверить len(objects) == target_count
    проверить уникальность objId
    вернуть raw XHR objects

После закрытия браузерной сессии Authorization отброшен.
```

Дополнительные защитные проверки: не продолжать цикл после пустой порции до достижения `target_count`; считать ошибкой порцию без новых `objId`; не скрывать изменение структуры ответа под пустым списком.

## Что ещё не решено / следующий шаг

- Реализовать production `NashDomClient.get_objects()` на основе зафиксированной последовательности.
- Утвердить точное размещение `objects_limit` в `SyncSettings`/конфиге.
- Отдельно спроектировать канонизацию внешних форматов данных в контракт Z. Текущий выбранный путь получения objects использует raw XHR-формат B; __NEXT_DATA__ - формат A исследован, но не является частью основного пути `get_objects()`. При появлении fallback-источников или других сущностей могут возникнуть форматы C/D.
- Отдельно исследовать получение developer и company-group данных.

## Локальные материалы исследования

- `examples/temp_data_research.py` и `temp_next_data.json` — чтение полного `__NEXT_DATA__`.
- `examples/temp_xhr_research.py` и `temp_xhr_research_result.json` — один клик, XHR interception и сравнение hash SSR до/после.
- `examples/temp_browser_api_research.py` и `temp_browser_api_research_result.json` — перехват `Authorization` в памяти и browser-context fetch.
- `examples/request.har` и `temp_request.txt` — снимки реального запроса; считать чувствительными и не коммитить.

Эти файлы — временные доказательства, а не production-реализация.
