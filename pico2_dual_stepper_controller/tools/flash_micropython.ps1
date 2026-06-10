param(
    [ValidateSet("pico", "pico2")]
    [string]$BoardModel = "pico",
    [string]$DriveLabel = "RPI-RP2",
    [string]$DownloadDirectory = $(Join-Path $PSScriptRoot "downloads")
)

switch ($BoardModel) {
    "pico" {
        $FirmwareUrl = "https://micropython.org/download/rp2-pico/rp2-pico-latest.uf2"
        $DownloadFileName = "RP2040_PICO-latest.uf2"
    }
    "pico2" {
        $FirmwareUrl = "https://micropython.org/download/RPI_PICO2/RPI_PICO2-latest.uf2"
        $DownloadFileName = "RPI_PICO2-latest.uf2"
    }
}

$DownloadPath = Join-Path $DownloadDirectory $DownloadFileName

$volume = Get-Volume | Where-Object { $_.FileSystemLabel -eq $DriveLabel } | Select-Object -First 1
if (-not $volume) {
    throw "No mounted drive with label '$DriveLabel' was found. Put the Pico 2 into BOOTSEL mode first."
}

if (-not $volume.DriveLetter) {
    throw "The drive '$DriveLabel' is mounted but does not have a drive letter assigned."
}

if (-not (Test-Path $DownloadDirectory)) {
    New-Item -ItemType Directory -Path $DownloadDirectory | Out-Null
}

Invoke-WebRequest -Uri $FirmwareUrl -OutFile $DownloadPath

$destination = "$($volume.DriveLetter):\$(Split-Path -Leaf $DownloadPath)"
Copy-Item -Path $DownloadPath -Destination $destination -Force

Write-Host "Copied $(Split-Path -Leaf $DownloadPath) to $destination"
Write-Host "If the Pico does not reboot out of BOOTSEL mode automatically, unplug and reconnect it or tap reset, then continue with tools\\sync_micropython_files.ps1."