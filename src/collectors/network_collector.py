"""
network_collector.py
=====================
Collects: IP Address, MAC Address, Subnet.

Picks the "active physical" adapter -- i.e. the one that is actually
IP-enabled and not a virtual/loopback/Bluetooth/VPN adapter -- rather
than blindly returning the first NIC found. Ties the MAC to the SAME
adapter as the reported IP, per the project chat's explicit warning.

Note on "Subnet": the real sample data stores a truncated network
prefix (e.g. "10.20.30.") rather than a dotted-decimal mask. We
compute the real mask AND derive that same truncated-prefix style so
either can be used -- see normalization_service for the final choice.
"""

import ipaddress

from models.system_info import SystemInfoRecord
from utils.wmi_utils import get_wmi, safe_query, IS_WINDOWS

VIRTUAL_ADAPTER_HINTS = (
    "virtual", "loopback", "bluetooth", "vmware", "virtualbox",
    "hyper-v", "docker", "wsl", "tap-", "tun",
)


def collect(record: SystemInfoRecord):
    if not IS_WINDOWS:
        record.set("ip_address", None, source="none", status="missing")
        record.set("mac_address", None, source="none", status="missing")
        record.set("subnet", None, source="none", status="missing")
        return

    conn = get_wmi()
    adapters = safe_query(
        lambda: list(conn.Win32_NetworkAdapterConfiguration(IPEnabled=True)),
        default=[],
    )

    candidate = _select_active_adapter(adapters)

    if candidate is None:
        record.set("ip_address", None, source="none", status="missing")
        record.set("mac_address", None, source="none", status="missing")
        record.set("subnet", None, source="none", status="missing")
        return

    ipv4 = next((ip for ip in (candidate.IPAddress or []) if _is_ipv4(ip)), None)
    idx = list(candidate.IPAddress or []).index(ipv4) if ipv4 in (candidate.IPAddress or []) else 0
    mask = None
    if candidate.IPSubnet and len(candidate.IPSubnet) > idx:
        mask = candidate.IPSubnet[idx]

    record.set("ip_address", ipv4, source="WMI:Win32_NetworkAdapterConfiguration")
    record.set("mac_address", candidate.MACAddress, source="WMI:Win32_NetworkAdapterConfiguration")

    # Subnet holds the REAL dotted-decimal subnet mask exactly as Windows
    # reports it (255.255.255.0, 255.255.252.0, ...).
    #
    # Note the mask says how BIG the network is, not WHICH network you are
    # on -- every site may well share 255.255.255.0. Identifying the site
    # therefore needs the network address (IP AND mask together), which
    # organization_collector computes for itself rather than reading it
    # back out of this column.
    if mask:
        record.set("subnet", mask,
                   source="WMI:Win32_NetworkAdapterConfiguration.IPSubnet",
                   raw=mask)
    else:
        record.set("subnet", None, source="none", status="missing",
                   note="Adapter reported an IP address but no subnet mask.")


def _select_active_adapter(adapters):
    """
    Pick the adapter actually carrying this machine's traffic.

    Name-based filtering alone is not enough: a machine can have two
    perfectly real-looking NICs (wired + Wi-Fi), or an Internet-Connection-
    Sharing / hotspot adapter on 192.168.137.x that is not named "virtual"
    at all. Returning whichever WMI happened to list first would put the
    wrong subnet on the record -- and Location is derived from the subnet,
    so that silently files the machine under the wrong site.

    The decisive signal is a DEFAULT GATEWAY: only the adapter with a real
    route off-network has one. DHCP is used as a weaker tie-breaker, since
    site machines are addressed by DHCP while ad-hoc/host-only adapters
    carry static addresses.
    """
    scored = []
    for a in adapters:
        desc = (getattr(a, "Description", "") or "").lower()
        if any(hint in desc for hint in VIRTUAL_ADAPTER_HINTS):
            continue
        ips = [ip for ip in (getattr(a, "IPAddress", None) or []) if _is_ipv4(ip)]
        ips = [ip for ip in ips if not ip.startswith("169.254.")]  # APIPA = no real network
        if not ips:
            continue

        gateways = [g for g in (getattr(a, "DefaultIPGateway", None) or [])
                    if g and g != "0.0.0.0"]
        score = 0
        if gateways:
            score += 2
        if getattr(a, "DHCPEnabled", False):
            score += 1
        scored.append((score, a))

    if scored:
        return max(scored, key=lambda pair: pair[0])[1]
    return adapters[0] if adapters else None


def _is_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
        return True
    except Exception:
        return False
