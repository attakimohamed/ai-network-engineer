# AI Network Engineer — FYP

> Automated network provisioning, discovery, and AI-assisted configuration management for multi-vendor environments.

**Status:** Core pipeline operational · AI agent layer in progress  
**Stack:** Python · Nmap · Netmiko · FastAPI · Groq API  
**Author:** Mohamed Attaki — BTS Systèmes & Réseaux Informatiques, Lycée Al Idrissi, Agadir

---

## What It Does

Most network provisioning workflows require an engineer to manually SSH into every new device, run vendor-specific commands, and document the result. This project automates that entire pipeline:

1. **Discovers** all devices connected to a managed switch — across multiple VRFs and subnets — using parallel Nmap scanning
2. **Fingerprints** each device (OS, vendor, MAC, open ports, CPE strings)
3. **Connects** via SSH using vendor-specific default credential lists
4. **Bootstraps** devices that have no SSH access via serial console fallback
5. **Pushes** a first configuration tailored to the detected vendor
6. **[In progress]** Accepts natural-language requests from an operator and translates them into device commands via an AI agent

---

## Physical Setup

```
Switch (10 ports)
├── Ports 1–8   →  VLANs 101–108  (production devices, one per port)
├── Port 9      →  VLAN 888       (provisioning — DHCP for factory-reset devices)
└── Port 10     →  VLAN 999       (management — laptop uplink)

Laptop (eth0)
├── eth0.101 … eth0.108   →  sub-interfaces, one per production VLAN
│   └── Each carries 3 subnets: 192.168.1.0/24 · 192.168.88.0/24 · 10.0.0.0/24
├── eth0.888              →  provisioning sub-interface
└── eth0.999              →  management sub-interface

Linux VRFs: vrf101 … vrf108
└── One VRF per sub-interface — isolates MAC tables, prevents ARP leakage between ports
```

The multi-subnet design on each VRF is intentional: factory-reset devices default to different ranges depending on vendor (Cisco → 192.168.x, MikroTik → 192.168.88.x, Huawei → 10.x). Covering all three means the scanner finds the device regardless of its default IP scheme.

---

## Pipeline Overview

```
[Switch ports] → [Nmap parallel scan] → [XML output]
                                              ↓
                                      [XML → JSON parser]
                                              ↓
                                   [SSH connect + cred bruteforce]
                                        ↙            ↘
                               [Config push]    [Console bootstrap]
                                                  (serial fallback)
                                        ↓
                               [AI agent layer]  ← in progress
                                        ↓
                               [FastAPI + Dashboard]  ← in progress
```

---

## Project Structure

```
fyp/
├── main.py               # Entry point — orchestrates all 5 phases
├── test_nmap.py          # Stage 1 — parallel VRF-aware discovery
├── xml_parser.py         # Stage 2 — nmap XML → structured JSON
├── ssh_pusher.py         # Stage 3 — SSH connect + config push
├── bootstrap.py          # Stage 3b — serial console fallback
│
├── scans/                # Nmap XML output (auto-created)
├── json/                 # Parsed device profiles (auto-created)
├── push_outputs/         # SSH push logs (auto-created)
│
├── bootstrap/            # Vendor bootstrap command files
│   ├── cisco.txt
│   ├── fortinet.txt
│   ├── huawei.txt
│   ├── mikrotik.txt
│   ├── ubiquiti.txt
│   └── unknown.txt
│
├── default_credentiels/  # Vendor default credential lists (JSON)
│   └── {vendor}.json
│
└── configs/              # Config files (AI-generated at runtime)
    └── Testing_configs/  # Manual test commands for pipeline validation
```

---

## Usage

```bash
sudo python3 main.py
```

`main.py` is the full pipeline entry point. It runs all 5 phases sequentially:
- Phase 1+2 — parallel VRF scan + XML parse (multiprocessing)
- Phase 3 — SSH connect to all discovered devices
- Phase 4 — serial console bootstrap for any that failed SSH, then retry SSH
- Phase 5 — push config to all connected devices

Requires `sudo` for nmap raw socket access and `ip vrf exec`.

---

## Modules

### `test_nmap.py` — Discovery

