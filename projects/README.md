# Projects

Each subdirectory here is a self-contained Raspberry Pi project.

## Creating a New Project

1. Copy the template:

   ```bash
   cp -r projects/template projects/<your_project_name>
   ```

2. Edit `projects/<your_project_name>/README.md` to describe your project.

3. Write your code in `main.py` (or add additional modules as needed).

4. Add any project-specific Python dependencies to the project's own `requirements.txt`.

## Project Conventions

| File | Purpose |
|------|---------|
| `README.md` | What the project does, wiring diagram, usage instructions |
| `main.py` | Entry point — run this on the Pi |
| `requirements.txt` | Pi-specific runtime dependencies for this project |
| `.env.example` | Template for environment variables (commit this, **not** `.env`) |
| `tests/` | Unit tests that can run on any machine |

## Running a Project on the Pi

```bash
# 1. Copy the project to the Pi
scp -r projects/my_project pi@raspberrypi.local:~/

# 2. SSH in and install dependencies
ssh pi@raspberrypi.local
cd ~/my_project
pip install -r requirements.txt

# 3. Run
python main.py
```

## Running Tests Locally (without a Pi)

```bash
source .venv/bin/activate
cd projects/my_project
pytest tests/
```

GPIO calls in tests are automatically mocked — see `mock_gpio.py` in the template.
