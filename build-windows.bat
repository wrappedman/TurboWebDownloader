@echo off
setlocal
cd /d "%~dp0"
echo === TurboWebDownloader Windows build ===
where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo Windows PowerShell 5.1 or newer is required. Windows 10/11 x64 is supported.
  pause
  exit /b 1
)
set "BUILD_PS=powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "BUILD_PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%BUILD_PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows.ps1" %*
set "BUILD_RESULT=%ERRORLEVEL%"
if not "%BUILD_RESULT%"=="0" echo Build failed. See build\logs for the complete diagnostic log.
for %%A in (%*) do if /I "%%~A"=="-NoPause" goto :finished
pause
:finished
exit /b %BUILD_RESULT%
