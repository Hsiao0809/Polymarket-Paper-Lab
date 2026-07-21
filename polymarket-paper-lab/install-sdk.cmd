@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Could not create the project virtual environment.
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-sdk.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 exit /b 1
call run.cmd sdk-check
endlocal
