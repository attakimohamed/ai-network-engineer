import xml.etree.ElementTree as ET
import json
from pathlib import Path

# -- PATHS --
JSON_DIR = Path("/home/kali/fyp/json")
JSON_DIR.mkdir(parents=True, exist_ok=True)

# -- PARSE ONE XML FILE → SAVE JSON → RETURN JSON PATH --
def parse_xml(xml_path):
    xml_path = Path(xml_path)
    tree     = ET.parse(xml_path)
    root     = tree.getroot()
    devices  = {}

    for host in root.findall("host"):
        i      = 0
        ip     = None
        mac    = None
        vendor = None

        for address in host.findall("address"):
            t = address.get("addrtype")
            if t == "ipv4":
                ip = address.get("addr")
            elif t == "mac":
                vendor = address.get("vendor")
                mac    = address.get("addr")

        if not ip:
            continue

        devices[ip] = {"ip": ip, "mac": mac, "vendor": vendor, "os": [], "ports": {}}

        for aport in host.findall("ports"):
            for nport in aport.findall("port"):
                protocol   = nport.get("protocol")
                portid     = nport.get("portid")
                cpes       = []
                name       = None
                product    = None
                extrainfo  = None
                method     = None
                conf       = None
                state      = None
                reason     = None
                reason_ttl = None

                for service in nport.findall("service"):
                    for cpe_el in service.findall("cpe"):
                        if cpe_el.text:
                            cpes.append(cpe_el.text.strip())
                    name      = service.get("name")
                    product   = service.get("product")
                    extrainfo = service.get("extrainfo")
                    method    = service.get("method")
                    conf      = service.get("conf")

                for staten in nport.findall("state"):
                    state      = staten.get("state")
                    reason     = staten.get("reason")
                    reason_ttl = staten.get("reason_ttl")

                if state != "open":
                    continue

                devices[ip]["ports"][f"{protocol}/{portid}"] = {
                    "port": portid, "protocol": protocol,
                    "state": state, "reason": reason,
                    "reason_ttl": reason_ttl, "cpe": cpes,
                    "name": name, "product": product,
                    "extrainfo": extrainfo, "method": method, "conf": conf,
                }

        for os_el in host.findall("os"):
            for osmatch in os_el.findall("osmatch"):
                os_name  = osmatch.get("name")
                accuracy = osmatch.get("accuracy")
                if devices[ip]["vendor"] is None:
                    for osclass in osmatch.findall("osclass"):
                        i += 1
                        if i == 1:
                            devices[ip]["vendor"] = osclass.get("vendor")
                devices[ip]["os"].append({"os": os_name, "accuracy": accuracy})

    json_path = JSON_DIR / f"{xml_path.stem}.json"
    with open(json_path, "w") as f:
        json.dump(devices, f, indent=4)

    print(f"[+] Parsed → {json_path.name}")
    return json_path
