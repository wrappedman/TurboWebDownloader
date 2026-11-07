@echo off
setlocal
cd /d "%~dp0"
echo === Start TurboWebDownloader ===
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or newer from python.org, then run this file again.
  pause
  exit /b 1
)
if not exist .venv py -3 -m venv .venv
if errorlevel 1 goto :error
call .venv\Scripts\activate.bat
python -m pip install -r requirements-desktop.txt
if errorlevel 1 goto :error
python -m playwright install chromium
if errorlevel 1 goto :error
python desktop.py
if errorlevel 1 goto :error
exit /b 0
:error
echo Startup failed. Review the error above.
echo For web mode, activate .venv and run: python run.py
pause
exit /b 1
