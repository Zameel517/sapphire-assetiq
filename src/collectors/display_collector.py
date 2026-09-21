"""
display_collector.py
=====================
Collects: Display Size (diagonal inches), No. of Displays, External Displays.

Each monitor is read from its EDID through WMI's root\\wmi namespace:
  WmiMonitorBasicDisplayParams          physical width/height (cm) -> diagonal
  WmiMonitorConnectionParams            how it is attached: built-in panel,
                                        HDMI, DisplayPort, VGA, DVI, ...
  WmiMonitorID                          manufacturer, model name, serial, year
  WmiMonitorListedSupportedSourceModes  native (preferred) resolution

Display Size is the machine's OWN screen: the built-in panel on a laptop or
all-in-one till. A desktop has no built-in panel, so its external monitor is
used; with several external monitors the first is reported and the value is
marked for review.
"""

import math

from models.system_info import SystemInfoRecord
from utils.wmi_utils import IS_WINDOWS, get_wmi_namespace, safe_query

# WmiMonitorConnectionParams.VideoOutputTechnology, read as unsigned 32-bit.
# Windows reports a built-in panel as 0x80000000.
_INTERNAL = 0x80000000
CONNECTION_NAMES = {
    _INTERNAL: "Built-in", 0xFFFFFFFF: "Other",
    0: "VGA", 1: "S-Video", 2: "Composite", 3: "Component", 4: "DVI", 5: "HDMI",
    6: "LVDS", 8: "D-Jpn", 9: "SDI", 10: "DisplayPort", 11: "eDP",
    12: "UDI", 13: "UDI embedded", 14: "SDTV dongle", 15: "Miracast",
    16: "Indirect wired",
}
# Connections wired inside the chassis, i.e. the machine's own screen.
BUILT_IN_CONNECTIONS = {_INTERNAL, 6, 11, 13}

# EDID manufacturer codes common on office and retail kit -> readable brand.
EDID_BRANDS = {
    "DEL": "Dell", "HWP": "HP", "HPN": "HP", "LEN": "Lenovo", "SAM": "Samsung",
    "SEC": "Samsung", "GSM": "LG", "LGD": "LG Display", "ACI": "Asus",
    "AUS": "Asus", "ACR": "Acer", "AOC": "AOC", "BNQ": "BenQ", "PHL": "Philips",
    "VSC": "ViewSonic", "AUO": "AU Optronics", "BOE": "BOE",
    "CMN": "Chimei Innolux", "SHP": "Sharp", "IVO": "InfoVision",
    "SDC": "Samsung Display", "MS_": "Microsoft",
}


def collect(record: SystemInfoRecord):
    if not IS_WINDOWS:
        _set_unreadable(record, "Not running on Windows")
        return

    try:
        ns = get_wmi_namespace("root\\wmi")
    except Exception:
        _set_unreadable(record, "WMI monitor namespace unavailable")
        return

    displays = describe_displays(
        safe_query(lambda: list(ns.WmiMonitorBasicDisplayParams()), default=[]),
        safe_query(lambda: list(ns.WmiMonitorID()), default=[]),
        safe_query(lambda: list(ns.WmiMonitorConnectionParams()), default=[]),
        safe_query(lambda: list(ns.WmiMonitorListedSupportedSourceModes()), default=[]),
    )
    if not displays:
        _set_unreadable(record, "No active monitor reported EDID data")
        return

    size, status, note = choose_display_size(displays)
    record.set("display_size", size, source="WMI:root\\wmi (monitor EDID)",
               raw={"displays": displays}, status=status, note=note)

    # How many screens, and what the external ones are. The serial number is a
    # monitor's only fixed identity: no monitor stores an asset code a PC can read.
    external = [d for d in displays if d["kind"] == "external"]
    built_in = [d for d in displays if d["kind"] == "built-in"]
    record.set("display_count", len(displays), source="WMI:root\\wmi (monitor EDID)",
               note=f"{len(built_in)} built-in, {len(external)} external, "
                    f"{len(displays) - len(built_in) - len(external)} unidentified")
    record.set("external_displays",
               "; ".join(describe(d, with_serial=True) for d in external) if external else "None",
               source="WMI:root\\wmi (monitor EDID)", raw=external or None)


