param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VersionFile = Join-Path $ProjectRoot "VERSION"
if (-not $Version) {
    $Version = (Get-Content -Raw -LiteralPath $VersionFile).Trim()
}
if (-not $Version) {
    throw "Version is empty"
}

$ReleaseDirectory = Join-Path $ProjectRoot "release"
$ArchiveName = "xmu-gym-monitor-v$Version-windows.zip"
$ArchivePath = Join-Path $ReleaseDirectory $ArchiveName
$Prefix = "xmu-gym-monitor-v$Version/"

New-Item -ItemType Directory -Path $ReleaseDirectory -Force | Out-Null
if (Test-Path -LiteralPath $ArchivePath) {
    Remove-Item -LiteralPath $ArchivePath -Force
}

Push-Location $ProjectRoot
try {
    git archive `
        --format=zip `
        --prefix=$Prefix `
        --output=$ArchivePath `
        HEAD
}
finally {
    Pop-Location
}

Write-Host "Release archive created: $ArchivePath"
