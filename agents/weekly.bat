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

REM Weekly: recalibrate confluence weights + confidence percentiles (~1-2 min)
REM Output: signals/confidence_calibration.json (read by confluence.py + decision_agent.py)
"%PY%" -X utf8 -u _calibrate_confidence.py

REM Weekly: benchmark NAV vs SPY/QQQ (alpha + sharpe + max DD)
REM Output: signals/benchmark_report.md
"%PY%" -X utf8 -u _benchmark_report.py

REM Weekly: trade postmortem (BUY/SELL pairing + attribution)
REM Output: signals/trade_postmortem.md (after enough live trades)
"%PY%" -X utf8 -u _trade_postmortem.py

REM Weekly: data source health check (yfinance / FRED / moomoo / Claude CLI / calibration / HMM)
"%PY%" -X utf8 -u _data_source_health.py

echo.
pause
endlocal
