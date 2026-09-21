"""
system_collector.py
====================
Collects: OS, Computer Name, Domain Name, Current User, Device Type.

Device Type uses SMBIOS chassis type as the primary signal, with a
hardware-heuristic fallback (battery presence) -- matches the project
chat's "don't rely on a single value" rule.
"""

import os
import platform
import socket

from models.system_info import SystemInfoRecord
from utils.wmi_utils import get_wmi, safe_query, IS_WINDOWS

# SMBIOS chassis type (Win32_SystemEnclosure.ChassisTypes) -> Device Type.
#
# Labels stay inside what the asset portal already receives: the real audit export
# only contains "Desktop" and "Laptop", so 2-in-1s map to the closest existing
# label instead of inventing a new one the import might reject. The exact
# chassis name is kept in the record's note for anyone who needs it.
CHASSIS_TYPE_MAP = {
    # Desktops -- including all-in-one retail tills (13) and mini PCs (35)
    "3": "Desktop", "4": "Desktop", "5": "Desktop", "6": "Desktop", "7": "Desktop",
    "13": "Desktop", "15": "Desktop", "16": "Desktop", "24": "Desktop",
    "34": "Desktop", "35": "Desktop", "36": "Desktop",
    # Laptops. 31 "Convertible": the keyboard is permanently attached and the
    # screen folds back 360 degrees (HP x360, Lenovo Yoga) -- a laptop that can
    # pose as a tablet.
    "8": "Laptop", "9": "Laptop", "10": "Laptop", "14": "Laptop", "31": "Laptop",
    # Tablets. 32 "Detachable": the screen half is the whole computer and the
    # keyboard comes off (Surface Pro) -- a tablet that can pose as a laptop.
    "30": "Tablet", "32": "Tablet",
    "17": "Server", "23": "Server", "28": "Server",
    "11": "Other", "12": "Other", "33": "Other",
}

CHASSIS_NAMES = {
    "1": "Other", "2": "Unknown", "3": "Desktop", "4": "Low Profile Desktop",
    "5": "Pizza Box", "6": "Mini Tower", "7": "Tower", "8": "Portable",
    "9": "Laptop", "10": "Notebook", "11": "Hand Held", "12": "Docking Station",
    "13": "All in One", "14": "Sub Notebook", "15": "Space-Saving", "16": "Lunch Box",
    "17": "Main System Chassis", "23": "Rack Mount Chassis", "24": "Sealed-Case PC",
    "28": "Blade", "30": "Tablet", "31": "Convertible (2-in-1)",
    "32": "Detachable (2-in-1)", "33": "IoT Gateway", "34": "Embedded PC",
    "35": "Mini PC", "36": "Stick PC",
}

# Win32_ComputerSystem.PCSystemType -- Windows' own power-profile class. Used
# when the chassis code is missing or junk: boards whose SMBIOS still says
# "Default string" typically report chassis 1 "Other" or 2 "Unknown".
PC_SYSTEM_TYPE_MAP = {
    "1": "Desktop", "2": "Laptop", "3": "Desktop",
    "4": "Server", "5": "Server", "7": "Server", "8": "Tablet",
}


def collect(record: SystemInfoRecord):
    _collect_os(record)
    _collect_computer_name(record)
    _collect_domain(record)
    _collect_current_user(record)
    _collect_device_type(record)


def _collect_os(record: SystemInfoRecord):
    if IS_WINDOWS:
        conn = get_wmi()
        os_info = safe_query(lambda: conn.Win32_OperatingSystem()[0])
        if os_info:
            caption = getattr(os_info, "Caption", "").strip()
            record.set("os_version", caption, source="WMI:Win32_OperatingSystem")
            return
    # Fallback (also used for local non-Windows testing)
    record.set("os_version", platform.platform(), source="platform",
                status="review", note="WMI unavailable; used platform module")


def _collect_computer_name(record: SystemInfoRecord):
    try:
        name = socket.gethostname() or os.environ.get("COMPUTERNAME")
        record.set("computer_name", name, source="socket.gethostname")
    except Exception:
        record.set("computer_name", None, source="socket", status="missing")


