"""
widgets.py
==========
Custom-drawn parts of the window -- rounded cards, pill buttons and badges, the
step timeline, the scrolling area and the dark sidebar -- built on plain
Tkinter canvases, so the program needs no extra UI library.
"""

import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from app_info import APP_VERSION
from gui import theme
from gui.icon import png_base64


def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=16, **kw)



class Card(tk.Canvas):
    """A white rounded card with a soft shadow; widgets go inside `.body`."""

    def __init__(self, parent, fonts):
        super().__init__(parent, bg=theme.PAGE, highlightthickness=0, bd=0, height=fonts.px(60))
        self.radius, self.pad = fonts.px(16), fonts.px(18)
        self.body = tk.Frame(self, bg=theme.CARD)
        self._window = self.create_window(self.pad, self.pad, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _e: self._fit())
        self.bind("<Configure>", lambda _e: self._redraw())

    def _fit(self):
        wanted = self.body.winfo_reqheight() + 2 * self.pad + 6
        if int(float(self.cget("height"))) != wanted:
            self.configure(height=wanted)
        self._redraw()

    def _redraw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 40 or h < 20:
            return
        self.delete("shape")
        rounded_rect(self, 2, 5, w - 1, h - 1, self.radius, fill=theme.SHADOW, outline="", tags="shape")
        rounded_rect(self, 1, 1, w - 3, h - 5, self.radius, fill=theme.CARD, outline=theme.CARD_BORDER, tags="shape")
        self.tag_lower("shape")
        self.itemconfigure(self._window, width=max(20, w - 2 * self.pad - 3))


class PillButton(tk.Canvas):
    """A rounded button with hover feedback, an optional icon and a disabled state."""

    STYLES = {   # fill, hover fill, text, border
        "primary": (theme.ACCENT, theme.ACCENT_HOVER, "#FFFFFF", None),
        "secondary": (theme.CARD, theme.ACCENT_SOFT, theme.INK, theme.CARD_BORDER),
        "ghost": (theme.PAGE, theme.GHOST_HOVER, theme.INK_SOFT, None),
    }

    def __init__(self, parent, fonts, text, command, glyph="", style="secondary"):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0, cursor="hand2")
        self.fonts, self.text, self.command, self.glyph, self.style = fonts, text, command, glyph, style
        self.enabled, self.hover = True, False
        self._measure = tkfont.Font(font=fonts.body_bold)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def _set_hover(self, hover: bool):
        self.hover = hover
        self._draw()

    def _release(self, event):
        if self.enabled and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.command()

    def _draw(self):
        px = self.fonts.px
        fill, hover_fill, fg, border = self.STYLES[self.style]
        if not self.enabled:
            fill, fg = (theme.LINE, theme.MUTED) if self.style == "primary" else (fill, theme.MUTED)
        elif self.hover:
            fill = hover_fill
        icon_width = px(24) if self.glyph else 0
        width, height = px(22) * 2 + icon_width + self._measure.measure(self.text), px(42)
        self.configure(width=width, height=height)
        self.delete("all")
        rounded_rect(self, 1, 1, width - 1, height - 1, height / 2, fill=fill, outline=border or fill)
        x = px(22)
        if self.glyph:
            self.create_text(x + px(8), height / 2, text=self.glyph, font=self.fonts.icon(11), fill=fg)
            x += icon_width
        self.create_text(x, height / 2, text=self.text, font=self.fonts.body_bold, fill=fg, anchor="w")


class Badge(tk.Canvas):
    """A small rounded status pill such as 'Review' or 'Missing'."""

    def __init__(self, parent, fonts):
        super().__init__(parent, bg=theme.CARD, highlightthickness=0, bd=0, width=1, height=fonts.px(22))
        self.fonts = fonts
        self._measure = tkfont.Font(font=fonts.tiny_bold)

    def show(self, text, fill, fg):
        px = self.fonts.px
        w, h = self._measure.measure(text) + px(20), px(22)
        self.configure(width=w)
        self.delete("all")
        rounded_rect(self, 0, 1, w, h - 1, (h - 2) / 2, fill=fill, outline="")
        self.create_text(w / 2, h / 2, text=text, font=self.fonts.tiny_bold, fill=fg)

    def clear(self):
        self.configure(width=1)
        self.delete("all")


