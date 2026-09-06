import importlib.util
import pathlib
import types
import unittest
from unittest import mock


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONSOLE_PATH = PROJECT_ROOT / "tools" / "controller_console.py"
SPEC = importlib.util.spec_from_file_location("controller_console", CONSOLE_PATH)
console = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(console)


class ControllerPortDiscoveryTests(unittest.TestCase):
    def test_explicit_port_is_used_without_discovery(self):
        with mock.patch.object(console.list_ports, "comports") as comports:
            self.assertEqual("COM9", console.find_controller_port("COM9"))
            comports.assert_not_called()

    def test_teensy_serial_port_is_discovered(self):
        ports = [types.SimpleNamespace(device="COM5", vid=0x16C0)]
        with mock.patch.object(console.list_ports, "comports", return_value=ports):
            self.assertEqual("COM5", console.find_controller_port())

    def test_pico_serial_port_is_still_discovered(self):
        ports = [types.SimpleNamespace(device="COM4", vid=0x2E8A)]
        with mock.patch.object(console.list_ports, "comports", return_value=ports):
            self.assertEqual("COM4", console.find_controller_port())

    def test_multiple_compatible_ports_require_explicit_selection(self):
        ports = [
            types.SimpleNamespace(device="COM4", vid=0x2E8A),
            types.SimpleNamespace(device="COM5", vid=0x16C0),
        ]
        with mock.patch.object(console.list_ports, "comports", return_value=ports):
            with self.assertRaisesRegex(RuntimeError, "multiple compatible"):
                console.find_controller_port()


class ControllerResponseTests(unittest.TestCase):
    def test_error_response_is_detected_for_one_shot_automation(self):
        self.assertTrue(console.response_has_error("error run-enable switch is in Stop"))
        self.assertTrue(console.response_has_error("ok stop\nerror invalid numeric argument"))
        self.assertFalse(console.response_has_error("ok stop"))


if __name__ == "__main__":
    unittest.main()
