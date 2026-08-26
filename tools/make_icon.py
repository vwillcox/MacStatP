"""Render the application icon and convert it to an .icns.

Uses the same gauge motif and palette as the panel, drawn with the
project's own rasteriser so there is no extra dependency.
"""

import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from raster import Canvas

S = 1024
BG = (11, 14, 20)
RING_OFF = (38, 46, 60)
CYAN = (0, 194, 255)
GREEN = (54, 222, 138)
AMBER = (255, 178, 40)


def heat(t):
    if t < 0.55:
        f = t / 0.55
        a, b = GREEN, AMBER
    else:
        f = min(1.0, (t - 0.55) / 0.45)
        a, b = AMBER, (255, 72, 92)
    return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))


def rounded(cv, x, y, w, h, r, colour):
    cv.rect(x + r, y, w - 2 * r, h, colour)
    cv.rect(x, y + r, w, h - 2 * r, colour)
    for cx, cy in ((x + r, y + r), (x + w - r, y + r),
                   (x + r, y + h - r), (x + w - r, y + h - r)):
        cv.circle(cx, cy, r, colour)


def main():
    cv = Canvas(S, S, (0, 0, 0))
    rounded(cv, 0, 0, S, S, int(S * 0.22), BG)

    cx = cy = S // 2
    r_out, r_in = int(S * 0.36), int(S * 0.26)
    segments, span, start = 28, 270, 135
    lit = 19                       # a dial sitting at a plausible load
    seg = span / segments
    gap = seg * 0.28
    for i in range(segments):
        a0 = math.radians(start + i * seg + gap * 0.5)
        a1 = math.radians(start + (i + 1) * seg - gap * 0.5)
        colour = heat((i + 0.5) / segments) if i < lit else RING_OFF
        cv.polygon([
            (cx + r_in * math.cos(a0), cy + r_in * math.sin(a0)),
            (cx + r_out * math.cos(a0), cy + r_out * math.sin(a0)),
            (cx + r_out * math.cos(a1), cy + r_out * math.sin(a1)),
            (cx + r_in * math.cos(a1), cy + r_in * math.sin(a1)),
        ], colour)

    # A short bar chart in the middle, echoing the per-core ticks.
    bw, gapx = int(S * 0.055), int(S * 0.028)
    heights = (0.20, 0.40, 0.30, 0.55, 0.34)
    total = len(heights) * bw + (len(heights) - 1) * gapx
    bx = cx - total // 2
    base = cy + int(S * 0.10)
    for i, hfrac in enumerate(heights):
        bh = int(S * 0.30 * hfrac)
        cv.rect(bx + i * (bw + gapx), base - bh, bw, bh, CYAN)

    out_dir = os.path.join(HERE, "..", "build")
    os.makedirs(out_dir, exist_ok=True)
    png = os.path.join(out_dir, "icon.png")
    cv.save(png)
    print("wrote", os.path.normpath(png))

    iconset = os.path.join(out_dir, "AppIcon.iconset")
    subprocess.run(["rm", "-rf", iconset], check=False)
    os.makedirs(iconset, exist_ok=True)
    for size in (16, 32, 64, 128, 256, 512, 1024):
        for scale, suffix in ((1, ""), (2, "@2x")):
            px = size * scale
            if px > 1024:
                continue
            name = "icon_%dx%d%s.png" % (size, size, suffix)
            subprocess.run(["sips", "-z", str(px), str(px), png,
                            "--out", os.path.join(iconset, name)],
                           capture_output=True, check=False)
    icns = os.path.join(out_dir, "AppIcon.icns")
    r = subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("iconutil failed:", r.stderr.strip(), file=sys.stderr)
        return 1
    print("wrote", os.path.normpath(icns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
