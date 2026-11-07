@echo off
setlocal
cd /d "%~dp0"
echo === TurboWebDownloader Windows build ===
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or newer from python.org, then run this file again.
  pause
  exit /b 1
)
if not exist .venv py -3 -m venv .venv
if errorlevel 1 goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :error
pip install -r requirements-desktop.txt
if errorlevel 1 goto :error
set PLAYWRIGHT_BROWSERS_PATH=%CD%\build\browsers
python -m playwright install chromium
if errorlevel 1 goto :error
python scripts\make_icon.py
if errorlevel 1 goto :error
pyinstaller --noconfirm --clean --windowed --onedir --name TurboWebDownloader --icon turboweb\static\app.ico --collect-all playwright --add-data "turboweb\templates;turboweb/templates" --add-data "turboweb\static;turboweb/static" --add-data "build\browsers;browsers" desktop.py
if errorlevel 1 goto :error
echo.
echo Done! Run dist\TurboWebDownloader\TurboWebDownloader.exe
echo Distribute the ENTIRE dist\TurboWebDownloader folder, not just the EXE.
pause
exit /b 0
:error
echo Build failed. Review the error above.
pause
exit /b 1
