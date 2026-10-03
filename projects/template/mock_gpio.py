"""
mock_gpio.py — A lightweight stand-in for RPi.GPIO when running on a
non-Raspberry-Pi machine (Windows, Ubuntu laptop, CI, etc.).

Usage in your project code:

    try:
        import RPi.GPIO as GPIO
    except (ImportError, RuntimeError):
        from mock_gpio import GPIO

Only the GPIO API calls used by typical simple projects are implemented here.
For full mocking, consider the `fake-rpigpio` PyPI package instead.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class _MockGPIO:
    """Minimal mock that silently accepts all common RPi.GPIO calls."""

    # Mode constants (match real RPi.GPIO values)
    BCM: int = 11
    BOARD: int = 10

    # Direction constants
    IN: int = 1
    OUT: int = 0

    # Level constants
    HIGH: int = 1
    LOW: int = 0

    # Pull-up/down
    PUD_UP: int = 22
    PUD_DOWN: int = 21
    PUD_OFF: int = 20

    # Edge detection
    RISING: int = 31
    FALLING: int = 32
    BOTH: int = 33

    def __init__(self) -> None:
        self._mode: int | None = None
        self._pin_states: dict[int, int] = {}
        self._pin_directions: dict[int, int] = {}

    def setmode(self, mode: int) -> None:
        self._mode = mode
        logger.debug("MockGPIO: setmode(%s)", mode)

    def getmode(self) -> int | None:
        return self._mode

    def setwarnings(self, flag: bool) -> None:  # noqa: FBT001
        logger.debug("MockGPIO: setwarnings(%s)", flag)

    def setup(
        self,
        channel: int | list[int],
        direction: int,
        pull_up_down: int = PUD_OFF,
        initial: int = -1,
    ) -> None:
        channels = [channel] if isinstance(channel, int) else channel
        for ch in channels:
            self._pin_directions[ch] = direction
            self._pin_states[ch] = initial if initial != -1 else self.LOW
            logger.debug("MockGPIO: setup(channel=%s, direction=%s)", ch, direction)

    def output(self, channel: int | list[int], value: int) -> None:
        channels = [channel] if isinstance(channel, int) else channel
        for ch in channels:
            self._pin_states[ch] = value
            logger.debug("MockGPIO: output(channel=%s, value=%s)", ch, value)

    def input(self, channel: int) -> int:
        value = self._pin_states.get(channel, self.LOW)
        logger.debug("MockGPIO: input(channel=%s) -> %s", channel, value)
        return value

    def cleanup(self, channel: int | list[int] | None = None) -> None:
        if channel is None:
            self._pin_states.clear()
            self._pin_directions.clear()
        else:
            channels = [channel] if isinstance(channel, int) else channel
            for ch in channels:
                self._pin_states.pop(ch, None)
                self._pin_directions.pop(ch, None)
        logger.debug("MockGPIO: cleanup(%s)", channel)

    # ── Interrupts / event detection (no-ops in mock) ──────────────────────
    def add_event_detect(self, channel: int, edge: int, callback=None, bouncetime: int = 0) -> None:  # noqa: ANN001
        logger.debug("MockGPIO: add_event_detect(channel=%s, edge=%s)", channel, edge)

    def remove_event_detect(self, channel: int) -> None:
        logger.debug("MockGPIO: remove_event_detect(channel=%s)", channel)

    def event_detected(self, channel: int) -> bool:
        return False

    def add_event_callback(self, channel: int, callback) -> None:  # noqa: ANN001
        logger.debug("MockGPIO: add_event_callback(channel=%s)", channel)

    # ── PWM ────────────────────────────────────────────────────────────────
    def PWM(self, channel: int, frequency: float) -> "_MockPWM":  # noqa: N802
        logger.debug("MockGPIO: PWM(channel=%s, frequency=%s)", channel, frequency)
        return _MockPWM(channel, frequency)


class _MockPWM:
    """Minimal PWM mock."""

    def __init__(self, channel: int, frequency: float) -> None:
        self._channel = channel
        self._frequency = frequency

    def start(self, duty_cycle: float) -> None:
        logger.debug("MockPWM: start(duty_cycle=%s) on channel %s", duty_cycle, self._channel)

    def ChangeDutyCycle(self, duty_cycle: float) -> None:  # noqa: N802
        logger.debug("MockPWM: ChangeDutyCycle(%s)", duty_cycle)

    def ChangeFrequency(self, frequency: float) -> None:  # noqa: N802
        logger.debug("MockPWM: ChangeFrequency(%s)", frequency)

    def stop(self) -> None:
        logger.debug("MockPWM: stop() on channel %s", self._channel)


# Singleton instance — import as `from mock_gpio import GPIO`
GPIO = _MockGPIO()
