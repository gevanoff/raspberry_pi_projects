# template

> **Replace this README with a description of your project.**

## What it does

_Describe your project here._

## Hardware

| Component | Pin / Connection |
|-----------|-----------------|
| Example LED | GPIO 17 (pin 11) |
| _Add your components_ | _..._ |

## Wiring Diagram

_Add a wiring diagram image or ASCII art here._

## Usage

On Raspberry Pi OS Bookworm or newer, install project packages in a virtual environment rather than the externally managed system Python:

```bash
# On the Raspberry Pi, from this project directory
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Using `--system-site-packages` keeps OS-provided Raspberry Pi libraries available inside the environment.

## Environment Variables

Copy `.env.example` to `.env` and fill in any required values:

```bash
cp .env.example .env
```

## Running Tests

```bash
# On your laptop/desktop (no Pi required)
cd projects/template
pytest tests/
```
