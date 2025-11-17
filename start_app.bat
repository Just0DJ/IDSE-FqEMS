@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel% neq 0 (
  where python >nul 2>nul || (echo Python not found. Install Python 3.10+ and try again.& pause & exit /b 1)
  if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
  )
) else (
  if not exist .venv (
    echo Creating virtual environment...
    py -m venv .venv
  )
)

call ".venv\Scripts\activate.bat"

python -m pip install --upgrade pip
pip install fastapi uvicorn jinja2 pandas numpy matplotlib xlsxwriter plotly

set ADMIN_USER=admin
set ADMIN_PASS=admin
set SMTP_HOST=
set SMTP_PORT=587
set SMTP_USER=
set SMTP_PASS=
set EMAIL_FROM=

uvicorn app:app --host 127.0.0.1 --port 8000 --reload