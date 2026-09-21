"""
intelligence_service.py
========================
The V1 AI / Data-Intelligence layer. Implements the six confirmed
V1 features that operate on ALREADY-COLLECTED factual data -- this
module never invents hardware facts, it only reasons about them
(per the project chat's core AI principle: "AI becomes useful AFTER
collection").

Features implemented here:
  1. Device Classification        -> _classify_device_type
  3. Data Anomaly Detection       -> _detect_anomalies
  6. Asset Consistency Checking   -> _check_consistency

(Feature 2 Data Validation and Feature 5 Missing-Info Detection live in
validation_service.py; Feature 4 Data Normalization lives in
normalization_service.py -- kept separate so each has one job.)
"""

from models.system_info import SystemInfoRecord

# Typical RAM range observed across a normal office fleet. Anything
# outside this is flagged for review, not rejected.
TYPICAL_RAM_RANGE_GB = (4, 64)
TYPICAL_DISK_RANGE_GB = (100, 4000)

# The largest laptop screens made are 18". EDID reports size in whole
# centimetres, so a real 18" panel can compute to about 18.2" -- the margin
# stops that being flagged.
MAX_LAPTOP_SCREEN_IN = 18.5


def run_intelligence_layer(record: SystemInfoRecord, existing_rows: list[dict] | None = None):
    """existing_rows: prior records from Google Sheets, keyed by schema header,
    used for duplicate/anomaly detection. Pass None/[] on a fresh sheet."""
    existing_rows = existing_rows or []
    _classify_device_type(record)
    _check_consistency(record)
    _detect_anomalies(record)
    _detect_duplicates(record, existing_rows)


def _classify_device_type(record: SystemInfoRecord):
    """Cross-check the chassis-derived Device Type against other hardware
    signals (model name keywords, battery). Flags disagreement instead of
    silently overwriting the deterministic chassis reading."""
    device_type_fv = record.fields["device_type"]
    model = (record.get("system_model") or "").lower()

    model_suggests_laptop = any(k in model for k in ("laptop", "notebook", "elitebook",
                                                        "latitude", "thinkpad", "probook"))
    model_suggests_desktop = any(k in model for k in ("optiplex", "desktop", "tower", "aio",
                                                         "all-in-one", "elitedesk"))

    current = device_type_fv.value
    if model_suggests_laptop and current == "Desktop":
        record.flag(f"Device Classification: chassis says 'Desktop' but model "
                     f"name '{record.get('system_model')}' suggests Laptop.")
        device_type_fv.status = "review"
    elif model_suggests_desktop and current == "Laptop":
        record.flag(f"Device Classification: chassis says 'Laptop' but model "
                     f"name '{record.get('system_model')}' suggests Desktop.")
        device_type_fv.status = "review"


def _check_consistency(record: SystemInfoRecord):
    """Rule-based internal consistency checks, including one tailored to a
    real bug pattern found in the provided sample data: a script silently
    using the MAC address as a fake Serial Number when BIOS serial is
    unavailable."""
    serial = record.get("serial_no")
    mac = record.get("mac_address")
    if serial and mac and str(serial).strip().lower() == str(mac).strip().lower():
        record.flag("Asset Consistency: Serial No is identical to MAC Address -- "
                     "this usually means BIOS serial was unavailable and a fallback "
                     "value was used. Recommend manual verification.")
        record.fields["serial_no"].status = "review"

    manufacturer = (record.get("manufacturer") or "").lower()
    if manufacturer == "not available" and record.get("system_model") == "Not Available":
        record.flag("Asset Consistency: both Manufacturer and System Model are "
                     "unreadable from SMBIOS on this machine -- likely a BIOS/UEFI "
                     "configuration issue worth flagging to IT.")

    ram = record.get("ram_gb")
    slots = record.get("ram_slots")
    if isinstance(ram, (int, float)) and isinstance(slots, (int, float)) and slots == 0:
        record.flag("Asset Consistency: RAM capacity reported but 0 memory modules detected.")

    _check_laptop_screen_size(record)


def _check_laptop_screen_size(record: SystemInfoRecord):
    """A 'Laptop' whose OWN screen is bigger than any laptop screen is almost
    certainly an all-in-one till whose firmware reports laptop values -- the
    pattern behind a batch of 20.4" 'Default string' tills in a real audit export.

    Only the built-in screen counts, so a laptop plugged into a 24" monitor
    is never flagged."""
    type_fv = record.fields["device_type"]
    if type_fv.value != "Laptop":
        return
    size = _built_in_screen_size(record.fields["display_size"])
    if size is not None and size > MAX_LAPTOP_SCREEN_IN:
        record.flag(f"Asset Consistency: Device Type is 'Laptop' but its built-in screen "
                    f"is {size}\" -- larger than any laptop screen. Likely an all-in-one "
                    f"till whose firmware reports laptop values; verify Device Type.")
        type_fv.status = "review"


def _built_in_screen_size(display_fv):
    """Size of the machine's own screen from display_collector's per-screen
    detail, or None when it cannot be told apart from an external monitor."""
    raw = display_fv.raw if isinstance(display_fv.raw, dict) else {}
    displays = raw.get("displays") or []
    built_in = [d for d in displays if d.get("kind") == "built-in" and d.get("size_in")]
    if built_in:
        return built_in[0]["size_in"]
    if len(displays) == 1 and displays[0].get("kind") == "unknown":
        return displays[0].get("size_in")
    return None


def _detect_anomalies(record: SystemInfoRecord):
    """Simple range-based anomaly detection against a normal-fleet baseline.
    This becomes far more valuable once compared against real historical
    fleet data (see _detect_duplicates for the cross-record version)."""
    ram = record.get("ram_gb")
    if isinstance(ram, (int, float)):
        low, high = TYPICAL_RAM_RANGE_GB
        if ram < low or ram > high:
            record.flag(f"Anomaly: RAM = {ram} GB is outside the typical "
                         f"fleet range ({low}-{high} GB).")

    disk = record.get("disk_gb")
    if isinstance(disk, (int, float)):
        low, high = TYPICAL_DISK_RANGE_GB
        if disk < low or disk > high:
            record.flag(f"Anomaly: Disk = {disk} GB is outside the typical "
                         f"fleet range ({low}-{high} GB).")


def _detect_duplicates(record: SystemInfoRecord, existing_rows: list[dict]):
    """AI Feature #6 (fleet-level): flag if this machine's identity fields
    collide with a DIFFERENT existing row already in the central sheet."""
    if not existing_rows:
        return

    my_computer_name = record.get("computer_name")
    my_serial = record.get("serial_no")
    my_mac = record.get("mac_address")

    for row in existing_rows:
        same_computer_name = row.get("Computer Name") == my_computer_name
        different_serial = (
            my_serial and row.get("Serial No") and row.get("Serial No") != my_serial
        )
        if same_computer_name and different_serial:
            record.flag(f"Possible duplicate/mismatch: Computer Name "
                         f"'{my_computer_name}' already exists with a different "
                         f"Serial No ({row.get('Serial No')} vs {my_serial}).")

        same_mac_different_name = (
            row.get("MAC Address") == my_mac and row.get("Computer Name") != my_computer_name
        )
        if my_mac and same_mac_different_name:
            record.flag(f"Possible duplicate: MAC Address {my_mac} already "
                         f"registered under a different Computer Name "
                         f"({row.get('Computer Name')}).")
