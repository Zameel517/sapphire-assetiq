"""
scan_runner.py
==============
One scan from start to finish, shared by every way of running the program:
the window (gui/app.py), the silent AD mode and the console mode (main.py).
Nothing here prints; progress is reported through a callback and the log.
"""

import os
from dataclasses import dataclass

from app_info import APP_NAME, APP_VERSION
from collector_service import run_full_collection
from config.settings import load_config
from utils.paths import bundle_dir, resolve


@dataclass
class ScanOptions:
    config: str | None = None
    company: str | None = None
    location: str | None = None


@dataclass
class RunPlan:
    config_path: str
    config_found: bool
    config: dict
    config_source: str = ""        # "--config", "next to the program", "built into the program"


@dataclass
class ScanResult:
    plan: RunPlan
    record: object = None
    sheets_action: str | None = None        # "inserted" / "updated"
    sheets_error: str | None = None
    format_warning: str | None = None
    layout_change: str | None = None
    spreadsheet_url: str | None = None

    @property
    def saved(self) -> bool:
        return bool(self.sheets_action)

    @property
    def destination(self) -> str:
        if self.sheets_action:
            return f"Saved to the Google Sheet (row {self.sheets_action})."
        if self.sheets_error:
            return "The inventory sheet could not be reached - nothing was saved."
        return "The results could not be saved - see the log file."


def plan_run(options: ScanOptions) -> RunPlan:
    """Find config.json and the Google key. Files placed next to the program win
    over the copies built into a one-file EXE, so either can be updated without
    touching the other."""
    bundled = bundle_dir()
    if options.config:
        config_path, source = os.path.abspath(options.config), "--config"
    else:
        beside = resolve("config.json")
        inside = os.path.join(bundled, "config.json") if bundled else None
        if os.path.exists(beside):
            config_path, source = beside, "next to the program"
        elif inside and os.path.exists(inside):
            config_path, source = inside, "built into the program"
        else:
            config_path, source = beside, "not found"
    config = load_config(config_path)

    key = config["google_credentials_path"]
    candidates = []
    if source != "built into the program":
        candidates.append(resolve(key, base=os.path.dirname(config_path)))
    candidates.append(resolve(key))
    if bundled:
        candidates.append(resolve(key, base=bundled))
    config["google_credentials_path"] = next((c for c in candidates if os.path.exists(c)), candidates[0])

    return RunPlan(config_path, os.path.exists(config_path), config, source)


def run_scan(options: ScanOptions, logger, on_progress=None) -> ScanResult:
    """Collect, check and save one computer's record.

    The Google Sheet is the only destination: nothing is written on the machine
    except the log. A scan that cannot reach the sheet is simply not saved, and
    the next run on that machine tries again.

    on_progress(stage, detail, ok) is called from the scanning thread; stage is
    "connect", "collect" (detail = collector label), "save" or "done"."""
    progress = on_progress or (lambda stage, detail, ok=True: None)
    plan = plan_run(options)
    result = ScanResult(plan=plan)

    logger.info(f"{APP_NAME} v{APP_VERSION} starting scan...")
    if not plan.config_found:
        logger.warning(f"config.json not found at {plan.config_path}; running with built-in defaults.")

    sheets_service, existing_rows = None, None
    progress("connect", "Connecting to Google Sheets", True)
    try:
        from services.sheets_service import SheetsService
        sheets_service = SheetsService(
            credentials_path=plan.config["google_credentials_path"],
            spreadsheet_id=plan.config["google_spreadsheet_id"],
            worksheet_name=plan.config.get("google_worksheet_name", "Inventory"),
        )
        existing_rows = sheets_service.fetch_all_rows()
        result.layout_change = sheets_service.layout_change
        result.spreadsheet_url = sheets_service.url
        logger.info(f"Connected to Google Sheets. {len(existing_rows)} existing row(s) found.")
        if sheets_service.layout_change:
            logger.warning(f"Google Sheets: {sheets_service.layout_change}.")
    except Exception as exc:
        result.sheets_error = str(exc)
        logger.error(f"Could not connect to Google Sheets: {exc}")
        progress("connect", str(exc), False)
        sheets_service = None

    overrides = {"company": options.company, "location": options.location}
    record = run_full_collection(plan.config, overrides, existing_rows, logger,
                                 on_step=lambda label, ok: progress("collect", label, ok))
    result.record = record

    progress("save", "Saving results", True)
    if sheets_service is None:
        logger.error("The inventory sheet could not be reached, so this scan was not saved. "
                     "The next run on this machine will try again.")
    else:
        try:
            result.sheets_action = sheets_service.upsert(record)
            result.format_warning = sheets_service.format_warning
            logger.info(f"Google Sheets: row {result.sheets_action}.")
            if sheets_service.match_note:
                logger.info(f"Google Sheets: {sheets_service.match_note}.")
            if sheets_service.duplicate_rows:
                others = ", ".join(str(r) for r in sheets_service.duplicate_rows)
                logger.warning(f"Google Sheets: this machine also sits in row(s) {others}; "
                               "those are older duplicates and can be deleted.")
            if sheets_service.format_warning:
                logger.warning("Google Sheets: row saved, but styling was skipped "
                               f"({sheets_service.format_warning}).")
            else:
                logger.info("Google Sheets: styling applied.")
        except Exception as exc:
            result.sheets_error = str(exc)
            logger.error(f"Failed to write to Google Sheets: {exc}")
            logger.error("Nothing was saved for this machine; the next run will try again.")

    if record.missing_fields():
        logger.warning(f"Fields needing manual review: {', '.join(record.missing_fields())}")
    logger.info("Scan complete.")
    progress("done", result.destination, result.saved)
    return result

