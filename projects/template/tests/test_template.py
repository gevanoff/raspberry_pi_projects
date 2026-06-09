"""
Tests for the template project.

These tests run on any machine (no Pi hardware required).
GPIO calls are intercepted by mock_gpio.
"""

import sys
import os

import pytest

# Ensure the project directory is on the path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub out RPi.GPIO before importing main so the mock is used
import mock_gpio  # noqa: E402
sys.modules.setdefault("RPi", type(sys)("RPi"))
sys.modules.setdefault("RPi.GPIO", mock_gpio.GPIO)  # type: ignore[assignment]


class TestMockGPIO:
    """Verify that mock_gpio behaves like a minimal subset of RPi.GPIO."""

    def setup_method(self) -> None:
        self.gpio = mock_gpio._MockGPIO()

    def test_setmode_bcm(self) -> None:
        self.gpio.setmode(mock_gpio._MockGPIO.BCM)
        assert self.gpio.getmode() == mock_gpio._MockGPIO.BCM

    def test_setup_output(self) -> None:
        self.gpio.setmode(mock_gpio._MockGPIO.BCM)
        self.gpio.setup(17, mock_gpio._MockGPIO.OUT)
        # Default state after setup is LOW
        assert self.gpio.input(17) == mock_gpio._MockGPIO.LOW

    def test_output_high_low(self) -> None:
        self.gpio.setmode(mock_gpio._MockGPIO.BCM)
        self.gpio.setup(17, mock_gpio._MockGPIO.OUT)
        self.gpio.output(17, mock_gpio._MockGPIO.HIGH)
        assert self.gpio.input(17) == mock_gpio._MockGPIO.HIGH
        self.gpio.output(17, mock_gpio._MockGPIO.LOW)
        assert self.gpio.input(17) == mock_gpio._MockGPIO.LOW

    def test_cleanup_single_pin(self) -> None:
        self.gpio.setup(17, mock_gpio._MockGPIO.OUT)
        self.gpio.output(17, mock_gpio._MockGPIO.HIGH)
        self.gpio.cleanup(17)
        # After cleanup the pin state should be gone
        assert self.gpio.input(17) == mock_gpio._MockGPIO.LOW  # falls back to default

    def test_cleanup_all(self) -> None:
        self.gpio.setup(17, mock_gpio._MockGPIO.OUT)
        self.gpio.setup(27, mock_gpio._MockGPIO.OUT)
        self.gpio.cleanup()
        assert self.gpio.input(17) == mock_gpio._MockGPIO.LOW
        assert self.gpio.input(27) == mock_gpio._MockGPIO.LOW

    def test_pwm_lifecycle(self) -> None:
        self.gpio.setup(18, mock_gpio._MockGPIO.OUT)
        pwm = self.gpio.PWM(18, 50)
        pwm.start(50.0)
        pwm.ChangeDutyCycle(75.0)
        pwm.ChangeFrequency(100.0)
        pwm.stop()  # Should not raise


class TestMainModule:
    """Smoke-test the main module setup/teardown without running the loop."""

    def test_setup_and_teardown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import main

        # setup() and teardown() should not raise on any platform
        main.setup()
        main.teardown()

    def test_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib
        import main

        monkeypatch.delenv("LED_PIN", raising=False)
        monkeypatch.delenv("BLINK_INTERVAL", raising=False)

        # Re-import to pick up env changes
        importlib.reload(main)

        assert main.LED_PIN == 17
        assert main.BLINK_INTERVAL == pytest.approx(1.0)

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib
        import main

        monkeypatch.setenv("LED_PIN", "27")
        monkeypatch.setenv("BLINK_INTERVAL", "0.5")

        importlib.reload(main)

        assert main.LED_PIN == 27
        assert main.BLINK_INTERVAL == pytest.approx(0.5)
