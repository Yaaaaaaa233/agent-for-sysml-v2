@echo off
REM sysml-modeling-agent -- one-shot test runner (Windows companion to run_tests.sh)
REM
REM   tests\run_tests.bat
REM
REM Standard library unittest only; no pytest needed.

setlocal EnableDelayedExpansion

set "HERE=%~dp0"
for %%I in ("%HERE%..") do set "ROOT=%%~fI"

if defined PYTHON (
  set "PY=%PYTHON%"
) else if exist "%ROOT%\.venv\Scripts\python.exe" (
  set "PY=%ROOT%\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo == sysml-modeling-agent tests ==
echo    interpreter : %PY%
echo    repo root   : %ROOT%
echo.

cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%\mcp-server;%PYTHONPATH%"

"%PY%" -m unittest discover -s tests -t tests -p "test_*.py" %*
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (echo.) else (echo TESTS FAILED with exit code %RC%)
endlocal & exit /b %RC%
