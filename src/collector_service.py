"""
collector_service.py
=====================
The orchestrator. Runs every collector, then normalization, validation,
and the AI/intelligence layer, in the exact order confirmed in the
project chat:

  Collect -> Normalize -> Validate -> AI/Intelligence -> Final Record

Error-handling rule (from the project chat, non-negotiable): one
collector failing must NEVER crash the whole scan. Every collector call
is wrapped so a single bad field degrades to "missing", not a crash.
"""

from collectors import (
    system_collector, hardware_collector, storage_collector,
    network_collector, display_collector, security_collector,
    outlook_collector, organization_collector,
)
from models.system_info import SystemInfoRecord
from services import normalization_service, validation_service, intelligence_service
from utils.wmi_utils import com_session


# The order and names of the collection steps, shown as progress in the window.
STEP_LABELS = ("System/OS info", "Hardware info", "Storage info", "Network info",
               "Display info", "Security info", "Outlook/email info", "Organization info")


def run_full_collection(config: dict, cli_overrides: dict | None = None,
                         existing_rows: list[dict] | None = None,
                         logger=None, on_step=None) -> SystemInfoRecord:
    """on_step(label, succeeded) is called after each collector, for progress displays."""
    record = SystemInfoRecord()

    steps = [
        ("System/OS info", lambda: system_collector.collect(record)),
        ("Hardware info", lambda: hardware_collector.collect(record)),
        ("Storage info", lambda: storage_collector.collect(record)),
        ("Network info", lambda: network_collector.collect(record)),
        ("Display info", lambda: display_collector.collect(record)),
        ("Security info", lambda: security_collector.collect(record)),
        ("Outlook/email info", lambda: outlook_collector.collect(record)),
        ("Organization info", lambda: organization_collector.collect(record, config, cli_overrides)),
    ]

    # Every collector runs inside one COM session on this thread (see wmi_utils).
    with com_session():
        for label, step_fn in steps:
            succeeded = True
            try:
                step_fn()
                record.log(f"SUCCESS  {label} collected")
            except Exception as exc:
                succeeded = False
                record.log(f"FAILURE  {label} raised {exc.__class__.__name__}: {exc}")
            if logger:
                logger.info(record.collection_log[-1])
            if on_step:
                on_step(label, succeeded)

    # --- Normalize ---
    try:
        normalization_service.normalize(record)
        record.log("SUCCESS  Normalization complete")
    except Exception as exc:
        record.log(f"FAILURE  Normalization raised {exc.__class__.__name__}: {exc}")

    # --- Validate ---
    try:
        validation_service.validate(record)
        validation_service.compute_data_quality_score(record)
        record.log(f"SUCCESS  Validation complete (score={record.data_quality_score}%)")
    except Exception as exc:
        record.log(f"FAILURE  Validation raised {exc.__class__.__name__}: {exc}")

    # --- AI / Intelligence layer ---
    try:
        intelligence_service.run_intelligence_layer(record, existing_rows)
        record.log(f"SUCCESS  AI/Intelligence layer complete ({len(record.ai_flags)} flag(s))")
    except Exception as exc:
        record.log(f"FAILURE  AI/Intelligence layer raised {exc.__class__.__name__}: {exc}")

    return record
