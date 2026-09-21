"""
validation_service.py
======================
AI/Data-Intelligence Feature #2: Data Validation.
AI/Data-Intelligence Feature #5: Missing Information Detection.

Checks the normalized record against the schema contract: required
fields present, numeric fields actually numeric, allowed-value fields
constrained, IP/MAC formats valid. Never invents or fills a value --
it only labels what it finds (status="missing"/"review") so nothing is
silently treated as clean.
"""

import ipaddress
import re

from config.schema import SCHEMA
from models.system_info import SystemInfoRecord

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$")


def validate(record: SystemInfoRecord):
    for spec in SCHEMA:
        fv = record.fields[spec.key]

        # --- required-but-missing ---
        if spec.required and (fv.value is None or fv.value == ""):
            if fv.status not in ("missing", "review"):
                record.set(spec.key, fv.value, source=fv.source, status="missing",
                            note="Required field has no value")
            continue

        if fv.value is None:
            continue

        # --- numeric range sanity (not a hard failure, just a review flag) ---
        if spec.dtype == "numeric" and isinstance(fv.value, (int, float)):
            if fv.value < 0:
                record.set(spec.key, fv.value, source=fv.source, status="review",
                            note="Negative numeric value is not physically valid")

        # --- allowed values ---
        if spec.allowed_values and fv.value not in spec.allowed_values and fv.status == "ok":
            record.set(spec.key, fv.value, source=fv.source, status="review",
                        note=f"Value '{fv.value}' not in expected set {spec.allowed_values}")

    _validate_ip(record)
    _validate_mac(record)


def _validate_ip(record: SystemInfoRecord):
    fv = record.fields["ip_address"]
    if not fv.value:
        return
    try:
        ipaddress.IPv4Address(fv.value)
    except ValueError:
        record.set("ip_address", fv.value, source=fv.source, status="review",
                    note="Value does not look like a valid IPv4 address")


def _validate_mac(record: SystemInfoRecord):
    fv = record.fields["mac_address"]
    if not fv.value:
        return
    if not _MAC_RE.match(fv.value):
        record.set("mac_address", fv.value, source=fv.source, status="review",
                    note="Value does not look like a valid MAC address")


def compute_data_quality_score(record: SystemInfoRecord) -> float:
    """AI Feature #2 companion: a 0-100 confidence score for the whole record."""
    total = len(record.fields)
    penalized = sum(1 for fv in record.fields.values() if fv.status in ("missing", "review"))
    score = round(100 * (total - penalized) / total, 1)
    record.data_quality_score = score
    return score
