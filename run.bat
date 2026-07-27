@echo off
setlocal

if /i not "%~1"=="--background" (
    start "" /b wscript.exe "%~dp0run.vbs"
    exit /b
)

cd /d "%~dp0"
set "UV_CACHE_DIR=%CD%\.cache\uv"
if not exist ".venv\Scripts\pythonw.exe" (
    if not exist "data\logs" mkdir "data\logs"
    uv venv --python 3.12 .venv >> "data\logs\launcher.log" 2>&1
    uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt >> "data\logs\launcher.log" 2>&1
)
set "PYTHONPATH=%CD%\src"
start "" /b ".venv\Scripts\pythonw.exe" -m digital_pet
exit /b
