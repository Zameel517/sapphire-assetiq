"""
organization_collector.py
==========================
Collects: Company, Location, Asset Tag (from the computer-naming convention).

Neither of these is a property Windows can report directly -- no API on
a laptop knows it is sitting in "Branch 3". Per the project chat we
never guess them from the laptop manufacturer and never silently invent
a value. But "not directly reportable" is NOT the same as "hardcode one
value into every machine": both fields are resolved AT RUNTIME from
signals the machine detects about itself.

Company precedence (first match wins):
  1. --company command-line override
  2. config.json "company"            (fleet constant, e.g. "ACME")
  3. Derived from the joined AD domain (COMPANY.local / COMPANY.store -> COMPANY)
  4. Unknown (flagged for review)

Location precedence (first match wins):
  1. --location command-line override
  2. config.json "vlan_location_map" looked up by the VLAN of the IP
     address THIS machine detected for itself ("10.20.30." -> Head Office)
  3. config.json "location"            (single-site deployments only)
  4. Unknown (flagged for review)

Step 2 is the one that matters for AD-wide deployment: one config.json
carrying the site register is built into the EXE, every machine reads its
own IP and looks ITSELF up. Same file on every endpoint, a different --
and correct -- answer on each. Only VLANs the company has confirmed belong in that
map; an unlisted VLAN reports "Unknown" for someone to fill in, never a
guessed neighbouring site.

This keeps the door open for a future central inventory API / AD site
lookup without changing any other collector.
"""

import ipaddress
import os
import re

from models.system_info import SystemInfoRecord

# Domain suffixes stripped when deriving Company from the AD domain.
_DOMAIN_SUFFIXES = (".local", ".store", ".com", ".net", ".org", ".lan", ".corp")


def collect(record: SystemInfoRecord, config: dict, cli_overrides: dict | None = None):
    cli_overrides = cli_overrides or {}
    _collect_company(record, config, cli_overrides)
    _collect_location(record, config, cli_overrides)
    _collect_asset_tag(record, config)


# --------------------------------------------------------------------------
# Asset Tag
# --------------------------------------------------------------------------

def _collect_asset_tag(record: SystemInfoRecord, config: dict):
    """The fleet names every computer after its asset code -- PC-00123, LT-0456, ...
    -- so when the firmware carries no real tag, the computer name IS the asset
    tag. Nothing here assumes a shape for those codes: whatever the machine calls
    itself is taken as it is, because the codes are not all one pattern."""
    firmware = record.fields["asset_tag"]
    if firmware.status == "ok" and str(firmware.value or "").strip():
        return                                  # a real tag from the firmware wins
    name = str(record.get("computer_name") or "").strip()
    if not name:
        return
    record.set("asset_tag", name.upper(), source="derived:computer_name",
               raw=firmware.raw,
               note="Taken from the computer name: the fleet names every machine after its "
                    "asset code, and this machine's firmware tag is a placeholder.")

# --------------------------------------------------------------------------
# Company
# --------------------------------------------------------------------------

def _collect_company(record: SystemInfoRecord, config: dict, cli_overrides: dict):
    cli_value = cli_overrides.get("company")
    if cli_value:
        record.set("company", cli_value, source="cli-argument")
        return

    config_value = config.get("company")
    if config_value:
        record.set("company", config_value, source="config.json")
        return

    derived = _company_from_domain(record)
    if derived:
        record.set("company", derived, source="derived:domain_name",
                   raw=record.get("domain_name"),
                   note="Derived from the joined AD domain, not configured.")
        return

    env_value = os.environ.get("SAPPHIRE_COMPANY")
    if env_value:
        record.set("company", env_value, source="environment-variable", status="review")
        return

    record.set("company", "Unknown", source="none", status="review",
               note="No CLI override, config.json company, or AD domain to derive "
                    "from. Fill in before importing into the asset portal.")


