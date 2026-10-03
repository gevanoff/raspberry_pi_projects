# Projects

Each subdirectory here is a self-contained Raspberry Pi project.

## Creating a New Project

1. Copy the template:

   ```bash
   cp -r projects/template projects/<your_project_name>
   ```

2. Edit `projects/<your_project_name>/README.md` to describe your project.

3. Write your code in `main.py` (or add additional modules as needed).

4. Keep the project's own `requirements.txt` self-contained: list every pip-managed runtime dependency imported by that project. The deployment workflow copies only the project directory, so do not rely on repository-root requirements being preinstalled.

## Project Conventions

| File | Purpose |
|------|---------|
| `README.md` | What the project does, wiring diagram, usage instructions |
| `main.py` | Entry point — run this on the Pi |
| `requirements.txt` | Pi-specific runtime dependencies for this project |
| `.env.example` | Template for environment variables (commit this, **not** `.env`) |
| `tests/` | Unit tests that can run on any machine |

## Running a Project on the Pi

Replace `<username>` with the username configured in Raspberry Pi Imager.

```bash
# 1. Copy the project to the Pi
scp -r projects/my_project <username>@raspberrypi.local:~/

# 2. SSH in
ssh <username>@raspberrypi.local

# 3. On the Pi, create and activate a project virtual environment
cd ~/my_project
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 4. Run
python main.py
```

Raspberry Pi OS Bookworm marks the system Python as externally managed, so project dependencies should be installed in a virtual environment. The `--system-site-packages` option keeps OS-provided camera and other Raspberry Pi packages available. Each project's `requirements.txt` must still contain its own pip-managed runtime dependencies.

## Running Tests Locally (without a Pi)

```bash
source .venv/bin/activate
cd projects/my_project
pytest tests/
```

GPIO calls in tests are automatically mocked — see `mock_gpio.py` in the template.
