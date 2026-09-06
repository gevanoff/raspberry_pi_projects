param(
    [string]$Port,
    [string]$Command,
    [switch]$NoStopOnExit
)

$consoleScript = Join-Path $PSScriptRoot "controller_console.py"
$pythonArguments = @($consoleScript)
if ($Port) {
    $pythonArguments += @("--port", $Port)
}
if ($Command) {
    $pythonArguments += @("--command", $Command)
}
if ($NoStopOnExit) {
    $pythonArguments += "--no-stop-on-exit"
}

& py @pythonArguments
exit $LASTEXITCODE
