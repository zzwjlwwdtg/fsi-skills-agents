@echo off
chcp 65001 > nul
setlocal

set "PY=C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe"
set "SCRIPT_DIR=%~dp0"
REM FRED_API_KEY 现在通过 secrets.local.json 读（config.py 自动加载）
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "TRADER_DRY_RUN=1"
if "%SNAPSHOT_TIMEOUT_SEC%"=="" set "SNAPSHOT_TIMEOUT_SEC=900"
if "%SNAPSHOT_WITH_AI%"=="" set "SNAPSHOT_WITH_AI=1"
if "%SNAPSHOT_AI_TIMEOUT_SEC%"=="" set "SNAPSHOT_AI_TIMEOUT_SEC=300"

cd /d "%SCRIPT_DIR%"

REM One-shot snapshot: regime + trump + signals + decisions + event calendar
"%PY%" -X utf8 -u _snapshot_today.py

echo.
pause
endlocal
