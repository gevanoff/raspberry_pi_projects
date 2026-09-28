param(
    [ValidateSet("controller", "self-test")]
    [string]$Target = "controller",
    [switch]$Upload,
    [string]$Port
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$teensyRoot = Join-Path $projectRoot "teensy"
$libraries = Join-Path $teensyRoot "libraries"
$sketch = if ($Target -eq "self-test") {
    Join-Path $teensyRoot "controller_self_test"
} else {
    Join-Path $teensyRoot "dual_stepper_controller"
}
$fqbn = "teensy:avr:teensy40:usb=serial,speed=600,opt=o2std,keys=en-us"

$arduinoCliCommand = Get-Command "arduino-cli" -ErrorAction SilentlyContinue
$arduinoCliPath = if ($arduinoCliCommand) { $arduinoCliCommand.Source } else { $null }
if (-not $arduinoCliPath) {
    $portableCli = Join-Path $env:LOCALAPPDATA "Programs\ArduinoCLI\arduino-cli.exe"
    if (Test-Path -LiteralPath $portableCli) {
        $arduinoCliPath = $portableCli
    }
}
if (-not $arduinoCliPath) {
    throw "arduino-cli was not found. Install it and the PJRC teensy:avr core first."
}

$coreList = & $arduinoCliPath core list --format json | ConvertFrom-Json
if (-not ($coreList.platforms | Where-Object { $_.id -eq "teensy:avr" -and $_.installed })) {
    throw "The PJRC teensy:avr core is not installed. See the Teensy setup section in README.md."
}

$arguments = @(
    "compile",
    "--fqbn", $fqbn,
    "--libraries", $libraries,
    "--warnings", "all"
)

if ($Upload) {
    if (-not $Port) {
        $boardList = & $arduinoCliPath board list --format json | ConvertFrom-Json
        $matches = @(
            $boardList.detected_ports |
                Where-Object { $_.matching_boards.fqbn -contains "teensy:avr:teensy40" }
        )
        if ($matches.Count -eq 0) {
            throw "No connected Teensy 4.0 upload port was found."
        }
        if ($matches.Count -gt 1) {
            $addresses = ($matches | ForEach-Object { $_.port.address }) -join ", "
            throw "Multiple Teensy 4.0 upload ports were found ($addresses). Use -Port."
        }
        $Port = $matches[0].port.address
    }
    $arguments += @("--upload", "--port", $Port)
}

$arguments += $sketch
& $arduinoCliPath @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
