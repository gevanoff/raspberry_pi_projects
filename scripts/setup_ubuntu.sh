#!/usr/bin/env bash
# =============================================================================
# setup_ubuntu.sh — Configure an Ubuntu (or Debian) desktop / laptop for
# Raspberry Pi development.
#
# Usage:
#   chmod +x scripts/setup_ubuntu.sh
#   ./scripts/setup_ubuntu.sh
#
# What this does:
#   1. Installs system packages (Python 3, Git, SSH tools, serial helpers)
#   2. Creates a local Python virtual environment (.venv/)
#   3. Installs development Python dependencies (requirements-dev.txt)
# =============================================================================

set -euo pipefail

# ── Helpers ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── 1. System packages ────────────────────────────────────────────────────────
info "Updating package lists…"
sudo apt-get update -qq

info "Installing system packages…"
sudo apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    git \
    curl \
    wget \
    openssh-client \
    sshpass \
    screen \
    minicom \
    nmap \
    avahi-daemon \
    avahi-utils \
    build-essential \
    libssl-dev \
    libffi-dev

# ── 2. Python virtual environment ────────────────────────────────────────────
VENV_DIR="${REPO_ROOT}/.venv"

if [[ -d "${VENV_DIR}" ]]; then
    warn "Virtual environment already exists at ${VENV_DIR} — skipping creation."
else
    info "Creating Python virtual environment at ${VENV_DIR}…"
    python3 -m venv "${VENV_DIR}"
fi

info "Upgrading pip inside the virtual environment…"
"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel

# ── 3. Python development dependencies ───────────────────────────────────────
info "Installing Python development dependencies…"
"${VENV_DIR}/bin/pip" install -r "${REPO_ROOT}/requirements-dev.txt"

# ── 4. (Optional) Add user to dialout group for serial port access ────────────
if ! groups "${USER}" | grep -q dialout; then
    info "Adding ${USER} to the 'dialout' group (needed for serial/USB access)…"
    sudo usermod -aG dialout "${USER}"
    warn "Log out and back in (or run 'newgrp dialout') for the group change to take effect."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Setup complete!"
echo -e "  Activate the virtual environment:  ${YELLOW}source .venv/bin/activate${NC}"
echo -e "  Deactivate when finished:          ${YELLOW}deactivate${NC}"
echo ""
echo -e "  Connect to your Pi (replace IP):   ${YELLOW}ssh pi@raspberrypi.local${NC}"
echo -e "  Copy files to Pi:                  ${YELLOW}scp -r projects/my_project pi@raspberrypi.local:~/${NC}"
