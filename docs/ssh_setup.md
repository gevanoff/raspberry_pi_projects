# SSH Setup for Raspberry Pi

This guide covers everything you need to connect to your Pi reliably over SSH, including password-less key-based auth and common troubleshooting tips.

---

## 1. Enable SSH on the Pi

**Option A — during imaging (recommended):**  
Use Raspberry Pi Imager's ⚙️ Advanced Options to enable SSH before flashing.

**Option B — after boot (headless):**  
Place an empty file named `ssh` in the `/boot` (or `/boot/firmware` on Bookworm) partition of the SD card before first boot.

**Option C — on a running Pi:**

```bash
sudo systemctl enable ssh --now
```

---

## 2. Generate an SSH Key Pair (on your laptop)

If you don't already have a key, generate one:

```bash
ssh-keygen -t ed25519 -C "raspberry-pi-dev"
```

Accept the default location (`~/.ssh/id_ed25519`) and optionally set a passphrase.

---

## 3. Copy Your Public Key to the Pi

```bash
ssh-copy-id pi@raspberrypi.local
```

Or manually:

```bash
cat ~/.ssh/id_ed25519.pub | ssh pi@raspberrypi.local "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

After this, `ssh pi@raspberrypi.local` should log in without a password.

---

## 4. Create an SSH Config Shortcut

Add a block to `~/.ssh/config` (create the file if it doesn't exist):

```
Host pi
    HostName raspberrypi.local
    User pi
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 60
```

Now you can simply run:

```bash
ssh pi
scp myfile.py pi:~/
```

---

## 5. Copy Files to / from the Pi

**Single file:**

```bash
scp projects/my_project/main.py pi@raspberrypi.local:~/my_project/
```

**Entire directory:**

```bash
scp -r projects/my_project pi@raspberrypi.local:~/
```

**Using rsync (faster for repeated syncs):**

```bash
rsync -avz --exclude '__pycache__' projects/my_project pi@raspberrypi.local:~/
```

---

## 6. Run Commands Remotely

```bash
# Single command
ssh pi "python ~/my_project/main.py"

# Interactive session
ssh pi
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ssh: connect to host raspberrypi.local port 22: No route to host` | Ensure the Pi is on, on the same network, and SSH is enabled. Try IP address instead. |
| `Host key verification failed` | Remove the old key: `ssh-keygen -R raspberrypi.local` |
| Permission denied (publickey) | Confirm `~/.ssh/authorized_keys` on the Pi contains your public key; check permissions (`chmod 700 ~/.ssh`, `chmod 600 ~/.ssh/authorized_keys`). |
| Can't find Pi's IP | Run `nmap -sn 192.168.1.0/24` or check your router's device list. |

---

## 8. Windows Tips

- **PowerShell / Windows Terminal**: The built-in `ssh` client (installed by the setup script) works identically to Linux/macOS.
- **PuTTY**: GUI SSH client installed by `setup_windows.ps1`. Useful for beginners.
- **WinSCP**: GUI file transfer client, installed by `setup_windows.ps1`. Drag-and-drop files to/from the Pi.
- **SSH key location on Windows**: `%USERPROFILE%\.ssh\id_ed25519`

Generate a key in PowerShell the same way:

```powershell
ssh-keygen -t ed25519 -C "raspberry-pi-dev"
ssh-copy-id pi@raspberrypi.local   # requires sshpass; or paste key manually
```
