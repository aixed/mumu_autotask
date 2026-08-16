@echo off
setlocal
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"

where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    start "" /b pythonw.exe -m mumu_autotask.gui --config "%~dp0config.json"
    exit /b 0
)

where pyw.exe >nul 2>nul
if not errorlevel 1 (
    start "" /b pyw.exe -3 -m mumu_autotask.gui --config "%~dp0config.json"
    exit /b 0
)

where python.exe >nul 2>nul
if not errorlevel 1 goto use_python

echo Python 3 was not found. Install Python 3.11 or newer and try again.
pause
exit /b 1

:use_python
python.exe -m mumu_autotask.gui --config "%~dp0config.json"
if errorlevel 1 goto launch_failed
exit /b 0

:launch_failed
pause
exit /b 1
