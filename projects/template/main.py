#!/usr/bin/env python3
"""
main.py — Entry point for the project.

Run on the Raspberry Pi:
    python main.py

Environment variables are loaded from a .env file if present.
"""

import os
import sys
import time

from dotenv import load_dotenv

# Load environment variables from .env (if it exists)
load_dotenv()

# ---------------------------------------------------------------------------
# Conditional GPIO import: use real hardware when running on a Pi,
# fall back to the mock library when developing on a laptop/desktop.
# ---------------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO  # type: ignore[import]
    ON_PI = True
except (ImportError, RuntimeError):
    from mock_gpio import GPIO  # noqa: F401  (provided in this template)
    ON_PI = False

# ---------------------------------------------------------------------------
# Configuration — override via environment variables or .env
# ---------------------------------------------------------------------------
LED_PIN: int = int(os.getenv("LED_PIN", "17"))
BLINK_INTERVAL: float = float(os.getenv("BLINK_INTERVAL", "1.0"))  # seconds


def setup() -> None:
    """Initialise GPIO."""
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LED_PIN, GPIO.OUT)
    GPIO.output(LED_PIN, GPIO.LOW)
    print(f"GPIO ready (running {'on Pi' if ON_PI else 'in mock mode'}).")


def loop() -> None:
    """Main application loop — blink the LED until interrupted."""
    print(f"Blinking LED on GPIO {LED_PIN} every {BLINK_INTERVAL}s. Press Ctrl+C to stop.")
    try:
        while True:
            GPIO.output(LED_PIN, GPIO.HIGH)
            time.sleep(BLINK_INTERVAL / 2)
            GPIO.output(LED_PIN, GPIO.LOW)
            time.sleep(BLINK_INTERVAL / 2)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")


def teardown() -> None:
    """Clean up GPIO state."""
    GPIO.cleanup()
    print("GPIO cleaned up.")


def main() -> int:
    setup()
    try:
        loop()
    finally:
        teardown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
