import sys
import time
import uselect

from machine import Pin

import config
from stepper import StepDirStepper


class DebouncedSwitch:
    def __init__(self, pin_number, debounce_ms):
        self.pin = Pin(pin_number, Pin.IN, Pin.PULL_UP)
        self.debounce_ms = debounce_ms
        initial_pressed = self.pin.value() == 0
        self._stable_pressed = initial_pressed
        self._last_raw_pressed = initial_pressed
        self._last_change_ms = time.ticks_ms()
        self._pressed_edge = False

    def update(self, now_ms):
        raw_pressed = self.pin.value() == 0
        if raw_pressed != self._last_raw_pressed:
            self._last_raw_pressed = raw_pressed
            self._last_change_ms = now_ms

        if time.ticks_diff(now_ms, self._last_change_ms) >= self.debounce_ms:
            if self._stable_pressed != self._last_raw_pressed and self._last_raw_pressed:
                self._pressed_edge = True
            self._stable_pressed = self._last_raw_pressed

    @property
    def pressed(self):
        return self._stable_pressed

    def consume_pressed_edge(self):
        pressed_edge = self._pressed_edge
        self._pressed_edge = False
        return pressed_edge


def clamp_rate(rate, max_rate):
    rate = int(rate)
    if rate > max_rate:
        return max_rate
    if rate < -max_rate:
        return -max_rate
    return rate


def describe_direction(direction):
    if direction > 0:
        return "forward"
    if direction < 0:
        return "reverse"
    return "stop"


class AxisController:
    def __init__(self, name, stepper, stepper_config):
        self.name = name
        self.stepper = stepper
        self.default_rate = abs(int(stepper_config.get("default_steps_per_second", config.DEFAULT_STEPS_PER_SECOND)))
        self.max_rate = abs(int(stepper_config.get("max_steps_per_second", self.default_rate)))
        self.acceleration = max(
            int(stepper_config.get("acceleration_steps_per_second_squared", self.default_rate * 4)),
            1,
        )
        self.external_rate = None
        self.serial_rate = 0
        self.move_target_position = None
        self.move_rate = self.default_rate
        self.ramped_rate = 0.0

    def stop(self):
        self.external_rate = None
        self.serial_rate = 0
        self.move_target_position = None
        self.move_rate = self.default_rate
        self.ramped_rate = 0.0
        self.stepper.set_rate(0)

    def set_external_rate(self, rate):
        self.external_rate = clamp_rate(rate, self.max_rate)

    def clear_external_rate(self):
        self.external_rate = None

    def set_serial_rate(self, rate):
        self.move_target_position = None
        self.move_rate = self.default_rate
        self.serial_rate = clamp_rate(rate, self.max_rate)

    def move_relative(self, delta_steps, rate=None):
        delta_steps = int(delta_steps)
        if delta_steps == 0:
            self.stop()
            return

        requested_rate = self.default_rate if rate is None else abs(int(rate))
        if requested_rate == 0:
            requested_rate = self.default_rate

        self.serial_rate = 0
        self.move_rate = min(requested_rate, self.max_rate)
        self.move_target_position = self.stepper.position_steps + delta_steps

    def zero_position(self):
        self.move_target_position = None
        self.stepper.set_position(0)

    def _desired_rate(self, jog_direction):
        if self.move_target_position is not None:
            current_position = self.stepper.position_steps
            if current_position == self.move_target_position:
                self.move_target_position = None
                return 0
            if self.move_target_position > current_position:
                return self.move_rate
            return -self.move_rate

        if self.external_rate is not None:
            return self.external_rate

        if self.serial_rate != 0:
            return self.serial_rate

        if jog_direction == 0:
            return 0
        return jog_direction * self.default_rate

    def _stop_for_limit(self, direction):
        if self.serial_rate * direction > 0:
            self.serial_rate = 0
        if self.move_target_position is not None:
            position = self.stepper.position_steps
            if (self.move_target_position - position) * direction > 0:
                self.move_target_position = None
        if self.ramped_rate * direction > 0 or self.stepper.current_rate * direction > 0:
            self.ramped_rate = 0.0
            self.stepper.set_rate(0)

    def update(self, now_us, dt_us, jog_direction=0, negative_limit_active=False, positive_limit_active=False):
        desired_rate = self._desired_rate(jog_direction)

        if negative_limit_active and desired_rate < 0:
            self._stop_for_limit(-1)
            desired_rate = 0
        if positive_limit_active and desired_rate > 0:
            self._stop_for_limit(1)
            desired_rate = 0

        if negative_limit_active and self.ramped_rate < 0:
            self._stop_for_limit(-1)
        if positive_limit_active and self.ramped_rate > 0:
            self._stop_for_limit(1)

        max_rate_delta = (self.acceleration * max(dt_us, 0)) / 1_000_000
        rate_error = desired_rate - self.ramped_rate
        if rate_error > max_rate_delta:
            self.ramped_rate += max_rate_delta
        elif rate_error < -max_rate_delta:
            self.ramped_rate -= max_rate_delta
        else:
            self.ramped_rate = float(desired_rate)

        if abs(self.ramped_rate) < 0.5:
            self.ramped_rate = 0.0

        self.stepper.set_rate(int(round(self.ramped_rate)))
        step_delta = self.stepper.update(now_us)
        if step_delta == 0 or self.move_target_position is None:
            return

        position = self.stepper.position_steps
        if step_delta > 0 and position >= self.move_target_position:
            self.stop()
        elif step_delta < 0 and position <= self.move_target_position:
            self.stop()

    def status_line(self, jog_direction=0, negative_limit_active=False, positive_limit_active=False):
        if self.move_target_position is not None:
            mode = "move"
            target = str(self.move_target_position)
        elif self.external_rate not in (None, 0):
            mode = "auto"
            target = "-"
        elif self.serial_rate != 0:
            mode = "serial"
            target = "-"
        elif jog_direction != 0:
            mode = "buttons"
            target = "-"
        else:
            mode = "idle"
            target = "-"

        return (
            "{name} mode={mode} pos={position} rate={rate} target={target} "
            "min_limit={min_limit} max_limit={max_limit}"
        ).format(
            name=self.name,
            mode=mode,
            position=self.stepper.position_steps,
            rate=self.stepper.current_rate,
            target=target,
            min_limit=negative_limit_active,
            max_limit=positive_limit_active,
        )


