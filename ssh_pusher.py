import json
import socket
from pathlib import Path
from datetime import datetime
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

# -- PATHS --
CREDS_DIR  = Path("/home/kali/fyp/default_credentials")
CONFIG_DIR = Path("/home/kali/fyp/configs")
OUTPUT_DIR = Path("/home/kali/fyp/push_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# -- VENDOR TO NETMIKO DEVICE TYPE --
VENDOR_MAP = {
    "cisco":    "cisco_ios",
    "huawei":   "huawei",
    "mikrotik": "mikrotik_routeros",
    "aruba":    "aruba_os",
    "fortinet": "fortinet",
    "ubiquiti": "ubiquiti_edge",
    "unknown":  "autodetect",
}

# -- READ JSON FILE --
def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

# -- EXTRACT VRF NUMBER FROM FILENAME --
def get_vrfid(path):
    parts    = Path(path).stem.split("-")
    vrf_part = next(p for p in parts if p.startswith("vrf"))
    return int(vrf_part[3:])

# -- CREATE A SOCKET BOUND TO A SPECIFIC INTERFACE (VRF TRICK) --
def make_vrf_socket(interface, ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode())
    sock.settimeout(10)
    sock.connect((ip, 22))
    return sock

# -- OPEN SSH SESSION AND RETURN IT (does NOT push config yet) --
def connect(json_path):
    json_path = Path(json_path)
    data      = load_json(json_path)

    ip, device  = next(iter(data.items()))
    vendor_raw  = (device.get("vendor") or "unknown").lower()
    vendor      = next((k for k in VENDOR_MAP if k in vendor_raw), "unknown")
    device_type = VENDOR_MAP[vendor]
    vrfid       = get_vrfid(json_path)
    iface       = f"eth0.{vrfid}"

    ssh_info = device.get("ports", {}).get("tcp/22", {})
    if ssh_info.get("state") != "open":
        print(f"[!] {ip} — SSH not open")
        return None, ip, vendor, vrfid

    print(f"[*] {ip} — trying SSH (VRF {vrfid} → {iface})")

    credentials = load_json(CREDS_DIR / f"{vendor}.json")

    for i, cred in enumerate(credentials, 1):
        print(f"[*] {ip} — attempt {i}: user='{cred['user']}'")
        try:
            sock = make_vrf_socket(iface, ip)
            conn = ConnectHandler(
                device_type=device_type,
                ip=ip,
                username=cred["user"],
                password=cred["pass"],
                sock=sock,
                timeout=10,
                session_timeout=60,
                fast_cli=False,
            )
            print(f"[+] {ip} — connected as '{cred['user']}'")
            return conn, ip, vendor, vrfid
        except NetmikoAuthenticationException:
            print(f"[-] {ip} — wrong credentials")
            continue
        except NetmikoTimeoutException:
            print(f"[!] {ip} — timed out")
            continue
        except Exception as e:
            print(f"[!] {ip} — error: {e}")
            continue

    print(f"[x] {ip} — all credentials failed")
    return None, ip, vendor, vrfid

# -- PUSH CONFIG TO AN ALREADY OPEN CONNECTION --
def push(conn, ip, vendor, vrfid):
    config_file = CONFIG_DIR / f"{vendor}.txt"

    if not config_file.exists():
        print(f"[!] {ip} — config file not found: {config_file}")
        conn.disconnect()
        return

    print(f"[*] {ip} — pushing config from {config_file.name}")

    try:
        output = conn.send_config_from_file(str(config_file))
        print(f"[+] {ip} — config pushed successfully")
    except Exception as e:
        print(f"[!] {ip} — push failed: {e}")
        output = str(e)
    finally:
        conn.disconnect()
        print(f"[*] {ip} — session closed")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_file  = OUTPUT_DIR / f"{timestamp}-vrf{vrfid}-{ip}.txt"
    with open(out_file, "w") as f:
        f.write(f"IP     : {ip}\n")
        f.write(f"VRF    : {vrfid}\n")
        f.write(f"Vendor : {vendor}\n\n")
        f.write(output)
    print(f"[*] {ip} — output saved → {out_file.name}")
