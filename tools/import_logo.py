"""
import_logo.py
==============
Turns a logo SVG into outline data the program can draw.

    python tools/import_logo.py [assets/assetiq-mark.svg]

Reads the SVG, flattens every curve into straight segments, scales the
result into a 0..1 box and writes src/gui/brand_logo.py. The program then draws
the logo itself at any size -- window icon, EXE icon, sidebar -- with no image
files to ship and no image library to install.

Re-run this only when the brand artwork changes.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_SVG = os.path.join(ROOT, "assets", "assetiq-mark.svg")
OUT = os.path.join(ROOT, "src", "gui", "brand_logo.py")

CURVE_STEPS = 24          # straight segments per curve; 24 is smooth at 256 px
MARK_MARGIN = 0.16        # blank border around the mark inside its square

_NUMBER = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_COMMAND = "MmLlHhVvCcSsQqTtZz"


def tokenize(d: str) -> list:
    """SVG path data -> a flat list of command letters and floats."""
    tokens, i = [], 0
    while i < len(d):
        ch = d[i]
        if ch in _COMMAND:
            tokens.append(ch)
            i += 1
        elif ch in ", \t\r\n":
            i += 1
        else:
            match = _NUMBER.match(d, i)
            if not match:
                i += 1
                continue
            tokens.append(float(match.group()))
            i = match.end()
    return tokens


def _cubic(p0, p1, p2, p3, steps=CURVE_STEPS) -> list:
    points = []
    for step in range(1, steps + 1):
        t = step / steps
        s = 1 - t
        points.append((
            s * s * s * p0[0] + 3 * s * s * t * p1[0] + 3 * s * t * t * p2[0] + t * t * t * p3[0],
            s * s * s * p0[1] + 3 * s * s * t * p1[1] + 3 * s * t * t * p2[1] + t * t * t * p3[1],
        ))
    return points


def parse_path(d: str) -> list:
    """SVG path -> list of closed polygons, curves flattened to segments."""
    tokens = tokenize(d)
    polygons, current = [], []
    x = y = start_x = start_y = 0.0
    last_control = None
    command = None
    i = 0

    def finish():
        if len(current) > 2:
            polygons.append(list(current))

    while i < len(tokens):
        if isinstance(tokens[i], str):
            command = tokens[i]
            i += 1
            if command in "Zz":
                finish()
                current.clear()
                x, y = start_x, start_y
                last_control = None
                continue
        relative = command.islower()
        letter = command.upper()

        if letter == "M":
            finish()
            current.clear()
            dx, dy = tokens[i], tokens[i + 1]
            i += 2
            x, y = (x + dx, y + dy) if relative else (dx, dy)
            start_x, start_y = x, y
            current.append((x, y))
            command = "l" if relative else "L"       # further pairs are line-tos
            last_control = None
        elif letter == "L":
            dx, dy = tokens[i], tokens[i + 1]
            i += 2
            x, y = (x + dx, y + dy) if relative else (dx, dy)
            current.append((x, y))
            last_control = None
        elif letter == "H":
            dx = tokens[i]
            i += 1
            x = x + dx if relative else dx
            current.append((x, y))
            last_control = None
        elif letter == "V":
            dy = tokens[i]
            i += 1
            y = y + dy if relative else dy
            current.append((x, y))
            last_control = None
        elif letter in ("C", "S"):
            if letter == "C":
                c1 = (tokens[i], tokens[i + 1])
                c2 = (tokens[i + 2], tokens[i + 3])
                end = (tokens[i + 4], tokens[i + 5])
                i += 6
                if relative:
                    c1 = (x + c1[0], y + c1[1])
                    c2 = (x + c2[0], y + c2[1])
                    end = (x + end[0], y + end[1])
            else:
                c2 = (tokens[i], tokens[i + 1])
                end = (tokens[i + 2], tokens[i + 3])
                i += 4
                if relative:
                    c2 = (x + c2[0], y + c2[1])
                    end = (x + end[0], y + end[1])
                c1 = (2 * x - last_control[0], 2 * y - last_control[1]) if last_control else (x, y)
            current.extend(_cubic((x, y), c1, c2, end))
            x, y = end
            last_control = c2
        elif letter in ("Q", "T"):
            if letter == "Q":
                q = (tokens[i], tokens[i + 1])
                end = (tokens[i + 2], tokens[i + 3])
                i += 4
                if relative:
                    q = (x + q[0], y + q[1])
                    end = (x + end[0], y + end[1])
            else:
                end = (tokens[i], tokens[i + 1])
                i += 2
                if relative:
                    end = (x + end[0], y + end[1])
                q = (2 * x - last_control[0], 2 * y - last_control[1]) if last_control else (x, y)
            c1 = (x + 2 / 3 * (q[0] - x), y + 2 / 3 * (q[1] - y))
            c2 = (end[0] + 2 / 3 * (q[0] - end[0]), end[1] + 2 / 3 * (q[1] - end[1]))
            current.extend(_cubic((x, y), c1, c2, end))
            x, y = end
            last_control = q
        else:
            raise ValueError(f"unsupported path command {command!r}")

    finish()
    return polygons


def parse_polygon(points: str) -> list:
    """SVG <polygon points="x,y x,y ..."> -> one closed outline."""
    numbers = [float(n) for n in _NUMBER.findall(points)]
    return [[(numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 1, 2)]]


def parse_rect(attrs: str) -> list:
    """SVG <rect> -> one closed outline."""
    def value(name, default=0.0):
        match = re.search(rf'\s{name}="([^"]+)"', attrs)
        return float(match.group(1)) if match else default

    x, y, w, h = value("x"), value("y"), value("width"), value("height")
    return [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]


def shapes_in(svg: str) -> list:
    """Every drawing element of the artwork, in document order.

    Illustrator exports curved letters as <path> but straight ones as <polygon>,
    so reading only paths silently loses letters."""
    found = []
    for match in re.finditer(r"<(path|polygon|rect)(\s[^>]*)?>", svg, re.S):
        kind, attrs = match.group(1), match.group(2)
        if kind == "path":
            data = re.search(r'\sd="([^"]+)"', attrs, re.S)
            if data:
                found.append(parse_path(data.group(1)))
        elif kind == "polygon":
            points = re.search(r'\spoints="([^"]+)"', attrs, re.S)
            if points:
                found.append(parse_polygon(points.group(1)))
        else:
            found.append(parse_rect(attrs))
    return found


def bbox(polygons):
    xs = [p[0] for poly in polygons for p in poly]
    ys = [p[1] for poly in polygons for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def scaled(polygons, offset_x, offset_y, scale, round_to=5):
    return [[(round((x - offset_x) * scale, round_to), round((y - offset_y) * scale, round_to))
             for x, y in poly] for poly in polygons]


def literal(polygons, indent=4) -> str:
    pad = " " * indent
    out = []
    for poly in polygons:
        points = ", ".join(f"({x}, {y})" for x, y in poly)
        out.append(f"{pad}[{points}],")
    return "\n".join(out)


def main(svg_path: str):
    with open(svg_path, encoding="utf-8") as fh:
        svg = fh.read()
    glyphs = shapes_in(svg)
    if not glyphs:
        raise SystemExit(f"no drawable shapes found in {svg_path}")

    # The leftmost shape is the square mark; the whole artwork is the wordmark.
    mark = min(glyphs, key=lambda polys: bbox(polys)[0])
    mx0, my0, mx1, my1 = bbox(mark)
    span = max(mx1 - mx0, my1 - my0)
    scale = (1 - 2 * MARK_MARGIN) / span
    mark_scaled = scaled(mark, mx0, my0, scale)
    # centre it in the 0..1 square
    w, h = (mx1 - mx0) * scale, (my1 - my0) * scale
    pad_x, pad_y = (1 - w) / 2, (1 - h) / 2
    mark_scaled = [[(round(x + pad_x, 5), round(y + pad_y, 5)) for x, y in poly] for poly in mark_scaled]

    word = [poly for glyph in glyphs for poly in glyph]
    wx0, wy0, wx1, wy1 = bbox(word)
    wscale = 1 / (wx1 - wx0)
    word_scaled = scaled(word, wx0, wy0, wscale)
    word_height = round((wy1 - wy0) * wscale, 5)

    source = os.path.relpath(svg_path, ROOT).replace("\\", "/")
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f'''"""
brand_logo.py
=============
The program's logo, as outlines.

