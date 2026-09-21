"""
sheets_service.py
==================
Replaces "one Excel file per computer" with "one row per computer in a
single central Google Sheet", per the confirmed V1 requirement.

Auth: Google Service Account (recommended -- see README "Google Sheets
Setup"). The service account's JSON key path is read from config/env,
NEVER hard-coded or bundled inside the EXE, per the project chat's
explicit security requirement.

Identity strategy (New-vs-Existing row detection), shared with the Excel
writer and implemented in config/identity.py:
  Asset Tag -> Computer Name -> Serial No -> MAC Address
The first of those fields holding a real (non-"Not Available") value AND
matching an existing row wins, so a machine scanned again updates its own row
instead of adding a second one. This handles the reality that Asset Tag is
often empty (confirmed in the real sample data).

Presentation: every write also restyles the sheet in ONE batch request
(navy header matching the local Excel export, per-column alignment and
number formats, fitted column widths, banded rows, borders, a filter row,
and yellow/red highlighting for values that need a human). Everything is
idempotent -- running the EXE on 500 machines never stacks duplicate
banding or rules -- and a formatting failure never blocks the data row.
"""

import os
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

from config.identity import describe as describe_identity, matching_rows
from config.schema import HEADERS, SCHEMA
from config.presentation import (
    HEADER_BG, HEADER_FG, HEADER_FONT_SIZE, BAND_BG, BORDER, REVIEW_BG, REVIEW_FG,
    MISSING_BG, MISSING_FG, HEADER_HEIGHT_PX, ROW_HEIGHT_PX, MAX_WIDTH_PX,
    MAX_WIDTH_OVERRIDES, NUMBER_PATTERNS, TEXT_KEYS, REVIEW_VALUES,
    fit_width as _fit_width, required_runs as _required_runs,
)
from models.system_info import SystemInfoRecord

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# How the sheet looks lives in config/presentation.py, shared with the Excel export.

# Formulas this program writes, so its own highlight rules can be told apart
# from any a person adds by hand.
_OWN_RULE = re.compile(r'^=(AND\(LEN\([A-Z]+2\)=0,LEN\(\$[A-Z]+2\)>0\)|OR\([A-Z]+2="Unknown",.*\))$')


