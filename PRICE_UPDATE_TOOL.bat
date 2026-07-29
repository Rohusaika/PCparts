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
  echo https://www.python.org/ から Python 3.11 以降をインストールし、
  echo インストール時に Add Python to PATH を有効にしてください。
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo 初回セットアップ: Python仮想環境を作成します。
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  if errorlevel 1 goto :error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
)

if not exist "..\docs" mkdir "..\docs"
echo.
echo 価格データを更新しています...
".venv\Scripts\python.exe" update_prices.py --mode mixed --output "..\docs\prices.json"
if errorlevel 1 goto :error

echo.
echo [OK] 次のファイルを更新しました:
echo %~dp0docs\prices.json
echo.
echo この prices.json を GitHub Pages など、Prefabの Remote JSON URL と同じ場所へアップロードしてください。
pause
exit /b 0

:error
echo.
echo [ERROR] 更新に失敗しました。上に表示されたエラーを確認してください。
pause
exit /b 1
