import time

from machine import Pin


class StepDirStepper:
    def __init__(
        self,
        step_pin,
        dir_pin,
        enable_pin=None,
        *,
        enable_active_low=True,
        direction_high_is_forward=True,
        pulse_width_us=20,
    ):
        self.step_pin = Pin(step_pin, Pin.OUT, value=0)
        self.dir_pin = Pin(dir_pin, Pin.OUT, value=0)
        self.enable_pin = None
        if enable_pin is not None:
            self.enable_pin = Pin(enable_pin, Pin.OUT)

        self.enable_active_low = enable_active_low
        self.direction_high_is_forward = direction_high_is_forward
        self.pulse_width_us = max(int(pulse_width_us), 2)

        self._current_rate = 0
        self._direction_sign = 0
        self._position_steps = 0
        self._step_is_high = False
        self._period_us = 0
        self._next_transition_us = None

        self._write_enable(False)

    def _write_enable(self, enabled):
        if self.enable_pin is None:
            return

        if self.enable_active_low:
            self.enable_pin.value(0 if enabled else 1)
        else:
            self.enable_pin.value(1 if enabled else 0)

    def _stop_now(self):
        self.step_pin.value(0)
        self._current_rate = 0
        self._direction_sign = 0
        self._step_is_high = False
        self._period_us = 0
        self._next_transition_us = None
        self._write_enable(False)

    def set_rate(self, steps_per_second):
        steps_per_second = int(steps_per_second)
        if steps_per_second == self._current_rate:
            return

        self._current_rate = steps_per_second
        if steps_per_second == 0:
            self._stop_now()
            return

        forward = steps_per_second > 0
        self._direction_sign = 1 if forward else -1
        if self.direction_high_is_forward:
            self.dir_pin.value(1 if forward else 0)
        else:
            self.dir_pin.value(0 if forward else 1)

        self._write_enable(True)
        self._period_us = max(int(1_000_000 / abs(steps_per_second)), self.pulse_width_us + 2)
        self._step_is_high = False
        self.step_pin.value(0)
        self._next_transition_us = time.ticks_add(time.ticks_us(), self._period_us)

    def update(self, now_us=None):
        if self._current_rate == 0 or self._next_transition_us is None:
            return 0

        if now_us is None:
            now_us = time.ticks_us()

        if time.ticks_diff(now_us, self._next_transition_us) < 0:
            return 0

        if self._step_is_high:
            self.step_pin.value(0)
            self._step_is_high = False
            low_time_us = max(self._period_us - self.pulse_width_us, 1)
            self._next_transition_us = time.ticks_add(now_us, low_time_us)
            return 0

        self.step_pin.value(1)
        self._step_is_high = True
        self._position_steps += self._direction_sign
        self._next_transition_us = time.ticks_add(now_us, self.pulse_width_us)
        return self._direction_sign

    @property
    def current_rate(self):
        return self._current_rate

    @property
    def position_steps(self):
        return self._position_steps

    def set_position(self, position_steps):
        self._position_steps = int(position_steps)