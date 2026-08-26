"""Renderer for the Presto Techno face.

Glyphs are filled polygons, so they scale to any size and stay bold at
the sizes this dashboard uses. Runs unchanged on the device and under
the Mac-side preview shim.
"""

from font_data import G, CAP, STEM

LEFT, CENTER, RIGHT = 0, 1, 2

_MISSING = 0.6  # advance for an unmapped character, as a fraction of size


def advance(ch):
    g = G.get(ch)
    return g[0] if g else None


def width(s, size, tracking=1):
    """Pixel width of s rendered at the given cap height."""
    k = size / CAP
    total = 0.0
    for ch in s:
        a = advance(ch)
        total += (a + tracking) * k if a is not None else size * _MISSING
    return total - (tracking * k if s else 0)


@micropython.native
def text(display, s, x, y, size, tracking=1, align=LEFT):
    """Draw s with its cap-line at y. Returns the advanced pen x.

    Two things keep small sizes crisp on an unantialiased panel:

    * each glyph starts on a whole pixel, so every instance of a letter
      renders identically instead of shifting with its position;
    * anything the design draws at the stem width is forced to the same
      pixel width, so stems and bars don't alternate between 2px and 3px
      depending on where they happen to land.
    """
    k = size / CAP
    if align == CENTER:
        x -= width(s, size, tracking) / 2
    elif align == RIGHT:
        x -= width(s, size, tracking)

    stem = int(STEM * k + 0.5)
    if stem < 1:
        stem = 1

    rect = display.rectangle
    poly = display.polygon
    gy = int(y + 0.5)
    pen = x
    for ch in s:
        data = G.get(ch)
        if data is None:
            pen += size * _MISSING
            continue
        gx = int(pen + 0.5)
        i = 2
        for _ in range(data[1]):
            n = data[i]
            i += 1
            if n == 0:
                # Rectangle: fills far faster than the equivalent polygon.
                dx0 = data[i]
                dy0 = data[i + 1]
                dx1 = data[i + 2]
                dy1 = data[i + 3]
                i += 4
                x0 = int(gx + dx0 * k + 0.5)
                y0 = int(gy + dy0 * k + 0.5)
                w = (stem if dx1 - dx0 == STEM
                     else int(gx + dx1 * k + 0.5) - x0)
                h = (stem if dy1 - dy0 == STEM
                     else int(gy + dy1 * k + 0.5) - y0)
                rect(x0, y0, w if w > 0 else 1, h if h > 0 else 1)
                continue
            pts = []
            for _p in range(n):
                # PicoGraphics takes integer vertices only.
                pts.append((int(gx + data[i] * k + 0.5),
                            int(gy + data[i + 1] * k + 0.5)))
                i += 2
            poly(pts)
        pen += (data[0] + tracking) * k
    return pen
