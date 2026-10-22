@echo off
setlocal
cd /d "%~dp0"
set "MINIERP_PY="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 -c "import sys, tkinter, sqlite3; assert sys.version_info >= (3,12)" >nul 2>nul
    if not errorlevel 1 set "MINIERP_PY=py -3.12"
)
if not defined MINIERP_PY (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -c "import sys, tkinter, sqlite3; assert sys.version_info >= (3,12)" >nul 2>nul
        if not errorlevel 1 set "MINIERP_PY=py -3"
    )
)
if not defined MINIERP_PY (
    python -c "import sys, tkinter, sqlite3; assert sys.version_info >= (3,12)" >nul 2>nul
    if not errorlevel 1 set "MINIERP_PY=python"
)
if not defined MINIERP_PY (
    echo Python 3.12 or newer with Tcl/Tk is required.
    echo Install Python from https://www.python.org/downloads/windows/
    echo Enable the Python launcher and Tcl/Tk options, then try again.
    pause
    exit /b 1
)
if not defined LOCALAPPDATA (
    echo Windows LOCALAPPDATA is not available. Demo was not started.
    pause
    exit /b 1
)
echo Mini ERP - Synthetic demo. No EBS connection or accounting posting.
echo Data folder: %LOCALAPPDATA%\MiniERP\Demo
%MINIERP_PY% -m app.demo --data-dir "%LOCALAPPDATA%\MiniERP\Demo"
if errorlevel 1 (
    echo.
    echo The demo could not start. Keep this window open and share the error above.
    pause
    exit /b 1
)
endlocal
