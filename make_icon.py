# KlikFix is free software: you may redistribute and/or modify it under
# the GNU General Public License, version 3 or later, as published by the
# Free Software Foundation. There is NO WARRANTY. See the LICENSE file.
"""Draw KlikFix's icon: full screen shrinking into a window.

A Windows 98 monitor with a teal desktop and a small navy-titled window, with
four gold arrows pulling in from the corners.

Build-time only (needs Pillow): ``py -3 make_icon.py`` writes ``icon.ico``.
Pixel art in the KlikBack manner: shapes are drawn without anti-aliasing,
small sizes are drawn at their own size, and 128/256 are the 64 master scaled
up with nearest-neighbour so they stay crisp and chunky.
"""

from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw

GREY = (192, 192, 192, 255)
LIGHT = (255, 255, 255, 255)
MID = (128, 128, 128, 255)
DARK = (0, 0, 0, 255)
NAVY = (0, 0, 128, 255)          # the Windows 98 title bar
TEAL = (0, 128, 128, 255)        # the Windows 98 desktop
GOLD = (244, 176, 32, 255)
OUTLINE = (20, 20, 36, 255)


def _scaled(size: int, *points):
    k = size / 64
    return [(round(x * k), round(y * k)) for x, y in points]


def _box(d, size, x0, y0, x1, y1, **style) -> None:
    (a, b), (c, e) = _scaled(size, (x0, y0), (x1, y1))
    d.rectangle((a, b, c, e), **style)


def _bevel(d, size, x0, y0, x1, y1, face=GREY) -> None:
    """A raised Windows 98 bevel: light top-left, black bottom-right."""
    _box(d, size, x0, y0, x1, y1, fill=face)
    (a, b), (c, e) = _scaled(size, (x0, y0), (x1, y1))
    d.line((a, b, c, b), fill=LIGHT)
    d.line((a, b, a, e), fill=LIGHT)
    d.line((c, b, c, e), fill=DARK)
    d.line((a, e, c, e), fill=DARK)


def _window(d, size, x0, y0, x1, y1, title: float) -> None:
    _bevel(d, size, x0, y0, x1, y1)
    _box(d, size, x0 + 2, y0 + 2, x1 - 2, y0 + 2 + title, fill=NAVY)


def _arrow(d, size, tip, direction, length=10.0, head=4.5, width=2.6) -> None:
    """A chunky gold arrow with a dark outline, pointing at ``tip``."""
    dx, dy = direction
    n = math.hypot(dx, dy)
    dx, dy = dx / n, dy / n
    px, py = -dy, dx
    tx, ty = tip
    bx, by = tx - dx * head, ty - dy * head
    ex, ey = tx - dx * length, ty - dy * length
    shaft = [(bx + px * width / 2, by + py * width / 2),
             (ex + px * width / 2, ey + py * width / 2),
             (ex - px * width / 2, ey - py * width / 2),
             (bx - px * width / 2, by - py * width / 2)]
    point = [(tx, ty), (bx + px * head, by + py * head),
             (bx - px * head, by - py * head)]
    for poly in (shaft, point):
        cx = sum(x for x, _ in poly) / len(poly)
        cy = sum(y for _, y in poly) / len(poly)
        fat = []
        for x, y in poly:
            r = max(1e-6, math.hypot(x - cx, y - cy))
            fat.append((x + (x - cx) / r * 1.3, y + (y - cy) / r * 1.3))
        d.polygon(_scaled(size, *fat), fill=OUTLINE)
    d.polygon(_scaled(size, *shaft), fill=GOLD)
    d.polygon(_scaled(size, *point), fill=GOLD)


def draw(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    _bevel(d, size, 1, 3, 62, 50)              # monitor bezel
    _box(d, size, 5, 7, 58, 46, fill=TEAL)     # screen
    _box(d, size, 26, 50, 37, 56, fill=MID)    # neck
    _bevel(d, size, 16, 55, 47, 61)            # foot
    if size >= 24:
        _window(d, size, 19, 17, 44, 36, title=5)
    else:  # bigger window, so it still reads at 16 px
        _window(d, size, 17, 15, 46, 38, title=6)
    if size >= 32:
        for tip, direction in (((18, 16), (1, 1)), ((45, 16), (-1, 1)),
                               ((18, 37), (1, -1)), ((45, 37), (-1, -1))):
            _arrow(d, size, tip, direction)
    return image


def build(path: str) -> list[Image.Image]:
    images = {s: draw(s) for s in (16, 24, 32, 48, 64)}
    images[128] = images[64].resize((128, 128), Image.NEAREST)
    images[256] = images[64].resize((256, 256), Image.NEAREST)
    order = [256, 128, 64, 48, 32, 24, 16]
    images[256].save(path, sizes=[(s, s) for s in order],
                     append_images=[images[s] for s in order[1:]])
    return [images[s] for s in (16, 24, 32, 48, 64, 128)]


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    shown = build(os.path.join(here, "icon.ico"))
    if len(sys.argv) > 1:  # optional preview sheet
        width = sum(i.width for i in shown) + 8 * (len(shown) + 1)
        sheet = Image.new("RGBA", (width, 144), (255, 255, 255, 255))
        x = 8
        for image in shown:
            sheet.alpha_composite(image, (x, 8))
            x += image.width + 8
        sheet.resize((width * 2, 288), Image.NEAREST).save(sys.argv[1])
