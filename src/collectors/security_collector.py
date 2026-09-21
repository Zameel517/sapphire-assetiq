"""
security_collector.py
======================
Collects: Antivirus, VPN.

Antivirus: queries root\\SecurityCenter2 (the same registry the Windows
Security app itself uses) rather than checking for one specific product
-- so third-party AV (Trend Micro, ESET, etc.) is detected correctly,
matching what we saw in the real sample data.

VPN: the real target format is a simple Yes/No (does a VPN CONNECTION
PROFILE exist), not a live connection check. We use Get-VpnConnection.
"""

from models.system_info import SystemInfoRecord
from utils.wmi_utils import get_wmi_security_center, safe_query, run_powershell, IS_WINDOWS


def collect(record: SystemInfoRecord):
    _collect_antivirus(record)
    _collect_vpn(record)


def _collect_antivirus(record: SystemInfoRecord):
    if not IS_WINDOWS:
        record.set("antivirus", None, source="none", status="missing")
        return

    conn = get_wmi_security_center()
    products = safe_query(lambda: list(conn.AntiVirusProduct()), default=[])

    if not products:
        record.set("antivirus", "Not Detected", source="WMI:root\\SecurityCenter2",
                    status="review")
        return

    names = [getattr(p, "displayName", "").strip() for p in products if getattr(p, "displayName", None)]
    record.set("antivirus", "; ".join(names) if names else "Not Detected",
                source="WMI:root\\SecurityCenter2:AntiVirusProduct")


def _collect_vpn(record: SystemInfoRecord):
    if not IS_WINDOWS:
        record.set("vpn", None, source="none", status="missing")
        return

    output = run_powershell("Get-VpnConnection -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count")
    if output is None:
        record.set("vpn", "No", source="PowerShell:Get-VpnConnection", status="review",
                    note="Command failed or unavailable; defaulted to No")
        return

    try:
        count = int(output.strip())
        record.set("vpn", "Yes" if count > 0 else "No",
                    source="PowerShell:Get-VpnConnection")
    except ValueError:
        record.set("vpn", "No", source="PowerShell:Get-VpnConnection", status="review")
