@echo off
setlocal EnableExtensions DisableDelayedExpansion

chcp 65001 >nul

set "SVC_ID=BitrixGateway"
set "WINSW=%~dp0bitrix-gateway.exe"

net session >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Запустите скрипт от имени администратора.
    exit /b 1
)

sc query "%SVC_ID%" >nul 2>&1
if errorlevel 1 (
    echo [ИНФО] Служба %SVC_ID% не установлена, останавливать нечего.
    exit /b 0
)

sc query "%SVC_ID%" | find "STOPPED" >nul
if not errorlevel 1 (
    echo [ИНФО] Служба %SVC_ID% уже остановлена.
    exit /b 0
)

echo [ИНФО] Останавливаю службу %SVC_ID%...
if exist "%WINSW%" (
    "%WINSW%" stop
) else (
    sc stop "%SVC_ID%" >nul
)

rem Ждём до 20 секунд
set "TRIES=0"
:wait_stop
sc query "%SVC_ID%" | find "STOPPED" >nul
if not errorlevel 1 goto stopped
set /a TRIES+=1
if %TRIES% GEQ 20 goto failed
ping -n 2 127.0.0.1 >nul
goto wait_stop

:stopped
echo [OK] Служба %SVC_ID% остановлена.
exit /b 0

:failed
echo [ОШИБКА] Служба не остановилась за 20 секунд.
echo          Состояние:
sc query "%SVC_ID%"
exit /b 1
