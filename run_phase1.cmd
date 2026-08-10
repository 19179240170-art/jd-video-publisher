@echo off
setlocal
set "PYTHON_EXE=python"
"%PYTHON_EXE%" "%~dp0run_phase1.py" --config "%~dp0config.json" %*
exit /b %ERRORLEVEL%