class ShuttleController:
    def __init__(self, axes, switches):
        machine_config = config.MACHINE
        self.carriage_axis = axes[machine_config["carriage_axis"]]
        self.chuck_axis = axes[machine_config["chuck_axis"]]
        self.negative_endstop_name = machine_config["carriage_negative_endstop"]
        self.positive_endstop_name = machine_config["carriage_positive_endstop"]
        self.negative_endstop = switches[self.negative_endstop_name]["switch"]
        self.positive_endstop = switches[self.positive_endstop_name]["switch"]
        self.carriage_rate = abs(int(machine_config.get("carriage_run_steps_per_second", self.carriage_axis.default_rate)))
        self.current_direction = 1 if int(machine_config.get("carriage_start_direction", 1)) >= 0 else -1
        self.auto_enabled = bool(machine_config.get("carriage_auto_start", False))
        self.chuck_index_steps = int(machine_config.get("chuck_index_steps", 0))
        self.chuck_index_rate = abs(int(machine_config.get("chuck_index_rate", self.chuck_axis.default_rate)))
        self.chuck_index_direction = 1 if int(machine_config.get("chuck_index_direction", 1)) >= 0 else -1
        self.last_reversal_source = "startup"

        if self.auto_enabled:
            self.start()

    def start(self):
        self.auto_enabled = True
        if self.current_direction < 0 and self.negative_endstop.pressed:
            self.current_direction = 1
        elif self.current_direction > 0 and self.positive_endstop.pressed:
            self.current_direction = -1
        self.carriage_axis.set_external_rate(self.current_direction * self.carriage_rate)

    def pause(self):
        self.auto_enabled = False
        self.carriage_axis.clear_external_rate()

    def reverse(self):
        self.current_direction *= -1
        self.last_reversal_source = "manual"
        if self.auto_enabled:
            self.carriage_axis.set_external_rate(self.current_direction * self.carriage_rate)

    def index_chuck(self, steps=None, rate=None):
        if steps is None:
            steps = self.chuck_index_steps * self.chuck_index_direction
        if rate is None:
            rate = self.chuck_index_rate
        self.chuck_axis.move_relative(steps, rate)

    def service(self):
        negative_edge = self.negative_endstop.consume_pressed_edge()
        positive_edge = self.positive_endstop.consume_pressed_edge()

        if self.current_direction < 0 and negative_edge:
            self._handle_reversal(self.negative_endstop_name)
        elif self.current_direction > 0 and positive_edge:
            self._handle_reversal(self.positive_endstop_name)

        if self.auto_enabled:
            self.carriage_axis.set_external_rate(self.current_direction * self.carriage_rate)
        else:
            self.carriage_axis.clear_external_rate()

    def _handle_reversal(self, source_name):
        self.current_direction *= -1
        self.last_reversal_source = source_name
        if self.auto_enabled:
            self.carriage_axis.set_external_rate(self.current_direction * self.carriage_rate)
        if self.chuck_index_steps != 0:
            self.index_chuck()

    def status_line(self):
        return (
            "shuttle enabled={enabled} direction={direction} carriage_rate={rate} "
            "index_steps={index_steps} index_rate={index_rate} last_reversal={last_reversal}"
        ).format(
            enabled=self.auto_enabled,
            direction=describe_direction(self.current_direction),
            rate=self.carriage_rate,
            index_steps=self.chuck_index_steps * self.chuck_index_direction,
            index_rate=self.chuck_index_rate,
            last_reversal=self.last_reversal_source,
        )


