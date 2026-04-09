@echo off
cd /d "%~dp0"
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python 3.13 or later is required.
    echo Download from https://www.python.org/downloads/
    pause
    exit /b 1
)
python -m pip install -r requirements.txt --quiet
python main.py
