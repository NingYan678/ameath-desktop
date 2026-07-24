@echo off
setlocal
cd /d "%~dp0"
set "UV_CACHE_DIR=%CD%\.cache\uv"
if not exist ".venv\Scripts\python.exe" uv venv --python 3.12 .venv
uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt
set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -m digital_pet
