"""The 480x480 status panel.

Rendering is split in two so the loop can run fast:

  _chrome   panel outlines, titles and fixed labels — drawn once
  _values   the readings themselves — redrawn every frame, each erasing
            only its own small box

Repainting all five card backgrounds every frame cost ~100 ms on its own,
which capped the display at about two updates a second.

Runs identically on the Presto and under tools/preview.py, so layout can
be iterated on the Mac and confirmed on hardware.
"""

import font
import theme
import widgets as W

SCREEN = 480
M = 6           # outer margin
GAP = 6

ROW1_Y, ROW1_H = 6, 190
ROW2_Y, ROW2_H = 202, 140
ROW3_Y, ROW3_H = 348, 126
COL_W = (SCREEN - M * 2 - GAP) // 2      # 231
COL2_X = M + COL_W + GAP                 # 243
FULL_W = SCREEN - M * 2                  # 468

HISTORY = 64  # samples kept for the sparklines

# Short titles: the close hint sits on the same line, and the headline
# underneath already says what the list is.
TITLES = {
    "cpu": "CPU",
    "gpu": "GPU",
    "mem": "MEMORY",
    "disk": "DISK",
    "net": "NETWORK",
}

# Shared column geometry for the two top cards.
TOP_CX = 108
TOP_CW = COL_W - TOP_CX - 12
ROW_A = 54       # first meter label
ROW_B = 95       # second meter label
PLOT_LABEL = 137
PLOT_Y = 154
PLOT_H = 24

MEM_CX = 100
MEM_CW = COL_W - MEM_CX - 12
MEM_ROWS = ("USED", "TOTAL", "WIRED", "COMP", "SWAP")
MEM_ROW_Y = 48
MEM_ROW_STEP = 17

DISK_CX = 14
DISK_CW = COL_W - 28


def fmt_bytes(n, places=1):
    """Compact size, e.g. 12.2G / 940M."""
    n = float(n or 0)
    if n <= 0:
        return "0"
    for unit, div in (("T", 1024.0 ** 4), ("G", 1024.0 ** 3),
                      ("M", 1024.0 ** 2), ("K", 1024.0)):
        if n >= div:
            v = n / div
            return ("%.0f%s" % (v, unit)) if v >= 100 or places == 0 else \
                   ("%.1f%s" % (v, unit))
    return "%dB" % int(n)


def fmt_rate(bps):
    """Split a byte rate into (number, unit) so they can be styled apart."""
    b = float(bps or 0)
    if b >= 1024.0 ** 3:
        return "%.1f" % (b / 1024.0 ** 3), "GB/S"
    if b >= 1024.0 ** 2:
        return "%.1f" % (b / 1024.0 ** 2), "MB/S"
    if b >= 1024.0:
        return "%.0f" % (b / 1024.0), "KB/S"
    return "%d" % int(b), "B/S"


def fit(s, size, maxw):
    """Trim text to fit maxw pixels, marking the cut with a full stop."""
    if font.width(s, size) <= maxw:
        return s
    while s and font.width(s + ".", size) > maxw:
        s = s[:-1]
    return (s + ".") if s else ""


def fmt_uptime(sec):
    sec = int(sec or 0)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return "UP %dD %dH" % (d, h)
    if h:
        return "UP %dH %dM" % (h, m)
    return "UP %dM" % m


