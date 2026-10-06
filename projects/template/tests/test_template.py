"""
Tests for the template project.

These tests run on any machine (no Pi hardware required).
GPIO calls are intercepted by mock_gpio.
"""

import hashlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
_MODULE_SUFFIX = hashlib.sha1(str(PROJECT_DIR).encode("utf-8")).hexdigest()[:12]


def _load_local_module(module_name: str, path: Path):
    """Load a project-local helper without sharing its import name across copies."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


mock_gpio = _load_local_module(
    f"raspberry_pi_mock_gpio_{_MODULE_SUFFIX}",
    PROJECT_DIR / "mock_gpio.py",
)


def _gpio_stub_module():
    """Expose this project's GPIO singleton through an RPi.GPIO-shaped module."""
    module = types.ModuleType("RPi.GPIO")
    for name in dir(mock_gpio.GPIO):
        if not name.startswith("_"):
            setattr(module, name, getattr(mock_gpio.GPIO, name))
    return module


def _load_template_main():
    """Load this project's main.py with a temporary, project-local RPi.GPIO stub."""
    module_name = f"raspberry_pi_template_main_{_MODULE_SUFFIX}"
    spec = importlib.util.spec_from_file_location(module_name, PROJECT_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    sentinel = object()
    previous_rpi = sys.modules.get("RPi", sentinel)
    previous_gpio = sys.modules.get("RPi.GPIO", sentinel)

    gpio_module = _gpio_stub_module()
    rpi_module = types.ModuleType("RPi")
    rpi_module.__path__ = []  # mark it as package-like for the dotted import
    rpi_module.GPIO = gpio_module
    sys.modules["RPi"] = rpi_module
    sys.modules["RPi.GPIO"] = gpio_module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_gpio is sentinel:
            sys.modules.pop("RPi.GPIO", None)
        else:
            sys.modules["RPi.GPIO"] = previous_gpio
        if previous_rpi is sentinel:
            sys.modules.pop("RPi", None)
        else:
            sys.modules["RPi"] = previous_rpi
    return module


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
        main = _load_template_main()

        # setup() and teardown() should not raise on any platform
        main.setup()
        main.teardown()

    def test_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import dotenv

        monkeypatch.delenv("LED_PIN", raising=False)
        monkeypatch.delenv("BLINK_INTERVAL", raising=False)
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)

        # Load the template module under its own name so another project's
        # cached "main" module cannot affect this test.
        main = _load_template_main()

        assert main.LED_PIN == 17
        assert main.BLINK_INTERVAL == pytest.approx(1.0)

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LED_PIN", "27")
        monkeypatch.setenv("BLINK_INTERVAL", "0.5")

        main = _load_template_main()

        assert main.LED_PIN == 27
        assert main.BLINK_INTERVAL == pytest.approx(0.5)
