param(
    [string]$ImagePath = "",
    [switch]$Circular
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Desktop = [Environment]::GetFolderPath("Desktop")
$Assets = Join-Path $ProjectRoot "assets"
$IconFileName = if ($Circular) {
    "gym-monitor-round.ico"
}
else {
    "gym-monitor.ico"
}
$IconPath = Join-Path $Assets $IconFileName
$Launcher = Join-Path $ProjectRoot "tools\LaunchGymMonitor.exe"
$ShortcutPath = Join-Path $Desktop "厦大健身房空位监控.lnk"

if (-not $ImagePath) {
    & (Join-Path $PSScriptRoot "create_desktop_shortcut.ps1")
    exit 0
}

if (-not (Test-Path -LiteralPath $ImagePath)) {
    throw "Icon image not found: $ImagePath"
}
if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "GUI launcher not found: $Launcher"
}

New-Item -ItemType Directory -Path $Assets -Force | Out-Null
Add-Type -AssemblyName System.Drawing

$sizes = @(16, 32, 48, 64, 128, 256)
$source = [System.Drawing.Image]::FromFile($ImagePath)
$pngPayloads = New-Object System.Collections.Generic.List[byte[]]

try {
    foreach ($size in $sizes) {
        $bitmap = [System.Drawing.Bitmap]::new(
            $size,
            $size,
            [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
        )
        try {
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            try {
                $graphics.InterpolationMode =
                    [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.SmoothingMode =
                    [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                $graphics.PixelOffsetMode =
                    [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                if ($Circular) {
                    $graphics.Clear(
                        [System.Drawing.Color]::Transparent
                    )
                    $padding = [Math]::Max(
                        1,
                        [Math]::Round($size * 0.03)
                    )
                    $innerSize = $size - (2 * $padding)
                    $circle = New-Object System.Drawing.Drawing2D.GraphicsPath
                    try {
                        $circle.AddEllipse(
                            $padding,
                            $padding,
                            $innerSize,
                            $innerSize
                        )
                        $graphics.SetClip($circle)
                        $graphics.DrawImage(
                            $source,
                            $padding,
                            $padding,
                            $innerSize,
                            $innerSize
                        )
                    }
                    finally {
                        $circle.Dispose()
                    }
                }
                else {
                    $graphics.DrawImage($source, 0, 0, $size, $size)
                }
            }
            finally {
                $graphics.Dispose()
            }

            $stream = New-Object System.IO.MemoryStream
            try {
                $bitmap.Save(
                    $stream,
                    [System.Drawing.Imaging.ImageFormat]::Png
                )
                $pngPayloads.Add($stream.ToArray())
            }
            finally {
                $stream.Dispose()
            }
        }
        finally {
            $bitmap.Dispose()
        }
    }
}
finally {
    $source.Dispose()
}

$fileStream = [System.IO.File]::Open(
    $IconPath,
    [System.IO.FileMode]::Create,
    [System.IO.FileAccess]::Write
)
try {
    $writer = New-Object System.IO.BinaryWriter($fileStream)
    try {
        $writer.Write([UInt16]0)
        $writer.Write([UInt16]1)
        $writer.Write([UInt16]$pngPayloads.Count)

        $offset = 6 + (16 * $pngPayloads.Count)
        for ($index = 0; $index -lt $pngPayloads.Count; $index++) {
            $size = $sizes[$index]
            $dimension = if ($size -eq 256) { 0 } else { $size }
            $payload = $pngPayloads[$index]
            $writer.Write([byte]$dimension)
            $writer.Write([byte]$dimension)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([UInt16]1)
            $writer.Write([UInt16]32)
            $writer.Write([UInt32]$payload.Length)
            $writer.Write([UInt32]$offset)
            $offset += $payload.Length
        }
        foreach ($payload in $pngPayloads) {
            $writer.Write($payload)
        }
    }
    finally {
        $writer.Dispose()
    }
}
finally {
    $fileStream.Dispose()
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $Launcher
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.IconLocation = "$IconPath,0"
$shortcut.Description = "打开厦大体育健身房空位监控"
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Host "Desktop shortcut: $ShortcutPath"
Write-Host "Icon: $IconPath"
