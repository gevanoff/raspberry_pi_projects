import pathlib
import sys
import types
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


class FakeTime:
    TICKS_PERIOD = 1 << 30

    def __init__(self):
        self.now_us = 0

    def reset(self):
        self.now_us = 0

    def advance_us(self, amount):
        self.now_us = (self.now_us + int(amount)) % self.TICKS_PERIOD

    def ticks_us(self):
        return self.now_us

    def ticks_ms(self):
        return (self.now_us // 1000) % self.TICKS_PERIOD

    def ticks_add(self, ticks, delta):
        return (ticks + int(delta)) % self.TICKS_PERIOD

    def ticks_diff(self, ticks1, ticks2):
        half_period = self.TICKS_PERIOD // 2
        return ((ticks1 - ticks2 + half_period) % self.TICKS_PERIOD) - half_period

    def sleep_us(self, amount):
        self.advance_us(amount)


FAKE_TIME = FakeTime()


class FakePin:
    IN = 0
    OUT = 1
    PULL_UP = 2
    instances = {}
    initial_values = {}

    def __init__(self, number, mode, pull=None, value=None):
        self.number = number
        self.mode = mode
        self.pull = pull
        if value is None:
            value = self.initial_values.get(
                number, 1 if mode == self.IN and pull == self.PULL_UP else 0
            )
        self._value = value
        self.events = [(FAKE_TIME.ticks_us(), value)]
        self.instances[number] = self

    def value(self, new_value=None):
        if new_value is None:
            return self._value
        self._value = int(bool(new_value))
        self.events.append((FAKE_TIME.ticks_us(), self._value))


class FakePoll:
    def register(self, stream, event):
        pass

    def poll(self, timeout):
        return []


machine_module = types.ModuleType("machine")
machine_module.Pin = FakePin
sys.modules["machine"] = machine_module

uselect_module = types.ModuleType("uselect")
uselect_module.POLLIN = 1
uselect_module.poll = FakePoll
sys.modules["uselect"] = uselect_module

import config  # noqa: E402
import stepper  # noqa: E402

stepper.time = FAKE_TIME

import main as controller  # noqa: E402

controller.time = FAKE_TIME


class SwitchStub:
    def __init__(self, pressed=False, edge=False):
        self.pressed = pressed
        self.edge = edge

    def consume_pressed_edge(self):
        edge = self.edge
        self.edge = False
        return edge


class AxisStub:
    def __init__(self, default_rate):
        self.default_rate = default_rate
        self.max_rate = 1000
        self.external_rate = None
        self.queued_moves = []
        self.stop_count = 0

    def stop(self):
        self.stop_count += 1
        self.external_rate = None

    def set_external_rate(self, rate):
        self.external_rate = rate

    def clear_external_rate(self):
        self.external_rate = None

    def queue_relative(self, steps, rate):
        self.queued_moves.append((steps, rate))


class StepperTests(unittest.TestCase):
    def setUp(self):
        FAKE_TIME.reset()
        FakePin.instances = {}
        FakePin.initial_values = {}

    def test_enable_pin_is_inactive_from_first_output_write(self):
        motor = stepper.StepDirStepper(2, 3, 4, enable_active_low=True)

        self.assertEqual([(0, 1), (0, 1)], motor.enable_pin.events)
        motor.set_rate(100)
        self.assertEqual(0, motor.enable_pin.value())
        motor.set_rate(0)
        self.assertEqual(1, motor.enable_pin.value())

    def test_rate_change_preserves_partial_step_interval(self):
        motor = stepper.StepDirStepper(2, 3, 4, pulse_width_us=20)
        motor.set_rate(10)
        FAKE_TIME.advance_us(50_000)

        motor.set_rate(20)
        FAKE_TIME.advance_us(24_999)
        self.assertEqual(0, motor.update())
        FAKE_TIME.advance_us(1)
        self.assertEqual(1, motor.update())
        self.assertEqual(1, motor.position_steps)

        high_event, low_event = motor.step_pin.events[-2:]
        self.assertEqual((75_000, 1), high_event)
        self.assertEqual((75_020, 0), low_event)

    def test_long_stall_does_not_create_catch_up_burst(self):
        motor = stepper.StepDirStepper(2, 3, 4, pulse_width_us=20)
        motor.set_rate(100)
        FAKE_TIME.advance_us(100_000)

        self.assertEqual(1, motor.update())
        self.assertEqual(0, motor.update())
        self.assertEqual(1, motor.position_steps)

    def test_step_deadline_survives_tick_counter_wrap(self):
        FAKE_TIME.now_us = FAKE_TIME.TICKS_PERIOD - 5_000
        motor = stepper.StepDirStepper(2, 3, 4, pulse_width_us=20)
        motor.set_rate(100)
        FAKE_TIME.advance_us(9_999)
        self.assertEqual(0, motor.update())
        FAKE_TIME.advance_us(1)
        self.assertEqual(1, motor.update())

    def test_axis_emits_steps_before_acceleration_finishes(self):
        motor = stepper.StepDirStepper(2, 3, 4, pulse_width_us=20)
        axis = controller.AxisController(
            "test",
            motor,
            {
                "default_steps_per_second": 100,
                "max_steps_per_second": 100,
                "acceleration_steps_per_second_squared": 100,
            },
        )
        axis.set_serial_rate(100)

        for _ in range(50):
            FAKE_TIME.advance_us(10_000)
            axis.update(FAKE_TIME.ticks_us(), 10_000)

        self.assertGreater(motor.position_steps, 0)
        self.assertLess(motor.current_rate, 100)

    def test_finite_move_uses_braking_speed_near_target(self):
        motor = stepper.StepDirStepper(2, 3, 4)
        axis = controller.AxisController(
            "test",
            motor,
            {
                "default_steps_per_second": 100,
                "max_steps_per_second": 100,
                "acceleration_steps_per_second_squared": 100,
            },
        )
        axis.move_relative(1000, 100)
        self.assertEqual(100, axis._desired_rate(0))
        motor.set_position(998)
        self.assertEqual(20, axis._desired_rate(0))

    def test_queued_relative_moves_preserve_every_index_request(self):
        motor = stepper.StepDirStepper(2, 3, 4)
        axis = controller.AxisController(
            "test",
            motor,
            {
                "default_steps_per_second": 100,
                "max_steps_per_second": 100,
                "acceleration_steps_per_second_squared": 100,
            },
        )

        axis.queue_relative(120, 80)
        axis.queue_relative(120, 80)
        self.assertEqual(240, axis.move_target_position)

    def test_finite_move_stops_at_exact_requested_position(self):
        motor = stepper.StepDirStepper(2, 3, 4)
        axis = controller.AxisController(
            "test",
            motor,
            {
                "default_steps_per_second": 100,
                "max_steps_per_second": 100,
                "acceleration_steps_per_second_squared": 1000,
            },
        )
        axis.move_relative(25, 100)

        for _ in range(5000):
            FAKE_TIME.advance_us(1000)
            axis.update(FAKE_TIME.ticks_us(), 1000)
            if axis.move_target_position is None:
                break

        self.assertEqual(25, motor.position_steps)
        self.assertEqual(0, motor.current_rate)
        self.assertIsNone(axis.move_target_position)

    def test_active_limit_immediately_cancels_motion_into_limit(self):
        motor = stepper.StepDirStepper(2, 3, 4)
        axis = controller.AxisController(
            "test",
            motor,
            {
                "default_steps_per_second": 100,
                "max_steps_per_second": 100,
                "acceleration_steps_per_second_squared": 1000,
            },
        )
        axis.move_relative(-100, 100)
        FAKE_TIME.advance_us(50_000)
        axis.update(FAKE_TIME.ticks_us(), 50_000)
        self.assertLess(motor.current_rate, 0)

        FAKE_TIME.advance_us(1000)
        axis.update(FAKE_TIME.ticks_us(), 1000, negative_limit_active=True)
        self.assertEqual(0, motor.current_rate)
        self.assertIsNone(axis.move_target_position)

    def test_direction_change_passes_through_a_stopped_update(self):
        motor = stepper.StepDirStepper(2, 3, 4)
        axis = controller.AxisController(
            "test",
            motor,
            {
                "default_steps_per_second": 100,
                "max_steps_per_second": 100,
                "acceleration_steps_per_second_squared": 1000,
            },
        )
        axis.ramped_rate = 10.0
        motor.set_rate(10)
        axis.set_serial_rate(-100)

        FAKE_TIME.advance_us(50_000)
        axis.update(FAKE_TIME.ticks_us(), 50_000)
        self.assertEqual(0, motor.current_rate)

        FAKE_TIME.advance_us(1000)
        axis.update(FAKE_TIME.ticks_us(), 1000)
        self.assertLess(motor.current_rate, 0)


class InputAndShuttleTests(unittest.TestCase):
    def setUp(self):
        FAKE_TIME.reset()
        FakePin.instances = {}
        FakePin.initial_values = {}

    def test_endstop_asserts_immediately_and_debounces_release(self):
        endstop = controller.DebouncedSwitch(10, 25, mode="endstop")
        endstop.pin.value(0)
        endstop.update(FAKE_TIME.ticks_ms())
        self.assertTrue(endstop.pressed)
        self.assertTrue(endstop.consume_pressed_edge())

        endstop.pin.value(1)
        endstop.update(FAKE_TIME.ticks_ms())
        self.assertTrue(endstop.pressed)
        FAKE_TIME.advance_us(25_000)
        endstop.update(FAKE_TIME.ticks_ms())
        self.assertFalse(endstop.pressed)

    def test_jog_debounces_start_and_releases_immediately(self):
        jog = controller.DebouncedSwitch(12, 25, mode="jog")
        jog.pin.value(0)
        jog.update(FAKE_TIME.ticks_ms())
        self.assertFalse(jog.pressed)
        FAKE_TIME.advance_us(25_000)
        jog.update(FAKE_TIME.ticks_ms())
        self.assertTrue(jog.pressed)

        jog.pin.value(1)
        jog.update(FAKE_TIME.ticks_ms())
        self.assertFalse(jog.pressed)

    def test_active_high_endstop_is_supported_for_normally_closed_wiring(self):
        FakePin.initial_values[10] = 0
        endstop = controller.DebouncedSwitch(10, 25, active_low=False, mode="endstop")
        self.assertFalse(endstop.pressed)
        endstop.pin.value(1)
        endstop.update(FAKE_TIME.ticks_ms())
        self.assertTrue(endstop.pressed)

    def _build_shuttle(self, negative, positive, run_enable=None, manual_index=None):
        if run_enable is None:
            run_enable = SwitchStub(True, False)
        if manual_index is None:
            manual_index = SwitchStub(False, False)
        carriage = AxisStub(450)
        chuck = AxisStub(180)
        axes = {"motor_a": carriage, "motor_b": chuck}
        switches = {
            config.MACHINE["carriage_negative_endstop"]: {"switch": negative},
            config.MACHINE["carriage_positive_endstop"]: {"switch": positive},
            config.MACHINE["run_enable_switch"]: {"switch": run_enable},
            config.MACHINE["manual_index_switch"]: {"switch": manual_index},
        }
        shuttle = controller.ShuttleController(axes, switches)
        shuttle.run_switch_armed = True
        shuttle.run_fault_latched = False
        return shuttle, carriage, chuck

    def test_paused_shuttle_ignores_endstop_edge_without_indexing(self):
        shuttle, carriage, chuck = self._build_shuttle(
            SwitchStub(False, False), SwitchStub(True, True)
        )

        shuttle.service()
        self.assertFalse(shuttle.auto_enabled)
        self.assertEqual(1, shuttle.current_direction)
        self.assertEqual([], chuck.queued_moves)
        self.assertIsNone(carriage.external_rate)

    def test_start_refuses_contradictory_endstops(self):
        shuttle, carriage, chuck = self._build_shuttle(SwitchStub(True), SwitchStub(True))

        with self.assertRaisesRegex(ValueError, "both carriage endstops"):
            shuttle.start()
        self.assertFalse(shuttle.auto_enabled)
        self.assertIsNone(carriage.external_rate)
        self.assertEqual([], chuck.queued_moves)

    def test_endstop_reversal_queues_one_index_while_running(self):
        shuttle, carriage, chuck = self._build_shuttle(
            SwitchStub(False, False), SwitchStub(False, False)
        )
        shuttle.start()
        shuttle.positive_endstop.pressed = True
        shuttle.positive_endstop.edge = True

        shuttle.service()
        self.assertEqual(-1, shuttle.current_direction)
        self.assertEqual(-450, carriage.external_rate)
        self.assertEqual([(120, 220)], chuck.queued_moves)

    def test_both_endstops_during_motion_pause_without_indexing(self):
        shuttle, carriage, chuck = self._build_shuttle(
            SwitchStub(False, False), SwitchStub(False, False)
        )
        shuttle.start()
        shuttle.negative_endstop.pressed = True
        shuttle.negative_endstop.edge = True
        shuttle.positive_endstop.pressed = True
        shuttle.positive_endstop.edge = True

        shuttle.service()
        self.assertFalse(shuttle.auto_enabled)
        self.assertIsNone(carriage.external_rate)
        self.assertEqual([], chuck.queued_moves)
        self.assertEqual("fault:both_endstops", shuttle.last_reversal_source)
        self.assertTrue(shuttle.run_fault_latched)

    def test_opposite_endstop_edge_pauses_as_an_input_fault(self):
        shuttle, carriage, chuck = self._build_shuttle(
            SwitchStub(True, True), SwitchStub(False, False)
        )
        shuttle.start()

        shuttle.service()
        self.assertFalse(shuttle.auto_enabled)
        self.assertIsNone(carriage.external_rate)
        self.assertEqual([], chuck.queued_moves)
        self.assertEqual(
            "fault:{name}".format(name=config.MACHINE["carriage_negative_endstop"]),
            shuttle.last_reversal_source,
        )
        self.assertTrue(shuttle.run_fault_latched)

    def test_run_switch_stop_immediately_stops_both_axes(self):
        run_enable = SwitchStub(True, False)
        shuttle, carriage, chuck = self._build_shuttle(
            SwitchStub(False), SwitchStub(False), run_enable
        )
        shuttle.start()
        run_enable.pressed = False

        shuttle.service()
        self.assertFalse(shuttle.auto_enabled)
        self.assertEqual(2, carriage.stop_count)
        self.assertEqual(1, chuck.stop_count)
        self.assertTrue(shuttle.run_switch_armed)
        self.assertFalse(shuttle.run_fault_latched)
        self.assertEqual("run_switch_stop", shuttle.last_reversal_source)

    def test_run_switch_go_edge_starts_only_after_stop_cycle(self):
        run_enable = SwitchStub(True, False)
        shuttle, carriage, chuck = self._build_shuttle(
            SwitchStub(False), SwitchStub(False), run_enable
        )
        shuttle.run_switch_armed = False
        with self.assertRaisesRegex(ValueError, "cycle the run-enable"):
            shuttle.start()

        run_enable.pressed = False
        shuttle.service()
        self.assertTrue(shuttle.run_switch_armed)
        run_enable.pressed = True
        run_enable.edge = True
        shuttle.service()
        self.assertTrue(shuttle.auto_enabled)
        self.assertFalse(shuttle.run_switch_armed)
        self.assertEqual(450, carriage.external_rate)

    def test_run_switch_already_in_go_at_boot_is_fault_latched(self):
        carriage = AxisStub(450)
        chuck = AxisStub(180)
        run_enable = SwitchStub(True, False)
        shuttle = controller.ShuttleController(
            {"motor_a": carriage, "motor_b": chuck},
            {
                config.MACHINE["carriage_negative_endstop"]: {"switch": SwitchStub(False)},
                config.MACHINE["carriage_positive_endstop"]: {"switch": SwitchStub(False)},
                config.MACHINE["run_enable_switch"]: {"switch": run_enable},
                config.MACHINE["manual_index_switch"]: {"switch": SwitchStub(False)},
            },
        )

        self.assertFalse(shuttle.auto_enabled)
        self.assertFalse(shuttle.run_switch_armed)
        self.assertTrue(shuttle.run_fault_latched)
        with self.assertRaisesRegex(ValueError, "clear the fault"):
            shuttle.start()

    def test_manual_index_switch_queues_once_per_close_edge(self):
        manual_index = SwitchStub(False, False)
        shuttle, carriage, chuck = self._build_shuttle(
            SwitchStub(False), SwitchStub(False), manual_index=manual_index
        )
        shuttle.start()
        manual_index.pressed = True
        manual_index.edge = True

        shuttle.service()
        shuttle.service()
        self.assertEqual([(120, 220)], chuck.queued_moves)

    def test_manual_index_is_ignored_while_run_switch_is_stopped(self):
        run_enable = SwitchStub(False, False)
        manual_index = SwitchStub(True, True)
        shuttle, carriage, chuck = self._build_shuttle(
            SwitchStub(False),
            SwitchStub(False),
            run_enable=run_enable,
            manual_index=manual_index,
        )

        shuttle.service()
        self.assertEqual([], chuck.queued_moves)
        self.assertFalse(shuttle.auto_enabled)


class ConfigurationTests(unittest.TestCase):
    def test_default_configuration_is_valid(self):
        controller.validate_configuration()

    def test_duplicate_gpio_is_rejected(self):
        switch_name = config.MACHINE["carriage_negative_endstop"]
        original_pin = config.SWITCHES[switch_name]["pin"]
        config.SWITCHES[switch_name]["pin"] = config.STEPPERS["motor_a"]["step_pin"]
        try:
            with self.assertRaisesRegex(ValueError, "assigned to both"):
                controller.validate_configuration()
        finally:
            config.SWITCHES[switch_name]["pin"] = original_pin


class SerialCommandTests(unittest.TestCase):
    def test_manual_carriage_control_is_rejected_during_auto_mode(self):
        carriage = AxisStub(450)
        chuck = AxisStub(180)
        shuttle = types.SimpleNamespace(carriage_axis=carriage, auto_enabled=True, run_enable=None)
        interface = controller.SerialCommandInterface(
            {"motor_a": carriage, "motor_b": chuck}, {}, shuttle
        )

        with self.assertRaisesRegex(ValueError, "pause the shuttle"):
            interface._require_manual_axis_control(carriage)
        interface._require_manual_axis_control(chuck)


if __name__ == "__main__":
    unittest.main()