class StepTimeline(tk.Canvas):
    """The scan's steps as connected nodes: waiting, running (pulsing), done or failed."""

    def __init__(self, parent, fonts, labels):
        super().__init__(parent, bg=theme.CARD, highlightthickness=0, bd=0, height=fonts.px(70))
        self.fonts, self.labels = fonts, list(labels)
        self.states = ["waiting"] * len(self.labels)
        self._pulse = 0
        self.bind("<Configure>", lambda _e: self._draw())
        self.after(60, self._tick)

    def reset(self):
        self.states = ["running"] + ["waiting"] * (len(self.labels) - 1)
        self._draw()

    def mark(self, label, ok):
        if label not in self.labels:
            return
        i = self.labels.index(label)
        self.states[i] = "done" if ok else "failed"
        if i + 1 < len(self.states) and self.states[i + 1] == "waiting":
            self.states[i + 1] = "running"
        self._draw()

    def running_label(self):
        return next((label for label, state in zip(self.labels, self.states) if state == "running"), None)

    def finish(self):
        self.states = [state if state in ("done", "failed") else "done" for state in self.states]
        self._draw()

    def fail_running(self):
        self.states = ["failed" if state == "running" else state for state in self.states]
        self._draw()

    def _tick(self):
        self._pulse = (self._pulse + 1) % 24
        if "running" in self.states:
            self._draw()
        self.after(60, self._tick)

    def _draw(self):
        w = self.winfo_width()
        if w < 60:
            return
        px, f = self.fonts.px, self.fonts
        self.delete("all")
        n, margin, y, node = len(self.labels), px(40), px(22), px(11)
        xs = [margin + i * (w - 2 * margin) / (n - 1) for i in range(n)]
        for i in range(n - 1):
            colour = theme.GOOD if self.states[i] == "done" else theme.LINE
            self.create_line(xs[i] + node + px(4), y, xs[i + 1] - node - px(4), y, fill=colour, width=px(3), capstyle="round")
        for x, label, state in zip(xs, self.labels, self.states):
            mark = None
            if state == "done":
                fill, outline, mark = theme.GOOD, theme.GOOD, "check"
            elif state == "failed":
                fill, outline, mark = theme.BAD, theme.BAD, "cross"
            elif state == "running":
                glow = node + px(3) + px(5) * abs(12 - self._pulse) / 12
                self.create_oval(x - glow, y - glow, x + glow, y + glow, fill=theme.ACCENT_SOFT, outline="")
                fill, outline = theme.ACCENT, theme.ACCENT
            else:
                fill, outline = theme.CARD, theme.LINE
            self.create_oval(x - node, y - node, x + node, y + node, fill=fill, outline=outline, width=px(2))
            if mark:
                glyph = f.glyph(mark)
                self.create_text(x, y, text=glyph or ("\u2713" if mark == "check" else "\u2715"),
                                 font=f.icon(9) if glyph else f.small_bold, fill="#FFFFFF")
            colour = theme.BAD if state == "failed" else (theme.INK if state in ("done", "running") else theme.MUTED)
            self.create_text(x, y + px(27), text=label, font=f.small_bold if state == "running" else f.small, fill=colour)


class ScrollArea(tk.Frame):
    """A vertically scrolling area; widgets go inside `.inner`."""

    def __init__(self, parent):
        super().__init__(parent, bg=theme.PAGE)
        self.canvas = tk.Canvas(self, bg=theme.PAGE, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=theme.PAGE)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self:
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
                return
            widget = widget.master

    def to_top(self):
        self.canvas.yview_moveto(0)