def _set_unreadable(record: SystemInfoRecord, note: str):
    record.set("display_size", None, source="none", status="missing", note=note)
    record.set("display_count", None, source="none", status="missing", note=note)
    record.set("external_displays", "Not Available", source="none", status="review", note=note)


def describe_displays(basic, ids, conns, modes) -> list[dict]:
    """Join the four WMI monitor classes by InstanceName into one dict per
    active screen. Built-in screens are listed first."""
    by_id = {_prop(m, "InstanceName"): m for m in ids}
    by_conn = {_prop(m, "InstanceName"): m for m in conns}
    by_mode = {_prop(m, "InstanceName"): m for m in modes}

    displays = []
    for b in basic:
        if _prop(b, "Active") is False:
            continue
        inst = _prop(b, "InstanceName")
        width_cm = _prop(b, "MaxHorizontalImageSize") or 0
        height_cm = _prop(b, "MaxVerticalImageSize") or 0
        size = round(math.hypot(width_cm, height_cm) / 2.54, 1) if width_cm and height_cm else None

        tech = _prop(by_conn.get(inst), "VideoOutputTechnology")
        tech = None if tech is None else int(tech) & 0xFFFFFFFF
        if tech is None:
            kind, connection = "unknown", "unknown"
        else:
            kind = "built-in" if tech in BUILT_IN_CONNECTIONS else "external"
            connection = CONNECTION_NAMES.get(tech, f"code {tech}")

        ident = by_id.get(inst)
        code = _edid_text(_prop(ident, "ManufacturerName"))
        displays.append({
            "kind": kind,
            "connection": connection,
            "size_in": size,
            "resolution": _native_resolution(by_mode.get(inst)),
            "brand": EDID_BRANDS.get(code, code) or None,
            "model": _edid_text(_prop(ident, "UserFriendlyName")) or None,
            "serial": _clean_serial(_edid_text(_prop(ident, "SerialNumberID"))),
            "year": _prop(ident, "YearOfManufacture"),
        })
    return sorted(displays, key=lambda d: 0 if d["kind"] == "built-in" else 1)


def choose_display_size(displays: list[dict]):
    """-> (Display Size, status, note)."""
    sized = [d for d in displays if d["size_in"]]
    if not sized:
        return None, "missing", "Monitors found but none reported a physical size"

    built_in = [d for d in sized if d["kind"] == "built-in"]
    external = [d for d in displays if d["kind"] == "external"]

    if built_in:
        note = f"Built-in screen: {describe(built_in[0])}"
        if external:
            note += f" | {len(external)} external: " + "; ".join(describe(d) for d in external)
        return built_in[0]["size_in"], "ok", note
    if len(sized) == 1:
        return sized[0]["size_in"], "ok", describe(sized[0])
    return (sized[0]["size_in"], "review",
            f"{len(sized)} monitors, no built-in screen; reporting the first: "
            + "; ".join(describe(d) for d in sized))


def describe(d: dict, with_serial: bool = False) -> str:
    brand, model = d.get("brand"), d.get("model")
    # EDID model names usually repeat the brand ("HP N246v"); don't print it twice.
    if brand and model and model.lower().startswith(brand.lower()):
        brand = None
    connection = d.get("connection")
    if d.get("kind") == "built-in" or connection in (None, "unknown"):
        connection = None   # "Built-in screen:" already says how it is attached
    parts = [brand, model, f'{d["size_in"]}"' if d.get("size_in") else None,
             connection, d.get("resolution")]
    if with_serial and d.get("serial"):
        parts.append(f"S/N {d['serial']}")
    return " ".join(p for p in parts if p)


def _prop(obj, name):
    if obj is None:
        return None
    try:
        return getattr(obj, name)
    except Exception:
        try:
            return obj.Properties_(name).Value
        except Exception:
            return None


def _edid_text(codes) -> str:
    if not codes:
        return ""
    try:
        return "".join(chr(int(c)) for c in codes if int(c)).strip()
    except Exception:
        return ""


def _clean_serial(serial: str):
    return None if not serial or set(serial) <= {"0"} else serial


def _native_resolution(mode_obj):
    try:
        modes = list(_prop(mode_obj, "MonitorSourceModes") or [])
        preferred = modes[int(_prop(mode_obj, "PreferredMonitorSourceModeIndex") or 0)]
        return f"{int(_prop(preferred, 'HorizontalActivePixels'))}x{int(_prop(preferred, 'VerticalActivePixels'))}"
    except Exception:
        return None
