"""
storage_collector.py
=====================
Collects: Disk (GB), Disk Type, No. of Disks.

Counts physical internal disks only (not mounted logical drives, not
USB/removable media) -- per the project chat's explicit rule.
"""

import json

from models.system_info import SystemInfoRecord
from utils.wmi_utils import get_wmi, safe_query, run_powershell, IS_WINDOWS

# Reads the BOOT disk (the drive Windows runs from), not whichever disk is
# listed first, and returns its media type, bus type and spindle speed as JSON.
# Single-quoted PowerShell throughout: double quotes do not survive being passed
# through subprocess to Windows PowerShell 5.1.
_BOOT_DISK_PS = (
    "$n = (Get-Partition -DriveLetter $env:SystemDrive.TrimEnd(':') -ErrorAction SilentlyContinue | Get-Disk).Number; "
    "$d = Get-PhysicalDisk | Where-Object { $_.DeviceId -eq [string]$n } | Select-Object -First 1; "
    "if (-not $d) { $d = Get-PhysicalDisk | Select-Object -First 1 }; "
    "$d | Select-Object @{n='MediaType';e={$_.MediaType.ToString()}}, "
    "@{n='BusType';e={$_.BusType.ToString()}}, SpindleSpeed | ConvertTo-Json -Compress"
)

_SPINDLE_UNKNOWN = 4294967295   # what Windows reports when it cannot tell


def collect(record: SystemInfoRecord):
    if not IS_WINDOWS:
        record.set("disk_gb", None, source="none", status="missing")
        record.set("disk_type", None, source="none", status="missing")
        record.set("disk_count", None, source="none", status="missing")
        return

    conn = get_wmi()
    disks = safe_query(lambda: list(conn.Win32_DiskDrive()), default=[])

    # Filter to physical, fixed, internal disks only
    physical_disks = [
        d for d in disks
        if getattr(d, "MediaType", "") and "removable" not in getattr(d, "MediaType", "").lower()
        and getattr(d, "InterfaceType", "") != "USB"
    ]

    if not physical_disks:
        record.set("disk_gb", None, source="none", status="missing")
        record.set("disk_type", None, source="none", status="missing")
        record.set("disk_count", 0, source="WMI:Win32_DiskDrive", status="review")
        return

    total_bytes = sum(int(d.Size) for d in physical_disks if getattr(d, "Size", None))
    total_gb = round(total_bytes / (1024 ** 3))
    record.set("disk_gb", total_gb, source="WMI:Win32_DiskDrive",
                raw=f"{total_bytes} bytes across {len(physical_disks)} disk(s)")
    record.set("disk_count", len(physical_disks), source="WMI:Win32_DiskDrive")

    detected = _detect_disk_type()
    if detected:
        disk_type, raw, note = detected
        record.set("disk_type", disk_type, source="PowerShell:Get-PhysicalDisk",
                    raw=raw, note=note)
    else:
        # Fallback: WMI can't natively distinguish SSD vs HDD reliably
        record.set("disk_type", "Unknown", source="WMI:Win32_DiskDrive",
                    status="review", note="Could not determine media type via Get-PhysicalDisk")


def _detect_disk_type():
    """Classify the boot disk -> (Disk Type, raw JSON, note), or None."""
    output = run_powershell(_BOOT_DISK_PS)
    if not output:
        return None
    try:
        info = json.loads(output)
    except ValueError:
        return None
    result = classify_disk(info.get("MediaType"), info.get("BusType"), info.get("SpindleSpeed"))
    if result is None:
        return None
    label, note = result
    return label, output, note


def classify_disk(media_type, bus_type, spindle_speed):
    """
    (MediaType, BusType, SpindleSpeed) -> (Disk Type, explanation), or None.

    Labels stay inside what the real audit export uses ("SSD" on every row;
    "HDD" is the only other physical kind), so nothing new reaches the asset portal.

    Windows often reports MediaType "Unspecified" -- notably for the eMMC
    storage soldered into low-cost tablets -- so instead of giving up with
    "Unknown", the bus type and spindle speed are used to work it out.
    """
    media = str(media_type or "").strip().lower()
    bus = str(bus_type or "").strip().lower()

    if bus in ("mmc", "sd"):
        return "SSD", (f"{bus_type} flash storage (eMMC/SD, typical of low-cost tablets); "
                       f"solid-state, recorded as SSD")
    if bus == "nvme":
        return "SSD", "NVMe drive (NVMe drives are always solid-state)"
    if media in ("ssd", "scm"):
        return "SSD", f"{bus_type or 'unknown bus'} solid-state drive"
    if media == "hdd":
        return "HDD", f"{bus_type or 'unknown bus'} spinning hard disk"

    # MediaType unspecified: spindle speed is only trustworthy on a real drive
    # bus. RAID controllers, USB bridges and virtual disks report junk values.
    if bus in ("sata", "ata", "atapi", "sas"):
        if spindle_speed == 0:
            return "SSD", f"MediaType unspecified; {bus_type} drive with spindle speed 0 (no platters)"
        if isinstance(spindle_speed, int) and 0 < spindle_speed < _SPINDLE_UNKNOWN:
            return "HDD", f"MediaType unspecified; {bus_type} drive spinning at {spindle_speed} rpm"
    return None
