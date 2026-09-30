# Dual Stepper Controller

This project contains two firmware targets for the same rail-carriage and chuck
controller:

- `teensy/dual_stepper_controller`: the recommended Teensy 4.0 C++ firmware
- `src`: the original Raspberry Pi Pico/Pico 2 MicroPython firmware

Both targets control:

- two stepper motors through external step/dir drivers such as A4988, DRV8825, or TMC2208/TMC2209 in step/dir mode
- two rail endstops, one run-enable switch, and one manual chuck-index switch using the selected controller's internal pull-ups

The Pico controller code in `src/` works on both Raspberry Pi Pico and Pico 2
boards. The Teensy target preserves the same command protocol and safety
interlocks, but it is a separate C++ implementation built with Teensyduino.

This project does not drive stepper motor coils directly from either controller.
Each motor uses its dedicated DM542 or TB6600 driver. The Teensy must connect to
those optocoupled inputs through the documented low-side transistor interface,
not directly from its GPIO pins. See
[`docs/teensy40_wiring.md`](docs/teensy40_wiring.md).

## Teensy 4.0 target

The Teensy firmware uses a fixed-size serial parser with no heap-allocated
`String` objects. It preserves fractional step deadlines during acceleration,
uses wrap-safe `micros()` arithmetic, produces a complete 20 us pulse, skips
catch-up bursts after a delayed loop, brakes finite moves, and passes direction
changes through zero speed.

Build it from PowerShell:

```powershell
./tools/build_teensy.ps1
```

Build and upload to the one connected Teensy 4.0:

```powershell
./tools/build_teensy.ps1 -Upload
```

Build or upload the on-device regression firmware:

```powershell
./tools/build_teensy.ps1 -Target self-test
./tools/build_teensy.ps1 -Target self-test -Upload
```

The self-test uses fake pins and time internally; it never drives the configured
motor outputs. Upload the production target again after running it.

Teensy pin assignments are compile-time checked in
`teensy/dual_stepper_controller/controller_config.h`:

| Function | Teensy pin |
| --- | ---: |
| Motor A STEP / DIR / ENABLE | 2 / 3 / 4 |
| Motor B STEP / DIR / ENABLE | 6 / 7 / 8 |
| Stop/Go, switch labeled 11 | 14 |
| Manual index, switch labeled 12 | 15 |
| Negative endstop, switch labeled 13 | 16 |
| Positive endstop, switch labeled 14 | 17 |

Install the toolchain with Arduino CLI and PJRC's board-manager URL:

```powershell
arduino-cli config init
arduino-cli config add board_manager.additional_urls https://www.pjrc.com/teensy/package_teensy_index.json
arduino-cli core update-index
arduino-cli core install teensy:avr@1.62.0
```

## Intended machine behavior

This build is now tailored for a rail carriage plus rotating chuck:

- motor A drives the carriage belt through the DM542 at a constant rate
- the switch labeled 13 (Pico GPIO12 / Teensy pin 16) is the carriage negative-end endstop
- the switch labeled 14 (Pico GPIO13 / Teensy pin 17) is the carriage positive-end endstop
- when the active carriage endstop is reached, motor A reverses direction
- each carriage reversal also commands motor B to rotate the chuck by a small fixed index amount
- the switch labeled 11 (Pico GPIO10 / Teensy pin 14) is the carriage Stop/Go run-enable control
- the switch labeled 12 (Pico GPIO11 / Teensy pin 15) manually commands one chuck index per close transition

Both axes still use acceleration ramps. The carriage shuttle is disabled on boot. It starts only after the run-enable switch has been observed in Stop and is then switched to Go. This Stop-to-Go interlock prevents an unexpected restart after boot, a controller reset, or an endstop fault.

Finite moves use acceleration and braking ramps. Chuck index requests are queued, so a new carriage reversal does not discard an unfinished index. The controller refuses to start the shuttle if both carriage endstops are active. If both endstops become active during motion, or the endstop opposite the direction of travel unexpectedly asserts, the shuttle pauses without indexing; `status` identifies the fault in `last_reversal`.

