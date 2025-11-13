#!/usr/bin/env python3
"""
collector.py
Fetches the YANG and /switch JSON from the simulator, validates basic constraints,
and prints the data in a readable summary.
"""

import requests
import re
import sys

SIM_URL = "http://localhost:5000"   # change if simulator runs elsewhere

# Basic validators corresponding to your YANG constraints
name_re = re.compile(r".*Ethernet0/\d+$")
def valid_name(n): return bool(name_re.match(n))

def valid_description(s): return 4 <= len(s) <= 50

def valid_mode(m): return m in ("access", "trunk")

def valid_vlan(v): 
    try:
        v = int(v)
        return 1 <= v <= 4094
    except Exception:
        return False

def validate_interface(iface):
    errors = []
    name = iface.get("name")
    if not name or not valid_name(name):
        errors.append(f"invalid name: {name}")
    desc = iface.get("description", "")
    if not valid_description(desc):
        errors.append(f"description length invalid ({len(desc)}): '{desc}'")
    mode = iface.get("mode")
    if not valid_mode(mode):
        errors.append(f"invalid mode: {mode}")

    # speed is read-only/operational (uint32) — ensure it's an integer >=0
    speed = iface.get("speed")
    if speed is None:
        errors.append("missing speed")
    else:
        try:
            if int(speed) < 0:
                errors.append(f"invalid speed: {speed}")
        except:
            errors.append(f"speed not integer: {speed}")

    # access vs trunk specifics
    if mode == "access":
        if "access-vlan" not in iface:
            errors.append("missing access-vlan for access mode")
        elif not valid_vlan(iface["access-vlan"]):
            errors.append(f"invalid access-vlan: {iface.get('access-vlan')}")
    elif mode == "trunk":
        tv = iface.get("trunked-vlan")
        if tv is None:
            errors.append("missing trunked-vlan for trunk mode")
        else:
            if not isinstance(tv, list) or not all(valid_vlan(v) for v in tv):
                errors.append(f"invalid trunked-vlan list: {tv}")

    return errors

def main():
    # 1) Optionally fetch YANG
    try:
        r = requests.get(f"{SIM_URL}/yang", timeout=5)
        if r.status_code == 200:
            print("Fetched YANG (first 200 chars):")
            print(r.text[:200].strip().replace("\n", " ") + "...\n")
        else:
            print("Could not fetch YANG: status", r.status_code)
    except Exception as e:
        print("Failed to fetch YANG:", e)

    # 2) Fetch /switch JSON
    try:
        r = requests.get(f"{SIM_URL}/switch", timeout=5)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print("Failed to fetch /switch:", e)
        sys.exit(1)

    # 3) Simple validation and printing
    sw = data.get("switch", {})
    hostname = sw.get("hostname", "(no hostname)")
    ifaces = sw.get("interface", [])
    print(f"Switch hostname: {hostname}")
    print(f"Found {len(ifaces)} interfaces\n")

    all_errors = False
    for idx, itf in enumerate(ifaces, 1):
        print(f"Interface #{idx}")
        print("  name       :", itf.get("name"))
        print("  description:", itf.get("description"))
        print("  speed (Mb) :", itf.get("speed"))
        print("  mode       :", itf.get("mode"))
        if itf.get("mode") == "access":
            print("  access-vlan:", itf.get("access-vlan"))
        else:
            print("  trunked-vlan:", itf.get("trunked-vlan"))

        errs = validate_interface(itf)
        if errs:
            all_errors = True
            print("  VALIDATION ERRORS:")
            for e in errs:
                print("   -", e)
        else:
            print("  VALIDATION: OK")
        print()

    if all_errors:
        print("One or more interfaces failed validation.")
    else:
        print("All interfaces validated OK.")

if __name__ == "__main__":
    main()
