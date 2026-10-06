# Подготовка dependencies и venv

Цель: Windows Server 2008 R2 SP1 с отдельно установленным Python 3.8.x.
Скрипты используют cmd.exe и стандартную библиотеку Python; PowerShell и uv
на сервере не нужны. Проверки на современной Windows не заменяют проверку
совместимости бинарных wheels с конкретным сервером.

## На dev-машине

После изменения зависимостей выполните `uv lock`, затем:

```bat
deploy\export-requirements.cmd
```

Используемые команды из корня checkout:

```bat
uv export --locked --all-packages --no-default-groups --no-emit-local --output-file deploy/requirements-runtime.txt
uv export --locked --all-packages --no-default-groups --group test --no-emit-local --output-file deploy/requirements-test.txt
```

- `requirements-runtime.txt`: только сторонние runtime-зависимости всего workspace.
- `requirements-test.txt`: ПОЛНОЕ окружение runtime + pytest/pytest-cov и их зависимости.
  Установщик test использует только этот файл; складывать два файла не требуется.
- Оба файла сохраняют точные версии, platform markers и SHA-256 из uv.lock.
  Их следует хранить в Git вместе с pyproject.toml, uv.lock и скриптами.
- Группа `dev` включает `test` через `{ include-group = "test" }` и сохраняет
  debugpy, pyright, ruff. Для полного dev workspace: `uv sync --all-packages`.
- Старый пользовательский `export-runtime-requirements.cmd` сохранён без изменений.
  Используйте новый `export-requirements.cmd`, чтобы обновлять оба артефакта.

## На сервере

Первое создание (замените пример на реальный путь):

```bat
deploy\install-runtime.cmd "C:\path\to\Python38\python.exe"
deploy\install-test.cmd "C:\path\to\Python38\python.exe"
```

Повторная установка после Git pull:

```bat
deploy\install-runtime.cmd
deploy\install-test.cmd
```

Окружения находятся в `.venv` и `.venv-test` относительно корня checkout.
Активация не нужна. При первом запуске обязателен существующий Python 3.8.x.
При повторном запуске проверяется Python самого venv; другой Python не подставляется.
Повреждённый каталог окружения вызывает ошибку, а не автоматическое удаление.

Установщики создают окружение через `python -m venv`, обеспечивают наличие pip
через `ensurepip`, закрепляют `pip==25.0.1`, затем устанавливают соответствующий
requirements с `--require-hashes --only-binary=:all:`. После этого выполняются
`pip check` и imports nashdom_sync, bitrix_gateway, runtime_files, platform_logging;
в test-окружении дополнительно импортируется pytest. Ошибки возвращают ненулевой код.

pip 25.0.1 объявляет `Requires-Python >=3.8`:
https://pypi.org/project/pip/25.0.1/
Сам pip устанавливается по точной версии из wheel; hashes применяются к
экспортированным runtime/test requirements. Безусловного обновления pip нет.

Нужен доступ к индексу пакетов по HTTPS либо предварительно подготовленный источник
wheels через штатные настройки pip. Скрипты не скачивают Python, не отключают TLS
проверки и не задают proxy. Сборка sdist запрещена: отсутствие совместимого wheel
приведёт к явной ошибке. На машине разработки старый bootstrap pip 21.1.1 оказался
несовместим с системным proxy; локальная проверка прошла с временным `NO_PROXY=*`.
Это настройка проверки, а не требование к серверу и не часть скриптов.

Повторный pip install не удаляет лишние ранее установленные пакеты. Для чистого
production окружения используйте свежий venv; dev venv содержит dev-инструменты.

## Импорт кода из checkout

В каждом окружении создаётся `Lib\site-packages\integration_platform.pth`.
Туда записываются отсортированные абсолютные пути существующих `apps/*/src`,
`services/*/src`, `packages/*/src` с pyproject.toml в каталоге member.
Имена workspace-пакетов при обнаружении не зашиты. Файл обновляется через временный
файл и замену, в локальной кодировке, которой Python 3.8 читает .pth.

Python добавляет эти каталоги в sys.path при запуске. Локальные пакеты не
устанавливаются через pip и не собираются; uv_build на сервере не нужен.
Console entry points и distribution metadata локальных пакетов при этом не
создаются. После переноса checkout создайте venv заново: venv не переносим.

## Ручная проверка тестов

```bat
.venv-test\Scripts\python.exe -m pytest -m "not bitrix_live and not nashdom_live and not browser"
```

Установщики не запускают pytest, Gateway, Sync, браузер или live smoke tests.
WinSW, Task Scheduler, production config и deploy/restart orchestration сюда не входят.


## Private browser/extract runtime settings

После обновления создайте `sync.browser.toml` и `sync.extract.toml` в
`C:\ProgramData\Universal\IntegrationPlatform`. Все поля обязательны;
невалидные или отсутствующие настройки останавливают запуск до создания браузера.
Старый `sync.paths.toml` больше не используется; перенесите browser_path/driver_path
в sync.browser.toml. Реальные private файлы не включаются в Git и не удаляются миграцией.

`sync.browser.toml`:
```toml
[browser]
headless = false
browser_path = "browser/chrome.exe"
driver_path = "browser/chromedriver.exe"
page_load_timeout_seconds = 120.0
script_timeout_seconds = 60.0
page_load_strategy = "eager"
disable_images = true
window_width = 1280
window_height = 720
```

`sync.extract.toml`:
```toml
[extract.nashdom]
objects_to_parse_count = 20
element_wait_timeout_seconds = 60.0
navigation_max_attempts = 3
navigation_retry_delay_seconds = 10.0
```

Browser paths разрешаются относительно ProgramData. Private layout также включает
`sync.manager-region.toml`, `sync.execution.toml`, `bitrix.secrets.toml`.
Tracked `config/sync.toml` содержит только logging/bitrix;
`config/sync.region_slugs.toml` остаётся tracked.

BrowserProvider задаёт page-load/script timeouts, стратегию загрузки и viewport.
Images блокируются только при disable_images=true. JavaScript сохраняется.
Chrome получает --disable-background-networking, --disable-component-update,
--disable-default-apps, --disable-extensions, --disable-sync, --no-first-run;
--headless=new добавляется только при headless=true.

Все WebDriverWait используют element_wait_timeout_seconds. Retry выполняется только
для driver.get (регион, browser-context, developer detail, company-group detail):
3 — общее число попыток, включая первую, с 10 секундами между попытками.
Повторяются TimeoutException и WebDriverException с net::ERR_*, timed out/timeout.
DOM/JSON/contract errors, отсутствие __NEXT_DATA__, challenge и неизвестные
WebDriver errors не повторяются. После transient failure выполняется best-effort
window.stop(); WARNING nashdom_navigation_retry содержит только безопасные metadata.
Transform/Load и fetch/XHR не повторяются.
