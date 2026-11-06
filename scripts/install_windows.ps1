param(
    [switch]$SkipDesktopShortcut
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$ExampleConfig = Join-Path $ProjectRoot "config\monitor_config.example.json"
$Config = Join-Path $ProjectRoot "config\monitor_config.json"

if (-not (Test-Path -LiteralPath $Requirements)) {
    throw "requirements.txt not found"
}

if (-not (Test-Path -LiteralPath $Python)) {
    python -m venv (Join-Path $ProjectRoot ".venv")
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r $Requirements

if (
    -not (Test-Path -LiteralPath $Config) -and
    (Test-Path -LiteralPath $ExampleConfig)
) {
    Copy-Item -LiteralPath $ExampleConfig -Destination $Config
}

if (-not $SkipDesktopShortcut) {
    & (Join-Path $PSScriptRoot "..\tools\create_desktop_shortcut.ps1")
}

Write-Host ""
Write-Host "Installation completed."
Write-Host "Start the desktop UI: tools\LaunchGymMonitor.exe"
Write-Host "Start background monitoring: tools\LaunchMonitorDaemon.exe"
