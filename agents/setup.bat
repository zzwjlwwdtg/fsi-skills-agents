@echo off
echo Installing Trading Agents dependencies...
set PY=C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe

%PY% -m pip install openai schedule winotify --quiet
if %errorlevel% neq 0 (
    echo ERROR: pip install failed
    pause
    exit /b 1
)

echo.
echo Done. Required packages installed:
%PY% -m pip show openai schedule winotify 2>nul | findstr "Name Version"
echo.

rem Check OPENAI_API_KEY
if "%OPENAI_API_KEY%"=="" (
    echo WARNING: OPENAI_API_KEY is not set.
    echo   The decision agent will fall back to rule-based mode.
    echo   To enable GPT-4o-mini, run:
    echo     set OPENAI_API_KEY=sk-...
    echo   Or add it to your System Environment Variables.
) else (
    echo OPENAI_API_KEY is set. GPT-4o-mini decision engine enabled.
)
echo.
pause
