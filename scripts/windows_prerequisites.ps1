# Windows PowerShell 5.1+. Also copied into the portable distribution.
[CmdletBinding()]
param(
    [string]$DownloadDirectory = (Join-Path $PSScriptRoot 'prerequisites'),
    [switch]$NonInteractive
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-VerifiedInstaller {
    param([string]$Url, [string]$Destination, [string]$Publisher)
    New-Item -ItemType Directory -Force -Path (Split-Path $Destination) | Out-Null
    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) {
        Write-Host "Downloading official installer: $Url"
        $temp = "$Destination.part"
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $temp -TimeoutSec 180
            Move-Item -Force -LiteralPath $temp -Destination $Destination
        } finally {
            if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
        }
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Destination
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch $Publisher) {
        Remove-Item -LiteralPath $Destination -Force
        throw "Installer signature verification failed: $Destination. Download only from the official vendor."
    }
    return $Destination
}

function Invoke-SystemInstaller {
    param([string]$Path, [string]$Arguments, [switch]$RequiresAdmin)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $admin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $start = @{ FilePath = $Path; ArgumentList = $Arguments; Wait = $true; PassThru = $true }
    if ($RequiresAdmin -and -not $admin) {
        if ($NonInteractive) { throw 'A system prerequisite needs administrator rights. Run this build as administrator or install that prerequisite manually.' }
        Write-Host 'Windows may request administrator permission for this official prerequisite installer.'
        $start.Verb = 'RunAs'
    }
    $process = Start-Process @start
    if ($process.ExitCode -eq 3010 -or $process.ExitCode -eq 1641) {
        throw 'A prerequisite was installed but Windows requires a restart. Restart Windows and run the build again.'
    }
    if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 1638) {
        throw "Prerequisite installer failed with exit code $($process.ExitCode): $Path"
    }
}

function Test-WebView2 {
    foreach ($key in @('HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients', 'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients')) {
        if (Test-Path $key) {
            foreach ($client in (Get-ChildItem $key -ErrorAction SilentlyContinue)) {
                $info = Get-ItemProperty $client.PSPath -ErrorAction SilentlyContinue
                if ($info.name -match 'WebView2' -and $info.pv -and $info.pv -ne '0.0.0.0') { return $true }
            }
        }
    }
    foreach ($root in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:LOCALAPPDATA)) {
        if ($root) {
            $path = Join-Path $root 'Microsoft\EdgeWebView\Application'
            if (Test-Path -LiteralPath $path) {
                foreach ($version in (Get-ChildItem -LiteralPath $path -Directory)) {
                    if (Test-Path -LiteralPath (Join-Path $version.FullName 'msedgewebview2.exe')) { return $true }
                }
            }
        }
    }
    return $false
}

function Test-VcRuntime {
    foreach ($key in @('HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64')) {
        $runtime = Get-ItemProperty $key -ErrorAction SilentlyContinue
        if ($runtime -and $runtime.Installed -eq 1) { return $true }
    }
    return $false
}

function Install-WindowsPrerequisites {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
        throw 'TurboWebDownloader builds require Windows 10/11 (or a compatible desktop Windows Server), x64. Windows ARM64 and 32-bit builds are not supported by this script.'
    }
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'Windows ARM64 is not supported by this x64 build script.'
    }
    $dotnet = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -ErrorAction SilentlyContinue
    if (-not $dotnet -or [int]$dotnet.Release -lt 528040) {
        $installer = Get-VerifiedInstaller 'https://go.microsoft.com/fwlink/?linkid=2088631' (Join-Path $DownloadDirectory 'dotnet48-web.exe') 'O=Microsoft Corporation'
        Invoke-SystemInstaller $installer '/q /norestart' -RequiresAdmin
        $dotnet = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -ErrorAction SilentlyContinue
        if (-not $dotnet -or [int]$dotnet.Release -lt 528040) { throw '.NET Framework 4.8 or newer is still missing. Restart Windows if installation requested it.' }
    }
    Write-Host '.NET Framework 4.8+: ready.'
    if (-not (Test-VcRuntime)) {
        $installer = Get-VerifiedInstaller 'https://aka.ms/vs/17/release/vc_redist.x64.exe' (Join-Path $DownloadDirectory 'vc_redist.x64.exe') 'O=Microsoft Corporation'
        Invoke-SystemInstaller $installer '/install /quiet /norestart' -RequiresAdmin
        if (-not (Test-VcRuntime)) { throw 'Microsoft Visual C++ x64 runtime is still missing.' }
    }
    Write-Host 'Microsoft Visual C++ x64 runtime: ready.'
    if (-not (Test-WebView2)) {
        $installer = Get-VerifiedInstaller 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' (Join-Path $DownloadDirectory 'MicrosoftEdgeWebview2Setup.exe') 'O=Microsoft Corporation'
        Invoke-SystemInstaller $installer '/silent /install'
        if (-not (Test-WebView2)) { throw 'WebView2 installation did not complete. Check Windows policy/network access or install Evergreen WebView2 from Microsoft, then retry.' }
    }
    Write-Host 'Microsoft Edge WebView2 runtime: ready.'
}

# Dot-sourcing exposes helpers to the build; direct execution installs prerequisites.
if ($MyInvocation.InvocationName -ne '.') {
    try { Install-WindowsPrerequisites; exit 0 }
    catch { Write-Host "Prerequisite setup failed: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
}
