$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Desktop = [Environment]::GetFolderPath("Desktop")
$Launcher = Join-Path $ProjectRoot "tools\LaunchGymMonitor.exe"
$IconPath = Join-Path $ProjectRoot "assets\gym-monitor-round.ico"
$ShortcutPath = Join-Path $Desktop "厦大健身房空位监控.lnk"

if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "GUI launcher not found: $Launcher"
}
if (-not (Test-Path -LiteralPath $IconPath)) {
    throw "Icon not found: $IconPath"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $Launcher
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.IconLocation = "$IconPath,0"
$shortcut.Description = "打开厦大体育健身房空位监控"
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Host "Desktop shortcut created: $ShortcutPath"
