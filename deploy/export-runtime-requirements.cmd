@echo off
setlocal EnableExtensions

rem Корень репозитория относительно каталога deploy.
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"

set "LOCK_FILE=%REPO_ROOT%\uv.lock"
set "OUTPUT_FILE=%SCRIPT_DIR%requirements-runtime.txt"

echo [INFO] Repository:
echo        %REPO_ROOT%
echo.

where uv >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv не найден в PATH.
    exit /b 1
)

if not exist "%LOCK_FILE%" (
    echo [ERROR] Не найден uv.lock:
    echo         %LOCK_FILE%
    exit /b 1
)

cd /d "%REPO_ROOT%"
if errorlevel 1 (
    echo [ERROR] Не удалось перейти в корень репозитория.
    exit /b 1
)

echo [INFO] Экспорт runtime-зависимостей...

uv export ^
    --locked ^
    --all-packages ^
    --no-default-groups ^
    --no-emit-local ^
    --output-file "%OUTPUT_FILE%"

if errorlevel 1 (
    echo.
    echo [ERROR] Не удалось экспортировать runtime-зависимости.
    exit /b 1
)

echo.
echo [OK] Runtime requirements созданы:
echo      %OUTPUT_FILE%

exit /b 0