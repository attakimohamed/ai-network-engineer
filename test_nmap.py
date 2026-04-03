import subprocess
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

# -- CONFIG --
VRFS       = [101, 102, 103, 104, 105, 106, 107, 108]
SUBNETS    = ["192.168.1.0/24", "192.168.88.0/24", "10.0.0.0/24"]
SCANS_DIR  = Path("/home/kali/fyp/scans")
SCANS_DIR.mkdir(parents=True, exist_ok=True)

# -- SCAN ONE VRF → SAVE XML → RETURN (vrfid, ip, xml_path) --
def discover_one_vrf(vrfid):
    date = datetime.now().strftime("%Y%m%d-%H%M%S")

    for subnet in SUBNETS:
        # quick ARP scan to find if anyone is alive
        p = subprocess.run(
            [
                "sudo", "ip", "vrf", "exec", f"vrf{vrfid}",
                "nmap", "-sn", "-PR", "-e", f"eth0.{vrfid}",
                "-n", "--max-retries", "0", "--host-timeout", "2s",
                subnet, "-oG", "-"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True
        )

        for line in p.stdout.splitlines():
            if line.startswith("Host: ") and "Status: Up" in line:
                ip       = line.split()[1]
                xml_path = SCANS_DIR / f"{date}-vrf{vrfid}-{ip}.xml"

                # deep scan on the found host
                subprocess.run(
                    [
                        "sudo", "ip", "vrf", "exec", f"vrf{vrfid}",
                        "nmap", "-4", "-e", f"eth0.{vrfid}",
                        "-sS", "-sV", "-O", "--osscan-guess", "-Pn",
                        "-p", "22,80,113,443,541,8013",
                        "-oX", str(xml_path), ip
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

                print(f"[+] VRF {vrfid} → {ip} — scan saved")
                return vrfid, ip, xml_path

    print(f"[-] VRF {vrfid} → no device found")
    return vrfid, None, None


# -- SCAN ALL VRFS IN PARALLEL → RETURN LIST OF XML PATHS --
def scan_all():
    with Pool(processes=len(VRFS)) as pool:
        results = pool.map(discover_one_vrf, VRFS)

    xml_paths = [xml_path for _, _, xml_path in results if xml_path is not None]
    return xml_paths


# -- RUN STANDALONE --
if __name__ == "__main__":
    xml_paths = scan_all()
    print(f"\n[+] Total devices found: {len(xml_paths)}")
    for p in xml_paths:
        print(f"    {p.name}")
