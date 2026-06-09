# =============================================================================
# setup_windows.ps1 — Configure a Windows 10/11 machine for Raspberry Pi
# development.
#
# Usage (run in PowerShell as Administrator):
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\setup_windows.ps1
#
# What this does:
#   1. Installs winget packages: Python, Git, PuTTY, WinSCP
#   2. Enables the built-in OpenSSH client Windows feature
#   3. Creates a local Python virtual environment (.venv\)
#   4. Installs development Python dependencies (requirements-dev.txt)
# =============================================================================

#Requires -Version 5.1

param(
    [switch]$SkipWinget,   # Use -SkipWinget to bypass package installation
    [switch]$NoVenv        # Use -NoVenv to skip virtual environment creation
)

$ErrorActionPreference = "Stop"

# ── Helpers ───────────────────────────────────────────────────────────────────
function Write-Step  { param($msg) Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "  [OK]  $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red; exit 1 }

$RepoRoot = Split-Path -Parent $PSScriptRoot

# ── 1. winget packages ────────────────────────────────────────────────────────
if (-not $SkipWinget) {
    Write-Step "Checking for winget…"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Fail "winget is not available.  Install the App Installer from the Microsoft Store, or re-run with -SkipWinget."
    }
    Write-Ok "winget found."

    $packages = @(
        @{ Id = "Python.Python.3.12";   Name = "Python 3.12"   },
        @{ Id = "Git.Git";              Name = "Git"            },
        @{ Id = "PuTTY.PuTTY";         Name = "PuTTY"          },
        @{ Id = "WinSCP.WinSCP";        Name = "WinSCP"         }
    )

    foreach ($pkg in $packages) {
        Write-Step "Installing $($pkg.Name)…"
        $result = winget install --id $pkg.Id --silent --accept-package-agreements --accept-source-agreements 2>&1
        if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq -1978335189) {
            # Exit code -1978335189 (0x8A150011) means "already installed"
            Write-Ok "$($pkg.Name) is ready."
        } else {
            Write-Warn "winget exited with code $LASTEXITCODE for $($pkg.Name) — check output above."
        }
    }
}

# ── 2. OpenSSH client (Windows optional feature) ─────────────────────────────
Write-Step "Enabling OpenSSH Client Windows feature…"
$sshFeature = Get-WindowsCapability -Online -Name "OpenSSH.Client*" -ErrorAction SilentlyContinue
if ($null -eq $sshFeature -or $sshFeature.State -ne "Installed") {
    try {
        Add-WindowsCapability -Online -Name "OpenSSH.Client~~~~0.0.1.0" | Out-Null
        Write-Ok "OpenSSH Client enabled."
    } catch {
        Write-Warn "Could not enable OpenSSH Client automatically: $_"
        Write-Warn "Enable it manually via Settings > Apps > Optional Features > OpenSSH Client."
    }
} else {
    Write-Ok "OpenSSH Client is already installed."
}

# ── 3. Refresh PATH ───────────────────────────────────────────────────────────
Write-Step "Refreshing PATH…"
$machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
$userPath    = [System.Environment]::GetEnvironmentVariable("PATH", "User")
$env:PATH    = "$machinePath;$userPath"

# ── 4. Python virtual environment ────────────────────────────────────────────
if (-not $NoVenv) {
    Write-Step "Locating Python…"
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Fail "Python not found in PATH.  Make sure Python 3.12 was installed and open a new terminal."
    }
    Write-Ok "Using Python: $($python.Source)"

    $venvDir = Join-Path $RepoRoot ".venv"

    if (Test-Path $venvDir) {
        Write-Warn ".venv already exists — skipping creation."
    } else {
        Write-Step "Creating Python virtual environment at $venvDir…"
        python -m venv $venvDir
        Write-Ok "Virtual environment created."
    }

    Write-Step "Upgrading pip…"
    & "$venvDir\Scripts\pip.exe" install --upgrade pip setuptools wheel | Out-Null

    Write-Step "Installing development dependencies…"
    & "$venvDir\Scripts\pip.exe" install -r "$RepoRoot\requirements-dev.txt"
    Write-Ok "Dependencies installed."
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Activate virtual environment (PowerShell):" -ForegroundColor White
Write-Host "    .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Activate virtual environment (Command Prompt):" -ForegroundColor White
Write-Host "    .venv\Scripts\activate.bat" -ForegroundColor Yellow
Write-Host ""
Write-Host "  SSH to your Pi (replace IP / hostname):" -ForegroundColor White
Write-Host "    ssh pi@raspberrypi.local" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Copy a project to the Pi:" -ForegroundColor White
Write-Host "    scp -r projects\my_project pi@raspberrypi.local:~/" -ForegroundColor Yellow
