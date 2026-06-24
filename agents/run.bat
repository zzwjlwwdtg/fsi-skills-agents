@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

set "PY=C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe"
set "SCRIPT_DIR=%~dp0"
REM Secrets (FRED_API_KEY, MOOMOO_ACC_ID) loaded from secrets.local.json by config.py
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM default: LIVE on moomoo SIMULATE account. for dry-run: set TRADER_DRY_RUN=1
if "%TRADER_DRY_RUN%"=="" set "TRADER_DRY_RUN=0"
if "%CLAUDE_DECISION_GATE%"=="" set "CLAUDE_DECISION_GATE=1"
if "%CLAUDE_DECISION_MODE%"=="" set "CLAUDE_DECISION_MODE=gate"
if "%CLAUDE_DECISION_TIMEOUT_SEC%"=="" set "CLAUDE_DECISION_TIMEOUT_SEC=180"
if "%CLAUDE_DECISION_FAIL_CLOSED%"=="" set "CLAUDE_DECISION_FAIL_CLOSED=1"
if "%CLAUDE_DECISION_FALLBACK_CODEX%"=="" set "CLAUDE_DECISION_FALLBACK_CODEX=0"

cd /d "%SCRIPT_DIR%"
if not exist logs mkdir logs

REM Single-instance guard: refuse to start if another orchestrator is alive.
REM orchestrator.py also locks via .orchestrator.lock, but this gives an
REM instant message in the bat window instead of waiting for python startup.
if exist ".orchestrator.lock" (
    set /p ORCH_PID=<.orchestrator.lock
    tasklist /FI "PID eq !ORCH_PID!" /FI "IMAGENAME eq python.exe" 2>nul | find /I "python.exe" >nul
    if not errorlevel 1 (
        echo ============================================================
        echo   [WARN] orchestrator already running ^(PID=!ORCH_PID!^)
        echo   This run.bat will NOT start a second instance.
        echo   To restart: taskkill /PID !ORCH_PID! /F ^&^& del .orchestrator.lock
        echo ============================================================
        pause
        endlocal
        exit /b 1
    )
    echo [INFO] stale lock for dead PID !ORCH_PID! - python will clear it
)

echo Trading Agents starting...
echo   TRADER_DRY_RUN=%TRADER_DRY_RUN%   (0=LIVE on moomoo SIMULATE, 1=dry log-only)
echo   CLAUDE_DECISION_GATE=%CLAUDE_DECISION_GATE%   (1=Claude pre-trade approval required)
echo   Tools menu: run tools.bat
echo   Log: logs\run_YYYYMMDD.log
echo.

"%PY%" -X utf8 orchestrator.py

pause
endlocal
