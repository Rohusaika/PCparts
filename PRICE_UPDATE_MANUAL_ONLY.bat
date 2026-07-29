@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0Tools"

set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>nul && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  echo [ERROR] Python 3 が見つかりません。
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  %PYTHON_CMD% -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
if not exist "..\docs" mkdir "..\docs"
".venv\Scripts\python.exe" update_prices.py --mode manual --output "..\docs\prices.json"
if errorlevel 1 goto :error
echo [OK] %~dp0docs\prices.json を更新しました。
pause
exit /b 0
:error
echo [ERROR] 更新に失敗しました。
pause
exit /b 1
