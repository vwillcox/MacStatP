"""Pages: alternative full-screen views of the same data.

The dials are one way to look at a machine; a list of sparklines, a
per-core heatmap or a network graph are others. Each page owns the whole
screen and draws its own header, and the settings decide which pages
exist and in what order.

Everything here works from `History`, which accumulates what arrives each
frame — the host sends a snapshot, not a series.
"""

import font
import theme
import widgets as W
from dashboard import fmt_bytes, fmt_net_rate, fmt_rate

SCREEN = 480
M = 6
HEADER_H = 44
DOTS_H = 20
DEPTH = 60          # samples kept per series


def _pct(v):
    return "%.1f%%" % v


def _rate(v):
    a, b = fmt_net_rate(v)
    return "%s%s" % (a, b)


def _drate(v):
    a, b = fmt_rate(v)
    return "%s%s" % (a, b)


# key -> (label, how to read it, how to show it, full-scale or None)
METRICS = {
    "cpu":       ("CPU LOAD", lambda d: d["cpu"]["pct"], _pct, 100.0),
    "cpu_peak":  ("CPU PEAK", lambda d: max(d["cpu"]["cores"] or [0]),
                  _pct, 100.0),
    "load":      ("LOAD AVG", lambda d: (d.get("load") or [0])[0],
                  lambda v: "%.2f" % v, None),
    "gpu":       ("GPU LOAD", lambda d: d["gpu"]["pct"], _pct, 100.0),
    "vram":      ("GPU VRAM", lambda d: d["gpu"]["vram"], fmt_bytes, None),
    "mem":       ("MEM USED", lambda d: d["mem"]["pct"], _pct, 100.0),
    "swap":      ("SWAP", lambda d: d["mem"]["swap"], fmt_bytes, None),
    "disk":      ("DISK USED", lambda d: d["disk"]["pct"], _pct, 100.0),
    "disk_read": ("DISK READ", lambda d: d["disk"]["r"], _drate, None),
    "disk_write": ("DISK WRITE", lambda d: d["disk"]["w"], _drate, None),
    "net_down":  ("NET DOWN", lambda d: _link_sum(d, "rx"), _rate, None),
    "net_up":    ("NET UP", lambda d: _link_sum(d, "tx"), _rate, None),
}

GLANCE_DEFAULT = ("cpu", "gpu", "mem", "disk", "net_down", "net_up")


def _link_sum(data, key):
    return sum(float(l.get(key, 0))
               for l in (data.get("net", {}).get("links") or []))


class History:
    """Keeps a rolling window of everything the pages might plot."""

    def __init__(self, depth=DEPTH):
        self.depth = depth
        self.series = {}
        self.cores = []

    def push(self, data):
        for key, (_label, read, _show, _full) in METRICS.items():
            try:
                v = float(read(data))
            except Exception:
                v = 0.0
            buf = self.series.get(key)
            if buf is None:
                buf = self.series[key] = []
            buf.append(v)
            if len(buf) > self.depth:
                del buf[0:len(buf) - self.depth]

        cores = data.get("cpu", {}).get("cores") or []
        while len(self.cores) < len(cores):
            self.cores.append([])
        del self.cores[len(cores):]
        for i, c in enumerate(cores):
            buf = self.cores[i]
            buf.append(float(c))
            if len(buf) > self.depth:
                del buf[0:len(buf) - self.depth]

    def get(self, key):
        return self.series.get(key) or []


# ── shared chrome ─────────────────────────────────────────────────────
def header(d, pens, title, host, accent=None):
    """Title on the left, machine on the right, a rule underneath."""
    pens.set(theme.TITLE)
    font.text(d, title, M + 10, 12, 24)
    if host:
        pens.set(theme.MUTED)
        font.text(d, str(host).upper(), SCREEN - M - 10, 17, 12,
                  align=font.RIGHT)
    pens.set(accent or theme.TEAL)
    d.rectangle(M + 10, HEADER_H - 8, int(SCREEN - 2 * (M + 10)), 2)
    return HEADER_H


def dots(d, pens, count, active):
    """The page indicator along the bottom."""
    if count < 2:
        return
    gap, r = 14, 3
    total = (count - 1) * gap
    x = SCREEN // 2 - total // 2
    y = SCREEN - DOTS_H // 2 - 4
    for i in range(count):
        pens.set(theme.TEAL if i == active else theme.TRACK)
        d.circle(int(x + i * gap), int(y), r if i == active else 2)


def content_box():
    return M, HEADER_H, SCREEN - 2 * M, SCREEN - HEADER_H - DOTS_H


