"""
icon.py
=======
The program's mark: the window icon, the EXE's file icon, and the logo in the
window's sidebar.

The outlines come from gui/brand_logo.py, generated from assets/assetiq-mark.svg
by tools/import_logo.py. They are filled in code at whatever size is asked for,
which keeps the mark sharp from a 16 px tray icon to a 256 px shortcut and means
no image files or image libraries have to ship with the program.
"""

import base64
import struct
import zlib

from gui.brand_logo import MARK, WORDMARK, WORDMARK_HEIGHT

# The sidebar's navy, as numbers, so building the icon never needs tkinter.
NAVY_TOP = (8, 22, 48)          # theme.NAVY
NAVY_BOTTOM = (18, 59, 112)     # theme.NAVY_LIGHT
WHITE = (255, 255, 255)
CORNER = 0.22                   # tile corner radius, as a fraction of the icon size


def _coverage(outlines, width: int, height: int, samples: int = 4) -> list:
    """How much of each pixel the filled outlines cover, 0..1.

    A scanline fill: every sub-row crosses the outlines an even number of times,
    and the spans between alternate crossings are inside (the even-odd rule),
    which keeps the counters inside A, P and R open. Coverage is exact
    horizontally and sampled `samples` times vertically -- far cheaper than
    testing every subpixel against an 800-point outline."""
    rows = [[0.0] * width for _ in range(height)]
    edges = [(y0, y1, x0, x1)
             for outline in outlines
             for (x0, y0), (x1, y1) in zip(outline, outline[1:] + outline[:1])
             if y0 != y1]
    for py in range(height):
        acc = rows[py]
        for sample in range(samples):
            v = (py + (sample + 0.5) / samples) / width      # x and y share one scale
            crossings = [x0 + (v - y0) * (x1 - x0) / (y1 - y0)
                         for y0, y1, x0, x1 in edges
                         if (y0 <= v < y1) or (y1 <= v < y0)]
            if not crossings:
                continue
            crossings.sort()
            for i in range(0, len(crossings) - 1, 2):
                start, end = crossings[i] * width, crossings[i + 1] * width
                if end <= 0 or start >= width:
                    continue
                start, end = max(start, 0.0), min(end, float(width))
                first, last = int(start), min(int(end), width - 1)
                if first >= last:
                    acc[first] += (end - start) / samples
                    continue
                acc[first] += (first + 1 - start) / samples
                for px in range(first + 1, last):
                    acc[px] += 1.0 / samples
                acc[last] += (end - last) / samples
    return [[c if c < 1.0 else 1.0 for c in row] for row in rows]


def _tile_alpha(u: float, v: float, size: int) -> float:
    """Coverage of the rounded-square tile the S sits on, with a soft 1 px edge."""
    radius = CORNER
    cx = min(max(u, radius), 1 - radius)
    cy = min(max(v, radius), 1 - radius)
    dx, dy = u - cx, v - cy
    distance = (dx * dx + dy * dy) ** 0.5 - radius        # negative inside
    return min(max(0.5 - distance * size, 0.0), 1.0)


def rgba_rows(size: int, samples: int = 4) -> list:
    """The icon as `size` rows of RGBA bytes: the white mark on a navy tile."""
    mark = _coverage(MARK, size, size, samples)
    rows = []
    for y in range(size):
        row = bytearray()
        line = mark[y]
        v = (y + 0.5) / size
        base = tuple(round(top + (bottom - top) * v) for top, bottom in zip(NAVY_TOP, NAVY_BOTTOM))
        for x in range(size):
            alpha = _tile_alpha((x + 0.5) / size, v, size)
            if alpha <= 0:
                row += bytes(4)
                continue
            ink = line[x]
            row += bytes((round(base[0] + (WHITE[0] - base[0]) * ink),
                          round(base[1] + (WHITE[1] - base[1]) * ink),
                          round(base[2] + (WHITE[2] - base[2]) * ink),
                          round(255 * alpha)))
        rows.append(bytes(row))
    return rows


def wordmark_rgba_rows(width: int, colour=WHITE, samples: int = 4) -> tuple:
    """The whole artwork in one colour on transparency: (height, rows)."""
    height = max(1, round(width * WORDMARK_HEIGHT))
    coverage = _coverage(WORDMARK, width, height, samples)
    rows = []
    for line in coverage:
        row = bytearray()
        for ink in line:
            row += bytes((colour[0], colour[1], colour[2], round(255 * ink)))
        rows.append(bytes(row))
    return height, rows


def _png(width: int, height: int, rows: list) -> bytes:
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def png_bytes(size: int) -> bytes:
    return _png(size, size, rgba_rows(size))


def png_base64(size: int) -> str:
    """For tkinter.PhotoImage(data=...)."""
    return base64.b64encode(png_bytes(size)).decode("ascii")


def wordmark_png_base64(width: int, colour=WHITE) -> tuple:
    """The wordmark for tkinter.PhotoImage(data=...): (data, height in pixels)."""
    height, rows = wordmark_rgba_rows(width, colour)
    return base64.b64encode(_png(width, height, rows)).decode("ascii"), height


def ico_bytes(sizes=(16, 24, 32, 48, 64, 128, 256)) -> bytes:
    """A multi-size Windows .ico with PNG-compressed images."""
    images = [png_bytes(size) for size in sizes]
    directory = struct.pack("<HHH", 0, 1, len(images))
    offset, blobs = 6 + 16 * len(images), b""
    for size, image in zip(sizes, images):
        edge = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
        blobs += image
    return directory + blobs
