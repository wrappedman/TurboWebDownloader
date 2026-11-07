[CmdletBinding()]
param(
    [switch]$NoPause,
    [switch]$NonInteractive,
    [ValidateSet('Auto', 'Bundled', 'System')][string]$BrowserMode = 'Auto',
    [string]$PythonPath
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$build = Join-Path $root 'build'
New-Item -ItemType Directory -Force -Path (Join-Path $build 'logs') | Out-Null
$log = Join-Path $build ('logs\build-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
Start-Transcript -Path $log | Out-Null
$success = $false

function Invoke-NativeLog {
    param([string]$Exe, [string[]]$Arguments)
    if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "Executable not found: $Exe" }
    $previous = $ErrorActionPreference
    try {
        # In Windows PowerShell, stderr redirection creates ErrorRecords even for
        # successful native warnings. Log them, then rely on the actual exit code.
        $ErrorActionPreference = 'Continue'
        & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    return $code
}

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    $code = Invoke-NativeLog $Exe $Arguments
    if ($code -ne 0) { throw "Command failed ($code): $Exe $($Arguments -join ' ')" }
}

function Test-BuildPython {
    param([string]$Exe)
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) { return $false }
    try {
        $answer = & $Exe -c "import sys, struct; print('BUILD_OK' if (3,11) <= sys.version_info[:2] < (3,14) and struct.calcsize('P') == 8 else 'UNSUPPORTED')" 2>$null
        return ($LASTEXITCODE -eq 0 -and $answer -eq 'BUILD_OK')
    } catch { return $false }
}

function Find-BuildPython {
    if ($PythonPath) {
        if (-not (Test-BuildPython $PythonPath)) { throw 'The specified -PythonPath must be an existing Python 3.11-3.13 x64 executable.' }
        return $PythonPath
    }
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $candidates.Add((Join-Path $build 'tools\Python313\python.exe'))
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @('-3.13','-3.12','-3.11')) {
            try { $found = & $launcher.Source $version -c 'import sys; print(sys.executable)' 2>$null } catch { continue }
            if ($LASTEXITCODE -eq 0 -and $found) { $candidates.Add([string]$found) }
        }
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch 'WindowsApps') { $candidates.Add($command.Source) }
    foreach ($base in @($env:LOCALAPPDATA, $env:ProgramFiles)) {
        if ($base) {
            foreach ($version in @('313','312','311')) {
                $candidates.Add((Join-Path $base "Programs\Python\Python$version\python.exe"))
                $candidates.Add((Join-Path $base "Python$version\python.exe"))
            }
        }
    }
    foreach ($candidate in $candidates) { if (Test-BuildPython $candidate) { return $candidate } }
    Write-Host 'No compatible x64 build Python found. Installing a separate Python 3.13 (your current Python/venv will not be changed).'
    # Use the newest 3.13 release with a signed Windows installer on python.org.
    $listing = Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/' -TimeoutSec 60
    $versions = [regex]::Matches($listing.Content, 'href="(3\.13\.\d+)/"') | ForEach-Object { $_.Groups[1].Value } | Sort-Object { [version]$_ } -Descending -Unique
    $installer = $null
    foreach ($version in ($versions | Select-Object -First 12)) {
        try {
            $url = "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
            $installer = Get-VerifiedInstaller $url (Join-Path $build "downloads\python-$version-amd64.exe") 'O=Python Software Foundation'
            break
        } catch { Write-Host "Could not use Python $version installer: $($_.Exception.Message)" }
    }
    if (-not $installer) { throw 'Could not download a signed Python 3.13 installer. Install Python 3.11-3.13 x64 from python.org manually, or use -PythonPath. Check your network restrictions.' }
    $destination = Join-Path $build 'tools\Python313'
    Invoke-SystemInstaller $installer ('/quiet InstallAllUsers=0 Include_launcher=0 Include_test=0 PrependPath=0 TargetDir="' + $destination + '"')
    $exe = Join-Path $destination 'python.exe'
    if (-not (Test-BuildPython $exe)) { throw 'Python installation could not be verified. Check the installer log/Windows policy.' }
    return $exe
}

