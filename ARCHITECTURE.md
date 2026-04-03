# Architecture — AI Network Engineer

## Problem Statement

When a factory-reset network device is plugged into a switch, it has no IP configuration, no SSH access, and its vendor may be unknown. Standard provisioning requires a human engineer to identify the device, find its console port, cable into it, and push an initial config manually — one device at a time.

This project automates that process entirely, from initial detection through first-push configuration, for a multi-vendor environment where the device vendor is determined at runtime.

---

## Network Architecture

### Physical Layer

```
┌──────────────────────────────────────────────┐
│               Managed Switch                 │
│                                              │
│  Port 1  ──  VLAN 101  ──  Device A          │
│  Port 2  ──  VLAN 102  ──  Device B          │
│  ...                                         │
│  Port 8  ──  VLAN 108  ──  Device H          │
│  Port 9  ──  VLAN 888  ──  [Provisioning]    │
│  Port 10 ──  VLAN 999  ──  Laptop            │
└──────────────────────────────────────────────┘
```

One device per port. Strict physical isolation at Layer 2.

**Port 9 (VLAN 888 — Provisioning):**  
A DHCP server runs on this VLAN. Factory-reset devices with no IP configuration are plugged here first. They acquire a DHCP address and become reachable before being moved to a production port.

### Laptop Sub-interface Design

The laptop's `eth0` is configured with one 802.1Q sub-interface per VLAN:

```
eth0
├── eth0.101  →  vrf101  →  192.168.1.0/24, 192.168.88.0/24, 10.0.0.0/24
├── eth0.102  →  vrf102  →  (same three subnets)
│   ...
├── eth0.108  →  vrf108  →  (same three subnets)
├── eth0.888  →  vrf888  →  provisioning subnet
└── eth0.999  →  vrf999  →  management
```

**Why three subnets per VRF?**  
Factory-reset devices default to different IP ranges per vendor:
- Cisco IOS → typically 192.168.1.x
- MikroTik → typically 192.168.88.x  
- Huawei / generic → often 10.x.x.x

By announcing all three subnets on every sub-interface, the scanner captures any device regardless of its factory default scheme.

### VRF Isolation

Each sub-interface is bound to a Linux VRF (`vrf101` … `vrf108`).

**Why VRFs?**  
Without VRF isolation, all sub-interfaces share the same kernel routing table and MAC address table. If two devices on different ports happen to use the same factory-default IP (e.g., both are 192.168.1.1), ARP responses collide and the wrong device gets reached.

VRFs give each port its own routing table and ARP cache. Traffic to `192.168.1.1` in `vrf101` is entirely separate from `192.168.1.1` in `vrf102`.

---

## Software Architecture

### Stage 1 — Discovery (`test_nmap.py`)

```
multiprocessing.Pool(8 workers)
    └── discover_one_vrf(vrfid) × 8 (parallel)
            ├── ip vrf exec vrf{id} nmap -sn -PR {subnet}   ← ARP ping
            │       └── for each "Status: Up" line
            └── ip vrf exec vrf{id} nmap -sS -sV -O {ip}    ← deep scan
                    └── save → scans/{timestamp}-vrf{id}-{ip}.xml
```

All nmap processes run inside the VRF namespace via `ip vrf exec`. This forces nmap to use the correct sub-interface and routes responses back through the right VLAN.

The two-phase scan (ARP ping first, deep scan only on live hosts) is a performance optimization — deep scans are expensive and the majority of ports may be empty.

### Stage 2 — Fingerprinting (`xml_parser.py`)

```
scans/{timestamp}-vrf{id}-{ip}.xml
    └── ET.parse()
            ├── extract: ip, mac, vendor (from MAC OUI)
            ├── extract: os matches + accuracy scores
            │       └── if vendor null → fallback to osclass.vendor
            └── extract: open ports only
                    └── per port: state, service name, product, CPE strings
    └── save → json/{timestamp}-vrf{id}-{ip}.json
```

