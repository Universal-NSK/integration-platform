@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem UTF-8 messages; supported by cmd.exe on Windows Server 2008 R2.
chcp 65001 >nul
if errorlevel 1 exit /b 1
for %%I in ("%~dp0..") do set "REPO_ROOT=%%~fI"
where uv >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] uv не найден в PATH. Экспорт выполняется на dev-машине.
    exit /b 1
)
if not exist "%REPO_ROOT%\uv.lock" (
    echo [ОШИБКА] Не найден uv.lock.
    exit /b 1
)
pushd "%REPO_ROOT%"
if errorlevel 1 exit /b 1
rem Runtime: all workspace third-party dependencies, no dependency groups.
rem Test: FULL runtime + test group, not an additive requirements file.
rem Relative output paths keep generated headers independent of checkout location.
uv export --locked --all-packages --no-default-groups --no-emit-local --output-file deploy/requirements-runtime.txt >nul
if errorlevel 1 goto failed
uv export --locked --all-packages --no-default-groups --group test --no-emit-local --output-file deploy/requirements-test.txt >nul
if errorlevel 1 goto failed
popd
echo [OK] requirements-runtime.txt и requirements-test.txt созданы.
exit /b 0
:failed
popd
echo [ОШИБКА] Экспорт не выполнен. Проверьте pyproject.toml и uv.lock.
exit /b 1
