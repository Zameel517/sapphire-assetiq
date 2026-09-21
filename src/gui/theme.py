"""
theme.py
========
Colours, fonts and icon glyphs for the window, kept in one place.
"""

import tkinter.font as tkfont

from config.presentation import MISSING_BG, MISSING_FG, REVIEW_BG, REVIEW_FG

PAGE = "#F3F6FB"
CARD = "#FFFFFF"
CARD_BORDER = "#E3E8F0"
SHADOW = "#E4E9F2"
LINE = "#E2E8F0"
INK = "#0F172A"
INK_SOFT = "#475569"
MUTED = "#94A3B8"

NAVY = "#081630"
NAVY_LIGHT = "#123B70"
ON_NAVY = "#FFFFFF"
ON_NAVY_SOFT = "#A9BCD8"
RING_TRACK = "#20406B"
DEVICE_GLOW = "#8DB9FF"

ACCENT = "#2F7BF6"
ACCENT_HOVER = "#1D63D8"
ACCENT_SOFT = "#E6EFFE"
GHOST_HOVER = "#E6EBF3"

GOOD = "#16A34A"
GOOD_BRIGHT = "#22C55E"
WARN_BRIGHT = "#F59E0B"
BAD = "#DC2626"
BAD_BRIGHT = "#F87171"
REVIEW_TEXT, REVIEW_FILL = f"#{REVIEW_FG}", f"#{REVIEW_BG}"
MISSING_TEXT, MISSING_FILL = f"#{MISSING_FG}", f"#{MISSING_BG}"

# Segoe Fluent Icons / Segoe MDL2 Assets code points.
GLYPHS = {
    "system": "\uE770", "laptop": "\uE7F8", "desktop": "\uE977", "tablet": "\uE70A",
    "monitor": "\uE7F4", "network": "\uE968", "storage": "\uEDA2", "mail": "\uE715",
    "shield": "\uEA18", "chip": "\uE950", "clock": "\uE823", "check": "\uE73E",
    "cross": "\uE711", "warning": "\uE7BA", "copy": "\uE8C8", "refresh": "\uE72C",
    "folder": "\uE838", "people": "\uE716", "info": "\uE946", "pulse": "\uE9D9",
}


def mix(a: str, b: str, t: float) -> str:
    """Blend two #RRGGBB colours; t=0 gives a, t=1 gives b."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


class Fonts:
    """Fonts chosen from what this PC has: Windows 11's Segoe UI Variable and
    Fluent icons, falling back to Segoe UI and MDL2 icons on Windows 10."""

    def __init__(self, root):
        families = set(tkfont.families(root))
        display = next((f for f in ("Segoe UI Variable Display", "Segoe UI") if f in families), "TkDefaultFont")
        text = next((f for f in ("Segoe UI Variable Text", "Segoe UI") if f in families), "TkDefaultFont")
        self.icon_family = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families), None)
        # Canvas drawing is measured in pixels; scale it with the screen's DPI like the text.
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.hero = (display, 22, "bold")
        self.title = (display, 14, "bold")
        self.brand = (display, 15, "bold")
        self.card_title = (display, 11, "bold")
        self.number = (display, 26, "bold")
        self.body = (text, 10)
        self.body_bold = (text, 10, "bold")
        self.small = (text, 9)
        self.small_bold = (text, 9, "bold")
        self.tiny = (text, 8)
        self.tiny_bold = (text, 8, "bold")

    def px(self, n: float) -> int:
        return int(round(n * self.scale))

    def icon(self, size: int):
        return (self.icon_family, size)

    def glyph(self, name: str) -> str:
        return GLYPHS.get(name, "") if self.icon_family else ""
