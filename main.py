import sys
from multiprocessing import Pool
from pathlib import Path

from test_nmap  import discover_one_vrf, VRFS
from xml_parser import parse_xml
from ssh_pusher import connect, push
from bootstrap  import bootstrap


# -- SCAN + PARSE FOR ONE VRF → returns json_path or None --
def scan_and_parse(vrfid):
    vrfid, ip, xml_path = discover_one_vrf(vrfid)
    if xml_path is None:
        return None
    json_path = parse_xml(xml_path)
    return json_path


def main():
    print("\n" + "="*50)
    print("   NETWORK AGENT — STARTING")
    print("="*50 + "\n")

    # ── PHASE 1+2 — scan and parse all VRFs in parallel ────────
    print("[PHASE 1-2] Scanning and parsing all VRFs in parallel...\n")
    with Pool(processes=len(VRFS)) as pool:
        results = pool.map(scan_and_parse, VRFS)

    # filter out VRFs with no device found
    json_paths = [r for r in results if r is not None]

    if not json_paths:
        print("[!] No devices found. Exiting.")
        sys.exit(0)

    print(f"\n[+] Found {len(json_paths)} device(s)")

    # ── PHASE 3 — connect to each device (in main process) ─────
    print("\n[PHASE 3] Connecting to all devices...\n")
    success_list   = []
    bootstrap_list = []

    for json_path in json_paths:
        conn, ip, vendor, vrfid = connect(json_path)
        if conn is not None:
            success_list.append((conn, ip, vendor, vrfid))
        else:
            bootstrap_list.append((json_path, ip, vendor, vrfid))

    print(f"\n[+] SSH success    : {len(success_list)} device(s)")
    print(f"[!] Need bootstrap : {len(bootstrap_list)} device(s)")

    # ── PHASE 4 — sequential bootstrap ─────────────────────────
    if bootstrap_list:
        print("\n[PHASE 4] Bootstrap required...\n")
        for json_path, ip, vendor, vrfid in bootstrap_list:
            success = bootstrap(json_path, ip, vendor, vrfid)
            if not success:
                print(f"[x] Bootstrap failed for {ip} — skipping")
                continue

            print(f"[*] Retrying SSH for {ip}...")
            conn, ip, vendor, vrfid = connect(json_path)
            if conn is not None:
                success_list.append((conn, ip, vendor, vrfid))
                print(f"[+] {ip} — ready")
            else:
                print(f"[x] {ip} — SSH still failed after bootstrap, skipping")

    # ── PHASE 5 — push config to all devices ───────────────────
    if not success_list:
        print("\n[!] No devices to configure. Exiting.")
        sys.exit(0)

    print(f"\n[PHASE 5] Pushing config to {len(success_list)} device(s)...\n")
    for conn, ip, vendor, vrfid in success_list:
        push(conn, ip, vendor, vrfid)

    print("\n" + "="*50)
    print("   ALL DEVICES CONFIGURED")
    print("="*50 + "\n")


if __name__ == "__main__":
    main()
