"""
hardware_collector.py
======================
Collects: Manufacturer, System Model, Serial No, Asset Tag, CPU,
RAM (GB), RAM Slots.

Known real-world issue this collector explicitly guards against (found
in the actual sample data provided): some machines report bad SMBIOS
data ("Default string") and some scripts silently fall back to the MAC
address as a fake "serial number." We never do that silently -- if we
fall back, the source/status make it visible.
"""

from config.schema import JUNK_STRING_MARKERS
from models.system_info import SystemInfoRecord
from utils.wmi_utils import get_wmi, safe_query, IS_WINDOWS


def _is_junk(value) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in JUNK_STRING_MARKERS


def collect(record: SystemInfoRecord):
    _collect_manufacturer_model(record)
    _collect_serial_and_asset_tag(record)
    _collect_cpu(record)
    _collect_ram(record)


def _collect_manufacturer_model(record: SystemInfoRecord):
    if not IS_WINDOWS:
        record.set("manufacturer", None, source="none", status="missing")
        record.set("system_model", None, source="none", status="missing")
        return

    conn = get_wmi()
    cs = safe_query(lambda: conn.Win32_ComputerSystem()[0])

    manufacturer_raw = getattr(cs, "Manufacturer", None) if cs else None
    model_raw = getattr(cs, "Model", None) if cs else None

    if _is_junk(manufacturer_raw):
        record.set("manufacturer", "Not Available", source="WMI:Win32_ComputerSystem",
                    status="review", raw=manufacturer_raw,
                    note="SMBIOS manufacturer field reported junk/placeholder value")
    else:
        record.set("manufacturer", manufacturer_raw.strip(),
                    source="WMI:Win32_ComputerSystem")

    if _is_junk(model_raw):
        record.set("system_model", "Not Available", source="WMI:Win32_ComputerSystem",
                    status="review", raw=model_raw,
                    note="SMBIOS model field reported junk/placeholder value")
    else:
        record.set("system_model", model_raw.strip(), source="WMI:Win32_ComputerSystem")

    # Lenovo reports its machine-type code as the model ("20RAS04800") and keeps
    # the product name people know ("ThinkPad E14") in the product Version field.
    if manufacturer_raw and manufacturer_raw.strip().lower().startswith("lenovo"):
        product = safe_query(lambda: conn.Win32_ComputerSystemProduct()[0])
        version = getattr(product, "Version", None) if product else None
        if not _is_junk(version) and version.strip().lower() != str(model_raw or "").strip().lower():
            record.set("system_model", version.strip(),
                       source="WMI:Win32_ComputerSystemProduct.Version", raw=model_raw,
                       note=f"Lenovo machine type {str(model_raw or '').strip()}")


def _collect_serial_and_asset_tag(record: SystemInfoRecord):
    if not IS_WINDOWS:
        record.set("serial_no", None, source="none", status="missing")
        record.set("asset_tag", None, source="none", status="missing")
        return

    conn = get_wmi()

    # --- Serial No: BIOS -> ComputerSystemProduct UUID -> Not Available ---
    bios = safe_query(lambda: conn.Win32_BIOS()[0])
    bios_serial = getattr(bios, "SerialNumber", None) if bios else None

    if not _is_junk(bios_serial):
        record.set("serial_no", bios_serial.strip(), source="WMI:Win32_BIOS")
    else:
        product = safe_query(lambda: conn.Win32_ComputerSystemProduct()[0])
        uuid_val = getattr(product, "UUID", None) if product else None
        if not _is_junk(uuid_val):
            record.set("serial_no", uuid_val, source="WMI:Win32_ComputerSystemProduct.UUID",
                        status="review", note="BIOS serial unavailable/junk; used system UUID")
        else:
            record.set("serial_no", "Not Available", source="none", status="missing",
                        note="BIOS serial and system UUID both unavailable")

    # --- Asset Tag: SMBIOS enclosure asset tag (often unpopulated) ---
    enclosure = safe_query(lambda: conn.Win32_SystemEnclosure()[0])
    asset_tag_raw = getattr(enclosure, "SMBIOSAssetTag", None) if enclosure else None
    if asset_tag_raw and not _is_junk(asset_tag_raw):
        record.set("asset_tag", asset_tag_raw.strip(), source="WMI:Win32_SystemEnclosure")
    else:
        record.set("asset_tag", "Not Available", source="none", status="missing",
                    note="Not populated in the firmware (SMBIOS); organization_collector uses "
                         "the computer name when it follows the asset-code pattern")


def _collect_cpu(record: SystemInfoRecord):
    if not IS_WINDOWS:
        record.set("cpu", None, source="none", status="missing")
        return
    conn = get_wmi()
    proc = safe_query(lambda: conn.Win32_Processor()[0])
    if proc:
        raw_name = getattr(proc, "Name", "").strip()
        normalized = " ".join(raw_name.split())  # collapse whitespace only here;
        record.set("cpu", normalized, source="WMI:Win32_Processor", raw=raw_name)
        # deeper normalization (strip @ x.xxGHz / (R)/(TM)) happens in normalization_service
    else:
        record.set("cpu", None, source="none", status="missing")


def _collect_ram(record: SystemInfoRecord):
    if not IS_WINDOWS:
        record.set("ram_gb", None, source="none", status="missing")
        record.set("ram_slots", None, source="none", status="missing")
        return

    conn = get_wmi()
    modules = safe_query(lambda: list(conn.Win32_PhysicalMemory()), default=[])

    if modules:
        total_bytes = sum(int(m.Capacity) for m in modules if getattr(m, "Capacity", None))
        total_gb = round(total_bytes / (1024 ** 3))
        record.set("ram_gb", total_gb, source="WMI:Win32_PhysicalMemory",
                    raw=f"{total_bytes} bytes across {len(modules)} module(s)")
        record.set("ram_slots", len(modules), source="WMI:Win32_PhysicalMemory",
                    status="review",
                    note="Counts installed memory MODULES, not necessarily total physical slots")
    else:
        record.set("ram_gb", None, source="none", status="missing")
        record.set("ram_slots", None, source="none", status="missing")