def _collect_domain(record: SystemInfoRecord):
    """
    Emits the AD DNS domain verbatim when joined ("COMPANY.local", "COMPANY.store"),
    and the single word "Workgroup" when not -- matching the real
    Sample-Equipment_Audits export exactly.

    Read from the machine at run time; nothing here is tied to any one
    site or domain. The workgroup NAME is preserved in .raw so no
    collected information is lost.
    """
    if IS_WINDOWS:
        conn = get_wmi()
        cs = safe_query(lambda: conn.Win32_ComputerSystem()[0])
        if cs is not None:
            reported = (getattr(cs, "Domain", "") or "").strip()
            if getattr(cs, "PartOfDomain", False):
                if reported:
                    record.set("domain_name", reported,
                               source="WMI:Win32_ComputerSystem.Domain")
                    return
                dns_domain = (os.environ.get("USERDNSDOMAIN") or "").strip()
                if dns_domain:
                    record.set("domain_name", dns_domain, source="env:USERDNSDOMAIN",
                               status="review",
                               note="PartOfDomain was true but WMI reported no "
                                    "domain name; used the logon DNS domain.")
                    return
                record.set("domain_name", "Unknown",
                           source="WMI:Win32_ComputerSystem", status="review",
                           note="Machine reports as domain-joined but no domain "
                                "name could be read.")
                return

            # Not joined. The contract wants the literal word, not a sentence.
            record.set("domain_name", "Workgroup",
                       source="WMI:Win32_ComputerSystem.PartOfDomain",
                       raw=reported or "Workgroup",
                       note="Not domain-joined; workgroup name is "
                            "'%s'." % (reported or "unknown"))
            return

    record.set("domain_name",
               os.environ.get("USERDNSDOMAIN")
               or os.environ.get("USERDOMAIN", "Unknown"),
               source="env", status="review",
               note="WMI unavailable; domain read from environment.")


def _collect_current_user(record: SystemInfoRecord):
    """
    The real export stores a bare username ("jane.doe", "POS01"), not
    DOMAIN\\user. The fully-qualified form is kept in .raw only.

    Deployed via Active Directory this may run either as a USER logon
    script (env vars are correct) or as a COMPUTER startup script under
    the SYSTEM account (env vars would report the machine account, which
    is useless for an inventory). Win32_ComputerSystem.UserName reports
    the interactively logged-on console user regardless of which account
    the process itself runs under, so it is tried first.
    """
    console_user = None
    if IS_WINDOWS:
        conn = get_wmi()
        cs = safe_query(lambda: conn.Win32_ComputerSystem()[0])
        if cs is not None:
            console_user = (getattr(cs, "UserName", "") or "").strip() or None

    if console_user:
        record.set("current_user", _bare_username(console_user),
                   source="WMI:Win32_ComputerSystem.UserName", raw=console_user)
        return

    try:
        domain = os.environ.get("USERDOMAIN", "")
        username = os.environ.get("USERNAME") or os.getlogin()
        qualified = f"{domain}\\{username}" if domain else username
        if _is_machine_account(username):
            record.set("current_user", None, source="env:USERNAME",
                       status="missing", raw=qualified,
                       note="Running as SYSTEM/machine account with no user "
                            "logged on. Deploy as a USER logon script if the "
                            "Current User column must be populated.")
            return
        record.set("current_user", username, source="env:USERNAME", raw=qualified)
    except Exception:
        record.set("current_user", None, source="env", status="missing")


def _bare_username(qualified: str) -> str:
    """'CORP\\jane.doe' -> 'jane.doe'; also handles user@domain form."""
    value = qualified.strip()
    if "\\" in value:
        value = value.split("\\")[-1]
    if "@" in value:
        value = value.split("@")[0]
    return value


def _is_machine_account(username: str) -> bool:
    """Computer startup scripts run as SYSTEM / COMPUTERNAME$."""
    if not username:
        return False
    lowered = username.strip().lower()
    return lowered.endswith("$") or lowered in ("system", "localsystem")


def _collect_device_type(record: SystemInfoRecord):
    if IS_WINDOWS:
        conn = get_wmi()
        enclosure = safe_query(lambda: conn.Win32_SystemEnclosure()[0])
        codes = [str(c) for c in (getattr(enclosure, "ChassisTypes", None) or [])] \
            if enclosure is not None else []

        # An enclosure can report several codes; use the first one we recognise.
        for code in codes:
            device_type = CHASSIS_TYPE_MAP.get(code)
            if device_type:
                record.set("device_type", device_type,
                           source="WMI:Win32_SystemEnclosure.ChassisTypes", raw=code,
                           note=f"SMBIOS chassis {code} = {CHASSIS_NAMES.get(code, 'unnamed')}")
                return

        # Chassis missing or junk -> Windows' own classification.
        cs = safe_query(lambda: conn.Win32_ComputerSystem()[0])
        pc_type = str(getattr(cs, "PCSystemType", "") or "") if cs is not None else ""
        device_type = PC_SYSTEM_TYPE_MAP.get(pc_type)
        if device_type:
            shown = ", ".join(f"{c} ({CHASSIS_NAMES.get(c, 'unnamed')})" for c in codes) or "none"
            record.set("device_type", device_type,
                       source="WMI:Win32_ComputerSystem.PCSystemType", raw=pc_type,
                       status="review",
                       note=f"Chassis code {shown} not usable; used Windows PCSystemType {pc_type}")
            return

        # Heuristic fallback: presence of a battery strongly implies laptop
        battery = safe_query(lambda: conn.Win32_Battery())
        if battery:
            record.set("device_type", "Laptop", source="heuristic:battery-present",
                        status="review", note="Chassis type unavailable/ambiguous")
            return
    record.set("device_type", "Unknown", source="none", status="missing")
