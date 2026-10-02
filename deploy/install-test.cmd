@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
if errorlevel 1 exit /b 1
for %%I in ("%~dp0..") do set "REPO_ROOT=%%~fI"
set "VENV_DIR=%REPO_ROOT%\.venv-test"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "REQUIREMENTS=%REPO_ROOT%\deploy\requirements-test.txt"
rem Ignore an activated environment or inherited Python source path.
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
if not "%~2"=="" (
    echo [ОШИБКА] Допустим только один аргумент: путь к Python 3.8.
    exit /b 1
)
if not exist "%REQUIREMENTS%" (
    echo [ОШИБКА] Нет файла "%REQUIREMENTS%". Выполните экспорт на dev-машине.
    exit /b 1
)
if exist "%VENV_DIR%" goto existing
if "%~1"=="" (
    echo [ОШИБКА] Для создания окружения укажите полный путь к Python 3.8 в кавычках.
    exit /b 1
)
if not exist "%~1" (
    echo [ОШИБКА] Python не найден: "%~1".
    exit /b 1
)
"%~1" -I -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 8) else 1)"
if errorlevel 1 goto version_error
echo [ИНФО] Создание "%VENV_DIR%"...
"%~1" -I -m venv "%VENV_DIR%"
if errorlevel 1 goto failed
:existing
if not exist "%VENV_PYTHON%" (
    echo [ОШИБКА] Окружение повреждено: отсутствует "%VENV_PYTHON%".
    exit /b 1
)
"%VENV_PYTHON%" -I -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 8) and sys.prefix != sys.base_prefix else 1)"
if errorlevel 1 goto version_error
rem uv-created development venvs may not contain pip; standard-library bootstrap.
"%VENV_PYTHON%" -I -m ensurepip
if errorlevel 1 goto failed
rem Pin pip: 25.0.1 declares Requires-Python >=3.8. No unbounded upgrade.
"%VENV_PYTHON%" -I -m pip install --only-binary=:all: "pip==25.0.1"
if errorlevel 1 goto failed
"%VENV_PYTHON%" -I -m pip install --require-hashes --only-binary=:all: -r "%REQUIREMENTS%"
if errorlevel 1 goto failed
rem Python 3.8 reads .pth with the locale encoding; write with the same encoding.
rem Enumerate workspace src directories without hardcoding member names.
"%VENV_PYTHON%" -I -c "import sys, pathlib, locale; root = pathlib.Path(sys.argv[1]); paths = sorted(p.resolve() for group in ('apps', 'services', 'packages') for p in root.glob(group + '/*/src') if p.is_dir() and (p.parent / 'pyproject.toml').is_file()); assert paths, 'No workspace src directories'; target = pathlib.Path(sys.prefix) / 'Lib' / 'site-packages' / 'integration_platform.pth'; content = ''.join(str(p) + '\n' for p in paths); temp = target.with_suffix('.pth.tmp'); temp.write_text(content, encoding=locale.getpreferredencoding(False)); temp.replace(target)" "%REPO_ROOT%"
if errorlevel 1 goto failed
"%VENV_PYTHON%" -I -m pip check
if errorlevel 1 goto failed
"%VENV_PYTHON%" -I -c "import nashdom_sync, bitrix_gateway, runtime_files, platform_logging, pytest; print('[OK] imports')"
if errorlevel 1 goto failed
echo [OK] Окружение готово: "%VENV_DIR%".
exit /b 0
:version_error
echo [ОШИБКА] Требуется Python 3.8.x; существующий Python должен принадлежать venv.
exit /b 1
:failed
echo [ОШИБКА] Установка не завершена. Причина указана выше.
exit /b 1
