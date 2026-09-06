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
        self.enable_active_low = bool(enable_active_low)
        self.enable_pin = None
        if enable_pin is not None:
            inactive_level = 1 if self.enable_active_low else 0
            self.enable_pin = Pin(enable_pin, Pin.OUT, value=inactive_level)

        self.direction_high_is_forward = bool(direction_high_is_forward)
        self.pulse_width_us = max(int(pulse_width_us), 2)

        self._current_rate = 0
        self._direction_sign = 0
        self._position_steps = 0
        self._period_us = 0
        self._next_step_us = None

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
        self._period_us = 0
        self._next_step_us = None
        self._write_enable(False)

    def set_rate(self, steps_per_second):
        steps_per_second = int(steps_per_second)
        maximum_rate = max(1, 1_000_000 // (self.pulse_width_us + 2))
        if steps_per_second > maximum_rate:
            steps_per_second = maximum_rate
        elif steps_per_second < -maximum_rate:
            steps_per_second = -maximum_rate

        if steps_per_second == self._current_rate:
            return

        previous_rate = self._current_rate
        previous_period_us = self._period_us
        previous_direction = self._direction_sign
        self._current_rate = steps_per_second
        if steps_per_second == 0:
            self._stop_now()
            return

        now_us = time.ticks_us()
        forward = steps_per_second > 0
        self._direction_sign = 1 if forward else -1
        self._period_us = max(
            (1_000_000 + abs(steps_per_second) - 1) // abs(steps_per_second),
            self.pulse_width_us + 2,
        )

        if previous_rate == 0 or previous_direction != self._direction_sign:
            self.step_pin.value(0)
            if self.direction_high_is_forward:
                self.dir_pin.value(1 if forward else 0)
            else:
                self.dir_pin.value(0 if forward else 1)
            self._next_step_us = time.ticks_add(now_us, self._period_us)
        else:
            # Keep the fraction of the current step interval that remains.  A
            # ramp updates the requested rate frequently; restarting a whole
            # interval on every update would suppress all steps until the ramp
            # finished.
            remaining_us = time.ticks_diff(self._next_step_us, now_us)
            if remaining_us <= 0:
                self._next_step_us = now_us
            else:
                scaled_remaining_us = (remaining_us * self._period_us) // previous_period_us
                self._next_step_us = time.ticks_add(now_us, scaled_remaining_us)

        self._write_enable(True)

    def update(self, now_us=None):
        if self._current_rate == 0 or self._next_step_us is None:
            return 0

        if now_us is None:
            now_us = time.ticks_us()

        if time.ticks_diff(now_us, self._next_step_us) < 0:
            return 0

        scheduled_step_us = self._next_step_us
        self.step_pin.value(1)
        time.sleep_us(self.pulse_width_us)
        self.step_pin.value(0)
        self._position_steps += self._direction_sign

        # Preserve normal cadence after small loop jitter, but skip missed
        # pulses after a long stall instead of issuing a hazardous catch-up
        # burst.
        next_step_us = time.ticks_add(scheduled_step_us, self._period_us)
        after_pulse_us = time.ticks_us()
        if time.ticks_diff(next_step_us, after_pulse_us) <= 0:
            next_step_us = time.ticks_add(after_pulse_us, self._period_us)
        self._next_step_us = next_step_us
        return self._direction_sign

    @property
    def current_rate(self):
        return self._current_rate

    @property
    def position_steps(self):
        return self._position_steps

    def set_position(self, position_steps):
        self._position_steps = int(position_steps)
