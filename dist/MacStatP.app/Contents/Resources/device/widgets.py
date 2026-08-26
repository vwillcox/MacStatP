"""Drawing primitives for the dashboard: chamfered cards, radial gauges,
bar meters and sparklines.

Everything here sticks to the small set of PicoGraphics calls that the
Mac-side preview shim also implements: set_pen, rectangle, polygon,
circle, line.
"""

import math

import font
import theme

CH = 6  # default corner chamfer, in pixels


def chamfered(x, y, w, h, c=CH):
    """Octagonal outline — the house shape for panels and pills."""
    x, y, w, h = int(x), int(y), int(w), int(h)
    c = int(min(c, w // 2, h // 2))
    return [
        (x + c, y), (x + w - c, y),
        (x + w, y + c), (x + w, y + h - c),
        (x + w - c, y + h), (x + c, y + h),
        (x, y + h - c), (x, y + c),
    ]


def fill_chamfered(d, x, y, w, h, c=CH):
    """Same shape as chamfered(), drawn as rectangles plus four corner
    triangles. Large fills are several times cheaper this way."""
    x, y, w, h = int(x), int(y), int(w), int(h)
    c = int(min(c, w // 2, h // 2))
    d.rectangle(x, y + c, w, h - 2 * c)
    d.rectangle(x + c, y, w - 2 * c, c)
    d.rectangle(x + c, y + h - c, w - 2 * c, c)
    d.polygon([(x, y + c), (x + c, y + c), (x + c, y)])
    d.polygon([(x + w - c, y), (x + w - c, y + c), (x + w, y + c)])
    d.polygon([(x + w, y + h - c), (x + w - c, y + h - c), (x + w - c, y + h)])
    d.polygon([(x, y + h - c), (x + c, y + h - c), (x + c, y + h)])


def card(d, pens, x, y, w, h, title=None, subtitle=None, accent=None):
    """Bordered panel with a title row. Returns the content-area top y."""
    pens.set(theme.BORDER)
    fill_chamfered(d, x, y, w, h)
    pens.set(theme.CARD)
    fill_chamfered(d, x + 2, y + 2, w - 4, h - 4, CH - 1)

    if title:
        pens.set(theme.TITLE)
        font.text(d, title, x + 12, y + 11, 19)
        if subtitle:
            pens.set(theme.MUTED)
            font.text(d, subtitle, x + w - 12, y + 14, 13, align=font.RIGHT)
        # Hairline under the title, tinted with the panel's accent.
        pens.set(accent or theme.BORDER)
        d.rectangle(x + 12, y + 36, w - 24, 1)
    return y + 42


_SEG_CACHE = {}
_HEAT_CACHE = {}


def _ring(cx, cy, r, segments, span, start):
    """Segment vertices for a dial. Cached: the geometry never changes,
    only which segments are lit."""
    key = (cx, cy, r, segments, span, start)
    pts = _SEG_CACHE.get(key)
    if pts is None:
        seg = span / segments
        gap = seg * 0.28
        r_out, r_in = r, r - 11
        pts = []
        for i in range(segments):
            a0 = math.radians(start + i * seg + gap * 0.5)
            a1 = math.radians(start + (i + 1) * seg - gap * 0.5)
            c0, s0 = math.cos(a0), math.sin(a0)
            c1, s1 = math.cos(a1), math.sin(a1)
            pts.append([
                (int(cx + r_in * c0 + 0.5), int(cy + r_in * s0 + 0.5)),
                (int(cx + r_out * c0 + 0.5), int(cy + r_out * s0 + 0.5)),
                (int(cx + r_out * c1 + 0.5), int(cy + r_out * s1 + 0.5)),
                (int(cx + r_in * c1 + 0.5), int(cy + r_in * s1 + 0.5)),
            ])
        _SEG_CACHE[key] = pts
    return pts


def _ring_colours(segments):
    cols = _HEAT_CACHE.get(segments)
    if cols is None:
        cols = [theme.heat((i + 0.5) / segments) for i in range(segments)]
        _HEAT_CACHE[segments] = cols
    return cols


def gauge(d, pens, cx, cy, r, pct, label, prev_lit=None,
          segments=28, span=270, start=135):
    """Radial dial: segmented ring, big value, caption underneath.

    Pass the previous return value as `prev_lit` to repaint only the
    segments that actually changed state — a dial sitting still then
    costs nothing but its centre text. Returns the new lit count.
    """
    frac = max(0.0, min(1.0, pct / 100.0))
    lit = int(round(frac * segments))
    r_in = r - 11

    ring = _ring(cx, cy, r, segments, span, start)
    # Colour each segment by where it sits on the scale, so the ring reads
    # as a gradient rather than one flat block.
    cols = _ring_colours(segments)
    if prev_lit is None:
        changed = range(segments)
    elif lit > prev_lit:
        changed = range(prev_lit, lit)
    elif lit < prev_lit:
        changed = range(lit, prev_lit)
    else:
        changed = ()
    for i in changed:
        pens.set(cols[i] if i < lit else theme.TRACK)
        d.polygon(ring[i])

    # Inner disc, with a faint halo in the current heat colour.
    pens.set(theme.dim(theme.heat(frac), 0.16))
    d.circle(int(cx), int(cy), int(r_in - 3))
    pens.set(theme.CARD)
    d.circle(int(cx), int(cy), int(r_in - 6))

    val = str(int(round(pct)))
    # Fit the value to the counter rather than to a fixed ratio, so "100"
    # stays inside the dial just as comfortably as "7".
    avail = 2 * (r_in - 6) - 8
    w28 = font.width(val, 28) or 1
    size = min(r * 0.70, 28.0 * avail / w28)
    lsize = r * 0.21
    top = cy - (size + 3 + lsize) / 2

    pens.set(theme.WHITE)
    font.text(d, val, cx, top, size, align=font.CENTER)
    pens.set(theme.MUTED)
    font.text(d, label, cx, top + size + 3, lsize, align=font.CENTER)
    return lit


def bar(d, pens, x, y, w, h, frac, colour, track=None):
    """Chamfered pill meter."""
    frac = max(0.0, min(1.0, frac))
    pens.set(track or theme.TRACK)
    d.polygon(chamfered(x, y, w, h, h // 2))
    fw = int(w * frac)
    if fw > 2:
        pens.set(colour)
        d.polygon(chamfered(x, y, fw, h, min(h // 2, fw // 2)))


def sparkline(d, pens, x, y, w, h, values, colour, peak=None, capacity=None):
    """Filled area chart, newest sample at the right edge.

    With `capacity` set the plot keeps a fixed time axis, so a partly
    filled history grows in from the right instead of stretching to fit.
    """
    if not values:
        return
    hi = peak if peak else max(values)
    if not hi or hi <= 0:
        hi = 1.0

    slots = capacity or len(values)
    vals = values[-slots:]
    step = w / float(slots)
    bw = max(1, int(step + 0.999))
    offset = slots - len(vals)

    # Precompute the bars, then draw each colour in one pass. Switching
    # pens per bar was costing more than the fills themselves.
    bars = []
    for i, v in enumerate(vals):
        vh = int(h * min(1.0, v / hi))
        if vh < 1:
            vh = 1
        bars.append((int(x + (offset + i) * step), y + h - vh, vh))

    rect = d.rectangle
    pens.set(theme.dim(colour, 0.30))
    for bx, by, vh in bars:
        rect(bx, by, bw, vh)
    # Bright cap so the trace stays readable against the fill.
    pens.set(colour)
    for bx, by, vh in bars:
        rect(bx, by, bw, 2 if vh > 2 else vh)


def dot(d, pens, cx, cy, r, colour):
    pens.set(colour)
    d.circle(int(cx), int(cy), int(r))


def trace(d, pens, x, y, w, h, values, colour, peak=None, capacity=None,
          thickness=2):
    """A line chart: just the shape, no fill.

    Reads better than a filled area when the value barely moves — a flat
    line says "steady", a solid block says nothing.
    """
    if not values:
        return
    hi = peak if peak else max(values)
    if not hi or hi <= 0:
        hi = 1.0

    slots = capacity or len(values)
    vals = values[-slots:]
    if len(vals) < 2:
        return
    step = w / float(slots - 1 if slots > 1 else 1)
    offset = slots - len(vals)

    pens.set(colour)
    px = int(x + offset * step)
    py = int(y + h - h * min(1.0, vals[0] / hi))
    for i in range(1, len(vals)):
        nx = int(x + (offset + i) * step)
        ny = int(y + h - h * min(1.0, vals[i] / hi))
        d.line(px, py, nx, ny, thickness)
        px, py = nx, ny


@micropython.native
def curve_points(x, y, w, h, values, peak=None, capacity=None, span=3):
    """A Catmull-Rom curve through the samples, one entry per pixel column.

    Returns (start_x, [y_pixel, ...]).

    The curve passes through every sample: this smooths the *line*, not
    the data. A real spike stays exactly as tall as it was, it just
    arrives and leaves on a curve instead of a staircase.
    """
    if not values:
        return (x, [])
    hi = peak if peak else max(values)
    if not hi or hi <= 0:
        hi = 1.0

    slots = capacity or len(values)
    vals = values[-slots:]
    n = len(vals)
    if n < 2:
        return (x, [])
    step = w / float(slots - 1) if slots > 1 else float(w)
    if step <= 0:
        return (x, [])
    bottom = y + h

    # Sample values become pixel rows once, so the interpolation below
    # runs in pixel space with no divide in the inner loop.
    ys = []
    for v in vals:
        f = v / hi
        if f < 0.0:
            f = 0.0
        elif f > 1.0:
            f = 1.0
        ys.append(bottom - h * f)

    # The cubic is evaluated every `span` pixels, not every pixel, and
    # the gaps are filled in by walking a straight line between those
    # knots. Over three pixels a cubic and a chord are indistinguishable,
    # and evaluating it per pixel was slow enough to miss the frame rate.
    #
    # Its coefficients only change when we cross into the next segment —
    # 59 of those against a few hundred columns — so they are computed
    # per segment and each knot just evaluates them.
    knots = []
    ap = knots.append
    last = n - 2
    inv = span / step
    seg = -1
    ca = cb = cc = cd = 0.0
    u = 0.0
    cols = int((n - 1) * step)
    for _ in range(cols // span + 1):
        i = int(u)
        if i > last:
            i = last
        if i != seg:
            seg = i
            p1 = ys[i]
            p2 = ys[i + 1]
            p0 = ys[i - 1] if i > 0 else p1
            p3 = ys[i + 2] if i + 2 < n else p2
            cd = p1
            cc = 0.5 * (p2 - p0)
            cb = 0.5 * (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3)
            ca = 0.5 * (3.0 * p1 - 3.0 * p2 + p3 - p0)
        t = u - i
        yy = ((ca * t + cb) * t + cc) * t + cd
        # Catmull-Rom overshoots around a sharp corner; the graph has a
        # floor and a ceiling, so clamp rather than let it escape.
        if yy < y:
            yy = y
        elif yy > bottom:
            yy = bottom
        ap(yy)
        u += inv

    out = []
    ap = out.append
    for k in range(len(knots) - 1):
        v = knots[k]
        delta = (knots[k + 1] - v) / span
        for _ in range(span):
            ap(int(v))
            v += delta
    ap(int(knots[-1]))
    return (int(x + (slots - n) * step), out)


def curve_fill(d, pens, x0, ys, bottom, colour, shade=0.28):
    """Shade the area under a curve from curve_points().

    Columns at the same height merge into one rectangle — an idle trace
    is mostly flat, and one wide fill beats two hundred narrow ones.
    """
    if not ys:
        return
    pens.set(theme.dim(colour, shade))
    rect = d.rectangle
    n = len(ys)
    i = 0
    while i < n:
        py = ys[i]
        j = i + 1
        while j < n and ys[j] == py:
            j += 1
        if bottom > py:
            rect(x0 + i, py, j - i, bottom - py)
        i = j


def curve_line(d, pens, x0, ys, colour, thickness=2):
    """Stroke a curve from curve_points().

    Each column spans from the previous row to this one, so a steep
    climb stays joined instead of breaking into dashes.
    """
    if not ys:
        return
    pens.set(colour)
    rect = d.rectangle
    prev = ys[0]
    for i in range(len(ys)):
        py = ys[i]
        top = py if py < prev else prev
        rect(x0 + i, top, 1, abs(py - prev) + thickness)
        prev = py
