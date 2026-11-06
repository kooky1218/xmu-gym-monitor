param(
    [string]$TaskName = "XMU Gym Monitor"
)

$ErrorActionPreference = "Stop"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & schtasks.exe /Query /TN $TaskName 2>$null | Out-Null
    $queryExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorAction
}
if ($queryExitCode -ne 0) {
    Write-Host "Scheduled task not found: $TaskName"
    exit 0
}

$ErrorActionPreference = "Continue"
try {
    & schtasks.exe /Delete /TN $TaskName /F
    $deleteExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorAction
}
if ($deleteExitCode -ne 0) {
    throw "schtasks failed with exit code $deleteExitCode"
}
Write-Host "Removed scheduled task: $TaskName"
