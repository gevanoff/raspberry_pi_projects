import math
import sys
import time
import uselect

from machine import Pin

import config
from stepper import StepDirStepper


class DebouncedSwitch:
    def __init__(self, pin_number, debounce_ms, *, active_low=True, mode="jog"):
        self.pin = Pin(pin_number, Pin.IN, Pin.PULL_UP)
        self.debounce_ms = max(int(debounce_ms), 0)
        self.active_low = bool(active_low)
        self.mode = mode
        initial_pressed = self._read_pressed()
        self._stable_pressed = initial_pressed
        self._last_raw_pressed = initial_pressed
        self._last_change_ms = time.ticks_ms()
        self._pressed_edge = False

    def _read_pressed(self):
        return (self.pin.value() == 0) if self.active_low else (self.pin.value() != 0)

    def update(self, now_ms):
        raw_pressed = self._read_pressed()
        if raw_pressed != self._last_raw_pressed:
            self._last_raw_pressed = raw_pressed
            self._last_change_ms = now_ms

        if self._stable_pressed == self._last_raw_pressed:
            return

        # Endstops assert immediately so debounce cannot add avoidable travel.
        # Jog controls release immediately so a released button cannot prolong
        # commanded motion.  The less safety-critical edge is debounced.
        change_is_immediate = (self.mode == "endstop" and raw_pressed) or (
            self.mode in ("jog", "run_enable", "manual_index") and not raw_pressed
        )
        if change_is_immediate or time.ticks_diff(now_ms, self._last_change_ms) >= self.debounce_ms:
            if raw_pressed:
                self._pressed_edge = True
            self._stable_pressed = raw_pressed

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
        self._move_relative(delta_steps, rate, queue=False)

    def queue_relative(self, delta_steps, rate=None):
        self._move_relative(delta_steps, rate, queue=True)

    def _move_relative(self, delta_steps, rate, queue):
        delta_steps = int(delta_steps)
        if delta_steps == 0:
            if not queue:
                self.stop()
            return

        requested_rate = self.default_rate if rate is None else abs(int(rate))
        if requested_rate == 0:
            requested_rate = self.default_rate

        self.serial_rate = 0
        self.move_rate = min(requested_rate, self.max_rate)
        if queue and self.move_target_position is not None:
            self.move_target_position += delta_steps
        else:
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
            distance = abs(self.move_target_position - current_position)
            braking_rate = max(int(math.sqrt(2 * self.acceleration * distance)), 1)
            move_rate = min(self.move_rate, braking_rate)
            if self.move_target_position > current_position:
                return move_rate
            return -move_rate

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

        dt_us = min(max(dt_us, 0), config.MAX_CONTROL_DT_US)
        max_rate_delta = (self.acceleration * dt_us) / 1_000_000
        ramp_target_rate = desired_rate
        if self.ramped_rate * desired_rate < 0:
            # Decelerate fully before changing the hardware direction pin.
            ramp_target_rate = 0
        rate_error = ramp_target_rate - self.ramped_rate
        if rate_error > max_rate_delta:
            self.ramped_rate += max_rate_delta
        elif rate_error < -max_rate_delta:
            self.ramped_rate -= max_rate_delta
        else:
            self.ramped_rate = float(ramp_target_rate)

        # Preserve sub-step/s acceleration while ramping away from rest.
        # Snapping every fractional value to zero can permanently stall a fast
        # control loop whose per-iteration acceleration increment is < 0.5.
        if ramp_target_rate == 0 and abs(self.ramped_rate) < 0.5:
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
        self.run_enable_name = machine_config.get("run_enable_switch")
        self.run_enable = None
        if self.run_enable_name is not None:
            self.run_enable = switches[self.run_enable_name]["switch"]
        self.manual_index_name = machine_config.get("manual_index_switch")
        self.manual_index_switch = None
        if self.manual_index_name is not None:
            self.manual_index_switch = switches[self.manual_index_name]["switch"]
        self.run_switch_armed = self.run_enable is None or not self.run_enable.pressed
        self.run_fault_latched = self.run_enable is not None and self.run_enable.pressed
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
        if self.run_enable is not None:
            if not self.run_enable.pressed:
                raise ValueError("run-enable switch is in Stop")
            if self.run_fault_latched:
                raise ValueError("cycle the run-enable switch through Stop to clear the fault")
            if not self.run_switch_armed:
                raise ValueError("cycle the run-enable switch through Stop before starting")
        if self.negative_endstop.pressed and self.positive_endstop.pressed:
            self.auto_enabled = False
            self.run_switch_armed = False
            self.run_fault_latched = True
            self.carriage_axis.clear_external_rate()
            self.last_reversal_source = "fault:both_endstops"
            raise ValueError("both carriage endstops are active")

        if self.current_direction < 0 and self.negative_endstop.pressed:
            self.current_direction = 1
        elif self.current_direction > 0 and self.positive_endstop.pressed:
            self.current_direction = -1

        self.carriage_axis.stop()
        self.auto_enabled = True
        self.run_switch_armed = False
        self.carriage_axis.set_external_rate(self.current_direction * self.carriage_rate)

    def pause(self):
        self.auto_enabled = False
        self.carriage_axis.clear_external_rate()

    def reverse(self):
        new_direction = -self.current_direction
        if new_direction < 0 and self.negative_endstop.pressed:
            raise ValueError("negative carriage endstop is active")
        if new_direction > 0 and self.positive_endstop.pressed:
            raise ValueError("positive carriage endstop is active")
        self.current_direction = new_direction
        self.last_reversal_source = "manual"
        if self.auto_enabled:
            self.carriage_axis.set_external_rate(self.current_direction * self.carriage_rate)

    def index_chuck(self, steps=None, rate=None):
        if steps is None:
            steps = self.chuck_index_steps * self.chuck_index_direction
        if rate is None:
            rate = self.chuck_index_rate
        self.chuck_axis.queue_relative(steps, rate)

    def service(self):
        negative_edge = self.negative_endstop.consume_pressed_edge()
        positive_edge = self.positive_endstop.consume_pressed_edge()
        run_edge = False
        manual_index_edge = False
        if self.run_enable is not None:
            run_edge = self.run_enable.consume_pressed_edge()

            if not self.run_enable.pressed:
                self.run_switch_armed = True
                self.run_fault_latched = False
                self._stop_from_run_switch()
            elif run_edge and self.run_switch_armed and not self.auto_enabled:
                try:
                    self.start()
                except ValueError:
                    self.run_switch_armed = False
        if self.manual_index_switch is not None:
            manual_index_edge = self.manual_index_switch.consume_pressed_edge()

        if self.auto_enabled:
            if self.negative_endstop.pressed and self.positive_endstop.pressed:
                self._pause_for_endstop_fault("both_endstops")
            elif self.current_direction < 0:
                if positive_edge:
                    self._pause_for_endstop_fault(self.positive_endstop_name)
                elif negative_edge:
                    self._handle_reversal(self.negative_endstop_name)
            elif self.current_direction > 0:
                if negative_edge:
                    self._pause_for_endstop_fault(self.negative_endstop_name)
                elif positive_edge:
                    self._handle_reversal(self.positive_endstop_name)

        if manual_index_edge and self._run_allows_motion():
            self.index_chuck()

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

    def _pause_for_endstop_fault(self, source_name):
        self.auto_enabled = False
        self.run_switch_armed = False
        self.run_fault_latched = True
        self.carriage_axis.clear_external_rate()
        self.last_reversal_source = "fault:{source}".format(source=source_name)

    def _stop_from_run_switch(self):
        self.auto_enabled = False
        self.carriage_axis.stop()
        self.chuck_axis.stop()
        self.last_reversal_source = "run_switch_stop"

    def _run_allows_motion(self):
        return self.run_enable is None or (
            self.run_enable.pressed and not self.run_fault_latched
        )

    def status_line(self):
        return (
            "shuttle enabled={enabled} direction={direction} run_enable={run_enable} "
            "run_armed={run_armed} run_fault={run_fault} carriage_rate={rate} "
            "index_steps={index_steps} index_rate={index_rate} last_reversal={last_reversal}"
        ).format(
            enabled=self.auto_enabled,
            direction=describe_direction(self.current_direction),
            run_enable="none" if self.run_enable is None else self.run_enable.pressed,
            run_armed=self.run_switch_armed,
            run_fault=self.run_fault_latched,
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
        self._discard_line = False
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
                if self._discard_line:
                    print("error command is too long")
                elif self._buffer:
                    self._handle_command(self._buffer.strip())
                self._buffer = ""
                self._discard_line = False
                continue

            if character == "\x03":
                self.shuttle.pause()
                for axis in self.axes.values():
                    axis.stop()
                self._buffer = ""
                self._discard_line = False
                print("ok stop")
                continue

            if 31 < ord(character) < 127:
                if self._discard_line:
                    continue
                if len(self._buffer) < 120:
                    self._buffer += character
                else:
                    self._buffer = ""
                    self._discard_line = True

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
                self._require_run_enable()
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
                self._require_manual_axis_control(axis)
                rate = int(parts[2])
                axis.set_serial_rate(rate)
                print("ok rate {name} {rate}".format(name=axis.name, rate=axis.serial_rate))
                return

            if command == "jog" and len(parts) in (3, 4):
                axis = self._get_axis(parts[1])
                self._require_manual_axis_control(axis)
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
                self._require_manual_axis_control(axis)
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
                self._require_manual_axis_control(axis)
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

    def _require_manual_axis_control(self, axis):
        self._require_run_enable()
        if axis is self.shuttle.carriage_axis and self.shuttle.auto_enabled:
            raise ValueError("pause the shuttle before controlling the carriage axis")

    def _require_run_enable(self):
        if self.shuttle.run_enable is not None:
            if not self.shuttle.run_enable.pressed:
                raise ValueError("run-enable switch is in Stop")
            if self.shuttle.run_fault_latched:
                raise ValueError("cycle the run-enable switch through Stop to clear the fault")

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


def validate_configuration():
    if not config.STEPPERS:
        raise ValueError("STEPPERS must define at least one axis")

    used_pins = {}
    for axis_name, stepper_config in config.STEPPERS.items():
        max_rate = int(stepper_config.get("max_steps_per_second", 0))
        default_rate = int(stepper_config.get("default_steps_per_second", config.DEFAULT_STEPS_PER_SECOND))
        acceleration = int(stepper_config.get("acceleration_steps_per_second_squared", 0))
        if max_rate <= 0:
            raise ValueError("{name} max_steps_per_second must be positive".format(name=axis_name))
        if default_rate <= 0 or default_rate > max_rate:
            raise ValueError(
                "{name} default_steps_per_second must be between 1 and max_steps_per_second".format(
                    name=axis_name
                )
            )
        if acceleration <= 0:
            raise ValueError(
                "{name} acceleration_steps_per_second_squared must be positive".format(name=axis_name)
            )

        for field_name in ("step_pin", "dir_pin", "enable_pin"):
            pin_number = stepper_config.get(field_name)
            if field_name == "enable_pin" and pin_number is None:
                continue
            _claim_pin(used_pins, pin_number, "{name}.{field}".format(name=axis_name, field=field_name))

    for switch_name, switch_config in config.SWITCHES.items():
        _claim_pin(used_pins, switch_config.get("pin"), switch_name)
        axis_name = switch_config.get("motor")
        mode = switch_config.get("mode", "jog")
        if mode not in ("jog", "endstop", "run_enable", "manual_index"):
            raise ValueError("{name} has an unsupported switch mode".format(name=switch_name))
        if mode in ("run_enable", "manual_index"):
            if axis_name is not None or "direction" in switch_config:
                raise ValueError(
                    "{name} {mode} must not define motor or direction".format(
                        name=switch_name,
                        mode=mode,
                    )
                )
        else:
            if axis_name not in config.STEPPERS:
                raise ValueError(
                    "{name} references unknown motor '{motor}'".format(name=switch_name, motor=axis_name)
                )
            if int(switch_config.get("direction", 0)) not in (-1, 1):
                raise ValueError("{name} direction must be -1 or 1".format(name=switch_name))

    machine_config = config.MACHINE
    carriage_axis_name = machine_config.get("carriage_axis")
    chuck_axis_name = machine_config.get("chuck_axis")
    if carriage_axis_name not in config.STEPPERS or chuck_axis_name not in config.STEPPERS:
        raise ValueError("MACHINE carriage_axis and chuck_axis must reference configured steppers")
    if carriage_axis_name == chuck_axis_name:
        raise ValueError("MACHINE carriage_axis and chuck_axis must be different")

    negative_name = machine_config.get("carriage_negative_endstop")
    positive_name = machine_config.get("carriage_positive_endstop")
    if negative_name == positive_name:
        raise ValueError("carriage endstops must be different switches")
    _validate_machine_endstop(negative_name, carriage_axis_name, -1)
    _validate_machine_endstop(positive_name, carriage_axis_name, 1)

    run_enable_name = machine_config.get("run_enable_switch")
    if run_enable_name is not None:
        run_enable_config = config.SWITCHES.get(run_enable_name)
        if run_enable_config is None or run_enable_config.get("mode") != "run_enable":
            raise ValueError("MACHINE run_enable_switch must reference a run_enable switch")
        if bool(machine_config.get("carriage_auto_start", False)):
            raise ValueError("carriage_auto_start must be False when a run-enable switch is configured")

    manual_index_name = machine_config.get("manual_index_switch")
    if manual_index_name is not None:
        manual_index_config = config.SWITCHES.get(manual_index_name)
        if manual_index_config is None or manual_index_config.get("mode") != "manual_index":
            raise ValueError("MACHINE manual_index_switch must reference a manual_index switch")

    carriage_rate = abs(int(machine_config.get("carriage_run_steps_per_second", 0)))
    carriage_max_rate = int(config.STEPPERS[carriage_axis_name]["max_steps_per_second"])
    if carriage_rate <= 0 or carriage_rate > carriage_max_rate:
        raise ValueError("carriage_run_steps_per_second must be between 1 and the carriage max rate")

    index_steps = int(machine_config.get("chuck_index_steps", 0))
    index_rate = abs(int(machine_config.get("chuck_index_rate", 0)))
    chuck_max_rate = int(config.STEPPERS[chuck_axis_name]["max_steps_per_second"])
    if index_steps != 0 and (index_rate <= 0 or index_rate > chuck_max_rate):
        raise ValueError("chuck_index_rate must be between 1 and the chuck max rate")

    pulse_width_us = int(config.STEP_PULSE_US)
    if pulse_width_us < 2:
        raise ValueError("STEP_PULSE_US must be at least 2")
    maximum_configured_rate = max(
        int(stepper_config["max_steps_per_second"]) for stepper_config in config.STEPPERS.values()
    )
    if pulse_width_us + 2 > 1_000_000 // maximum_configured_rate:
        raise ValueError("STEP_PULSE_US is too long for the configured maximum step rate")
    if int(config.SWITCH_DEBOUNCE_MS) < 0:
        raise ValueError("SWITCH_DEBOUNCE_MS cannot be negative")
    if int(config.MAIN_LOOP_IDLE_US) < 0:
        raise ValueError("MAIN_LOOP_IDLE_US cannot be negative")
    if int(config.MAX_CONTROL_DT_US) <= 0:
        raise ValueError("MAX_CONTROL_DT_US must be positive")
    if int(config.SERIAL_READ_CHUNK) <= 0:
        raise ValueError("SERIAL_READ_CHUNK must be positive")


def _claim_pin(used_pins, pin_number, owner):
    if isinstance(pin_number, bool) or not isinstance(pin_number, int) or pin_number < 0:
        raise ValueError("{owner} must use a non-negative integer GPIO pin".format(owner=owner))
    if pin_number in used_pins:
        raise ValueError(
            "GPIO {pin} is assigned to both {first} and {second}".format(
                pin=pin_number,
                first=used_pins[pin_number],
                second=owner,
            )
        )
    used_pins[pin_number] = owner


def _validate_machine_endstop(switch_name, carriage_axis_name, expected_direction):
    switch_config = config.SWITCHES.get(switch_name)
    if switch_config is None:
        raise ValueError("MACHINE references unknown endstop '{name}'".format(name=switch_name))
    if (
        switch_config.get("mode") != "endstop"
        or switch_config.get("motor") != carriage_axis_name
        or int(switch_config.get("direction", 0)) != expected_direction
    ):
        raise ValueError(
            "{name} must be a carriage endstop with direction {direction}".format(
                name=switch_name,
                direction=expected_direction,
            )
        )


def build_stepper(stepper_config):
    return StepDirStepper(
        stepper_config["step_pin"],
        stepper_config["dir_pin"],
        stepper_config.get("enable_pin"),
        enable_active_low=stepper_config.get("enable_active_low", config.ENABLE_ACTIVE_LOW),
        direction_high_is_forward=stepper_config.get("direction_high_is_forward", True),
        pulse_width_us=config.STEP_PULSE_US,
    )


def build_switches():
    switches = {}
    for switch_name, switch_config in config.SWITCHES.items():
        switches[switch_name] = {
            "config": switch_config,
            "switch": DebouncedSwitch(
                switch_config["pin"],
                config.SWITCH_DEBOUNCE_MS,
                active_low=switch_config.get("active_low", True),
                mode=switch_config.get("mode", "jog"),
            ),
        }
    return switches


def gate_physical_jog(jog_direction, shuttle):
    if jog_direction != 0 and not shuttle._run_allows_motion():
        return 0
    return jog_direction


def collect_axis_inputs(axis_name, switches):
    jog_direction = 0
    negative_limit_active = False
    positive_limit_active = False

    for switch_state in switches.values():
        switch_config = switch_state["config"]
        if switch_config.get("motor") != axis_name:
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
    validate_configuration()
    axes = {}
    try:
        for axis_name, stepper_config in config.STEPPERS.items():
            axes[axis_name] = AxisController(axis_name, build_stepper(stepper_config), stepper_config)

        switches = build_switches()
        shuttle = ShuttleController(axes, switches)
        serial_console = SerialCommandInterface(axes, switches, shuttle)

        print("ready: type 'help' for commands")
        previous_loop_us = time.ticks_us()

        while True:
            now_ms = time.ticks_ms()
            for switch_state in switches.values():
                switch_state["switch"].update(now_ms)

            shuttle.service()

            now_us = time.ticks_us()
            dt_us = time.ticks_diff(now_us, previous_loop_us)
            previous_loop_us = now_us

            for axis_name, axis in axes.items():
                jog_direction, negative_limit_active, positive_limit_active = collect_axis_inputs(
                    axis_name, switches
                )
                jog_direction = gate_physical_jog(jog_direction, shuttle)
                axis.update(
                    time.ticks_us(),
                    dt_us,
                    jog_direction,
                    negative_limit_active,
                    positive_limit_active,
                )

            serial_console.service()
            time.sleep_us(config.MAIN_LOOP_IDLE_US)
    finally:
        for axis in axes.values():
            try:
                axis.stop()
            except Exception:
                pass


if __name__ == "__main__":
    main()
