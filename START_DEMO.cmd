@echo off
setlocal EnableExtensions DisableDelayedExpansion
if /I "%~1"=="--check" goto check_mode
if /I "%~1"=="--run" goto run_mode
"%ComSpec%" /d /k call "%~f0" --run
exit /b

:check_mode
set "MINIERP_ARGS=--check"
goto detect_python

:run_mode
echo.
echo Mini ERP - startup diagnostics
set "MINIERP_ARGS="

:detect_python
cd /d "%~dp0"
if not exist "%~dp0START_DEMO.py" goto incomplete_package
if not exist "%~dp0app\demo.py" goto incomplete_package
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto try_python
py -3 "%~dp0START_DEMO.py" %MINIERP_ARGS%
exit /b %ERRORLEVEL%

:try_python
where python >nul 2>nul
if errorlevel 1 goto missing_python
python "%~dp0START_DEMO.py" %MINIERP_ARGS%
exit /b %ERRORLEVEL%

:incomplete_package
echo ERROR: The package is incomplete. Extract ALL files from the ZIP first.
echo Expected app\demo.py and START_DEMO.py next to this CMD file.
exit /b 1

:missing_python
echo ERROR: Python was not found through py or python on PATH.
echo You may have Python installed in another location.
echo This window stays open so the error can be read.
exit /b 1
