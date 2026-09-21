"""
normalization_service.py
=========================
AI/Data-Intelligence Feature #4: Data Normalization.

Converts collected raw values into the exact structured form the
destination schema expects. Never touches deterministic hardware
facts -- only reshapes how they are represented (per the project
chat's core AI principle).

Rules implemented (all derived from real formatting issues seen in
the actual sample data provided):
  - CPU:        strip (R)/(TM), collapse "@ x.xxGHz" clock speed suffix
  - Display:    strip a trailing unit like "15.3 inch" -> 15.3 (float)
  - Numerics:   coerce numeric fields to int/float; "Not Available" stays text
  - Manufacturer/Model: already normalized upstream in hardware_collector
"""

import re

from config.schema import NUMERIC_FIELDS
from models.system_info import SystemInfoRecord

_CPU_NOISE = re.compile(r"\(R\)|\(TM\)|\(r\)|\(tm\)", re.IGNORECASE)
_CPU_CLOCK_SUFFIX = re.compile(r"\s*@\s*[\d.]+\s*[GgMm][Hh][Zz]\s*$")
_UNIT_SUFFIX = re.compile(r"[a-zA-Z\"']+\s*$")

NON_NUMERIC_MARKERS = {"not available", "unknown", "n/a", ""}


def normalize(record: SystemInfoRecord):
    _normalize_cpu(record)
    _normalize_display_size(record)
    _coerce_numeric_fields(record)


def _normalize_cpu(record: SystemInfoRecord):
    fv = record.fields["cpu"]
    if not fv.value:
        return
    cleaned = _CPU_NOISE.sub("", fv.value)
    cleaned = _CPU_CLOCK_SUFFIX.sub("", cleaned)
    cleaned = " ".join(cleaned.split())
    if cleaned != fv.value:
        record.set("cpu", cleaned, source=fv.source, raw=fv.raw or fv.value,
                    status=fv.status, note=fv.note)


def _normalize_display_size(record: SystemInfoRecord):
    fv = record.fields["display_size"]
    if fv.value is None:
        return
    if isinstance(fv.value, (int, float)):
        return  # already numeric
    text = str(fv.value).strip()
    stripped = _UNIT_SUFFIX.sub("", text).strip()
    try:
        numeric = float(stripped)
        record.set("display_size", numeric, source=fv.source, raw=fv.raw or fv.value,
                    status=fv.status, note=fv.note)
    except ValueError:
        record.set("display_size", None, source=fv.source, status="review",
                    note=f"Could not parse numeric size from '{fv.value}'")


def _coerce_numeric_fields(record: SystemInfoRecord):
    for key in NUMERIC_FIELDS:
        fv = record.fields[key]
        if fv.value is None:
            continue
        if isinstance(fv.value, (int, float)):
            continue
        text = str(fv.value).strip().lower()
        if text in NON_NUMERIC_MARKERS:
            continue
        digits = re.sub(r"[^\d.]", "", str(fv.value))
        if not digits:
            record.set(key, None, source=fv.source, status="review",
                        note=f"Expected numeric value, got '{fv.value}'")
            continue
        try:
            numeric = float(digits) if "." in digits else int(digits)
            record.set(key, numeric, source=fv.source, raw=fv.raw or fv.value,
                        status=fv.status, note=fv.note)
        except ValueError:
            record.set(key, None, source=fv.source, status="review",
                        note=f"Could not coerce '{fv.value}' to numeric")
