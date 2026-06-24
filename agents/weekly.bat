@echo off
chcp 65001 > nul
setlocal

set "PY=C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe"
set "SCRIPT_DIR=%~dp0"
REM Secrets loaded from secrets.local.json by config.py
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%SCRIPT_DIR%"

REM Weekly: refresh module accuracy report (5-10 min)
REM Output: signals/module_accuracy.md (auto-injected into Claude prompt)
"%PY%" -X utf8 -u _backtest_modules_accuracy.py

echo.
pause
endlocal