## Serial control

The host console uses `pyserial`. Install the declared host dependency once:

```powershell
py -m pip install -r requirements-host.txt
```

The board also exposes a USB serial command interface. Once the Pico or Teensy is running and enumerated as a serial port, start the dedicated controller console:

```powershell
./tools/controller_console.ps1
```

The console auto-detects a connected Raspberry Pi Pico or PJRC Teensy, prints
the current status, and presents a `controller>` prompt. If more than one
compatible controller is connected, select the port explicitly:

```powershell
./tools/controller_console.ps1 -Port COM5
```

Type `exit`, `quit`, Ctrl+C, or Ctrl+Z followed by Enter to close the console. It sends `stop` before disconnecting so that losing the console does not intentionally leave commanded motion active. Do not use `mpremote` as the controller terminal: it enters the MicroPython REPL and interrupts `main.py`.

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

The physical run-enable switch is a master motion interlock for serial motion commands as well as the automatic shuttle. `start` is rejected while the switch is in Stop or a fault still requires a Stop-to-Go cycle.

`pause` decelerates and pauses the automatic carriage shuttle; it does not cancel independent chuck motion. `stop` immediately disables both axes and cancels all automatic, serial, and finite-move commands. While the shuttle is running, manual `rate`, `jog`, `move`, and `zero` commands for the carriage axis are rejected; pause it first. This prevents two control modes from silently competing for the carriage.

## Switch roles

Each switch entry in `src/config.py` has:

- `pin`: the Pico GPIO number
- `mode`: `endstop`, `run_enable`, `manual_index`, or `jog`
- `motor`: `motor_a` or `motor_b` for endstop and jog inputs
- `direction`: `1` for forward/max, `-1` for reverse/min for endstop and jog inputs
- `active_low`: `True` when a closed switch pulls the input low; `False` when an open switch is the active/fault state

The current default uses two carriage endstops, one run-enable switch, and one manual-index switch. A triggered carriage endstop reverses the shuttle and starts a chuck index move. Any triggered endstop also blocks motion farther into that same direction. Opening the run-enable switch immediately disables both axes and cancels pending motion. Closing the manual-index switch queues one index; holding it closed does not repeat.

Current default configuration:

```python
SWITCHES = {
    "switch_11_stop_go": {"pin": 10, "mode": "run_enable", "active_low": True},
    "switch_12_manual_index": {"pin": 11, "mode": "manual_index", "active_low": True},
    "switch_13_negative_endstop": {"pin": 12, "mode": "endstop", "motor": "motor_a", "direction": -1, "active_low": True},
    "switch_14_positive_endstop": {"pin": 13, "mode": "endstop", "motor": "motor_a", "direction": 1, "active_low": True},
}
```

The automatic shuttle and chuck index behavior is configured in `MACHINE` inside `src/config.py`.

Endstop assertion is acted on immediately; only release is debounced. The run-enable switch is debounced when entering Go, while entering Stop disables motion immediately. Manual-index assertion is debounced and only its close edge creates an index request.

## Pico default pin map

Edit `src/config.py` if your wiring differs.

| Function | GPIO |
| --- | --- |
| Motor A step | 2 |
| Motor A dir | 3 |
| Motor A enable | 4 |
| Motor B step | 6 |
| Motor B dir | 7 |
| Motor B enable | 8 |
| Stop/Go, switch labeled 11 | 10 |
| Manual chuck index, switch labeled 12 | 11 |
| Negative rail endstop, switch labeled 13 | 12 |
| Positive rail endstop, switch labeled 14 | 13 |

The example assumes enable is active-low, which matches many common stepper drivers.

## Pico wiring notes

- Tie Pico GND to both motor-driver GND pins.
- Power the motor drivers from the correct external motor supply. Do not power the motors from the Pico.
- Connect each switch between its GPIO pin and GND. Closing GPIO10 to GND means Go; opening it means Stop.
- Leave the Pico inputs configured with pull-ups enabled.
- DM542 and TB6600 inputs are often opto-isolated and may not be happy with direct 3.3 V drive in every wiring mode. Verify the driver input current and logic thresholds before wiring the Pico directly. If needed, use proper level-shifting or transistor drivers for `STEP`, `DIR`, and `ENA`.

