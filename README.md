# Raspberry Pi Projects

A collection of Raspberry Pi projects with a ready-to-use development environment for both **Windows** and **Ubuntu/Debian** machines.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/gevanoff/raspberry_pi_projects.git
cd raspberry_pi_projects

# Ubuntu / Debian
chmod +x scripts/setup_ubuntu.sh && ./scripts/setup_ubuntu.sh
source .venv/bin/activate

# Windows (PowerShell — run as Administrator)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_windows.ps1
.\.venv\Scripts\Activate.ps1
```

See **[docs/getting_started.md](docs/getting_started.md)** for the full onboarding guide, including flashing Raspberry Pi OS and SSH configuration.

## Repository Layout

```
raspberry_pi_projects/
├── .gitignore              # Python, OS, IDE, Pi-specific ignores
├── requirements.txt        # Pi runtime Python dependencies
├── requirements-dev.txt    # Dev-machine tooling (lint, test, SSH helpers)
├── scripts/
│   ├── setup_ubuntu.sh     # One-shot Ubuntu dev-machine setup
│   └── setup_windows.ps1  # One-shot Windows dev-machine setup
├── docs/
│   ├── getting_started.md  # Full onboarding guide
│   └── ssh_setup.md        # SSH keys, config shortcuts, troubleshooting
└── projects/
    ├── README.md           # Per-project conventions
    └── template/           # Copy this to start a new project
        ├── main.py         # Entry point with GPIO mock fallback
        ├── mock_gpio.py    # Lightweight RPi.GPIO mock for non-Pi machines
        ├── requirements.txt
        ├── .env.example
        └── tests/
            └── test_template.py
```

## Creating a New Project

```bash
cp -r projects/template projects/my_project
# Edit projects/my_project/README.md and main.py
```

## Running Tests (no Pi required)

```bash
source .venv/bin/activate
cd projects/template
pytest tests/ -v
```
