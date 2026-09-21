"""
app.py
======
The program's own window: a dark sidebar with this computer's identity and an
animated data-quality ring, a live timeline of the scan, and every collected
field grouped into cards -- with Review / Missing badges that mean the same as
the yellow / red highlighting in the Excel file and the inventory sheet.

It deliberately never shows where the inventory is kept: access to it is given
to IT admins separately.
"""

import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

from app_info import APP_NAME, APP_VERSION
from collector_service import STEP_LABELS
from config.schema import SCHEMA
from gui import theme
from gui.icon import png_base64
from gui.widgets import Badge, Card, PillButton, ScrollArea, Sidebar, StepTimeline
from scan_runner import plan_run, run_scan
from utils.logger import get_logger
from utils.paths import log_dir

GROUPS = [
    ("Identity", "people", ["company", "location", "asset_tag", "computer_name", "domain_name", "current_user"]),
    ("Device", "laptop", ["device_type", "manufacturer", "system_model", "serial_no", "os_version"]),
    ("Processor & memory", "chip", ["cpu", "ram_gb", "ram_slots"]),
    ("Storage", "storage", ["disk_gb", "disk_type", "disk_count"]),
    ("Displays", "monitor", ["display_size", "display_count", "external_displays"]),
    ("Network", "network", ["ip_address", "subnet", "mac_address", "vpn"]),
    ("Email & security", "shield", ["outlook_email", "antivirus"]),
    ("Record", "clock", ["created_at", "updated_at"]),
]
HEADERS = {spec.key: spec.header for spec in SCHEMA}
LABELS = {"os_version": "Operating system", "ram_gb": "RAM", "disk_gb": "Disk size",
          "display_size": "Screen size", "created_at": "First scanned", "updated_at": "Last updated"}
UNITS = {"ram_gb": " GB", "disk_gb": " GB", "display_size": "\""}
DEVICE_GLYPHS = {"Laptop": "laptop", "Desktop": "desktop", "Tablet": "tablet", "Server": "desktop"}


def launch(options) -> int | None:
    """Open the window and run until it is closed. Returns None when there is
    no desktop to draw on (a service session, say), so the caller can fall back
    to a silent scan."""
    _enable_dpi_awareness()
    try:
        root = tk.Tk()
    except tk.TclError:
        return None
    FetcherWindow(root, options)
    root.mainloop()
    return 0