Scans all 8 VRFs in parallel using Python `multiprocessing.Pool`.

For each VRF:
- Runs a fast ARP ping scan (`nmap -sn -PR`) across all 3 subnets
- On first live host found, runs a deep scan: SYN (`-sS`), service version (`-sV`), OS detection (`-O --osscan-guess`)
- Targeted ports: `22, 80, 113, 443, 541, 8013`
- Output: one XML file per device, named `{timestamp}-vrf{id}-{ip}.xml`

All scans run inside their VRF namespace via `ip vrf exec vrf{id}` to ensure traffic exits the correct sub-interface.

### `xml_parser.py` — Fingerprinting

Parses nmap XML into structured JSON per device:

```json
{
  "192.168.1.1": {
    "ip": "192.168.1.1",
    "mac": "AA:BB:CC:DD:EE:FF",
    "vendor": "Cisco Systems",
    "os": [{"os": "Cisco IOS 15.x", "accuracy": "94"}],
    "ports": {
      "tcp/22": {
        "state": "open",
        "name": "ssh",
        "product": "Cisco SSH",
        "cpe": ["cpe:/o:cisco:ios:15"]
      }
    }
  }
}
```

Only open ports are included. Vendor is resolved from MAC OUI first, then OS class if MAC vendor is null.

### `ssh_pusher.py` — Connection & Push

For each JSON device profile:
- Checks SSH port is open
- Resolves vendor → Netmiko device type via `VENDOR_MAP`
- Creates a socket **bound to the VRF sub-interface** (`SO_BINDTODEVICE`) before passing it to Netmiko — this is the key trick that forces traffic through the correct VLAN
- Iterates vendor credential list until one succeeds
- `connect()` — returns a live Netmiko session
- `push()` — sends a config file via `send_config_from_file()`, saves timestamped output log

Config files in `configs/` are generated at runtime by the AI agent based on operator instructions. `configs/Testing_configs/` contains manual test commands used to validate the pipeline independently of the AI layer.

Supported vendors: Cisco IOS · Huawei · MikroTik RouterOS · Aruba OS · Fortinet · Ubiquiti EdgeOS

### `bootstrap.py` — Console Fallback

Called when SSH authentication fails on all credentials:
- Identifies which switch port the device is on from the VRF ID (`port = vrfid - 100`)
- Prompts the operator to physically move that device to a USB console cable
- Sends vendor bootstrap commands via `pyserial` at 9600 baud
- Bootstrap sets `admin/admin` and enables SSH
- After bootstrap, the device re-enters the SSH pipeline

---

## Supported Vendors

| Vendor    | Netmiko Type          | Bootstrap | Default Creds |
|-----------|-----------------------|-----------|---------------|
| Cisco     | `cisco_ios`           | ✅        | ✅            |
| Fortinet  | `fortinet`            | ✅        | ✅            |
| Huawei    | `huawei`              | ✅        | ✅            |
| MikroTik  | `mikrotik_routeros`   | ✅        | ✅            |
| Ubiquiti  | `ubiquiti_edge`       | ✅        | ✅            |
| Unknown   | `autodetect`          | ✅ (generic) | —          |

---

## Requirements

```
python >= 3.10
netmiko
pyserial
nmap (system)
```

> Nmap scans require `sudo`. The process runs as root or with appropriate capabilities in the lab environment.

---

## Roadmap

- [x] VRF-aware parallel Nmap discovery
- [x] XML → JSON fingerprint parser
- [x] Multi-vendor SSH connect with credential cycling
- [x] VRF socket binding (SO_BINDTODEVICE)
- [x] Serial console bootstrap fallback
- [x] Vendor-specific first-push config templates
- [ ] AI agent layer (Groq API — natural language → device commands)
- [ ] Session manager (persistent multi-device session pool)
- [ ] FastAPI backend
- [ ] Topology documentation generator (Markdown / PDF export)
- [ ] Web dashboard

---

## Context

This project is the final-year project (Stage PFE) for a BTS Systèmes et Réseaux Informatiques program. It was designed and built from scratch to solve a real provisioning problem: bringing up factory-reset network devices of unknown vendor automatically, with zero manual SSH setup.

