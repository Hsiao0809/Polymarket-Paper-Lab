@echo off
setlocal EnableDelayedExpansion
set "PYTHONPATH=%~dp0;%~dp0src"
set "PYTHON_EXE=python"
set "PYTHON_ARGS="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 if not exist "%~dp0.venv\Scripts\python.exe" (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.12"
)
if /I "%~1"=="test" (
  "%PYTHON_EXE%" %PYTHON_ARGS% -m unittest -v tests.test_model tests.test_decision tests.test_polymarket tests.test_strategies
) else (
  "%PYTHON_EXE%" %PYTHON_ARGS% -m paperlab.cli %*
)
endlocal
