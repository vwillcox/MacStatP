"""Rasterise a specimen of the Presto Techno face for visual iteration."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glyphs
from raster import Canvas

CAP = glyphs.CAP


def draw_text(cv, s, x, y, size, colour, tracking=1):
    """y is the cap-line; size is cap height in pixels."""
    k = size / CAP
    pen = x
    for ch in s:
        g = glyphs.GLYPHS.get(ch)
        if g is None:
            pen += size * 0.6
            continue
        for poly in g[1]:
            cv.polygon([(pen + px * k, y + py * k) for px, py in poly], colour)
        pen += (glyphs.advance(ch) + tracking) * k
    return pen - x


def main():
    cv = Canvas(760, 460, (10, 12, 18))
    white = (235, 240, 250)
    cyan = (0, 200, 255)
    amber = (255, 180, 40)
    muted = (120, 134, 158)

    y = 20
    draw_text(cv, "ABCDEFGHIJKLM", 16, y, 30, white); y += 44
    draw_text(cv, "NOPQRSTUVWXYZ", 16, y, 30, white); y += 44
    draw_text(cv, "0123456789", 16, y, 30, cyan); y += 44
    draw_text(cv, ".,:/-+%()*'!?#", 16, y, 30, amber); y += 52

    draw_text(cv, "CPU", 16, y, 26, white)
    draw_text(cv, "GPU", 120, y, 26, white)
    draw_text(cv, "RAM", 224, y, 26, white)
    draw_text(cv, "DISK", 328, y, 26, white)
    draw_text(cv, "NETWORK", 452, y, 26, white); y += 46

    draw_text(cv, "85", 16, y, 64, cyan)
    draw_text(cv, "100", 130, y, 64, amber)
    draw_text(cv, "7.3", 300, y, 64, white); y += 78

    draw_text(cv, "\x11 12.4 MB/S", 16, y, 24, cyan)
    draw_text(cv, "\x10 0.8 MB/S", 260, y, 24, amber); y += 40
    draw_text(cv, "LOAD 3.33  PEAK 56%  221/245 GB", 16, y, 18, muted)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "build", "font_specimen.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cv.save(out)
    print("wrote", os.path.normpath(out))


if __name__ == "__main__":
    main()
