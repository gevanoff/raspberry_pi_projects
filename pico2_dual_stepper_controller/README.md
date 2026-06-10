# Pico Dual Stepper Controller

This project configures a Raspberry Pi Pico-class board to control:

- two stepper motors through external step/dir drivers such as A4988, DRV8825, or TMC2208/TMC2209 in step/dir mode
- four basic switches wired as active-low inputs using the Pico's internal pull-ups

The controller code in `src/` works on both Raspberry Pi Pico and Pico 2 boards. The only board-specific part in this project is which MicroPython UF2 you flash.

This project does not drive stepper motor coils directly from the Pico. Each motor must use a dedicated motor driver.

## Intended machine behavior

This build is now tailored for a rail carriage plus rotating chuck:

- motor A drives the carriage belt through the DM542 at a constant rate
- switch 1 is the carriage negative-end endstop
- switch 2 is the carriage positive-end endstop
- when the active carriage endstop is reached, motor A reverses direction
- each carriage reversal also commands motor B to rotate the chuck by a small fixed index amount
- switch 3 manually jogs the chuck forward through the TB6600
- switch 4 manually jogs the chuck reverse through the TB6600

Both axes still use acceleration ramps. The carriage shuttle is disabled on boot by default for safety; start it explicitly over USB serial when the mechanics are ready.

## Serial control

The board also exposes a USB serial command interface. Once the Pico is running and enumerated as a serial port, you can connect with `mpremote`:

```powershell
py -m mpremote connect auto
```

Available commands:

- `start`
- `pause`
- `reverse`
- `index [steps] [rate]`
- `help`
- `status`
- `stop`
- `rate <axis> <steps_per_second>`
- `jog <axis> <forward|reverse|stop> [rate]`
- `move <axis> <delta_steps> [rate]`
- `zero <axis>`

Axis names can be `motor_a`, `motor_b`, `a`, or `b`.

Examples:

```text
status
start
index
jog b forward 120
move b -1600 300
pause
```

Manual chuck jogging remains active whenever there is no active chuck index move or serial-rate command in progress.

## Switch roles

Each switch entry in `src/config.py` has:

- `pin`: the Pico GPIO number
- `mode`: `jog` or `endstop`
- `motor`: `motor_a` or `motor_b`
- `direction`: `1` for forward/max, `-1` for reverse/min

The current default uses two carriage endstops and two chuck jog buttons. A triggered carriage endstop reverses the shuttle and starts a chuck index move. Any triggered endstop also blocks motion farther into that same direction.

Current default configuration:

```python
SWITCHES = {
	"switch_1": {"pin": 10, "mode": "endstop", "motor": "motor_a", "direction": -1},
	"switch_2": {"pin": 11, "mode": "endstop", "motor": "motor_a", "direction": 1},
	"switch_3": {"pin": 12, "mode": "jog", "motor": "motor_b", "direction": 1},
	"switch_4": {"pin": 13, "mode": "jog", "motor": "motor_b", "direction": -1},
}
```

The automatic shuttle and chuck index behavior is configured in `MACHINE` inside `src/config.py`.

## Default pin map

Edit `src/config.py` if your wiring differs.

| Function | GPIO |
| --- | --- |
| Motor A step | 2 |
| Motor A dir | 3 |
| Motor A enable | 4 |
| Motor B step | 6 |
| Motor B dir | 7 |
| Motor B enable | 8 |
| Switch 1 | 10 |
| Switch 2 | 11 |
| Switch 3 | 12 |
| Switch 4 | 13 |

The example assumes enable is active-low, which matches many common stepper drivers.

## Wiring notes

- Tie Pico GND to both motor-driver GND pins.
- Power the motor drivers from the correct external motor supply. Do not power the motors from the Pico.
- Connect each switch between its GPIO pin and GND.
- Leave the Pico inputs configured with pull-ups enabled.
- DM542 and TB6600 inputs are often opto-isolated and may not be happy with direct 3.3 V drive in every wiring mode. Verify the driver input current and logic thresholds before wiring the Pico directly. If needed, use proper level-shifting or transistor drivers for `STEP`, `DIR`, and `ENA`.

## Flash MicroPython to the board

The board is flashable when it appears as the `RPI-RP2` USB drive.

1. Hold `BOOTSEL` while plugging the Pico 2 into USB.
2. Confirm the `RPI-RP2` drive appears.
3. Run the correct flash command for your board:

```powershell
./tools/flash_micropython.ps1 -BoardModel pico
```

or:

```powershell
./tools/flash_micropython.ps1 -BoardModel pico2
```

The script uses these official MicroPython UF2 images:

- `pico`: `https://micropython.org/download/rp2-pico/rp2-pico-latest.uf2`
- `pico2`: `https://micropython.org/download/RPI_PICO2/RPI_PICO2-latest.uf2`

If the board later identifies itself to `mpremote` as `Raspberry Pi Pico with RP2040`, use `-BoardModel pico`.

## Copy the project files to the board

After MicroPython is installed and the Pico has rebooted into normal runtime mode:

1. Install `mpremote` on the host if needed:

```powershell
py -m pip install mpremote
```

2. Sync the project files:

```powershell
./tools/sync_micropython_files.ps1
```

That script copies `src/config.py`, `src/stepper.py`, and `src/main.py` to the Pico filesystem and then resets the board.

## Tuning

You will most likely want to adjust these values in `src/config.py`:

- `default_steps_per_second` per motor
- `max_steps_per_second` per motor
- `acceleration_steps_per_second_squared` per motor
- `MACHINE["carriage_run_steps_per_second"]`
- `MACHINE["carriage_auto_start"]`
- `MACHINE["chuck_index_steps"]`
- `MACHINE["chuck_index_rate"]`
- `STEP_PULSE_US`
- `SWITCH_DEBOUNCE_MS`
- `ENABLE_ACTIVE_LOW`

If your drivers require inverted direction logic, flip `direction_high_is_forward` for the affected motor.