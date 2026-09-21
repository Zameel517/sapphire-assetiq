"""
schema.py
=========
Single source of truth for the 27-field record contract.

This mirrors the ACTUAL column headers/order found in the real
"the customer's real audit export" export (the real target format used
today), not the hypothetical names discussed early in the project chat.

If the asset portal's import template ever changes, this is the ONLY file
that needs to change -- collectors, normalization, validation and the
Google Sheets writer all read from here.
"""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class FieldSpec:
    key: str                 # internal field name used in SystemInfoRecord
    header: str               # exact column header for the sheet
    dtype: str                 # "text" | "numeric" | "datetime"
    required: bool = True
    identity_candidate: bool = False
    allowed_values: Optional[tuple] = None
    normalizer: Optional[str] = None  # name of normalization rule to apply


# Order matters: this is the exact column order written to Google Sheets.
SCHEMA: list[FieldSpec] = [
    FieldSpec("company", "Company", "text", identity_candidate=False),
    FieldSpec("location", "Location", "text"),
    FieldSpec("subnet", "Subnet", "text"),
    FieldSpec("asset_tag", "Asset Tag", "text", required=False, identity_candidate=True),
    FieldSpec("device_type", "Device Type", "text",
              allowed_values=("Laptop", "Desktop", "Server", "Tablet", "Other")),
    FieldSpec("os_version", "OS", "text"),
    FieldSpec("computer_name", "Computer Name", "text", identity_candidate=True),
    FieldSpec("domain_name", "Domain Name", "text"),
    FieldSpec("manufacturer", "Manufacturer", "text"),
    FieldSpec("system_model", "System Model", "text"),
    FieldSpec("serial_no", "Serial No", "text", identity_candidate=True),
    FieldSpec("cpu", "CPU", "text"),
    FieldSpec("ram_gb", "RAM (GB)", "numeric"),
    FieldSpec("ram_slots", "RAM Slots", "numeric", required=False),
    FieldSpec("disk_gb", "Disk (GB)", "numeric"),
    FieldSpec("disk_type", "Disk Type", "text",
              allowed_values=("HDD", "SATA SSD", "NVMe SSD", "SSD", "Unknown")),
    FieldSpec("disk_count", "No. of Disks", "numeric"),
    FieldSpec("display_size", "Display Size", "numeric"),
    FieldSpec("display_count", "No. of Displays", "numeric", required=False),
    FieldSpec("external_displays", "External Displays", "text", required=False),
    FieldSpec("mac_address", "MAC Address", "text", identity_candidate=True),
    FieldSpec("current_user", "Current User", "text"),
    FieldSpec("outlook_email", "Outlook Email", "text", required=False),
    FieldSpec("antivirus", "Antivirus", "text", required=False),
    FieldSpec("vpn", "VPN", "text", allowed_values=("Yes", "No")),
    FieldSpec("ip_address", "IP Address", "text"),
    FieldSpec("created_at", "Created At", "datetime"),
    FieldSpec("updated_at", "Updated At", "datetime", required=False),
]

HEADERS: list[str] = [f.header for f in SCHEMA]
FIELD_KEYS: list[str] = [f.key for f in SCHEMA]
NUMERIC_FIELDS: list[str] = [f.key for f in SCHEMA if f.dtype == "numeric"]
IDENTITY_CANDIDATES: list[str] = [f.key for f in SCHEMA if f.identity_candidate]

# Values that indicate "bad SMBIOS data" rather than a real value.
# Seen in real data: 'Default string', 'To Be Filled By O.E.M.', etc.
JUNK_STRING_MARKERS = {
    "default string",
    "to be filled by o.e.m.",
    "system product name",
    "system manufacturer",
    "system serial number",
    "none",
    "not specified",
    "n/a",
    "",
    # Asset-tag placeholders manufacturers leave in the firmware. Lenovo's
    # "No Asset Information" was being recorded as a real tag -- and, as the
    # first identity field, would have matched every Lenovo to the same row.
    "no asset information",
    "no asset tag",
    "chassis asset tag",
    "asset tag",
    "asset-1234567890",
    "system version",
    "unknown",
    "0",
    "00000000",
}
