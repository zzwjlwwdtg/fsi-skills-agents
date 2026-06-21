@echo off
chcp 65001 > nul

set "PY=C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe"
set "SCRIPT_DIR=%~dp0"
REM FRED_API_KEY + MOOMOO_ACC_ID 通过 secrets.local.json 读（config.py 自动加载）
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

echo Trading Agents starting...
echo   TRADER_DRY_RUN=%TRADER_DRY_RUN%   (0=LIVE on moomoo SIMULATE, 1=dry log-only)
echo   CLAUDE_DECISION_GATE=%CLAUDE_DECISION_GATE%   (1=Claude pre-trade approval required)
echo   Tools menu: run tools.bat
echo   Log: logs\run_YYYYMMDD.log
echo.

"%PY%" -X utf8 orchestrator.py

pause
