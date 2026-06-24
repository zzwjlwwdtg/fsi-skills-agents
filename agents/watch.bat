@echo off
chcp 65001 > nul
setlocal

set "PY=C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe"
set "SCRIPT_DIR=%~dp0"
REM Secrets loaded from secrets.local.json by config.py (not needed here, log-only)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM Initial backlog lines (default 30). Override: set WATCH_TAIL=100 before launch.
if "%WATCH_TAIL%"=="" set "WATCH_TAIL=30"

cd /d "%SCRIPT_DIR%"
if not exist logs mkdir logs

title Orchestrator Log Watcher
echo Orchestrator Log Watcher - Ctrl+C or X to close (orchestrator keeps running)
echo Backlog: %WATCH_TAIL% lines. Override with: set WATCH_TAIL=N
echo.

"%PY%" -X utf8 -u _log_watch.py

endlocal