try {
    Write-Host "Build log: $log"
    # Runtime installation is explicit and may prompt for UAC/restart, never forced.
    . (Join-Path $PSScriptRoot 'windows_prerequisites.ps1') -DownloadDirectory (Join-Path $build 'downloads') -NonInteractive:$NonInteractive
    Install-WindowsPrerequisites
    Write-Host '[1/6] Select compatible Python'
    $python = Find-BuildPython
    Write-Host "Build Python: $python"
    Write-Host '[2/6] Prepare isolated build environment'
    $venv = Join-Path $build 'venv'
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    # This environment is private to the builder, not the application's .venv.
    $reset = -not (Test-BuildPython $venvPython)
    if (-not $reset) {
        $base = & $venvPython -c 'import sys; print(sys._base_executable)'
        $reset = ([string]$base -ne [string]$python)
    }
    if ($reset) {
        if (Test-Path -LiteralPath $venv) { Remove-Item -LiteralPath $venv -Recurse -Force }
        Invoke-Checked $python @('-m','venv',$venv)
    }
    Invoke-Checked $venvPython @('-m','pip','install','--upgrade','pip','setuptools','wheel')
    Invoke-Checked $venvPython @('-m','pip','install','-r',(Join-Path $root 'requirements-desktop.txt'))
    Invoke-Checked $venvPython @('-m','pip','check')
    Write-Host '[3/6] Prepare capture browser'
    $browsers = Join-Path $build 'browsers'
    $env:PLAYWRIGHT_BROWSERS_PATH = $browsers
    $bundled = $false
    if ($BrowserMode -ne 'System') {
        $code = Invoke-NativeLog $venvPython @('-m','playwright','install','chromium')
        $bundled = $code -eq 0
        if ($bundled) {
            $code = Invoke-NativeLog $venvPython @('-c',"from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); print('Bundled Chromium:', b.version); b.close(); p.stop()")
            $bundled = $code -eq 0
        }
        if (-not $bundled -and $BrowserMode -eq 'Bundled') { throw 'Bundled Chromium could not be downloaded/launched. A 403/location restriction cannot be repaired by this script. Use -BrowserMode System with installed Chrome/Edge, or configure a trusted PLAYWRIGHT_DOWNLOAD_HOST/proxy, then retry.' }
    }
    if (-not $bundled) {
        Write-Host 'Using an installed Chrome/Edge. This EXE distribution will require an installed browser for capture.' -ForegroundColor Yellow
        # Ignore any partial Playwright download and validate the real fallback.
        $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $build 'no-bundled-browser'
        Invoke-Checked $venvPython @('-c',"from playwright.sync_api import sync_playwright; from turboweb.browser import launch_browser; p=sync_playwright().start(); b,label=launch_browser(p); print('System browser:',label); b.close(); p.stop()")
        $env:PLAYWRIGHT_BROWSERS_PATH = $browsers
    }
    Write-Host '[4/6] Generate icon and validate imports'
    Invoke-Checked $venvPython @('scripts/make_icon.py')
    Invoke-Checked $venvPython @('-c',"import webview, clr; from turboweb.app import create_app; from turboweb.native import DesktopAPI; print('Desktop imports OK')")
    Write-Host '[5/6] Package application'
    $output = Join-Path $root 'dist\TurboWebDownloader'
    if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Force -Recurse }
    $arguments = @('-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir','--name','TurboWebDownloader',
        '--workpath',(Join-Path $build 'pyinstaller'),'--specpath',(Join-Path $build 'spec'),
        '--icon',(Join-Path $root 'turboweb/static/app.ico'),'--collect-all','playwright',
        '--hidden-import','webview.platforms.edgechromium','--hidden-import','webview.platforms.winforms',
        '--add-data',((Join-Path $root 'turboweb/templates') + ';turboweb/templates'),
        '--add-data',((Join-Path $root 'turboweb/static') + ';turboweb/static'))
    if ($bundled) { $arguments += @('--add-data',($browsers + ';browsers')) }
    $arguments += (Join-Path $root 'desktop.py')
    Invoke-Checked $venvPython $arguments
    Write-Host '[6/6] Verify and prepare portable distribution'
    $exe = Join-Path $output 'TurboWebDownloader.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw 'PyInstaller did not produce TurboWebDownloader.exe.' }
    $report = Join-Path $build 'logs\packaged-self-test.json'
    if (Test-Path -LiteralPath $report) { Remove-Item -LiteralPath $report -Force }
    $smoke = Start-Process -FilePath $exe -ArgumentList ('--self-test "' + $report + '"') -PassThru
    if (-not $smoke.WaitForExit(120000)) { $smoke.Kill(); throw 'Packaged EXE self-test timed out. See Windows security/antivirus policy.' }
    $smoke.Refresh()
    if (-not (Test-Path -LiteralPath $report)) { throw 'Packaged EXE could not write its self-test report. Check antivirus/quarantine and build logs.' }
    $check = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    if ($smoke.ExitCode -ne 0 -or -not $check.ok) { throw ("Packaged EXE self-test failed: " + $check.error) }
    Write-Host "Packaged EXE self-test passed ($($check.browser))."
    Copy-Item -LiteralPath (Join-Path $root 'README.md'), (Join-Path $root 'LICENSE') -Destination $output
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'windows_prerequisites.ps1') -Destination (Join-Path $output 'Install-prerequisites.ps1')
    @'
@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-prerequisites.ps1"
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
'@ | Set-Content -LiteralPath (Join-Path $output 'Install-prerequisites.bat') -Encoding Ascii
    $mode = 'system Chrome/Edge required'
    if ($bundled) { $mode = 'bundled Playwright Chromium' }
    @{
        built_at = (Get-Date).ToString('o'); python = (& $venvPython --version | Out-String).Trim();
        browser = $mode; windows = [Environment]::OSVersion.VersionString;
        note = 'Distribute the whole folder, not the EXE alone. A GUI launch must be checked on the destination PC.'
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'build-info.json') -Encoding UTF8
    "TurboWebDownloader`r`nRun TurboWebDownloader.exe. Keep _internal beside it.`r`nCapture browser: $mode.`r`nOn another PC, run Install-prerequisites.bat first (.NET 4.8+, WebView2, VC++ x64; internet/UAC may be needed).`r`nNo Python installation is required to RUN the EXE.`r`n" | Set-Content -LiteralPath (Join-Path $output 'START HERE.txt') -Encoding UTF8
    $zip = Join-Path $root 'dist\TurboWebDownloader-Windows-x64.zip'
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($output, $zip)
    Write-Host "SUCCESS: $exe" -ForegroundColor Green
    Write-Host "Portable ZIP: $zip"
    Write-Host "Browser mode: $mode"
    Write-Host 'Distribute the entire folder or ZIP, never just the EXE.'
    $success = $true
} catch {
    Write-Host "BUILD FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Details: $($_.ScriptStackTrace)"
    Write-Host "Log: $log"
} finally {
    Stop-Transcript | Out-Null
}
if ($success) { exit 0 } else { exit 1 }