def _enable_dpi_awareness():
    """Sharp text on high-DPI screens instead of Windows' blurry bitmap scaling."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _short(label: str) -> str:
    return label.replace(" info", "").replace("/email", "").replace("System/OS", "System")


def _display(key: str, value) -> str:
    if value is None or value == "":
        return ""
    text = str(value).replace("Microsoft ", "") if key == "os_version" else str(value)
    return f"{text}{UNITS.get(key, '')}"


class FieldRow:
    """One field in a card: label, value and a Review / Missing badge."""

    def __init__(self, parent, fonts, key, row):
        px = fonts.px
        self.label = tk.Label(parent, text=LABELS.get(key, HEADERS[key]), font=fonts.small,
                              fg=theme.INK_SOFT, bg=theme.CARD, anchor="w")
        self.value = tk.Label(parent, font=fonts.body, bg=theme.CARD, anchor="w", justify="left")
        self.badge = Badge(parent, fonts)
        self.label.grid(row=row, column=0, sticky="nw", pady=px(5), padx=(0, px(14)))
        self.value.grid(row=row, column=1, sticky="nw", pady=px(5))
        self.badge.grid(row=row, column=2, sticky="ne", pady=px(4), padx=(px(8), 0))
        self.reset()

    def reset(self):
        self.value.configure(text="...", fg=theme.MUTED)
        self.badge.clear()

    def show(self, text, status):
        self.value.configure(text=text or "Not available", fg=theme.INK if text else theme.MUTED)
        if status == "review":
            self.badge.show("Review", theme.REVIEW_FILL, theme.REVIEW_TEXT)
        elif status == "missing":
            self.badge.show("Missing", theme.MISSING_FILL, theme.MISSING_TEXT)
        else:
            self.badge.clear()


class FetcherWindow:
    def __init__(self, root: tk.Tk, options):
        self.root, self.options = root, options
        self.fonts = theme.Fonts(root)
        self.plan = plan_run(options)
        self.events: queue.Queue = queue.Queue()
        self.result, self.scanning, self.scan_id = None, False, 0
        self.started = datetime.now()
        self.check_labels = []

        px = self.fonts.px
        root.title(f"{APP_NAME}  v{APP_VERSION}")
        width = min(px(1240), root.winfo_screenwidth() - px(40))
        height = min(px(820), root.winfo_screenheight() - px(80))
        root.geometry(f"{width}x{height}+{max(0, (root.winfo_screenwidth() - width) // 2)}"
                      f"+{max(0, (root.winfo_screenheight() - height) // 2 - px(20))}")
        root.minsize(min(px(980), width), min(px(620), height))
        root.configure(bg=theme.PAGE)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._set_window_icon()
        self._build()
        root.after(400, self.start_scan)
        root.after(80, self._drain_events)

    # ------------------------------------------------------------------ layout
    def _set_window_icon(self):
        try:
            self._icons = [tk.PhotoImage(data=png_base64(size)) for size in (32, 48)]
            self.root.iconphoto(True, *self._icons)
        except tk.TclError:
            pass

    def _build(self):
        f, px = self.fonts, self.fonts.px
        hint = "Results are sent to your IT department's inventory."
        self.sidebar = Sidebar(self.root, f, hint)
        self.sidebar.pack(side="left", fill="y")

        main = tk.Frame(self.root, bg=theme.PAGE)
        main.pack(side="left", fill="both", expand=True)

        header = tk.Frame(main, bg=theme.PAGE)
        header.pack(fill="x", padx=px(32), pady=(px(22), px(6)))
        self.headline = tk.Label(header, font=f.hero, fg=theme.INK, bg=theme.PAGE, anchor="w")
        self.headline.pack(fill="x")
        self.subline = tk.Label(header, font=f.body, fg=theme.INK_SOFT, bg=theme.PAGE, anchor="w", justify="left")
        self.subline.pack(fill="x", pady=(px(2), 0))

        footer = tk.Frame(main, bg=theme.PAGE)
        footer.pack(side="bottom", fill="x", padx=px(32), pady=(px(10), px(18)))
        self.close_button = PillButton(footer, f, "Close", self.close, style="ghost")
        self.close_button.pack(side="right")
        self.scan_button = PillButton(footer, f, "Scan again", self.start_scan, glyph=f.glyph("refresh"),
                                      style="primary")
        self.scan_button.pack(side="right", padx=(0, px(10)))
        self.copy_button = PillButton(footer, f, "Copy details", self.copy_results, glyph=f.glyph("copy"))
        self.copy_button.pack(side="right", padx=(0, px(10)))
        self.footnote = tk.Label(footer, font=f.small, fg=theme.MUTED, bg=theme.PAGE, anchor="w")
        self.footnote.pack(side="left")

        timeline_card = Card(main, f)
        timeline_card.pack(fill="x", padx=px(26), pady=(px(6), px(2)))
        self.timeline = StepTimeline(timeline_card.body, f, [_short(label) for label in STEP_LABELS])
        self.timeline.pack(fill="x")

        self.scroll = ScrollArea(main)
        self.scroll.pack(fill="both", expand=True, padx=(px(26), px(12)), pady=(px(4), 0))
        grid = self.scroll.inner
        grid.grid_columnconfigure(0, weight=1, uniform="cards")
        grid.grid_columnconfigure(1, weight=1, uniform="cards")

        checks = Card(grid, f)
        checks.grid(row=0, column=0, columnspan=2, sticky="ew", padx=px(6), pady=px(6))
        self.checks_body = self._section(checks, "pulse", "Checks")
        self.checks_body.bind("<Configure>", lambda e: self._wrap_checks(e.width))

        self.rows = {}
        for i, (title, glyph, keys) in enumerate(GROUPS):
            card = Card(grid, f)
            card.grid(row=1 + i // 2, column=i % 2, sticky="new", padx=px(6), pady=px(6))
            fields = self._section(card, glyph, title)
            fields.grid_columnconfigure(1, weight=1)
            for row, key in enumerate(keys):
                self.rows[key] = FieldRow(fields, f, key, row)
            fields.bind("<Configure>", lambda e, k=keys: self._rewrap(k, e.width))

    def _section(self, card, glyph, title):
        f, px = self.fonts, self.fonts.px
        head = tk.Frame(card.body, bg=theme.CARD)
        head.pack(fill="x")
        if f.glyph(glyph):
            tk.Label(head, text=f.glyph(glyph), font=f.icon(14), fg=theme.ACCENT, bg=theme.CARD).pack(
                side="left", padx=(0, px(10)))
        tk.Label(head, text=title, font=f.card_title, fg=theme.INK, bg=theme.CARD).pack(side="left")
        tk.Frame(card.body, bg=theme.LINE, height=1).pack(fill="x", pady=(px(10), px(6)))
        body = tk.Frame(card.body, bg=theme.CARD)
        body.pack(fill="x")
        return body

    def _rewrap(self, keys, width):
        px = self.fonts.px
        for key in keys:
            row = self.rows[key]
            row.value.configure(wraplength=max(px(120), width - row.label.winfo_reqwidth() - px(110)))

    def _wrap_checks(self, width):
        for label in self.check_labels:
            label.configure(wraplength=max(self.fonts.px(200), width - self.fonts.px(40)))

    # -------------------------------------------------------------------- scan
    def start_scan(self):
        if self.scanning:
            return
        self.scanning, self.result = True, None
        self.scan_id += 1
        self.started = datetime.now()
        self.plan = plan_run(self.options)
        self.timeline.reset()
        self.sidebar.start_scan()
        self.headline.configure(text="Scanning this computer", fg=theme.INK)
        self.subline.configure(text="Reading system details. This usually takes under a minute.", fg=theme.INK_SOFT)
        self.footnote.configure(text="")
        for row in self.rows.values():
            row.reset()
        self._show_checks(None)
        self.scan_button.set_enabled(False)
        self.copy_button.set_enabled(False)
        self.scroll.to_top()
        threading.Thread(target=self._scan_worker, args=(self.scan_id,), daemon=True).start()

    def _scan_worker(self, scan_id):
        """Runs off the UI thread and talks to the window only through the queue."""
        try:
            logger = get_logger(log_dir=log_dir())
            result = run_scan(self.options, logger,
                              on_progress=lambda stage, detail, ok=True:
                              self.events.put(("progress", scan_id, stage, detail, ok)))
            self.events.put(("finished", scan_id, result))
        except Exception as exc:
            self.events.put(("crashed", scan_id, exc))

    def _drain_events(self):
        try:
            while True:
                kind, scan_id, *payload = self.events.get_nowait()
                if scan_id == self.scan_id:
                    getattr(self, f"_on_{kind}")(*payload)
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    def _on_progress(self, stage, detail, ok):
        if stage == "connect":
            if ok:
                self.subline.configure(text="Connecting to the IT inventory...", fg=theme.INK_SOFT)
            else:
                self.subline.configure(text="The IT inventory can't be reached right now - "
                                            "this scan cannot be saved.", fg=theme.REVIEW_TEXT)
        elif stage == "collect":
            self.timeline.mark(_short(detail), ok)
            upcoming = self.timeline.running_label()
            text = f"Reading {upcoming.lower()} details..." if upcoming else "Checking the results..."
            self.subline.configure(text=text, fg=theme.INK_SOFT)
        elif stage == "save":
            self.subline.configure(text="Saving results...", fg=theme.INK_SOFT)

    def _on_finished(self, result):
        self.result, self.scanning = result, False
        record = result.record
        self.timeline.finish()

        statuses = [fv.status for fv in record.fields.values()]
        review, missing = statuses.count("review"), statuses.count("missing")
        maker, product = (str(record.get(k) or "").replace("Not Available", "") for k in ("manufacturer", "system_model"))
        # Many makers repeat their name in the model ("HP 348 G4"): don't print "HP HP 348 G4".
        model = product if maker and product.lower().startswith(maker.lower()) else " ".join(p for p in (maker, product) if p)
        self.sidebar.finish(quality=record.data_quality_score or 0, ok=len(statuses) - review - missing,
                            review=review, missing=missing,
                            glyph=DEVICE_GLYPHS.get(record.get("device_type"), "system"),
                            model=model or "Model not reported",
                            os_name=_display("os_version", record.get("os_version")))

        if result.sheets_action:
            headline, detail, colour = "Scan complete", "Sent to your IT department's inventory.", theme.GOOD
        else:
            headline, detail, colour = ("Scan finished, but nothing was saved",
                                        "The IT inventory couldn't be reached - details are in the log file.",
                                        theme.BAD)
        self.headline.configure(text=headline, fg=theme.INK if result.saved else theme.BAD)
        self.subline.configure(text=f"{detail}   \u00b7   {datetime.now():%d %b %Y, %H:%M}", fg=colour)
        self.footnote.configure(text=f"Scanned in {(datetime.now() - self.started).total_seconds():.0f} seconds")

        self._show_checks(record.ai_flags)
        self._reveal(record, [key for _, _, keys in GROUPS for key in keys], 0, self.scan_id)
        self.scan_button.set_enabled(True)
        self.copy_button.set_enabled(True)

    def _on_crashed(self, exc):
        self.scanning = False
        self.sidebar.stop()
        self.timeline.fail_running()
        self.headline.configure(text="The scan stopped because of an error", fg=theme.BAD)
        self.subline.configure(text=f"{exc.__class__.__name__}: {exc}", fg=theme.BAD)
        self.scan_button.set_enabled(True)
        messagebox.showerror(APP_NAME, f"The scan stopped because of an error:\n\n{exc}\n\n"
                                       f"Details are in the log folder:\n{log_dir()}")

    def _reveal(self, record, keys, index, scan_id):
        """Fill the cards one field at a time, for a gentle cascade."""
        if scan_id != self.scan_id or index >= len(keys):
            return
        key = keys[index]
        fv = record.fields[key]
        self.rows[key].show(_display(key, fv.value), fv.status)
        self.root.after(22, lambda: self._reveal(record, keys, index + 1, scan_id))

    def _show_checks(self, flags):
        f, px = self.fonts, self.fonts.px
        for child in self.checks_body.winfo_children():
            child.destroy()
        self.check_labels = []
        if flags is None:
            items = [("info", theme.MUTED, theme.MUTED, "Consistency checks run when the scan finishes.")]
        elif flags:
            items = [("warning", theme.REVIEW_TEXT, theme.INK, flag) for flag in flags]
        else:
            items = [("check", theme.GOOD, theme.INK,
                      "Everything looks consistent - no conflicts found in the collected details.")]
        for glyph, glyph_colour, text_colour, text in items:
            line = tk.Frame(self.checks_body, bg=theme.CARD)
            line.pack(fill="x", pady=px(3))
            if f.glyph(glyph):
                tk.Label(line, text=f.glyph(glyph), font=f.icon(11), fg=glyph_colour, bg=theme.CARD).pack(
                    side="left", anchor="n", padx=(0, px(10)), pady=(px(2), 0))
            label = tk.Label(line, text=text, font=f.body, fg=text_colour, bg=theme.CARD, anchor="w",
                             justify="left", wraplength=px(760))
            label.pack(side="left", fill="x")
            self.check_labels.append(label)
        self._wrap_checks(self.checks_body.winfo_width())

    # ----------------------------------------------------------------- buttons
    def copy_results(self):
        if not self.result:
            return
        record = self.result.record
        lines = []
        for spec in SCHEMA:
            value = record.fields[spec.key].value
            lines.append(f"{spec.header}: {'' if value is None else value}")
        lines.append(f"Data Quality Score: {record.data_quality_score}%")
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        self.footnote.configure(text="Details copied to the clipboard", fg=theme.GOOD)
        self.root.after(2500, lambda: self.footnote.configure(fg=theme.MUTED))

    def close(self):
        if self.scanning and not messagebox.askyesno(APP_NAME, "A scan is still running. Close anyway?"):
            return
        self.root.destroy()
