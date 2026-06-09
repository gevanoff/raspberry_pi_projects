# Getting Started with Raspberry Pi Development

This guide walks you through setting up your development environment on either **Ubuntu/Debian** or **Windows**, then connecting to your Raspberry Pi and deploying your first project.

---

## Prerequisites

| Item | Notes |
|------|-------|
| Raspberry Pi (any model) | Pi 3B+ / 4B / 5 recommended |
| MicroSD card (≥16 GB) | Class 10 / A1 or faster |
| [Raspberry Pi Imager](https://www.raspberrypi.com/software/) | Flashes the OS onto the card |
| Network connection | Pi and laptop on the same LAN |

---

## 1. Flash Raspberry Pi OS

1. Open **Raspberry Pi Imager**.
2. Choose **Raspberry Pi OS (64-bit)** (Bookworm or newer).
3. Click the ⚙️ **Advanced options** gear icon and:
   - Set a hostname (e.g. `raspberrypi`)
   - Enable **SSH** with a username/password or public key
   - Configure your Wi-Fi SSID and password
4. Flash to the SD card, insert it into the Pi, and power on.

---

## 2. Set Up Your Development Machine

### Ubuntu / Debian

```bash
git clone https://github.com/<your-username>/raspberry_pi_projects.git
cd raspberry_pi_projects
chmod +x scripts/setup_ubuntu.sh
./scripts/setup_ubuntu.sh
```

Activate the virtual environment before writing or running any Python code:

```bash
source .venv/bin/activate
```

### Windows (PowerShell — run as Administrator)

```powershell
git clone https://github.com/<your-username>/raspberry_pi_projects.git
cd raspberry_pi_projects
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_windows.ps1
```

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

---

## 3. Connect to the Pi via SSH

Once the Pi is booted and on your network:

```bash
# By hostname (requires avahi / mDNS)
ssh pi@raspberrypi.local

# By IP address
ssh pi@<IP_ADDRESS>
```

> **Tip:** Run `nmap -sn 192.168.1.0/24` to discover the Pi's IP if the hostname doesn't resolve.

See [docs/ssh_setup.md](ssh_setup.md) for SSH key configuration and other tips.

---

## 4. Repository Layout

```
raspberry_pi_projects/
├── .gitignore              # Ignores build artifacts, secrets, OS files
├── requirements.txt        # Pi runtime Python dependencies
├── requirements-dev.txt    # Dev-machine Python tooling
├── scripts/
│   ├── setup_ubuntu.sh     # Ubuntu/Debian dev-machine setup
│   └── setup_windows.ps1  # Windows dev-machine setup
├── docs/
│   ├── getting_started.md  # This file
│   └── ssh_setup.md        # SSH configuration guide
└── projects/
    ├── README.md           # How to create a new project
    └── template/           # Copy this to start a new project
```

---

## 5. Create a New Project

```bash
cp -r projects/template projects/my_new_project
cd projects/my_new_project
# Edit main.py and README.md
```

Deploy to the Pi:

```bash
scp -r projects/my_new_project pi@raspberrypi.local:~/
ssh pi@raspberrypi.local "cd ~/my_new_project && pip install -r requirements.txt && python main.py"
```

---

## 6. Run Tests Locally

```bash
source .venv/bin/activate          # or .venv\Scripts\Activate.ps1 on Windows
pytest --cov=. --cov-report=term-missing
```

---

## Useful Resources

- [Raspberry Pi Documentation](https://www.raspberrypi.com/documentation/)
- [gpiozero Documentation](https://gpiozero.readthedocs.io/)
- [Pinout.xyz — GPIO pin reference](https://pinout.xyz/)
- [paho-mqtt Python client](https://eclipse.dev/paho/files/paho.mqtt.python/html/index.html)
- [Adafruit CircuitPython / Blinka](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux)
