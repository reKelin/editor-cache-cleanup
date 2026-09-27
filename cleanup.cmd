@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not exist "%~dp0.venv\Scripts\python.exe" goto system_python
"%~dp0.venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul
if errorlevel 1 goto system_python
"%~dp0.venv\Scripts\python.exe" "%~dp0editor_cleanup.py" %*
goto finished

:system_python
python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul
if errorlevel 1 goto python_launcher
python "%~dp0editor_cleanup.py" %*
goto finished

:python_launcher
py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul
if errorlevel 1 goto missing_python
py -3 "%~dp0editor_cleanup.py" %*
goto finished

:missing_python
echo Python 3.9+ was not found. Install Python from https://www.python.org/downloads/
echo Enable "Add python.exe to PATH", then reopen this launcher.
if "%~1"=="" pause
exit /b 1

:finished
set "CLEANUP_EXIT=%errorlevel%"
if not "%~1"=="" exit /b %CLEANUP_EXIT%
pause
exit /b %CLEANUP_EXIT%
