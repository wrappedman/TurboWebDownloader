@echo off
setlocal
cd /d "%~dp0"
echo === TurboWebDownloader - Web mode ===
if exist ".venv\Scripts\python.exe" goto :setup
python --version >nul 2>nul
if errorlevel 1 goto :try_launcher
python -m venv .venv
if errorlevel 1 goto :error
goto :setup
:try_launcher
py -3 --version >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or newer from python.org, then run this file again.
  pause
  exit /b 1
)
py -3 -m venv .venv
if errorlevel 1 goto :error
:setup
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Python 3.11 or newer is required. Recreate .venv using a supported Python version.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m turboweb.browser
if errorlevel 1 echo Browser detection failed. The app will still start; see capture logs for details.
echo.
echo Open http://127.0.0.1:8080 in your browser after the server starts.
echo Keep this window open while using the app. Press Ctrl+C to stop.
".venv\Scripts\python.exe" run.py
if errorlevel 1 goto :error
exit /b 0
:error
echo.
echo Setup or startup failed. Review the error above.
echo Installing Python dependencies requires an internet connection.
pause
exit /b 1
