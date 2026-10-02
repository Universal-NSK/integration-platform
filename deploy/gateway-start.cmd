@echo off
setlocal EnableExtensions DisableDelayedExpansion

chcp 65001 >nul

set "SVC_ID=BitrixGateway"
set "WINSW=%~dp0bitrix-gateway.exe"
set "WINSW_XML=%~dp0bitrix-gateway.xml"

net session >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Запустите скрипт от имени администратора.
    exit /b 1
)

rem Если exe ещё не переименован, делаем копию из WinSW.NET2.exe
if not exist "%WINSW%" (
    if exist "%~dp0WinSW.NET2.exe" copy /y "%~dp0WinSW.NET2.exe" "%WINSW%" >nul
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

if not exist "%~dp0logs" mkdir "%~dp0logs"

sc query "%SVC_ID%" >nul 2>&1
if errorlevel 1 (
    echo [ИНФО] Служба %SVC_ID% не установлена, устанавливаю...
    "%WINSW%" install
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить службу. Смотрите вывод выше.
        exit /b 1
    )
)

sc query "%SVC_ID%" | find "RUNNING" >nul
if not errorlevel 1 (
    echo [ИНФО] Служба %SVC_ID% уже запущена.
    exit /b 0
)

echo [ИНФО] Запускаю службу %SVC_ID%...
"%WINSW%" start
if errorlevel 1 (
    echo [ОШИБКА] Не удалось запустить службу.
    echo          Логи: %~dp0logs
    exit /b 1
)

echo.
"%WINSW%" status
echo.
echo [OK] Готово. Логи: %~dp0logs
exit /b 0