Vendor resolution priority:
1. MAC OUI lookup (most reliable — from nmap's built-in database)
2. OS class vendor from nmap OS detection (fallback when MAC vendor is null, e.g., VM or spoofed MAC)

Only open ports are written to JSON. Filtered/closed ports are discarded.

### Stage 3 — SSH Connection (`ssh_pusher.py`)

The critical design decision here is the **VRF socket binding**:

```python
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode())
sock.connect((ip, 22))
```

`SO_BINDTODEVICE` forces the TCP socket to exit through a specific network interface (`eth0.101`, `eth0.102`, etc.) regardless of the kernel's routing table. Without this, SSH connections to devices with identical factory IPs would be ambiguous — the kernel would route to whichever appeared first in the routing table.

This socket is passed directly to Netmiko's `ConnectHandler`, which accepts a pre-connected socket via the `sock=` parameter.

**Credential cycling:**
```
for each credential in {vendor}.json:
    try connect → if success: return live session
    except AuthenticationException: try next
    except TimeoutException: abort (device unreachable)
all failed → trigger bootstrap()
```

### Stage 3b — Bootstrap Fallback (`bootstrap.py`)

When all SSH credentials fail, the device likely has a non-default password or SSH disabled entirely. The bootstrap path:

```
bootstrap(ip, vendor, vrfid)
    ├── port_number = vrfid - 100   (VRF 101 → port 1, etc.)
    ├── prompt operator: "Unplug port {N}, connect console cable"
    ├── open /dev/ttyUSB0 at 9600 baud
    ├── load bootstrap/{vendor}.txt
    └── send each command with 1s inter-command delay
            └── device now has admin/admin + SSH enabled
```

After bootstrap, the device is plugged back into its switch port and re-enters the SSH pipeline.

**Inter-command delay:** 1 second between commands is conservative but necessary — some devices (especially Cisco IOS during `crypto key generate`) take several seconds to complete a command. A tighter delay causes commands to be sent before the device is ready.

---

## Data Flow

```
Physical device plugged into switch port N
    ↓
nmap ARP scan finds IP on eth0.{vrfid}
    ↓
nmap deep scan → {timestamp}-vrf{N+100}-{ip}.xml
    ↓
xml_parser → {timestamp}-vrf{N+100}-{ip}.json
    {
      "ip": ..., "mac": ..., "vendor": ...,
      "os": [...], "ports": {"tcp/22": {...}}
    }
    ↓
ssh_pusher.connect()
    → check ports["tcp/22"].state == "open"
    → resolve vendor → netmiko device_type
    → SO_BINDTODEVICE socket on eth0.{vrfid}
    → cycle credentials from default_credentiels/{vendor}.json
    ↓
  [success]                    [failure]
ssh session open           bootstrap() via serial
    ↓                              ↓
ssh_pusher.push()          device gets admin/admin
configs/{vendor}.txt       → re-enter SSH pipeline
    ↓
push_outputs/{timestamp}-vrf{N}-{ip}.txt (log)
    ↓
[AI agent — in progress]
```

---

## Planned: AI Agent Layer

The AI agent will sit between the operator and the device sessions:

```
Operator (natural language)
    ↓
Groq API (LLM)
    ├── parse intent
    ├── query available device sessions
    ├── generate vendor-appropriate commands
    └── push via existing Netmiko sessions
    ↓
FastAPI backend → Dashboard
```

The session pool from `ssh_pusher.connect()` will be kept alive rather than disconnected after push, giving the AI agent persistent access to all devices simultaneously.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Multiprocessing over threading for nmap | nmap is a subprocess — GIL doesn't help. True parallelism via `Pool` cuts scan time by ~8× |
| `SO_BINDTODEVICE` socket trick | Only reliable way to force Netmiko traffic through a specific VRF sub-interface |
| Two-phase nmap (ARP → deep) | ARP ping is near-instant. Deep scans on empty ports waste 30–60s each |
| 3 subnets per VRF | Covers factory defaults of all major vendors without manual per-vendor config |
| VRFs over policy routing | VRFs give full MAC/ARP isolation per port, not just routing isolation |
| Serial at 9600 baud | Universal default across all major vendors — safe for any console port |
| 1s inter-command delay | Conservative but safe for slow operations like RSA key generation |
