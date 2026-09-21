"""
system_info.py
===============
The internal data model. This is the "structured model" the project chat
insisted on: raw Python code should never be the data model.

Every field is stored as a FieldValue, which keeps:
  - value       : the final (normalized) value that will be written out
  - raw         : the untouched value exactly as collected
  - source      : where it came from (BIOS / WMI / Registry / Config / etc.)
  - status      : "ok" | "missing" | "review" | "not_applicable"
  - note        : optional human-readable explanation

This means nothing is ever silently dropped, and the AI/intelligence layer
always has the raw value available for reasoning.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from config.schema import FIELD_KEYS


@dataclass
class FieldValue:
    value: Any = None
    raw: Any = None
    source: str = "unknown"
    status: str = "missing"   # ok | missing | review | not_applicable
    note: str = ""

    def to_output(self):
        """What actually gets written to the sheet/JSON/CSV."""
        return self.value if self.status in ("ok", "review") else self.value


@dataclass
class SystemInfoRecord:
    """
    A full 28-field record for one machine.
    Access pattern: record.fields["ram_gb"].value
    """
    fields: dict[str, FieldValue] = field(default_factory=dict)
    collection_log: list[str] = field(default_factory=list)
    ai_flags: list[str] = field(default_factory=list)
    data_quality_score: Optional[float] = None

    def __post_init__(self):
        for key in FIELD_KEYS:
            if key not in self.fields:
                self.fields[key] = FieldValue()

    def set(self, key: str, value: Any, source: str, status: str = "ok",
            raw: Any = None, note: str = ""):
        self.fields[key] = FieldValue(
            value=value, raw=raw if raw is not None else value,
            source=source, status=status, note=note,
        )

    def get(self, key: str) -> Any:
        return self.fields[key].value

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.collection_log.append(f"[{timestamp}] {message}")

    def flag(self, message: str):
        self.ai_flags.append(message)

    def missing_fields(self) -> list[str]:
        return [k for k, v in self.fields.items() if v.status == "missing"]

    def review_fields(self) -> list[str]:
        return [k for k, v in self.fields.items() if v.status == "review"]

    def as_output_row(self) -> dict[str, Any]:
        """key -> final value, ready for the sheet/CSV/JSON writer."""
        return {k: v.to_output() for k, v in self.fields.items()}

    def as_debug_dict(self) -> dict[str, Any]:
        """Full detail (value/raw/source/status) -- useful for logs/JSON."""
        return {
            k: {
                "value": v.value, "raw": v.raw, "source": v.source,
                "status": v.status, "note": v.note,
            }
            for k, v in self.fields.items()
        }