# ── page: at a glance ─────────────────────────────────────────────────
def glance(d, pens, data, hist, keys=GLANCE_DEFAULT, host=""):
    """A row per metric: name, its recent shape, and the current value."""
    header(d, pens, "AT A GLANCE", host)
    x, y, w, h = content_box()
    keys = [k for k in keys if k in METRICS][:8] or list(GLANCE_DEFAULT)
    rh = h // len(keys)

    lw = int(max(font.width(METRICS[k][0], 13) for k in keys))
    vx = x + w - 6
    gx = int(x + 10 + lw + 14)
    gw = int(max(30, vx - 90 - gx))

    for i, key in enumerate(keys):
        label, read, show, full = METRICS[key]
        ry = y + i * rh
        if i % 2 == 0:
            pens.set(theme.ROW)
            d.rectangle(x, ry, w, rh - 1)

        pens.set(theme.TEXT)
        font.text(d, label, x + 10, ry + (rh - 13) // 2, 13)

        series = hist.get(key)
        if series:
            W.trace(d, pens, gx, ry + 7, gw, rh - 14, series,
                    theme.TEAL, peak=full, capacity=hist.depth)
        try:
            value = show(float(read(data)))
        except Exception:
            value = "-"
        pens.set(theme.TITLE)
        font.text(d, value, vx, ry + (rh - 13) // 2, 13, align=font.RIGHT)


# ── page: cores, as bars ──────────────────────────────────────────────
def cores_bars(d, pens, data, hist, host="", **_kw):
    """One bar per logical core, coloured by how busy it is."""
    header(d, pens, "CORES", host)
    x, y, w, h = content_box()
    cores = data.get("cpu", {}).get("cores") or []
    if not cores:
        pens.set(theme.MUTED)
        font.text(d, "NO CORE DATA", SCREEN // 2, y + h // 2, 15,
                  align=font.CENTER)
        return

    rh = max(8, h // len(cores))
    size = max(9, min(13, rh - 4))
    nw = int(font.width("88", size))
    vw = int(font.width("100.0%", size))
    bx = int(x + 8 + nw + 8)
    bw = int(max(20, x + w - 8 - vw - 10 - bx))
    bh = int(max(4, rh - 4))

    for i, c in enumerate(cores):
        ry = y + i * rh
        pens.set(theme.MUTED)
        font.text(d, str(i), x + 8, ry + (rh - size) // 2, size)
        pens.set(theme.TRACK)
        d.rectangle(bx, ry + (rh - bh) // 2, bw, bh)
        fill = int(bw * min(1.0, max(0.0, c) / 100.0))
        if fill > 0:
            pens.set(theme.ramp(c / 100.0))
            d.rectangle(bx, ry + (rh - bh) // 2, fill, bh)
        pens.set(theme.TEXT)
        font.text(d, "%.1f%%" % c, x + w - 8, ry + (rh - size) // 2, size,
                  align=font.RIGHT)


# ── page: cores, as a heatmap ─────────────────────────────────────────
def cores_heat(d, pens, data, hist, host="", **_kw):
    """Each core's recent history as a band of colour, oldest at the left."""
    header(d, pens, "CORES", host)
    x, y, w, h = content_box()
    rows = hist.cores
    if not rows:
        pens.set(theme.MUTED)
        font.text(d, "COLLECTING", SCREEN // 2, y + h // 2, 15,
                  align=font.CENTER)
        return

    size = max(8, min(12, (h // len(rows)) - 2))
    nw = int(font.width("88", size))
    gx = int(x + 6 + nw + 6)
    gw = int(x + w - 4 - gx)
    rh = max(3, h // len(rows))
    cols = hist.depth
    cw = max(1, int(gw / cols + 0.999))

    for i, series in enumerate(rows):
        ry = y + i * rh
        pens.set(theme.MUTED)
        font.text(d, str(i), x + 6, ry + max(0, (rh - size) // 2), size)
        # Right-aligned in time: the newest sample is always at the edge,
        # so a partly filled history grows in from the left.
        offset = cols - len(series)
        for j, v in enumerate(series):
            pens.set(theme.ramp(v / 100.0))
            d.rectangle(int(gx + (offset + j) * (gw / cols)), ry, cw,
                        max(1, rh - 1))


# ── page: network graph ───────────────────────────────────────────────
def net_graph(d, pens, data, hist, host="", **_kw):
    """Down and up over time, on a shared scale."""
    header(d, pens, "NETWORK", host)
    x, y, w, h = content_box()
    down = hist.get("net_down")
    up = hist.get("net_up")
    peak = max([1.0] + down + up)

    legend_h = 20
    gy = y + 16
    gh = h - 16 - legend_h

    # Scale marker, so the shape means something.
    pens.set(theme.MUTED)
    font.text(d, "%s/S" % fmt_bytes(peak, 0), x + 6, y, 11)
    font.text(d, "0", x + 6, gy + gh - 10, 11)

    gx = int(x + 6 + font.width("000.0M/S", 11) + 6)
    gw = int(x + w - 6 - gx)
    for frac in (0.0, 0.5, 1.0):
        pens.set(theme.dim(theme.BORDER, 1.0))
        d.rectangle(gx, int(gy + gh * frac), gw, 1)

    # Both areas first, then both lines, so neither trace ends up buried
    # under the other's fill.
    dx, dy = W.curve_points(gx, gy, gw, gh, down, peak=peak,
                            capacity=hist.depth)
    ux, uy = W.curve_points(gx, gy, gw, gh, up, peak=peak,
                            capacity=hist.depth)
    bottom = gy + gh
    W.curve_fill(d, pens, dx, dy, bottom, theme.TEAL)
    W.curve_fill(d, pens, ux, uy, bottom, theme.RED)
    W.curve_line(d, pens, dx, dy, theme.TEAL)
    W.curve_line(d, pens, ux, uy, theme.RED)

    ly = y + h - legend_h + 4
    for i, (label, colour) in enumerate((("DOWN", theme.TEAL),
                                         ("UP", theme.RED))):
        lx = gx + i * 90
        pens.set(colour)
        d.rectangle(lx, ly + 3, 10, 6)
        pens.set(theme.MUTED)
        font.text(d, label, lx + 16, ly, 11)


RENDERERS = {
    "glance": glance,
    "cores_bars": cores_bars,
    "cores_heat": cores_heat,
    "net_graph": net_graph,
}

TITLES = {
    "glance": "At a glance",
    "cores_bars": "Cores, as bars",
    "cores_heat": "Cores, as a heatmap",
    "net_graph": "Network graph",
    "dials": "Dials",
}