class SerialCommandInterface:
    def __init__(self, axes, switches, shuttle):
        self.axes = axes
        self.switches = switches
        self.shuttle = shuttle
        self._buffer = ""
        self._poller = uselect.poll()
        self._poller.register(sys.stdin, uselect.POLLIN)

    def service(self):
        for _ in range(config.SERIAL_READ_CHUNK):
            if not self._poller.poll(0):
                return

            character = sys.stdin.read(1)
            if not character:
                return

            if character in "\r\n":
                if self._buffer:
                    self._handle_command(self._buffer.strip())
                    self._buffer = ""
                continue

            if character == "\x03":
                self.shuttle.pause()
                for axis in self.axes.values():
                    axis.stop()
                self._buffer = ""
                print("ok stop")
                continue

            if 31 < ord(character) < 127:
                if len(self._buffer) < 120:
                    self._buffer += character

    def _handle_command(self, raw_command):
        parts = raw_command.split()
        if not parts:
            return

        command = parts[0].lower()
        try:
            if command in ("help", "?"):
                self._print_help()
                return

            if command == "status":
                self._print_status()
                return

            if command == "start":
                self.shuttle.start()
                print("ok start")
                return

            if command == "pause":
                self.shuttle.pause()
                print("ok pause")
                return

            if command == "reverse":
                self.shuttle.reverse()
                print("ok reverse {direction}".format(direction=describe_direction(self.shuttle.current_direction)))
                return

            if command == "index" and len(parts) in (1, 2, 3):
                steps = None if len(parts) == 1 else int(parts[1])
                rate = None if len(parts) < 3 else int(parts[2])
                self.shuttle.index_chuck(steps, rate)
                print("ok index")
                return

            if command == "stop":
                self.shuttle.pause()
                for axis in self.axes.values():
                    axis.stop()
                print("ok stop")
                return

            if command == "rate" and len(parts) == 3:
                axis = self._get_axis(parts[1])
                rate = int(parts[2])
                axis.set_serial_rate(rate)
                print("ok rate {name} {rate}".format(name=axis.name, rate=axis.serial_rate))
                return

            if command == "jog" and len(parts) in (3, 4):
                axis = self._get_axis(parts[1])
                direction = self._parse_direction(parts[2])
                if len(parts) == 4:
                    rate = abs(int(parts[3]))
                else:
                    rate = axis.default_rate
                axis.set_serial_rate(direction * rate)
                print(
                    "ok jog {name} {direction} {rate}".format(
                        name=axis.name,
                        direction=describe_direction(direction),
                        rate=abs(axis.serial_rate),
                    )
                )
                return

            if command == "move" and len(parts) in (3, 4):
                axis = self._get_axis(parts[1])
                delta_steps = int(parts[2])
                if len(parts) == 4:
                    rate = int(parts[3])
                else:
                    rate = None
                axis.move_relative(delta_steps, rate)
                print(
                    "ok move {name} delta={delta} target={target} rate={rate}".format(
                        name=axis.name,
                        delta=delta_steps,
                        target=axis.move_target_position,
                        rate=axis.move_rate,
                    )
                )
                return

            if command == "zero" and len(parts) == 2:
                axis = self._get_axis(parts[1])
                axis.zero_position()
                print("ok zero {name}".format(name=axis.name))
                return

            raise ValueError("unknown command")
        except Exception as exc:
            print("error {message}".format(message=exc))

    def _get_axis(self, axis_name):
        normalized = axis_name.lower()
        alias_map = {
            "a": "motor_a",
            "b": "motor_b",
        }
        normalized = alias_map.get(normalized, normalized)
        if normalized not in self.axes:
            raise ValueError("unknown axis '{name}'".format(name=axis_name))
        return self.axes[normalized]

    def _parse_direction(self, token):
        normalized = token.lower()
        if normalized in ("forward", "fwd", "+", "positive", "pos"):
            return 1
        if normalized in ("reverse", "rev", "-", "negative", "neg"):
            return -1
        if normalized in ("stop", "0"):
            return 0
        raise ValueError("unknown direction '{token}'".format(token=token))

    def _print_help(self):
        print("help: start | pause | reverse | index [steps] [rate]")
        print("help: status | stop | rate <axis> <steps_per_second>")
        print("help: jog <axis> <forward|reverse|stop> [rate]")
        print("help: move <axis> <delta_steps> [rate] | zero <axis>")

    def _print_status(self):
        print(self.shuttle.status_line())
        active_switches = []
        for switch_name, switch_state in self.switches.items():
            if switch_state["switch"].pressed:
                active_switches.append(switch_name)

        if active_switches:
            print("switches active={names}".format(names=",".join(active_switches)))
        else:
            print("switches active=none")

        for axis_name, axis in self.axes.items():
            jog_direction, negative_limit_active, positive_limit_active = collect_axis_inputs(axis_name, self.switches)
            print(axis.status_line(jog_direction, negative_limit_active, positive_limit_active))