class SheetsService:
    def __init__(self, credentials_path: str, spreadsheet_id: str, worksheet_name: str = "Inventory"):
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f"Google service-account credentials not found at '{credentials_path}'. "
                "Set GOOGLE_APPLICATION_CREDENTIALS or config.json:'google_credentials_path'."
            )
        creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(spreadsheet_id)
        self._worksheet = self._get_or_create_worksheet(worksheet_name)
        self.url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={self._worksheet.id}"
        self.layout_change: str | None = None
        self.format_warning: str | None = None
        self.match_note: str | None = None          # why this run updated or inserted
        self.duplicate_rows: list[int] = []         # older copies of this machine, if any
        self._ensure_header_row()

    def _get_or_create_worksheet(self, name: str):
        try:
            return self._spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(name, rows=1000, cols=len(HEADERS) + 2)
            return ws

    def _ensure_header_row(self):
        """Make row 1 match schema.py. If the column list has changed, every
        existing row is re-placed BY HEADER NAME, so an added or removed column
        can never leave a value sitting under the wrong header.

        Columns a person added to the sheet by hand (a monitor asset tag, a
        remarks column, ...) are never dropped: they are kept, with their
        values, to the right of the program's own columns."""
        values = self._worksheet.get_all_values()
        current = list(values[0]) if values else []
        while current and current[-1] == "":
            current.pop()
        if current[:len(HEADERS)] == HEADERS:
            return          # layout is current; hand-added columns after it are left alone

        data = values[1:]
        if data and len(set(current) & set(HEADERS)) < len(HEADERS) // 2:
            raise RuntimeError(
                f"Worksheet '{self._worksheet.title}' has {len(data)} row(s) under columns that "
                f"do not match this program's layout; refusing to rewrite it. Point "
                f"google_worksheet_name at the inventory tab or an empty one.")

        extra = [h for h in current if h and h not in HEADERS]
        layout = HEADERS + extra
        width = max(len(layout), max((len(r) for r in values), default=0))
        if self._worksheet.col_count < width:
            self._worksheet.add_cols(width - self._worksheet.col_count)
        pad = [""] * (width - len(layout))
        table = [layout + pad]
        for row in data:
            by_name = dict(zip(current, row))
            table.append([by_name.get(h, "") for h in layout] + pad)
        self._worksheet.update(values=table, range_name="A1", value_input_option="USER_ENTERED")
        self._worksheet.freeze(rows=1)

        if current:
            added = [h for h in HEADERS if h not in current]
            self.layout_change = (f"column layout updated (added: {', '.join(added) or 'none'}; "
                                  f"other columns kept: {', '.join(extra) or 'none'}); "
                                  f"{len(data)} existing row(s) realigned by column name")

    def fetch_all_rows(self) -> list[dict]:
        """Returns all existing rows as header->value dicts (for AI dedupe checks)."""
        return self._worksheet.get_all_records(expected_headers=HEADERS)

    def find_existing_row_index(self, record: SystemInfoRecord, existing_rows: list[dict]) -> int | None:
        """The 1-indexed data row holding this machine (2 = first data row), or
        None if the inventory has never seen it. Matching: config/identity.py."""
        rows, _matched_on = matching_rows(record, existing_rows)
        return rows[0] if rows else None

    def upsert(self, record: SystemInfoRecord) -> str:
        """Adds a new row or updates the existing one. Returns 'inserted' or 'updated'."""
        existing_rows = self.fetch_all_rows()
        rows, matched_on = matching_rows(record, existing_rows)
        row_index = rows[0] if rows else None
        self.duplicate_rows = rows[1:]
        self.match_note = (
            f"matched existing row {row_index} on {matched_on}" if row_index else
            f"no existing row matched ({describe_identity(record)}) in {len(existing_rows)} row(s)")

        now = datetime.now().strftime("%b %d, %Y - %H:%M")
        row_values = self._row_values(record, existing_rows, row_index, now)

        # Style BEFORE writing, so the new cells already carry their text /
        # number formats when the USER_ENTERED value lands in them.
        self.format_warning = None
        try:
            data = self._data_table(existing_rows, row_values, row_index)
            self.apply_formatting(data)
        except Exception as exc:
            # Presentation must never cost a completed scan its data row.
            self.format_warning = f"{exc.__class__.__name__}: {exc}"

        if row_index is None:
            # Look again, right before adding. Collecting and styling take
            # seconds, and another run of this same machine -- someone starting
            # the (windowless) EXE twice, or a logon script firing twice -- can
            # add its row in that time. Updating that row beats a duplicate.
            existing_rows = self.fetch_all_rows()
            rows, matched_on = matching_rows(record, existing_rows)
            if not rows:
                self._worksheet.append_row(row_values, value_input_option="USER_ENTERED")
                return "inserted"
            row_index = rows[0]
            self.duplicate_rows = rows[1:]
            self.match_note = (f"another run added this machine while this scan was running; "
                               f"updated row {row_index} ({matched_on}) instead of adding a second one")
            row_values = self._row_values(record, existing_rows, row_index, now)

        self._worksheet.update(values=[row_values], range_name=f"A{row_index}",
                               value_input_option="USER_ENTERED")
        return "updated"

    @staticmethod
    def _row_values(record: SystemInfoRecord, existing_rows: list[dict],
                    row_index: int | None, now: str) -> list:
        """The row as it will be written; an update keeps the original Created At."""
        if row_index is None:
            record.set("created_at", now, source="system-clock")
            record.set("updated_at", "", source="system-clock")
        else:
            existing_created_at = existing_rows[row_index - 2].get("Created At") or now
            record.set("created_at", existing_created_at, source="preserved-from-existing-row")
            record.set("updated_at", now, source="system-clock")
        return [record.as_output_row()[f.key] for f in SCHEMA]

    # ----------------------------------------------------------------------
    # Presentation
    # ----------------------------------------------------------------------

    def apply_formatting(self, data_rows: list[list[str]]):
        """Restyle the inventory tab in a single batchUpdate request."""
        sheet_id = self._worksheet.id
        n_cols = len(HEADERS)
        last_row = len(data_rows) + 1                 # +1 for the header

        meta = self._spreadsheet.fetch_sheet_metadata(params={
            "fields": "sheets(properties(sheetId,gridProperties),"
                      "bandedRanges(bandedRangeId),conditionalFormats,basicFilter)"
        })
        sheet_meta = next((s for s in meta.get("sheets", [])
                           if s["properties"]["sheetId"] == sheet_id), {})
        grid_rows = sheet_meta.get("properties", {}).get("gridProperties", {}).get("rowCount", last_row)

        requests = []
        requests += self._frame_requests(sheet_id, n_cols, last_row, max(grid_rows, last_row))
        requests += self._column_requests(sheet_id, data_rows)
        requests += self._banding_requests(sheet_id, n_cols, sheet_meta)
        requests += self._highlight_requests(sheet_id, sheet_meta)
        current_filter = (sheet_meta.get("basicFilter") or {}).get("range") or {}
        if (current_filter.get("startColumnIndex", 0), current_filter.get("endColumnIndex")) != (0, n_cols):
            # No filter yet, or one sized for an older column list.
            requests.append({"setBasicFilter": {"filter": {"range": {
                "sheetId": sheet_id, "startRowIndex": 0,
                "startColumnIndex": 0, "endColumnIndex": n_cols}}}})

        self._spreadsheet.batch_update({"requests": requests})

    @staticmethod
    def _data_table(existing_rows, row_values, row_index) -> list[list[str]]:
        """All data rows as they will look after this write (for fitting widths)."""
        rows = [["" if r.get(h) is None else str(r.get(h)) for h in HEADERS] for r in existing_rows]
        new = ["" if v is None else str(v) for v in row_values]
        if row_index is None:
            rows.append(new)
        else:
            rows[row_index - 2] = new
        return rows

    def _frame_requests(self, sheet_id, n_cols, last_row, grid_rows):
        header_range = {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                        "startColumnIndex": 0, "endColumnIndex": n_cols}
        line = {"style": "SOLID", "color": _rgb(BORDER)}
        return [
            {"updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"}},
            {"repeatCell": {
                "range": header_range,
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _rgb(HEADER_BG),
                    "textFormat": {"foregroundColor": _rgb(HEADER_FG), "bold": True, "fontSize": HEADER_FONT_SIZE},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "wrapStrategy": "WRAP",
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,"
                          "verticalAlignment,wrapStrategy)"}},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": HEADER_HEIGHT_PX}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": grid_rows},
                "properties": {"pixelSize": ROW_HEIGHT_PX}, "fields": "pixelSize"}},
            {"updateBorders": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": last_row,
                          "startColumnIndex": 0, "endColumnIndex": n_cols},
                "top": line, "bottom": line, "left": line, "right": line,
                "innerHorizontal": line, "innerVertical": line}},
        ]

    def _column_requests(self, sheet_id, data_rows):
        requests = []
        for idx, spec in enumerate(SCHEMA):
            fmt = {
                "horizontalAlignment": "CENTER",     # every data cell sits centred under its header
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "CLIP",
            }
            if spec.key in NUMBER_PATTERNS:
                fmt["numberFormat"] = {"type": "NUMBER", "pattern": NUMBER_PATTERNS[spec.key]}
            elif spec.key in TEXT_KEYS:
                fmt["numberFormat"] = {"type": "TEXT"}
            requests.append({"repeatCell": {
                # No endRowIndex: the format covers every future row too.
                "range": {"sheetId": sheet_id, "startRowIndex": 1,
                          "startColumnIndex": idx, "endColumnIndex": idx + 1},
                "cell": {"userEnteredFormat": fmt},
                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,"
                          "wrapStrategy,numberFormat)"}})
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                          "startIndex": idx, "endIndex": idx + 1},
                "properties": {"pixelSize": _fit_width(
                    spec.header, [r[idx] for r in data_rows],
                    MAX_WIDTH_OVERRIDES.get(spec.key, MAX_WIDTH_PX))},
                "fields": "pixelSize"}})
        return requests

    @staticmethod
    def _banding_requests(sheet_id, n_cols, sheet_meta):
        props = {"headerColor": _rgb(HEADER_BG),
                 "firstBandColor": _rgb("FFFFFF"),
                 "secondBandColor": _rgb(BAND_BG)}
        rng = {"sheetId": sheet_id, "startRowIndex": 0,
               "startColumnIndex": 0, "endColumnIndex": n_cols}
        existing = sheet_meta.get("bandedRanges") or []
        if existing:
            # Adding banding over banding is an API error -- update ours instead,
            # including its width, so newly added columns are shaded too.
            return [{"updateBanding": {
                "bandedRange": {"bandedRangeId": existing[0]["bandedRangeId"],
                                "range": rng, "rowProperties": props},
                "fields": "range,rowProperties"}}]
        return [{"addBanding": {"bandedRange": {"range": rng, "rowProperties": props}}}]

    @staticmethod
    def _highlight_requests(sheet_id, sheet_meta):
        """Yellow for placeholder values, red for blank required cells.

        Rules are keyed by formula AND column span. When the column list changes,
        this program's own out-of-date rules are deleted and rebuilt; rules a
        person added by hand never match that pattern and are left alone."""
        wanted = []
        first = _col_letter(0)
        review = "=OR(" + ",".join(f'{first}2="{v}"' for v in REVIEW_VALUES) + ")"
        wanted.append((review, ((0, len(HEADERS)),), REVIEW_BG, REVIEW_FG))

        # Only flag a blank cell on a row that actually holds a machine,
        # otherwise the ~1000 empty rows below the data would all turn red.
        anchor = _col_letter(next(i for i, s in enumerate(SCHEMA) if s.key == "computer_name"))
        for start, end in _required_runs():
            formula = f"=AND(LEN({_col_letter(start)}2)=0,LEN(${anchor}2)>0)"
            wanted.append((formula, ((start, end),), MISSING_BG, MISSING_FG))
        wanted_keys = {(formula, spans) for formula, spans, _, _ in wanted}

        requests, present = [], set()
        existing = sheet_meta.get("conditionalFormats") or []
        for index in range(len(existing) - 1, -1, -1):   # high -> low keeps indexes valid
            rule = existing[index]
            values = rule.get("booleanRule", {}).get("condition", {}).get("values", [])
            formula = values[0].get("userEnteredValue", "") if values else ""
            if not _OWN_RULE.match(formula):
                continue                                  # someone's own rule: leave it
            spans = tuple((r.get("startColumnIndex", 0), r.get("endColumnIndex"))
                          for r in rule.get("ranges", []))
            key = (formula, spans)
            if key in wanted_keys and key not in present:
                present.add(key)
            else:
                requests.append({"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": index}})

        for formula, spans, bg, fg in wanted:
            if (formula, spans) in present:
                continue
            requests.append({"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [{"sheetId": sheet_id, "startRowIndex": 1,
                            "startColumnIndex": s, "endColumnIndex": e} for s, e in spans],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA",
                                  "values": [{"userEnteredValue": formula}]},
                    "format": {"backgroundColor": _rgb(bg),
                               "textFormat": {"foregroundColor": _rgb(fg)}}}}}})
        return requests


def _rgb(hex_color: str) -> dict:
    return {"red": int(hex_color[0:2], 16) / 255,
            "green": int(hex_color[2:4], 16) / 255,
            "blue": int(hex_color[4:6], 16) / 255}


def _col_letter(index: int) -> str:
    return re.sub(r"\d+$", "", rowcol_to_a1(1, index + 1))