For the Teensy 4.0, direct connection is not supported by this project. Follow
the exact common-anode sink-interface wiring in
[`docs/teensy40_wiring.md`](docs/teensy40_wiring.md).

The default `active_low=True` switch configuration matches normally-open switches connected to ground. For a more fault-tolerant endstop circuit, use a normally-closed switch connected to ground and set that endstop's `active_low` to `False`; either an opened switch or a broken wire then reports an active limit. For long or noisy wiring, use appropriate external pull resistors, shielding, and/or hardware filtering rather than relying only on the internal pull-up.

## Safety and timing scope

- Treat the software endstops as process controls, not as a safety-rated emergency stop. Use a hard-wired emergency-stop circuit that removes motor power where injury or machine damage is possible.
- Treat the Stop/Go switch (Pico GPIO10 / Teensy pin 14) as an operational control, not an emergency stop. Stop removes step commands and disables the drivers, but it does not physically disconnect the motor power supply.
- Both targets drive step pulses cooperatively from their main loops. They guarantee the configured minimum pulse width and deliberately skip missed pulses after a long runtime stall instead of emitting a catch-up burst. The current hundreds-of-steps-per-second configuration is appropriate for this design; use dedicated timer/peripheral pulse generation if substantially higher rates or tightly bounded jitter are required.
- A stop, uncaught exception, or keyboard interrupt drives `STEP` low and disables every axis that was initialized successfully. Hardware should still default driver-enable inputs to the safe state during reset and before MicroPython starts.
- Configuration is validated before motion starts, including GPIO collisions, axis and endstop references, direction values, positive rates, and pulse-width/rate compatibility.

## Pico: flash MicroPython to the board

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

## Pico: copy the project files to the board

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

When more than one serial device is connected, select the Pico explicitly:

```powershell
./tools/sync_micropython_files.ps1 -Device COM4
```

## Tuning

You will most likely want to adjust these values in `src/config.py`:

- `default_steps_per_second` per motor
- `max_steps_per_second` per motor
- `acceleration_steps_per_second_squared` per motor
- `MACHINE["carriage_run_steps_per_second"]`
- `MACHINE["carriage_auto_start"]`
- `MACHINE["run_enable_switch"]`
- `MACHINE["manual_index_switch"]`
- `MACHINE["chuck_index_steps"]`
- `MACHINE["chuck_index_rate"]`
- `STEP_PULSE_US`
- `SWITCH_DEBOUNCE_MS`
- `ENABLE_ACTIVE_LOW`

If your drivers require inverted direction logic, flip `direction_high_is_forward` for the affected motor.

`MAX_CONTROL_DT_US` caps how much acceleration can be applied after a delayed main-loop iteration, preventing a serial or runtime stall from turning into a large rate jump.

## Regression tests

Install the host dependencies before running the Python console tests:

```powershell
py -m pip install -r requirements-host.txt
```

The tests use mocked GPIO and MicroPython timing, so they can run without a connected Pico:

```powershell
py -m unittest discover -s tests -v
```

They cover ramp timing, pulse width, delayed-loop behavior, tick-counter wraparound, exact finite moves, braking, immediate limit stops, asymmetric switch debounce, contradictory endstops, Stop-to-Go interlocking, queued indexing, GPIO validation, and command-mode conflicts. Before operating real mechanics, also verify direction polarity, endstop polarity, travel clearance, and emergency-stop behavior at a deliberately low configured rate.

The Teensy target has a separate on-device regression sketch covering the same
critical scheduler and interlock behavior. Build it with
`./tools/build_teensy.ps1 -Target self-test`; use `-Upload` only when the Teensy
is disconnected from driver signals or you have otherwise established that the
self-test cannot affect the machine.