class Sidebar(tk.Canvas):
    """The dark panel on the left: brand, this computer, the data-quality ring and counts."""

    def __init__(self, parent, fonts, hint):
        super().__init__(parent, width=fonts.px(300), bg=theme.NAVY, highlightthickness=0, bd=0)
        self.fonts, self.hint = fonts, hint
        self.name = os.environ.get("COMPUTERNAME", "This computer")
        self.model, self.os_name, self.device_glyph = "Reading hardware details...", "", "system"
        self.scanning, self.spin = False, 0
        self.quality = self.target = None
        self.counts = None
        self.logo, self.logo_width = None, 0      # the mark, rebuilt only when its size changes
        self.bind("<Configure>", lambda _e: self._draw())
        self.after(33, self._tick)

    def start_scan(self):
        self.scanning, self.quality, self.target, self.counts = True, None, None, None
        self.model, self.os_name, self.device_glyph = "Reading hardware details...", "", "system"
        self._refresh()

    def finish(self, quality, ok, review, missing, glyph, model, os_name):
        self.scanning = False
        self.quality, self.target = 0.0, float(quality)
        self.counts = (ok, review, missing)
        self.device_glyph, self.model, self.os_name = glyph, model, os_name
        self._refresh()

    def stop(self):
        self.scanning = False
        self._refresh()

    def _tick(self):
        if self.scanning:
            self.spin = (self.spin + 1) % 60
            self._refresh()
        elif self.target is not None and self.quality is not None and self.quality != self.target:
            self.quality += (self.target - self.quality) * 0.12
            if abs(self.target - self.quality) < 0.3:
                self.quality = self.target
            self._refresh()
        self.after(33, self._tick)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50:
            return
        px = self.fonts.px
        bands = 48
        for i in range(bands):
            colour = theme.mix(theme.NAVY, theme.NAVY_LIGHT, i / (bands - 1))
            self.create_rectangle(0, h * i / bands, w, h * (i + 1) / bands + 1, fill=colour, outline="")
        self.create_oval(w - px(130), -px(120), w + px(150), px(150), outline="",
                         fill=theme.mix(theme.NAVY, "#FFFFFF", 0.035))
        self.create_oval(-px(150), h - px(230), px(170), h + px(90), outline="",
                         fill=theme.mix(theme.NAVY_LIGHT, "#FFFFFF", 0.05))
        self._draw_logo(px)
        self.create_text(px(80), px(60), text="AssetIQ", font=self.fonts.small,
                         fill=theme.ON_NAVY_SOFT, anchor="w")
        self.create_line(px(26), px(96), w - px(26), px(96), fill=theme.mix(theme.NAVY, "#FFFFFF", 0.14))
        self._refresh()

    def _draw_logo(self, px):
        """The mark (gui/icon.py) beside the product name."""
        size = px(44)
        if self.logo is None or self.logo_width != size:
            try:
                self.logo, self.logo_width = tk.PhotoImage(data=png_base64(size)), size
            except tk.TclError:
                self.logo = None
        if self.logo is not None:
            self.create_image(px(24), px(22), image=self.logo, anchor="nw")
        self.create_text(px(80), px(38), text="SAPPHIRE", font=self.fonts.brand,
                         fill=theme.ON_NAVY, anchor="w")

    def _refresh(self):
        self.delete("dyn")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50:
            return
        px, f = self.fonts.px, self.fonts
        x = px(26)
        self.create_text(x, px(122), text="THIS COMPUTER", font=f.tiny_bold, fill=theme.ON_NAVY_SOFT,
                         anchor="w", tags="dyn")
        text_x, glyph = x, f.glyph(self.device_glyph)
        if glyph:
            self.create_text(x + px(18), px(168), text=glyph, font=f.icon(28), fill=theme.DEVICE_GLOW, tags="dyn")
            text_x = x + px(54)
        wrap = w - text_x - px(18)
        self.create_text(text_x, px(152), text=self.name, font=f.title, fill=theme.ON_NAVY, anchor="w",
                         width=wrap, tags="dyn")
        self.create_text(text_x, px(176), text=_fit(self.model, 30), font=f.small, fill=theme.ON_NAVY_SOFT,
                         anchor="w", tags="dyn")
        self.create_text(text_x, px(195), text=_fit(self.os_name, 30), font=f.small, fill=theme.ON_NAVY_SOFT,
                         anchor="w", tags="dyn")

        cx, cy, r, thick = w / 2, px(318), px(74), px(12)
        box = (cx - r, cy - r, cx + r, cy + r)
        self.create_oval(*box, outline=theme.RING_TRACK, width=thick, tags="dyn")
        if self.scanning:
            self.create_arc(*box, start=-self.spin * 6, extent=95, style="arc", outline=theme.ACCENT,
                            width=thick, tags="dyn")
            self.create_text(cx, cy - px(9), text="Scanning", font=f.card_title, fill=theme.ON_NAVY, tags="dyn")
            self.create_text(cx, cy + px(14), text="please wait", font=f.small, fill=theme.ON_NAVY_SOFT, tags="dyn")
        elif self.quality is not None:
            colour = (theme.GOOD_BRIGHT if self.target >= 85 else
                      theme.WARN_BRIGHT if self.target >= 60 else theme.BAD_BRIGHT)
            if self.quality > 0.2:
                self.create_arc(*box, start=90, extent=-min(359.9, self.quality * 3.6), style="arc",
                                outline=colour, width=thick, tags="dyn")
            self.create_text(cx, cy - px(8), text=f"{self.quality:.0f}%", font=f.number, fill=theme.ON_NAVY, tags="dyn")
            self.create_text(cx, cy + px(24), text="data quality", font=f.small, fill=theme.ON_NAVY_SOFT, tags="dyn")
        else:
            self.create_text(cx, cy, text="-", font=f.number, fill=theme.ON_NAVY_SOFT, tags="dyn")

        if self.counts:
            ok, review, missing = self.counts
            y = px(428)
            for colour, text in ((theme.GOOD_BRIGHT, f"{ok} fields look good"),
                                 (theme.WARN_BRIGHT, f"{review} to review"),
                                 (theme.BAD_BRIGHT, f"{missing} missing")):
                self.create_oval(x, y - px(5), x + px(10), y + px(5), fill=colour, outline="", tags="dyn")
                self.create_text(x + px(20), y, text=text, font=f.body, fill=theme.ON_NAVY, anchor="w", tags="dyn")
                y += px(28)

        self.create_text(x, h - px(44), text=self.hint, font=f.small, fill=theme.ON_NAVY_SOFT, anchor="sw",
                         width=w - 2 * x, tags="dyn")
        self.create_text(x, h - px(22), text=f"Version {APP_VERSION}", font=f.tiny,
                         fill=theme.mix(theme.ON_NAVY_SOFT, theme.NAVY, 0.35), anchor="w", tags="dyn")


def _fit(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"