def build_stepper(stepper_config):
    return StepDirStepper(
        stepper_config["step_pin"],
        stepper_config["dir_pin"],
        stepper_config.get("enable_pin"),
        enable_active_low=config.ENABLE_ACTIVE_LOW,
        direction_high_is_forward=stepper_config.get("direction_high_is_forward", True),
        pulse_width_us=config.STEP_PULSE_US,
    )


def build_switches():
    switches = {}
    for switch_name, switch_config in config.SWITCHES.items():
        switches[switch_name] = {
            "config": switch_config,
            "switch": DebouncedSwitch(switch_config["pin"], config.SWITCH_DEBOUNCE_MS),
        }
    return switches


def collect_axis_inputs(axis_name, switches):
    jog_direction = 0
    negative_limit_active = False
    positive_limit_active = False

    for switch_state in switches.values():
        switch_config = switch_state["config"]
        if switch_config["motor"] != axis_name:
            continue
        if not switch_state["switch"].pressed:
            continue

        direction = int(switch_config.get("direction", 0))
        mode = switch_config.get("mode", "jog")
        if mode == "jog":
            if direction > 0:
                jog_direction += 1
            elif direction < 0:
                jog_direction -= 1
        elif mode == "endstop":
            if direction > 0:
                positive_limit_active = True
            elif direction < 0:
                negative_limit_active = True

    if jog_direction > 0:
        jog_direction = 1
    elif jog_direction < 0:
        jog_direction = -1

    return jog_direction, negative_limit_active, positive_limit_active


def main():
    axes = {
        axis_name: AxisController(axis_name, build_stepper(stepper_config), stepper_config)
        for axis_name, stepper_config in config.STEPPERS.items()
    }
    switches = build_switches()
    shuttle = ShuttleController(axes, switches)
    serial_console = SerialCommandInterface(axes, switches, shuttle)

    print("ready: type 'help' for commands")
    previous_loop_us = time.ticks_us()

    while True:
        now_ms = time.ticks_ms()
        for switch_state in switches.values():
            switch_state["switch"].update(now_ms)

        serial_console.service()
        shuttle.service()

        now_us = time.ticks_us()
        dt_us = time.ticks_diff(now_us, previous_loop_us)
        previous_loop_us = now_us

        for axis_name, axis in axes.items():
            jog_direction, negative_limit_active, positive_limit_active = collect_axis_inputs(axis_name, switches)
            axis.update(now_us, dt_us, jog_direction, negative_limit_active, positive_limit_active)

        time.sleep_us(config.MAIN_LOOP_IDLE_US)


if __name__ == "__main__":
    main()