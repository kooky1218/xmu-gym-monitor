param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("A", "B", "C", "D")]
    [string]$Scenario,

    [string]$TargetDate = "2026-11-03",
    [string]$Output = ""
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $ProjectRoot "logs\auth_diagnostic.jsonl"
}

$env:PYTHONUTF8 = "1"
& (Join-Path $ProjectRoot ".venv\Scripts\python.exe") `
    -m tools.run_auth_diagnostic `
    --scenario $Scenario `
    --target-date $TargetDate `
    --output $Output

exit $LASTEXITCODE
