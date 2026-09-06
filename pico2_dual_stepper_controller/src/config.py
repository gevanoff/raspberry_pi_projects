STEPPERS = {
    "motor_a": {
        "step_pin": 2,
        "dir_pin": 3,
        "enable_pin": 4,
        "direction_high_is_forward": True,
        "default_steps_per_second": 450,
        "max_steps_per_second": 650,
        "acceleration_steps_per_second_squared": 1200,
    },
    "motor_b": {
        "step_pin": 6,
        "dir_pin": 7,
        "enable_pin": 8,
        "direction_high_is_forward": True,
        "default_steps_per_second": 180,
        "max_steps_per_second": 500,
        "acceleration_steps_per_second_squared": 1500,
    },
}

SWITCHES = {
    "switch_11_stop_go": {
        "pin": 10,
        "mode": "run_enable",
        "active_low": True,
    },
    "switch_12_manual_index": {
        "pin": 11,
        "mode": "manual_index",
        "active_low": True,
    },
    "switch_13_negative_endstop": {
        "pin": 12,
        "mode": "endstop",
        "motor": "motor_a",
        "direction": -1,
        "active_low": True,
    },
    "switch_14_positive_endstop": {
        "pin": 13,
        "mode": "endstop",
        "motor": "motor_a",
        "direction": 1,
        "active_low": True,
    },
}

MACHINE = {
    "carriage_axis": "motor_a",
    "chuck_axis": "motor_b",
    "carriage_negative_endstop": "switch_13_negative_endstop",
    "carriage_positive_endstop": "switch_14_positive_endstop",
    "run_enable_switch": "switch_11_stop_go",
    "manual_index_switch": "switch_12_manual_index",
    "carriage_run_steps_per_second": 450,
    "carriage_start_direction": 1,
    "carriage_auto_start": False,
    "chuck_index_steps": 120,
    "chuck_index_rate": 220,
    "chuck_index_direction": 1,
}

DEFAULT_STEPS_PER_SECOND = 400
DEFAULT_MOVE_STEPS = 200
STEP_PULSE_US = 20
SWITCH_DEBOUNCE_MS = 25
ENABLE_ACTIVE_LOW = True
MAIN_LOOP_IDLE_US = 100
MAX_CONTROL_DT_US = 50000
SERIAL_READ_CHUNK = 32
