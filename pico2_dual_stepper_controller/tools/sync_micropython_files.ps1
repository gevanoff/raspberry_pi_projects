param(
    [string]$ProjectRoot = $(Split-Path -Parent $PSScriptRoot)
)

$files = @(
    "config.py",
    "stepper.py",
    "main.py"
)

foreach ($file in $files) {
    $sourcePath = Join-Path $ProjectRoot "src\$file"
    py -m mpremote connect auto fs cp $sourcePath ":$file"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to copy $file to the Pico."
    }
}

py -m mpremote connect auto reset
if ($LASTEXITCODE -ne 0) {
    throw "Failed to reset the Pico after copying files."
}

Write-Host "Copied project files and reset the Pico."