"""
presentation.py
================
How the inventory LOOKS, defined once and shared by the Google Sheet writer
(services/sheets_service.py) and the local Excel export (output/local_export.py),
so the two outputs can never drift apart.
"""

from config.schema import SCHEMA

HEADER_BG = "1F4E78"                          # navy header
HEADER_FG = "FFFFFF"
HEADER_FONT_SIZE = 10
BAND_BG = "EEF3F9"                            # soft alternate-row tint
BORDER = "C9D3E0"
REVIEW_BG, REVIEW_FG = "FFF2CC", "7F6000"     # yellow: value needs a human
MISSING_BG, MISSING_FG = "F8CBAD", "9C2A00"   # red: required value is blank

HEADER_HEIGHT_PX = 42
ROW_HEIGHT_PX = 26
MIN_WIDTH_PX, MAX_WIDTH_PX = 80, 320
# Room for the filter arrow drawn at the right of every header cell, so header
# text never runs underneath it.
FILTER_BUTTON_PX = 22
# Free-text columns that can list several monitors get more room before clipping.
MAX_WIDTH_OVERRIDES = {"external_displays": 620}

NUMBER_PATTERNS = {
    "ram_gb": "0", "ram_slots": "0", "disk_gb": "#,##0",
    "disk_count": "0", "display_size": "0.0", "display_count": "0",
}

# Identifiers are pinned to plain text, otherwise a digits-only serial or asset
# tag would be read as a number -- dropping leading zeros or becoming 1.23E+19.
TEXT_KEYS = {"subnet", "asset_tag", "computer_name", "serial_no",
             "mac_address", "ip_address"}

# Placeholder values the collectors emit when something needs a human.
REVIEW_VALUES = ("Unknown", "Not Available", "Outlook Not Found")


def fit_width(header: str, values: list[str], max_px: int = MAX_WIDTH_PX) -> int:
    """Pixel width that shows the longest value without clipping, and the
    header clear of its filter arrow. Long headers wrap onto two lines rather
    than forcing a wide column."""
    longest_value = max((len(v) for v in values), default=0)
    header_chars = min(len(header), 14)
    px = max(longest_value * 7 + 28, header_chars * 8 + 28 + FILTER_BUTTON_PX)
    return max(MIN_WIDTH_PX, min(max_px, px))


def required_runs() -> list[tuple[int, int]]:
    """Contiguous [start, end) column spans of required fields."""
    runs, start = [], None
    for i, spec in enumerate(SCHEMA):
        if spec.required and start is None:
            start = i
        elif not spec.required and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(SCHEMA)))
    return runs
