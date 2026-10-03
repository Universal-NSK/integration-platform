@echo off
setlocal EnableExtensions DisableDelayedExpansion

chcp 65001 >nul
if errorlevel 1 exit /b 1

for %%I in ("%~dp0..") do set "REPO_ROOT=%%~fI"

set "SVC_ID=BitrixGateway"
set "WINSW=%~dp0bitrix-gateway.exe"
set "WINSW_XML=%~dp0bitrix-gateway.xml"
set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"

set "HEALTH_URL=http://127.0.0.1:8765/health"

rem Максимум ~30 секунд на переход службы в RUNNING.
set "START_MAX_ATTEMPTS=30"

rem Gateway должен успешно ответить несколько раз подряд.
set "HEALTH_REQUIRED_SUCCESSES=5"

rem Максимальное количество попыток /health.
set "HEALTH_MAX_ATTEMPTS=15"


rem ------------------------------------------------------------
rem Проверка прав администратора.
rem ------------------------------------------------------------

net session >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Запустите скрипт от имени администратора.
    exit /b 1
)


rem ------------------------------------------------------------
rem Проверка production Python.
rem ------------------------------------------------------------

if not exist "%PYTHON%" (
    echo [ОШИБКА] Не найден Python production-окружения:
    echo          "%PYTHON%"
    echo.
    echo Сначала выполните install-runtime.cmd.
    exit /b 1
)


rem ------------------------------------------------------------
rem Проверка WinSW.
rem ------------------------------------------------------------

if not exist "%WINSW%" (
    if exist "%~dp0WinSW.NET2.exe" (
        copy /y "%~dp0WinSW.NET2.exe" "%WINSW%" >nul

        if errorlevel 1 (
            echo [ОШИБКА] Не удалось создать "%WINSW%".
            exit /b 1
        )
    )
)

if not exist "%WINSW%" (
    echo [ОШИБКА] Не найден "%WINSW%".
    echo          Положите рядом WinSW.NET2.exe или bitrix-gateway.exe.
    exit /b 1
)

if not exist "%WINSW_XML%" (
    echo [ОШИБКА] Не найден конфиг "%WINSW_XML%".
    exit /b 1
)

if not exist "%~dp0logs" (
    mkdir "%~dp0logs"

    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать каталог логов:
        echo          "%~dp0logs"
        exit /b 1
    )
)


rem ------------------------------------------------------------
rem Установка службы.
rem ------------------------------------------------------------

sc query "%SVC_ID%" >nul 2>&1

if errorlevel 1 (
    echo [ИНФО] Служба %SVC_ID% не установлена, устанавливаю...

    "%WINSW%" install

    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить службу.
        echo          Смотрите вывод WinSW выше.
        exit /b 1
    )
)


rem ------------------------------------------------------------
rem Проверяем, запущена ли служба уже сейчас.
rem ------------------------------------------------------------

call :is_service_running

if not errorlevel 1 (
    echo [ИНФО] Служба %SVC_ID% уже запущена.
    goto health_begin
)


rem ------------------------------------------------------------
rem Запуск службы.
rem ------------------------------------------------------------

echo [ИНФО] Запускаю службу %SVC_ID%...

"%WINSW%" start

if errorlevel 1 (
    echo [ОШИБКА] Не удалось отправить команду запуска службы.
    echo          Логи: %~dp0logs
    exit /b 1
)


rem ------------------------------------------------------------
rem Ожидаем RUNNING.
rem ------------------------------------------------------------

set "START_ATTEMPT=0"

:wait_running

call :is_service_running

if not errorlevel 1 goto health_begin

set /a START_ATTEMPT+=1

if %START_ATTEMPT% GEQ %START_MAX_ATTEMPTS% goto start_timeout

echo [ИНФО] Ожидание запуска службы... %START_ATTEMPT%/%START_MAX_ATTEMPTS%

rem ~1 секунда.
ping -n 2 127.0.0.1 >nul

goto wait_running


:start_timeout

echo.
echo [ОШИБКА] Служба не перешла в состояние RUNNING.
echo.

sc query "%SVC_ID%"

echo.
echo Логи:
echo   %~dp0logs

exit /b 1


rem ------------------------------------------------------------
rem Health-check.
rem ------------------------------------------------------------

:health_begin

echo.
echo [ИНФО] Служба находится в состоянии RUNNING.
echo.
echo [ИНФО] Проверка Gateway:
echo        %HEALTH_URL%
echo.

set "HEALTH_ATTEMPT=0"
set "HEALTH_SUCCESS=0"


:health_loop

set /a HEALTH_ATTEMPT+=1

echo [ИНФО] Health-check %HEALTH_ATTEMPT%/%HEALTH_MAX_ATTEMPTS%...

"%PYTHON%" -I -c "import json, urllib.request; r = urllib.request.urlopen('%HEALTH_URL%', timeout=3); data = json.load(r); raise SystemExit(0 if r.status == 200 and data.get('status') == 'ok' else 1)" >nul 2>&1

if errorlevel 1 goto health_failed_once


rem ------------------------------------------------------------
rem Успешный health-check.
rem ------------------------------------------------------------

set /a HEALTH_SUCCESS+=1

echo [OK] Gateway отвечает. Последовательных успехов: %HEALTH_SUCCESS%/%HEALTH_REQUIRED_SUCCESSES%.

if %HEALTH_SUCCESS% GEQ %HEALTH_REQUIRED_SUCCESSES% goto healthy

rem ~2 секунды.
ping -n 3 127.0.0.1 >nul

goto health_loop


rem ------------------------------------------------------------
rem Неуспешный health-check.
rem ------------------------------------------------------------

:health_failed_once

set "HEALTH_SUCCESS=0"

echo [ИНФО] Gateway пока недоступен.

if %HEALTH_ATTEMPT% GEQ %HEALTH_MAX_ATTEMPTS% goto health_failed

rem Проверяем, не умерла ли сама служба.
call :is_service_running

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Во время health-check служба перестала быть RUNNING.
    goto health_failed
)

rem ~2 секунды.
ping -n 3 127.0.0.1 >nul

goto health_loop


:health_failed

echo.
echo [ОШИБКА] Gateway не прошёл проверку доступности.
echo          Выполнено попыток: %HEALTH_ATTEMPT%
echo.
echo Состояние службы:

sc query "%SVC_ID%"

echo.
echo Логи WinSW:
echo   %~dp0logs
echo.
echo Логи приложения:
echo   C:\ProgramData\Universal\IntegrationPlatform\bitrix_gateway

exit /b 1


:healthy

echo.
"%WINSW%" status
echo.
echo [OK] Gateway запущен и стабильно отвечает на /health.
echo      Успешных последовательных проверок: %HEALTH_SUCCESS%.
echo      Логи WinSW: %~dp0logs

exit /b 0


rem ============================================================
rem Подпрограммы
rem ============================================================

:is_service_running

sc query "%SVC_ID%" 2>nul | findstr /R /C:"STATE *: *4 *RUNNING" >nul

if errorlevel 1 (
    exit /b 1
)

exit /b 0