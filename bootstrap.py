import json
import time
from pathlib import Path
import serial

# -- PATHS --
BOOTSTRAP_DIR = Path("/home/kali/fyp/bootstrap")
SERIAL_PORT   = "/dev/ttyUSB0"
BAUD_RATE     = 9600

# -- LOAD VENDOR BOOTSTRAP COMMANDS --
def load_commands(path):
    with open(path, "r") as f:
        return [line.rstrip("\n") for line in f.readlines()]

# -- SEND COMMANDS THROUGH CONSOLE CABLE --
def send_via_console(commands):
    ser = serial.Serial(port=SERIAL_PORT, baudrate=BAUD_RATE, timeout=2)
    time.sleep(1)
    ser.write(b"\r\n")
    time.sleep(1)

    for cmd in commands:
        if cmd.strip() == "" or cmd.startswith("#"):
            continue
        print(f"[>] {cmd}")
        ser.write((cmd + "\r\n").encode())
        time.sleep(1)
        output = ser.read(ser.in_waiting or 1)
        if output:
            print(output.decode(errors="ignore"), end="")

    ser.close()
    print("\n[*] Console session closed.")

# -- MAIN BOOTSTRAP FUNCTION --
def bootstrap(json_path, ip, vendor, vrfid):
    port_number    = vrfid - 100
    bootstrap_file = BOOTSTRAP_DIR / f"{vendor}.txt"

    if not bootstrap_file.exists():
        print(f"[!] No bootstrap file for vendor: {vendor}")
        return False

    print(f"\n[!] Bootstrap required for {ip}")
    print(f"[*] Vendor  : {vendor}")
    print(f"[*] Switch port : {port_number}")
    print(f"\n>>> Unplug the device from switch port {port_number}")
    print(f">>> Connect its console port to your laptop USB adapter")
    print(f">>> Then press ENTER")
    input()

    print(f"[*] Connecting to console {SERIAL_PORT}...")
    commands = load_commands(bootstrap_file)
    send_via_console(commands)

    print(f"[+] Bootstrap done for {ip}")
    time.sleep(2)
    return True
