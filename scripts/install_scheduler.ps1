param(
    [string]$TaskName = "XMU Gym Monitor",
    [string]$StartAt = "",
    [int]$IntervalMinutes = 0,
    [switch]$AtLogon,
    [switch]$WakeToRun,
    [switch]$DryRun,
    [switch]$KeepTaskXml,
    [string]$ConfigPath = "",
    [string]$DatabasePath = ""
)

$ErrorActionPreference = "Stop"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$AppPath = Join-Path $ProjectRoot "app.py"
$ConfigPath = if ($ConfigPath) {
    [System.IO.Path]::GetFullPath($ConfigPath)
} else {
    Join-Path $ProjectRoot "config\monitor_config.json"
}
$DatabasePath = if ($DatabasePath) {
    [System.IO.Path]::GetFullPath($DatabasePath)
} else {
    Join-Path $ProjectRoot "data\monitor_state.sqlite3"
}

if (-not (Test-Path -LiteralPath $Pythonw)) {
    throw "Pythonw not found: $Pythonw"
}
if (-not (Test-Path -LiteralPath $AppPath)) {
    throw "Application entry not found: $AppPath"
}

if ($IntervalMinutes -le 0) {
    if (Test-Path -LiteralPath $ConfigPath) {
        $config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
        $IntervalMinutes = [int]$config.check_interval_minutes
    }
}
if ($IntervalMinutes -lt 5) {
    $IntervalMinutes = 5
}
if ($IntervalMinutes -gt 60) {
    throw "IntervalMinutes must not exceed 60."
}

$startDateTime = if ($StartAt) {
    [datetime]::Parse($StartAt)
} else {
    (Get-Date).AddMinutes(1)
}
$userId = "$env:USERDOMAIN\$env:USERNAME"
$escapedUser = [System.Security.SecurityElement]::Escape($userId)
$escapedPython = [System.Security.SecurityElement]::Escape($Pythonw)
$arguments = (
    '"{0}" --run-once --config "{1}" --database "{2}"' -f
    $AppPath,
    $ConfigPath,
    $DatabasePath
)
$escapedArguments = [System.Security.SecurityElement]::Escape($arguments)
$escapedWorkingDirectory = [System.Security.SecurityElement]::Escape($ProjectRoot)
$startBoundary = $startDateTime.ToString("yyyy-MM-ddTHH:mm:ss")

if ($AtLogon) {
    $triggerXml = @"
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$escapedUser</UserId>
      <Repetition>
        <Interval>PT${IntervalMinutes}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </LogonTrigger>
"@
} else {
    $triggerXml = @"
    <TimeTrigger>
      <Repetition>
        <Interval>PT${IntervalMinutes}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>$startBoundary</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
"@
}

$wakeValue = if ($WakeToRun) { "true" } else { "false" }
$taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$escapedUser</Author>
    <Description>XMU gym read-only availability monitor, every $IntervalMinutes minutes.</Description>
  </RegistrationInfo>
  <Triggers>
$triggerXml
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$escapedUser</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>$wakeValue</WakeToRun>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$escapedPython</Command>
      <Arguments>$escapedArguments</Arguments>
      <WorkingDirectory>$escapedWorkingDirectory</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$tempXml = Join-Path ([System.IO.Path]::GetTempPath()) (
    "xmu-gym-monitor-{0}.xml" -f [guid]::NewGuid().ToString("N")
)
try {
    [System.IO.File]::WriteAllText(
        $tempXml,
        $taskXml,
        [System.Text.Encoding]::Unicode
    )
    if ($DryRun) {
        Write-Host "Dry run: task XML generated successfully."
        Write-Host "Task XML: $tempXml"
        return
    }
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & schtasks.exe /Create /TN $TaskName /XML $tempXml /F
        $taskExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($taskExitCode -ne 0) {
        throw "schtasks failed with exit code $taskExitCode"
    }
} finally {
    if ($KeepTaskXml) {
        Write-Host "Task XML kept at: $tempXml"
    } else {
        Remove-Item -LiteralPath $tempXml -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Interval: $IntervalMinutes minutes"
Write-Host "WakeToRun: $($WakeToRun.IsPresent)"
Write-Host "Logon mode: Interactive current user (works while locked, not while signed out)"
Write-Host "Config: $ConfigPath"
Write-Host "Database: $DatabasePath"
