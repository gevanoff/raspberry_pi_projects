#!/usr/bin/env python3
"""Interactive serial console for the Pico or Teensy dual-stepper controller."""

import argparse
import sys
import time

import serial
from serial.tools import list_ports


SUPPORTED_USB_VENDOR_IDS = {
    0x2E8A: "Raspberry Pi Pico",
    0x16C0: "PJRC Teensy",
}
DEFAULT_BAUD_RATE = 115200


def find_controller_port(explicit_port=None):
    if explicit_port:
        return explicit_port

    candidates = [
        port.device for port in list_ports.comports() if port.vid in SUPPORTED_USB_VENDOR_IDS
    ]
    if not candidates:
        raise RuntimeError("no Raspberry Pi Pico or PJRC Teensy serial port was found")
    if len(candidates) > 1:
        raise RuntimeError(
            "multiple compatible controller ports were found ({ports}); use --port".format(
                ports=", ".join(candidates)
            )
        )
    return candidates[0]


def open_controller(port_name, baud_rate):
    connection = serial.Serial()
    connection.port = port_name
    connection.baudrate = baud_rate
    connection.timeout = 0
    connection.write_timeout = 1
    connection.rtscts = False
    connection.dsrdtr = False
    connection.dtr = False
    connection.rts = False
    connection.open()
    return connection


def read_response(connection, first_byte_timeout=0.5, idle_timeout=0.15):
    chunks = []
    deadline = time.monotonic() + first_byte_timeout
    received_data = False

    while time.monotonic() < deadline:
        waiting = connection.in_waiting
        if waiting:
            chunks.append(connection.read(waiting))
            received_data = True
            deadline = time.monotonic() + idle_timeout
        else:
            time.sleep(0.01)

    if not received_data:
        return ""

    response = b"".join(chunks).decode("utf-8", errors="replace")
    return response.replace("\r\n", "\n").replace("\r", "\n").strip()


def send_command(connection, command):
    connection.write((command.strip() + "\r\n").encode("ascii"))
    connection.flush()
    return read_response(connection)


def response_has_error(response):
    return any(line.startswith("error ") for line in response.splitlines())


def stop_safely(connection):
    try:
        response = send_command(connection, "stop")
        if response:
            print(response)
    except (OSError, serial.SerialException):
        pass


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", help="serial port, such as COM5; defaults to Pico/Teensy auto-detection"
    )
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD_RATE, help="serial baud rate")
    parser.add_argument("--command", help="send one command instead of starting an interactive console")
    parser.add_argument(
        "--no-stop-on-exit",
        action="store_true",
        help="do not send the safety stop command when the console exits",
    )
    return parser.parse_args(argv)


def main(argv=None):
    arguments = parse_arguments(argv)
    connection = None
    exit_code = 0

    try:
        port_name = find_controller_port(arguments.port)
        connection = open_controller(port_name, arguments.baud)
        connection.reset_input_buffer()
        print("Connected to controller on {port} at {baud} baud.".format(port=port_name, baud=arguments.baud))

        if arguments.command is not None:
            response = send_command(connection, arguments.command)
            if response:
                print(response)
                if response_has_error(response):
                    exit_code = 1
            else:
                print("No response from controller.", file=sys.stderr)
                exit_code = 1
            return exit_code

        print("Type 'help' for controller commands or 'exit' to stop safely and quit.")
        initial_status = send_command(connection, "status")
        if initial_status:
            print(initial_status)
        else:
            print("Warning: the controller did not answer the initial status request.", file=sys.stderr)

        while True:
            try:
                command = input("controller> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not command:
                continue
            if command.lower() in ("exit", "quit"):
                break

            response = send_command(connection, command)
            if response:
                print(response)
            else:
                print("No response from controller.")
    except (OSError, RuntimeError, serial.SerialException) as exc:
        print("Controller console error: {message}".format(message=exc), file=sys.stderr)
        exit_code = 1
    finally:
        if connection is not None and connection.is_open:
            if not arguments.no_stop_on_exit:
                print("Sending safety stop before disconnecting.")
                stop_safely(connection)
            connection.close()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