class Dashboard:
    def __init__(self, display, pens):
        self.d = display
        self.p = pens
        self.cpu_hist = []
        self.gpu_hist = []
        self.links = {}     # device name -> recent total throughput
        self._mode = None
        self._lit = {}      # gauge id -> lit segment count from last frame
        self._last = {}     # field id -> value drawn last frame

    # ── history ───────────────────────────────────────────────────────
    @staticmethod
    def _add(buf, v):
        buf.append(v)
        if len(buf) > HISTORY:
            del buf[0:len(buf) - HISTORY]

    def push(self, data):
        self._add(self.cpu_hist, float(data.get("cpu", {}).get("pct", 0)))
        self._add(self.gpu_hist, float(data.get("gpu", {}).get("pct", 0)))
        for ln in data.get("net", {}).get("links", []) or []:
            dev = ln.get("d", "?")
            buf = self.links.get(dev)
            if buf is None:
                buf = self.links[dev] = []
            self._add(buf, float(ln.get("rx", 0)) + float(ln.get("tx", 0)))

    def seed(self, links):
        """Restore sparkline history saved on the SD card across reboots."""
        if isinstance(links, dict):
            for dev, vals in links.items():
                self.links[dev] = [float(v) for v in vals][-HISTORY:]

    # ── helpers ───────────────────────────────────────────────────────
    def _clr(self, x, y, w, h, colour=None):
        self.p.set(colour or theme.CARD)
        self.d.rectangle(int(x), int(y), int(w), int(h))

    # ── frame ─────────────────────────────────────────────────────────
    def render(self, data, linked=True, full=False):
        if full or self._mode != "dash":
            self._chrome(data)
            self._mode = "dash"
            self._lit = {}
            self._last = {}
        self._cpu(data)
        self._gpu(data)
        self._mem(data)
        self._disk(data)
        self._net(data)

    def _chrome(self, data):
        """Panels and fixed labels. Everything here is frame-invariant."""
        d, p = self.d, self.p
        p.set(theme.BG)
        d.clear()

        for x, y, w, h, title, accent in (
                (M, ROW1_Y, COL_W, ROW1_H, "CPU", theme.ACCENT["cpu"]),
                (COL2_X, ROW1_Y, COL_W, ROW1_H, "GPU", theme.ACCENT["gpu"]),
                (M, ROW2_Y, COL_W, ROW2_H, "MEMORY", theme.ACCENT["mem"]),
                (COL2_X, ROW2_Y, COL_W, ROW2_H, "DISK", theme.ACCENT["disk"]),
                (M, ROW3_Y, FULL_W, ROW3_H, "NETWORK", theme.ACCENT["rx"])):
            W.card(d, p, x, y, w, h, title, accent=accent)

        for x, a, b, plot in ((M, "LOAD", "PEAK", "CORES"),
                              (COL2_X, "VRAM", "PEAK", "HISTORY")):
            cx = x + TOP_CX
            W.meter_label(d, p, cx, ROW1_Y + ROW_A, a)
            W.meter_label(d, p, cx, ROW1_Y + ROW_B, b)
            p.set(theme.MUTED)
            font.text(d, plot, cx, ROW1_Y + PLOT_LABEL, 12)

        cx = M + MEM_CX
        for i, label in enumerate(MEM_ROWS):
            p.set(theme.MUTED)
            font.text(d, label, cx, ROW2_Y + MEM_ROW_Y + i * MEM_ROW_STEP, 12)

        dx = COL2_X + DISK_CX
        for i, label in enumerate(("READ", "WRITE")):
            p.set(theme.MUTED)
            font.text(d, label, dx, ROW2_Y + 110 + i * 16, 12)

    # ── panels ────────────────────────────────────────────────────────
    def _cpu(self, data):
        d, p = self.d, self.p
        x, y = M, ROW1_Y
        cpu = data.get("cpu", {})
        cores = cpu.get("cores", []) or []
        ncpu = max(1, int(cpu.get("n", 1)))
        load = (data.get("load") or [0, 0, 0])[0]
        peak = max(cores) if cores else 0.0

        self._lit["cpu"] = W.gauge(d, p, x + 58, y + 114, 50,
                                   float(cpu.get("pct", 0)), "CPU %",
                                   self._lit.get("cpu"))

        cx = x + TOP_CX
        W.meter_value(d, p, cx, y + ROW_A, TOP_CW, "%.2f" % load,
                      min(1.0, load / ncpu), theme.ACCENT["cpu"])
        W.meter_value(d, p, cx, y + ROW_B, TOP_CW, "%d%%" % int(peak),
                      peak / 100.0, theme.heat(peak / 100.0))

        # Per-core ticks: one slim column per logical core. Each cell
        # repaints its own track, so no separate erase is needed.
        by, bh = y + PLOT_Y, PLOT_H
        cell = TOP_CW / float(max(1, len(cores))) if cores else TOP_CW
        for i, c in enumerate(cores):
            ch = max(2, int(bh * min(1.0, c / 100.0)))
            bx = int(cx + i * cell)
            bw = max(1, int(cell) - 1)
            p.set(theme.TRACK)
            d.rectangle(bx, by, bw, bh)
            p.set(theme.heat(c / 100.0))
            d.rectangle(bx, by + bh - ch, bw, ch)

    def _gpu(self, data):
        d, p = self.d, self.p
        x, y = COL2_X, ROW1_Y
        gpu = data.get("gpu", {})
        pct = float(gpu.get("pct", 0))
        vram = int(gpu.get("vram", 0))
        total = int(data.get("mem", {}).get("total", 0)) or 1
        peak = max(self.gpu_hist) if self.gpu_hist else pct

        self._lit["gpu"] = W.gauge(d, p, x + 58, y + 114, 50, pct, "GPU %",
                                   self._lit.get("gpu"))

        cx = x + TOP_CX
        W.meter_value(d, p, cx, y + ROW_A, TOP_CW, fmt_bytes(vram),
                      min(1.0, vram / float(total)), theme.ACCENT["gpu"])
        W.meter_value(d, p, cx, y + ROW_B, TOP_CW, "%d%%" % int(peak),
                      peak / 100.0, theme.heat(peak / 100.0))

        self._clr(cx, y + PLOT_Y, TOP_CW, PLOT_H)
        W.sparkline(d, p, cx, y + PLOT_Y, TOP_CW, PLOT_H, self.gpu_hist,
                    theme.ACCENT["gpu"], peak=100.0, capacity=HISTORY)

    def _mem(self, data):
        d, p = self.d, self.p
        x, y = M, ROW2_Y
        mem = data.get("mem", {})

        self._lit["mem"] = W.gauge(d, p, x + 54, y + 90, 42,
                                   float(mem.get("pct", 0)), "RAM %",
                                   self._lit.get("mem"))

        cx = x + MEM_CX
        vals = (mem.get("used"), mem.get("total"), mem.get("wired"),
                mem.get("comp"), mem.get("swap"))
        self._clr(cx + MEM_CW - 58, y + MEM_ROW_Y - 2, 58,
                  len(MEM_ROWS) * MEM_ROW_STEP)
        p.set(theme.TEXT)
        for i, v in enumerate(vals):
            font.text(d, fmt_bytes(v), cx + MEM_CW,
                      y + MEM_ROW_Y + i * MEM_ROW_STEP, 12, align=font.RIGHT)

    def _disk(self, data):
        d, p = self.d, self.p
        x, y = COL2_X, ROW2_Y
        dk = data.get("disk", {})
        pct = float(dk.get("pct", 0))
        cx, cw = x + DISK_CX, DISK_CW

        val = "%d" % int(round(pct))
        self._clr(cx, y + 44, 115, 38)
        p.set(theme.WHITE)
        font.text(d, val, cx, y + 46, 34)
        p.set(theme.MUTED)
        font.text(d, "%", cx + font.width(val, 34) + 5, y + 60, 17)

        self._clr(cx + cw - 92, y + 44, 92, 36)
        p.set(theme.TEXT)
        font.text(d, fmt_bytes(dk.get("used")), cx + cw, y + 46, 14,
                  align=font.RIGHT)
        p.set(theme.MUTED)
        font.text(d, "OF " + fmt_bytes(dk.get("total")), cx + cw, y + 66, 12,
                  align=font.RIGHT)

        W.bar(d, p, cx, y + 90, cw, 12, pct / 100.0, theme.heat(pct / 100.0))

        rv, ru = fmt_rate(dk.get("r"))
        wv, wu = fmt_rate(dk.get("w"))
        for i, (txt, colour) in enumerate((("%s %s" % (rv, ru), theme.CYAN),
                                           ("%s %s" % (wv, wu), theme.AMBER))):
            yy = y + 110 + i * 16
            self._clr(cx + cw - 100, yy - 2, 100, 16)
            p.set(colour)
            font.text(d, txt, cx + cw, yy, 12, align=font.RIGHT)

    def _net(self, data):
        """One row per interface: Wi-Fi and the live wired link."""
        d, p = self.d, self.p
        x, y, w = M, ROW3_Y, FULL_W
        links = data.get("net", {}).get("links", []) or []

        for i in range(2):
            ry = y + 46 + i * 40
            self._clr(x + 8, ry, w - 16, 32)
            if i >= len(links):
                continue
            ln = links[i]
            up = bool(ln.get("up", 1))
            dev = str(ln.get("d", "")).upper()

            p.set(theme.TEXT if up else theme.MUTED)
            font.text(d, str(ln.get("n", "NET")).upper(), x + 16, ry + 2, 15)
            p.set(theme.MUTED)
            font.text(d, dev, x + 16, ry + 20, 11)
            if not up:
                font.text(d, "DOWN", x + 62, ry + 20, 11)

            for j, (key, arrow, colour) in enumerate(
                    (("rx", "\x11", theme.ACCENT["rx"]),
                     ("tx", "\x10", theme.ACCENT["tx"]))):
                bx = x + 106 + j * 144
                val, unit = fmt_rate(ln.get(key, 0))
                p.set(colour if up else theme.TRACK)
                font.text(d, arrow, bx, ry + 5, 16)
                p.set(theme.TEXT if up else theme.MUTED)
                vx = bx + 20
                font.text(d, val, vx, ry + 2, 22)
                p.set(theme.MUTED)
                font.text(d, unit, vx + font.width(val, 22) + 5, ry + 13, 11)

            # Each row scales to its own history: a quiet Wi-Fi link stays
            # readable next to a busy wired one.
            W.sparkline(d, p, x + 392, ry + 2, 60, 26,
                        self.links.get(dev, []), theme.ACCENT["rx"],
                        capacity=HISTORY)

    # ── drill-down ────────────────────────────────────────────────────
    def hit_test(self, x, y):
        """Which panel is under a touch, or None."""
        for name, bx, by, bw, bh in (
                ("cpu", M, ROW1_Y, COL_W, ROW1_H),
                ("gpu", COL2_X, ROW1_Y, COL_W, ROW1_H),
                ("mem", M, ROW2_Y, COL_W, ROW2_H),
                ("disk", COL2_X, ROW2_Y, COL_W, ROW2_H),
                ("net", M, ROW3_Y, FULL_W, ROW3_H)):
            if bx <= x < bx + bw and by <= y < by + bh:
                return name
        return None

    def detail(self, view, data, det):
        """Full-screen breakdown for one panel.

        `det` is the host's drill-down block; until the first one arrives
        the screen still renders, showing the summary and a waiting note.
        """
        d, p = self.d, self.p
        if self._mode != "detail:" + view:
            p.set(theme.BG)
            d.clear()
            self._mode = "detail:" + view
            self._last = {}
            W.card(d, p, M, M, FULL_W, SCREEN - M * 2,
                   TITLES.get(view, view.upper()),
                   subtitle="TAP TO CLOSE",
                   accent=theme.ACCENT.get(view, theme.CYAN))

        x = M + 16
        w = FULL_W - 32
        rows = (det or {}).get("rows") or []
        headline = self._headline(view, data)

        # The host only refreshes process listings about once a second, so
        # skip the repaint entirely while nothing on screen would change.
        sig = (headline, len(rows),
               "".join("%s%s" % (r.get("n"), self._row_label(view, r))
                       for r in rows[:9]))
        if self._last.get("sig") == sig:
            return
        self._last["sig"] = sig

        self._clr(x, 52, w, SCREEN - M - 60)
        p.set(theme.TEXT)
        font.text(d, headline, x, 54, 15)
        if view == "gpu":
            self._gpu_detail(x, w, det, data)
            return
        if not rows:
            p.set(theme.MUTED)
            font.text(d, "COLLECTING...", x, 100, 14)
            return

        # Volumes are compared by how full they are; everything else by
        # its share of the busiest entry.
        top = 100.0 if view == "disk" else max(
            [self._row_value(view, r) for r in rows] + [1.0])
        yy = 86
        for r in rows[:9]:
            val = self._row_value(view, r)
            label = self._row_label(view, r)
            lw = font.width(label, 13)
            p.set(theme.MUTED)
            font.text(d, label, x + w, yy, 13, align=font.RIGHT)
            p.set(theme.TEXT)
            font.text(d, fit(r.get("n", "?"), 14, w - lw - 12), x, yy, 14)
            W.bar(d, p, x, yy + 19, w, 8, val / top,
                  theme.ACCENT.get(view, theme.CYAN))
            yy += 41

    @staticmethod
    def _row_value(view, r):
        if view == "net":
            return float(r.get("i", 0)) + float(r.get("o", 0))
        return float(r.get("v", 0))

    @staticmethod
    def _row_label(view, r):
        if view == "cpu":
            return "%.1f%%  PID %d" % (r.get("v", 0), r.get("p", 0))
        if view == "mem":
            return "%s  PID %d" % (fmt_bytes(r.get("v")), r.get("p", 0))
        if view == "net":
            iv, iu = fmt_rate(r.get("i", 0))
            ov, ou = fmt_rate(r.get("o", 0))
            return "\x11%s%s  \x10%s%s" % (iv, iu, ov, ou)
        if view == "disk":
            return "%s OF %s  %.0f%%" % (fmt_bytes(r.get("u")),
                                         fmt_bytes(r.get("t")),
                                         r.get("v", 0))
        return ""

    @staticmethod
    def _headline(view, data):
        cpu = data.get("cpu", {})
        mem = data.get("mem", {})
        if view == "cpu":
            return "%d%% OF %d CORES   LOAD %.2f" % (
                int(cpu.get("pct", 0)), cpu.get("n", 0),
                (data.get("load") or [0])[0])
        if view == "mem":
            return "%s USED OF %s   %d%%" % (
                fmt_bytes(mem.get("used")), fmt_bytes(mem.get("total")),
                int(mem.get("pct", 0)))
        if view == "net":
            return "TOP TALKERS BY THROUGHPUT"
        if view == "disk":
            return "MOUNTED VOLUMES"
        return "GPU ENGINES"

    def _gpu_detail(self, x, w, det, data):
        d, p = self.d, self.p
        g = (det or {}).get("gpu") or {}
        total = int(data.get("mem", {}).get("total", 0)) or 1
        yy = 92
        for label, val, frac in (
                ("DEVICE", "%d%%" % g.get("device", 0),
                 g.get("device", 0) / 100.0),
                ("RENDERER", "%d%%" % g.get("render", 0),
                 g.get("render", 0) / 100.0),
                ("TILER", "%d%%" % g.get("tiler", 0),
                 g.get("tiler", 0) / 100.0),
                ("VRAM IN USE", fmt_bytes(g.get("inuse")),
                 g.get("inuse", 0) / total),
                ("VRAM ALLOCATED", fmt_bytes(g.get("alloc")),
                 g.get("alloc", 0) / total),
                ("PARAMETER BUFFER", fmt_bytes(g.get("pb")),
                 g.get("pb", 0) / total)):
            p.set(theme.TEXT)
            font.text(d, label, x, yy, 15)
            p.set(theme.MUTED)
            font.text(d, val, x + w, yy, 15, align=font.RIGHT)
            W.bar(d, p, x, yy + 21, w, 9, min(1.0, frac), theme.ACCENT["gpu"])
            yy += 56

    # ── standby ───────────────────────────────────────────────────────
    def splash(self, title, lines, colour=None):
        """Full-screen notice, used before the host link comes up."""
        d, p = self.d, self.p
        p.set(theme.BG)
        d.clear()
        self._mode = "splash"
        W.card(d, p, M, 150, FULL_W, 180)
        p.set(colour or theme.CYAN)
        font.text(d, title, SCREEN // 2, 186, 34, align=font.CENTER)
        yy = 244
        for ln in lines:
            p.set(theme.MUTED)
            font.text(d, ln, SCREEN // 2, yy, 15, align=font.CENTER)
            yy += 24