def _company_from_domain(record: SystemInfoRecord) -> str | None:
    """COMPANY.local / COMPANY.store -> COMPANY. Returns None for workgroup machines."""
    domain = record.get("domain_name")
    if not domain or not isinstance(domain, str):
        return None
    domain = domain.strip()
    if not domain or domain.lower() == "workgroup":
        return None
    lowered = domain.lower()
    for suffix in _DOMAIN_SUFFIXES:
        if lowered.endswith(suffix):
            return domain[: -len(suffix)]
    # Unqualified NetBIOS-style domain (e.g. "CORP") -- use as-is.
    return domain.split(".")[0]


# --------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------

def _collect_location(record: SystemInfoRecord, config: dict, cli_overrides: dict):
    cli_value = cli_overrides.get("location")
    if cli_value:
        record.set("location", cli_value, source="cli-argument")
        return

    site_map = {str(k).strip(): v for k, v in (
        config.get("vlan_location_map") or config.get("subnet_location_map") or {}).items()}
    ip = record.get("ip_address")        # the VLAN this machine sits on
    mask = record.get("subnet")          # real dotted-decimal mask
    network = _network_of(ip, mask)

    if site_map and (ip or network is not None):
        label = str(network) if network is not None else ip
        matched = _lookup_location(network, ip, site_map)
        if matched:
            record.set("location", matched,
                       source="derived:vlan_location_map", raw=label)
            return
        # Detected a network nobody has registered as a site yet. Never guess
        # a neighbouring site -- flag it so IT extends the map.
        record.set("location", "Unknown", source="vlan_location_map",
                   status="review", raw=label,
                   note=f"VLAN '{label}' is not listed in config.json "
                        f"vlan_location_map. Add it so this site resolves "
                        f"automatically on every machine there.")
        return

    config_value = config.get("location")
    if config_value:
        record.set("location", config_value, source="config.json",
                   note="Fixed location from config.json (single-site deployment). "
                        "Prefer vlan_location_map for fleet-wide rollout.")
        return

    env_value = os.environ.get("SAPPHIRE_LOCATION")
    if env_value:
        record.set("location", env_value, source="environment-variable", status="review")
        return

    record.set("location", "Unknown", source="none", status="review",
               note="No network detected and no vlan_location_map configured. "
                    "Fill in before importing into the asset portal.")


def _network_of(ip, mask):
    """IP + mask -> the network this machine sits on. 192.168.1.141 /
    255.255.255.0 -> 192.168.1.0/24. Handles any mask width, so a /22 site
    resolves as correctly as a /24."""
    if not ip or not mask:
        return None
    try:
        return ipaddress.ip_network(f"{ip}/{mask}", strict=False)
    except Exception:
        return None


def _lookup_location(network, ip, site_map: dict):
    """
    Match against the site register, accepting every sane way a VLAN could
    be written in config.json:
        "10.20.30."        VLAN prefix, how most sites write them (preferred)
        "10.20.30"         same, no trailing dot
        "10.20.30.0/24"    CIDR, when a site needs an exact mask width
        "10.20.30.0"       network address
    """
    candidates = []
    if network is not None:
        addr = str(network.network_address)
        candidates += [str(network), addr]
        octets = addr.split(".")
        if len(octets) == 4:
            candidates += [".".join(octets[:3]) + ".", ".".join(octets[:3])]
    if ip:
        octets = str(ip).split(".")
        if len(octets) == 4:
            candidates += [".".join(octets[:3]) + ".", ".".join(octets[:3])]

    for key in candidates:
        if key in site_map:
            return site_map[key]

    # Last resort: a map key written as CIDR that simply CONTAINS this IP.
    if ip:
        try:
            addr_obj = ipaddress.ip_address(str(ip))
        except Exception:
            return None
        for key, value in site_map.items():
            if "/" not in key:
                continue
            try:
                if addr_obj in ipaddress.ip_network(key, strict=False):
                    return value
            except Exception:
                continue
    return None