GENERATED FILE -- do not edit by hand. Produced by tools/import_logo.py from
{source}, with every curve flattened to straight
segments and scaled into a 0..1 box. Drawing the logo from outlines means the
program ships no image files and needs no image library, and the mark stays
sharp at every size, from a 16 px tray icon to a 256 px shortcut.

MARK      the square mark used for the window and EXE icons, centred in a 0..1 square.
WORDMARK  the whole artwork in a box 1.0 wide and WORDMARK_HEIGHT high.

Both are lists of closed outlines; fill them with the even-odd rule so holes
(letter counters, cut lines) stay open.
"""

MARK = [
{literal(mark_scaled)}
]

WORDMARK_HEIGHT = {word_height}

WORDMARK = [
{literal(word_scaled)}
]
''')
    print(f"  read   {source}: {len(glyphs)} shape(s), {sum(len(g) for g in glyphs)} outline(s)")
    print(f"  mark   S -> {len(mark_scaled)} outline(s), {sum(len(p) for p in mark_scaled)} points")
    print(f"  word   full logo -> {len(word_scaled)} outline(s), aspect 1 : {word_height}")
    print(f"  wrote  {os.path.relpath(OUT, ROOT)} ({os.path.getsize(OUT) / 1024:.0f} KB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SVG)
