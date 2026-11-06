param(
    [int]$DelaySeconds = 15
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Output = Join-Path $ProjectRoot "work\lock_test_result.json"
$ErrorOutput = Join-Path $ProjectRoot "work\lock_test_error.txt"
$Work = Join-Path $ProjectRoot "work"

New-Item -ItemType Directory -Path $Work -Force | Out-Null
Set-Location $ProjectRoot
Start-Sleep -Seconds $DelaySeconds

$startedAt = Get-Date
$stateBefore = & $Python -c "import json; from src.platform.windows_state import snapshot_windows_state; print(json.dumps(snapshot_windows_state(), ensure_ascii=False))"
$readerOutput = & $Python -m src.monitor.miniprogram_reader --no-cache 2> $ErrorOutput
$readerExitCode = $LASTEXITCODE
$stateAfter = & $Python -c "import json; from src.platform.windows_state import snapshot_windows_state; print(json.dumps(snapshot_windows_state(), ensure_ascii=False))"
$finishedAt = Get-Date

$document = [PSCustomObject]@{
    started_at = $startedAt.ToString("o")
    finished_at = $finishedAt.ToString("o")
    workstation_locked_before = (
        $stateBefore | ConvertFrom-Json
    ).workstation_locked
    workstation_locked_after = (
        $stateAfter | ConvertFrom-Json
    ).workstation_locked
    reader_exit_code = $readerExitCode
    reader_result = $readerOutput | ConvertFrom-Json
    state_before = $stateBefore | ConvertFrom-Json
    state_after = $stateAfter | ConvertFrom-Json
}
$document |
    ConvertTo-Json -Depth 12 |
    Set-Content -LiteralPath $Output -Encoding UTF8
