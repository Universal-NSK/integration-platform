@echo off
setlocal EnableExtensions DisableDelayedExpansion

chcp 65001 >nul
if errorlevel 1 exit /b 1

for %%I in ("%~dp0..") do set "REPO_ROOT=%%~fI"

set "PYTHON=%REPO_ROOT%\.venv-test\Scripts\python.exe"

rem Не наследуем случайное Python-окружение пользователя.
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"

if not exist "%PYTHON%" (
    echo [ОШИБКА] Не найдено тестовое окружение:
    echo          "%PYTHON%"
    echo.
    echo Сначала выполните:
    echo   deploy\install-test.cmd "C:\path\to\Python38\python.exe"
    exit /b 1
)

cd /d "%REPO_ROOT%"
if errorlevel 1 (
    echo [ОШИБКА] Не удалось перейти в корень репозитория.
    exit /b 1
)

echo [ИНФО] Проверка Python test environment...

"%PYTHON%" -I -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 8) and sys.prefix != sys.base_prefix else 1)"
if errorlevel 1 (
    echo [ОШИБКА] .venv-test должен использовать Python 3.8.x.
    exit /b 1
)

echo [ИНФО] Проверка зависимостей...

"%PYTHON%" -I -m pip check
if errorlevel 1 (
    echo [ОШИБКА] pip check обнаружил проблему.
    exit /b 1
)

echo [ИНФО] Проверка импортов...

"%PYTHON%" -I -c "import nashdom_sync, bitrix_gateway, runtime_files, platform_logging, pytest"
if errorlevel 1 (
    echo [ОШИБКА] Не удалось импортировать приложение или pytest.
    exit /b 1
)

echo.
echo [ИНФО] Запуск non-live тестов...
echo.

"%PYTHON%" -I -m pytest ^
    -m "not bitrix_live and not nashdom_live and not browser" ^
    %*

set "TEST_EXIT=%ERRORLEVEL%"

echo.

if not "%TEST_EXIT%"=="0" (
    echo [ОШИБКА] Тесты завершились с кодом %TEST_EXIT%.
    exit /b %TEST_EXIT%
)

echo [OK] Все non-live тесты прошли.
exit /b 0