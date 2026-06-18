@echo off
cd /d "%~dp0"
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python 3.13 or later is required.
    echo Download from https://www.python.org/downloads/
    pause
    exit /b 1
)
python -m venv create Open_PS_Calc_venv
.\Open_PS_Calc_venv\bin\python.exe -m pip install --no-cache-dir -r requirements.txt
.\Open_PS_Calc_venv\bin\python.exe main.py
