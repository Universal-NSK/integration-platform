@echo off
setlocal EnableExtensions DisableDelayedExpansion

chcp 65001 >nul

rem Использование: gateway-uninstall.cmd [/logs]
rem   /logs - дополнительно удалить папку логов

set "SVC_ID=BitrixGateway"
set "WINSW=%~dp0bitrix-gateway.exe"
set "SVC_KEY=HKLM\SYSTEM\CurrentControlSet\Services\%SVC_ID%"
set "EVT_KEY=HKLM\SYSTEM\CurrentControlSet\Services\EventLog\Application\%SVC_ID%"
set "NEED_REBOOT=0"

net session >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Запустите скрипт от имени администратора.
    exit /b 1
)

rem --- 1. Остановка ---
sc query "%SVC_ID%" >nul 2>&1
if errorlevel 1 goto after_service

sc query "%SVC_ID%" | find "STOPPED" >nul
if errorlevel 1 (
    echo [ИНФО] Останавливаю службу %SVC_ID%...
    if exist "%WINSW%" (
        "%WINSW%" stop
    ) else (
        sc stop "%SVC_ID%" >nul
    )
    ping -n 4 127.0.0.1 >nul
)

rem --- 2. Удаление службы ---
echo [ИНФО] Удаляю службу %SVC_ID%...
if exist "%WINSW%" "%WINSW%" uninstall

sc query "%SVC_ID%" >nul 2>&1
if not errorlevel 1 (
    echo [ИНФО] Служба осталась, удаляю через sc delete...
    sc delete "%SVC_ID%"
    ping -n 3 127.0.0.1 >nul
)

:after_service

rem --- 3. Остаточные процессы ---
taskkill /f /im bitrix-gateway.exe >nul 2>&1

rem --- 4. Записи в реестре ---
reg query "%EVT_KEY%" >nul 2>&1
if not errorlevel 1 (
    echo [ИНФО] Удаляю источник событий: %EVT_KEY%
    reg delete "%EVT_KEY%" /f >nul
)

reg query "%SVC_KEY%" >nul 2>&1
if not errorlevel 1 (
    echo [ИНФО] Удаляю ветку службы: %SVC_KEY%
    reg delete "%SVC_KEY%" /f >nul 2>&1
)

rem --- 5. Логи ---
if /i "%~1"=="/logs" (
    if exist "%~dp0logs" (
        echo [ИНФО] Удаляю папку логов: %~dp0logs
        rmdir /s /q "%~dp0logs"
    )
)

rem --- 6. Итоговая проверка ---
sc query "%SVC_ID%" >nul 2>&1
if not errorlevel 1 set "NEED_REBOOT=1"

reg query "%SVC_KEY%" >nul 2>&1
if not errorlevel 1 set "NEED_REBOOT=1"

echo.
if "%NEED_REBOOT%"=="1" (
    echo [ВНИМАНИЕ] Служба помечена на удаление, но ещё не удалена полностью.
    echo            Закройте services.msc и Диспетчер задач и перезагрузите сервер.
    exit /b 2
)

echo [OK] Служба %SVC_ID% и записи в реестре удалены.
exit /b 0
