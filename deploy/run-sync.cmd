@echo off
setlocal EnableExtensions DisableDelayedExpansion

chcp 65001 >nul
if errorlevel 1 exit /b 1

for %%I in ("%~dp0..") do set "REPO_ROOT=%%~fI"

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"

set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"

if not exist "%PYTHON%" (
    echo [ОШИБКА] Не найдено production-окружение:
    echo          "%PYTHON%"
    echo.
    echo Сначала выполните:
    echo   deploy\install-runtime.cmd "C:\path\to\Python38\python.exe"
    exit /b 1
)

cd /d "%REPO_ROOT%"
if errorlevel 1 (
    echo [ОШИБКА] Не удалось перейти в корень репозитория.
    exit /b 1
)

"%PYTHON%" -I -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 8) and sys.prefix != sys.base_prefix else 1)"
if errorlevel 1 (
    echo [ОШИБКА] .venv должен использовать Python 3.8.x.
    exit /b 1
)

echo [ИНФО] Запуск NashDom Sync...
echo.

"%PYTHON%" -I -c "from nashdom_sync.main import main; main()"

set "APP_EXIT=%ERRORLEVEL%"

echo.

if not "%APP_EXIT%"=="0" (
    echo [ОШИБКА] NashDom Sync завершился с кодом %APP_EXIT%.
    exit /b %APP_EXIT%
)

echo [OK] NashDom Sync завершён успешно.
exit /b 0