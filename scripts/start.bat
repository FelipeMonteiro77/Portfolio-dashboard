@echo off
REM Portfolio Dashboard v2 — local launcher.
REM Starts the FastAPI backend, waits a moment, then opens the dashboard in
REM the default browser.

cd /d "%~dp0\.."
echo Starting Portfolio Dashboard v2 backend on http://127.0.0.1:8766 ...
start "" "py" -3.11 -m uvicorn backend.server:app --host 127.0.0.1 --port 8766
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8766/"
