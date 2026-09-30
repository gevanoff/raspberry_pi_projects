# Teensy 4.0 wiring for DM542 and TB6600 drivers

Do not connect the DM542 or TB6600 signal terminals directly to Teensy GPIO.
The Teensy 4.0 pins are 3.3 V only and PJRC recommends no more than 4 mA per
output. The driver inputs are optocoupler LEDs marked for a 5–24 V signal and
can require more current.

The circuit below is a common-anode, low-side-sink interface. "Common anode"
means that the positive side of each driver input goes to +5 V. A transistor
turns that input on by connecting its negative side to ground. The Teensy only
controls the transistor input and does not carry the driver optocoupler current.

## Parts

- one Toshiba `TBD62083APG` DIP-18 eight-channel DMOS sink-driver IC
- one DIP-18 socket, strongly recommended
- six 100 kΩ resistors
- two 10 kΩ resistors
- one 100 nF ceramic capacitor across signal +5 V and ground near the interface
- perfboard or a terminal breakout, plus removable terminal blocks/connectors

The `TBD62083APG` is deliberately specified instead of a classic `ULN2803A`.
The TBD part accepts a 2.5 V or greater HIGH input and has a low MOSFET on
resistance. A Darlington ULN2803 can lose roughly a volt at its output, which is
an avoidable margin problem when the driver signal supply is only 5 V.

If the Toshiba part is unavailable, eight discrete `PN2222A`/`2N2222A`
transistors can implement the same functions, but their resistor wiring and pin
layout are different. Do not substitute a generic bidirectional I2C logic-level
converter.

## Teensy pin map

| Function | Teensy pin | Existing physical label |
| --- | ---: | --- |
| Carriage STEP | 2 | Motor A step |
| Carriage DIR | 3 | Motor A direction |
| Carriage ENABLE control | 4 | Motor A enable |
| Chuck STEP | 6 | Motor B step |
| Chuck DIR | 7 | Motor B direction |
| Chuck ENABLE control | 8 | Motor B enable |
| Stop/Go | 14 | Switch 11 |
| Manual chuck index | 15 | Switch 12 |
| Negative rail endstop | 16 | Switch 13 |
| Positive rail endstop | 17 | Switch 14 |

Teensy pin 13 is intentionally unused because it is connected to the onboard
LED and is unsuitable for one of these pull-up switch inputs.

## TBD62083APG pin map

The DIP is viewed from the top, with its notch upward. Pins 1–9 descend the
left side; pins 10–18 ascend the right side. Verify the notch and pin 1 mark
before soldering.

| TBD pin | Name | Connect to |
| ---: | --- | --- |
| 1 | I1 | Teensy 2, plus 100 kΩ from this pin to ground |
| 18 | O1 | DM542 `PUL-`/`STEP-` |
| 2 | I2 | Teensy 3, plus 100 kΩ from this pin to ground |
| 17 | O2 | DM542 `DIR-` |
| 3 | I3 | Teensy 6, plus 100 kΩ from this pin to ground |
| 16 | O3 | TB6600 `PUL-`/`STEP-` |
| 4 | I4 | Teensy 7, plus 100 kΩ from this pin to ground |
| 15 | O4 | TB6600 `DIR-` |
| 5 | I5 | Teensy 4, plus 100 kΩ from this pin to ground |
| 14 | O5 | Node `ENABLE-A` described below |
| 6 | I6 | Teensy 8, plus 100 kΩ from this pin to ground |
| 13 | O6 | Node `ENABLE-B` described below |
| 7 | I7 | Node `ENABLE-A`, plus 10 kΩ from this node to signal +5 V |
| 12 | O7 | DM542 `ENA-` |
| 8 | I8 | Node `ENABLE-B`, plus 10 kΩ from this node to signal +5 V |
| 11 | O8 | TB6600 `ENA-` |
| 9 | GND | Teensy GND and buck-converter negative |
| 10 | COMMON | Leave disconnected; the loads are optocouplers, not coils |

Connect the driver positive signal terminals as follows:

```text
signal +5 V ---- DM542 PUL+, DIR+, ENA+
             `-- TB6600 PUL+, DIR+, ENA+
```

The two-stage enable channels are intentional:

```text
Teensy 4 -- I5/O5 --+-- I7/O7 -- DM542 ENA-
                    `-- 10 kΩ -- signal +5 V

Teensy 8 -- I6/O6 --+-- I8/O8 -- TB6600 ENA-
                    `-- 10 kΩ -- signal +5 V
```

When a Teensy enable pin is LOW or floating during reset, the second output
sinks `ENA-`. On the usual DM542/TB6600 enable convention, that activates the
driver's "offline" input and disables motor current. A Teensy HIGH releases
`ENA-` and enables motion. Driver clones are inconsistent, so confirm this
behavior with unloaded mechanics before depending on it. If either driver does
the opposite, leave its `ENA` wires disconnected and correct the documented
hardware/firmware polarity before further testing.

## Switch wiring

For the current normally-open arrangement, connect one side of each switch to
its Teensy pin and the other side to Teensy GND. The firmware enables the
Teensy's internal pull-ups, so an open switch reads inactive and a closed switch
reads active.

Normally-closed endstops are preferable in the finished machine because a
broken wire then becomes a limit fault. That conversion also requires changing
the corresponding `ActiveLow` constants in `controller_config.h`; do not change
only the wire or only the software.

## Power boundaries

- USB may power the Teensy during development.
- The buck converter supplies the driver optocoupler +5 V signal rail.
- Tie buck negative, interface pin 9, and Teensy GND together.
- Do not connect buck +5 V to Teensy `VIN` while USB is attached. Teensy VUSB
  and VIN are connected unless the board's separation pads are cut.
- Motor-supply positive and negative go only to the drivers' motor-power input
  terminals. They do not go to Teensy GPIO or the Teensy 3.3 V pin.
- Keep motor cables physically separate from STEP/DIR/endstop wiring. Use
  twisted pairs for driver signals and switches where practical.

The Stop/Go switch is an operating control, not an emergency stop. A real
emergency-stop circuit must remove hazardous energy or use an appropriately
rated safety circuit independently of the Teensy firmware.

## Component references

- [PJRC Teensy 4.0 electrical and power specifications](https://www.pjrc.com/store/teensy40.html)
- [Toshiba TBD62083APG product page](https://toshiba.semicon-storage.com/us/semiconductor/product/linear-ics/transistor-arrays/detail.TBD62083APG.html)
- [Toshiba TBD62083A-series datasheet](https://toshiba.semicon-storage.com/info/TBD62083APG_datasheet_en_20160511.pdf?did=29893&prodName=TBD62083APG)
- [Leadshine DM542E manual](https://www.leadshine.com/upfiles/downloads/d5375bf4c28b5c75b2d150c9762781c9_1651052967281.pdf); use the label/manual for the exact installed DM542 variant if it differs

## Safe commissioning order

1. Assemble the Teensy, interface, and switches with motor power disconnected.
2. Check resistance between +5 V and ground before applying power.
3. Verify every TBD pin against the table and check for adjacent-pin shorts.
4. Power only USB and confirm the controller reports all four switches open.
5. Exercise and verify each switch in the serial `status` output.
6. Apply signal +5 V with driver motor power still disconnected, then verify
   each TBD output level with a multimeter or logic probe.
7. Connect one powered driver with its motor mechanically unloaded and its
   current setting reduced. Verify ENABLE, direction, and a very short move.
8. Repeat for the second driver.
9. Only after polarity is confirmed, perform slow endstop and Stop/Go tests.
