@echo off
chcp 65001 > nul
setlocal

REM Public snapshot generator - freezes webui state to docs/ for GitHub Pages
REM Schedule via Windows Task Scheduler every 30 minutes.

set "PY=C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe"
set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%..\"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%SCRIPT_DIR%"

REM 1. Regenerate docs/data/*.json + docs/index.html from live webui
"%PY%" -X utf8 -u snapshot_generator.py
if errorlevel 1 (
  echo snapshot_generator failed - aborting commit
  goto :end
)

REM 2. Auto-commit + push docs/ to main branch (weekly manual squash to keep history clean)
cd /d "%REPO_ROOT%"
git add docs/
git diff --cached --quiet
if not errorlevel 1 (
  echo no changes to commit
  goto :end
)
git commit -m "snapshot: docs auto-refresh %DATE% %TIME%"
git push origin main

:end
endlocal
