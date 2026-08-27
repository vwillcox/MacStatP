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
# Between cards. Not smaller: at 2 the two card borders meet and read as
# one thick rule, and the panels stop looking separate.
GAP = 3
FULL_W = SCREEN - M * 2

HISTORY = 64  # samples kept for the sparklines

# Room kept clear at the bottom for the page indicator, when there is
# more than one page. Set by main.py.
BOTTOM_INSET = 0

# Panels can be switched off individually, so nothing here assumes a
# fixed grid: whatever is enabled is packed into rows that fill the
# screen, and each panel lays its contents out from the box it is given.
PANEL_ORDER = ("cpu", "gpu", "mem", "disk", "net")
ALWAYS_FULL_WIDTH = ("net",)   # two interface rows; too cramped in half

# Relative row heights when several rows share the screen. A row takes the
# largest weight among its panels. The four dials want the same room as
# each other; the network needs less, since it is two lines of text.
ROW_WEIGHT = {"cpu": 1.0, "gpu": 1.0, "mem": 1.0, "disk": 1.0, "net": 0.72}

TITLES = {
    "cpu": "CPU",
    "gpu": "GPU",
    "mem": "MEMORY",
    "disk": "DISK",
    "net": "NETWORK",
}

TITLE_H = 44    # card title and its hairline
PAD = 12        # inside a card


def pack(enabled):
    """Lay the enabled panels out over the whole screen.

    Pairs share a row; a panel that must be full width, or a leftover odd
    one, gets a row to itself. Row heights are shared out by weight, and
    the last row is stretched to the bottom margin so rounding cannot
    leave a gap.
    """
    # `enabled` is an ordered sequence: the running order is chosen in
    # the settings, so it is followed rather than sorted into a canonical
    # one. Anything unrecognised is skipped.
    keys, seen = [], set()
    for k in enabled or ():
        if k in ROW_WEIGHT and k not in seen:
            seen.add(k)
            keys.append(k)
    rows, pending = [], []
    for k in keys:
        if k in ALWAYS_FULL_WIDTH:
            if pending:
                rows.append(pending)
                pending = []
            rows.append([k])
        else:
            pending.append(k)
            if len(pending) == 2:
                rows.append(pending)
                pending = []
    if pending:
        rows.append(pending)
    if not rows:
        return {}

    bottom = SCREEN - M - BOTTOM_INSET
    avail = bottom - M - GAP * (len(rows) - 1)
    weights = [max(ROW_WEIGHT.get(k, 1.0) for k in row) for row in rows]
    total = sum(weights) or 1.0

    out = {}
    y = M
    for i, row in enumerate(rows):
        if i == len(rows) - 1:
            h = bottom - y              # absorb the rounding
        else:
            h = int(avail * weights[i] / total)
        n = len(row)
        w = (SCREEN - M * 2 - GAP * (n - 1)) // n
        x = M
        for k in row:
            out[k] = (x, y, w, h)
            x += w + GAP
        y += h + GAP
    return out


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


NET_BITS = False   # set from the host's settings


def set_net_units(bits):
    global NET_BITS
    NET_BITS = bool(bits)


def fmt_net_rate(bps):
    """Network throughput, in bits or bytes depending on the setting."""
    if not NET_BITS:
        return fmt_rate(bps)
    # BPS rather than BIT/S: the long form is wide enough to collide with
    # the next column in the network panel.
    b = float(bps or 0) * 8.0
    if b >= 1000.0 ** 3:
        return "%.1f" % (b / 1000.0 ** 3), "GBPS"
    if b >= 1000.0 ** 2:
        return "%.1f" % (b / 1000.0 ** 2), "MBPS"
    if b >= 1000.0:
        return "%.0f" % (b / 1000.0), "KBPS"
    return "%d" % int(b), "BPS"


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
        self._net_rows = 2  # interfaces the network panel last drew
        self.panels = PANEL_ORDER
        self._rects = {}
        self._geom = {}
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

    _DRAW = {}          # both filled in below, once the methods exist
    _GEOM = {}

    def invalidate(self):
        """Force a full repaint.

        The renderer skips anything whose text is unchanged, so a change
        in formatting has to drop those caches or stale units would stay
        on screen.
        """
        self._mode = None
        self._lit = {}
        self._last = {}

    # ── helpers ───────────────────────────────────────────────────────
    def _clr(self, x, y, w, h, colour=None):
        self.p.set(colour or theme.CARD)
        self.d.rectangle(int(x), int(y), int(w), int(h))

    # ── geometry ──────────────────────────────────────────────────────
    # Each panel works out its contents from the box it is handed, so the
    # same code draws a half-width card and a full-screen one. Where
    # there is more room than the contents need, the surplus goes into
    # the gaps and what is left is centred, rather than stretching
    # everything or stranding it at the top.

    @staticmethod
    def _gauge_geom(x, y, w, h):
        """A single dial, centred in whatever box the panel is given.

        The main screen is meant to be read at a glance from across a
        desk, so each panel carries its headline figure and nothing else;
        the breakdown is a tap away. It also means a panel has nothing
        that can fail to fit — a dial simply scales.
        """
        top = y + TITLE_H
        bottom = y + h - PAD
        # No floor on the radius: forcing a minimum is what used to push
        # content past the edge of a short card. Below the point where a
        # dial could be read at all, draw nothing and leave the title.
        r = int(min((bottom - top) * 0.48, w * 0.40, 112))
        return {"cx": x + w // 2, "cy": (top + bottom) // 2,
                "r": r if r >= 12 else 0}

    @staticmethod
    def _net_geom(x, y, w, h, rows=2):
        top = y + TITLE_H
        avail = y + h - PAD - top
        row_h = avail // max(1, rows)
        sx = x + int(w * 0.80)
        # A short card cannot fit a name, a device and a rate stacked up.
        # Below this the device line goes and everything sits on one
        # baseline, rather than the two rows drawing over each other.
        compact = row_h < 34
        vsize = max(13, min(24, int(row_h * 0.62)))
        lsize = max(11, min(15, row_h - 4))
        return {"top": top, "avail": avail, "rows": rows,
                "row_h": row_h, "compact": compact,
                "lx": x + PAD + 4, "lsize": lsize,
                "rx": x + int(w * 0.22), "tx": x + int(w * 0.52),
                "sx": sx, "sw": max(24, x + w - PAD - sx),
                "sh": max(8, min(row_h - 6, 60)),
                "vsize": vsize,
                # The arrow and the unit have to live inside the row too.
                # At full size the arrow was taller than a short row and
                # got clipped away, and the unit's vertical offset put it
                # in the row below.
                "asize": max(9, min(16, vsize)),
                "usize": max(9, min(11, vsize - 2))}

    # ── frame ─────────────────────────────────────────────────────────
    def set_panels(self, panels):
        """Choose which panels are shown. Order is fixed; membership isn't."""
        want = tuple(k for k in (panels or ()) if k in ROW_WEIGHT)
        if want != self.panels:
            self.panels = want
            self.invalidate()

    def render(self, data, linked=True, full=False):
        if full or self._mode != "dash":
            self._chrome(data)
            self._mode = "dash"
            self._lit = {}
            self._last = {}
            self._net_rows = 2
        for key in self.panels:
            rect = self._rects.get(key)
            if not rect:
                continue
            # Clip to the card. The panels are careful about their own
            # bounds, but a belt as well as braces: a panel that gets its
            # arithmetic wrong should draw itself badly, not scribble over
            # its neighbour.
            x, y, w, h = rect
            self.d.set_clip(x, y, w, h)
            try:
                self._DRAW[key](self, data, x, y, w, h)
            finally:
                self.d.remove_clip()

    def _chrome(self, data):
        """Panels and fixed labels. Everything here is frame-invariant."""
        d, p = self.d, self.p
        p.set(theme.BG)
        d.clear()
        self._rects = pack(self.panels)
        # Worked out once per layout: measuring text to size the columns
        # is not something to repeat six times a second.
        self._geom = {k: self._GEOM[k](*r) for k, r in self._rects.items()}

        if not self._rects:
            p.set(theme.MUTED)
            font.text(d, "ALL PANELS ARE OFF", SCREEN // 2, 216, 22,
                      align=font.CENTER)
            font.text(d, "ENABLE ONE IN SETTINGS", SCREEN // 2, 250, 13,
                      align=font.CENTER)
            return

        for key, (x, y, w, h) in self._rects.items():
            W.card(d, p, x, y, w, h, TITLES[key],
                   accent=theme.ACCENT.get(key, theme.CYAN))

    # ── panels ────────────────────────────────────────────────────────
    def _dial(self, key, pct, caption):
        g = self._geom[key]
        if not g["r"]:
            return
        self._lit[key] = W.gauge(self.d, self.p, g["cx"], g["cy"], g["r"],
                                 pct, caption, self._lit.get(key))

    def _cpu(self, data, x, y, w, h):
        self._dial("cpu", float(data.get("cpu", {}).get("pct", 0)), "CPU %")

    def _gpu(self, data, x, y, w, h):
        self._dial("gpu", float(data.get("gpu", {}).get("pct", 0)), "GPU %")

    def _mem(self, data, x, y, w, h):
        self._dial("mem", float(data.get("mem", {}).get("pct", 0)), "RAM %")

    def _disk(self, data, x, y, w, h):
        self._dial("disk", float(data.get("disk", {}).get("pct", 0)), "DISK %")

    def _net(self, data, x, y, w, h):
        """One row per live interface.

        A link that is down is not sent at all, so a machine with Wi-Fi
        switched off shows one row using the whole card rather than a
        dead row taking up half of it.
        """
        d, p = self.d, self.p
        links = data.get("net", {}).get("links", []) or []
        rows = max(1, len(links))
        if rows != self._net_rows:
            # The row count changed, so whatever was drawn before has to
            # go before the new layout is drawn over it.
            self._net_rows = rows
            self._geom["net"] = self._net_geom(x, y, w, h, rows)
            self._clr(x + 4, y + TITLE_H - 2, w - 8,
                      y + h - PAD - (y + TITLE_H) + 4)
        g = self._geom["net"]
        vsize = g["vsize"]

        if not links:
            p.set(theme.MUTED)
            font.text(d, "NO ACTIVE LINKS", x + w // 2,
                      g["top"] + g["avail"] // 2 - 8, 15, align=font.CENTER)
            return

        # Each interface owns a band; its contents sit in the middle of
        # it rather than at the top, so a tall NETWORK card doesn't leave
        # both rows stranded against their titles.
        content_h = min(g["row_h"],
                        max(g["sh"], vsize + 6,
                            34 if not g["compact"] else g["lsize"] + 4))
        for i in range(2):
            band = g["top"] + i * g["row_h"]
            self._clr(x + 8, band, w - 16, g["row_h"] - 2)
            ry = band + max(0, (g["row_h"] - content_h) // 2)
            if i >= len(links):
                continue
            ln = links[i]
            up = bool(ln.get("up", 1))
            dev = str(ln.get("d", "")).upper()

            p.set(theme.TEXT if up else theme.MUTED)
            name = str(ln.get("n", "NET")).upper()
            font.text(d, name, g["lx"], ry, g["lsize"])
            p.set(theme.MUTED)
            if g["compact"]:
                # No room underneath, so the down marker follows the name.
                if not up:
                    font.text(d, "DOWN",
                              g["lx"] + font.width(name, g["lsize"]) + 6,
                              ry + 2, 10)
            else:
                font.text(d, dev, g["lx"], ry + 18, 11)
                if not up:
                    font.text(d, "DOWN", g["lx"] + 46, ry + 18, 11)

            for key, arrow, colour, bx in (
                    ("rx", "\x11", theme.ACCENT["rx"], g["rx"]),
                    ("tx", "\x10", theme.ACCENT["tx"], g["tx"])):
                val, unit = fmt_net_rate(ln.get(key, 0))
                p.set(colour if up else theme.TRACK)
                font.text(d, arrow, bx, ry + (vsize - g["asize"]) // 2 + 2,
                          g["asize"])
                p.set(theme.TEXT if up else theme.MUTED)
                vx = bx + 20
                font.text(d, val, vx, ry, vsize)
                p.set(theme.MUTED)
                # Sit the unit on the value's baseline rather than below
                # it, so a short row cannot push it into the next one.
                usize = g["usize"]
                uy = ry + (vsize - usize) if g["compact"] else ry + vsize * 0.5
                font.text(d, unit, vx + font.width(val, vsize) + 5,
                          uy, usize)

            # Each row scales to its own history: a quiet Wi-Fi link stays
            # readable next to a busy wired one.
            W.sparkline(d, p, g["sx"], ry, g["sw"], g["sh"],
                        self.links.get(dev, []), theme.ACCENT["rx"],
                        capacity=HISTORY)

    # ── drill-down ────────────────────────────────────────────────────
    def hit_test(self, x, y):
        """Which panel is under a touch, or None."""
        for name, (bx, by, bw, bh) in self._rects.items():
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
            iv, iu = fmt_net_rate(r.get("i", 0))
            ov, ou = fmt_net_rate(r.get("o", 0))
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
            cores = cpu.get("cores") or [0]
            return "%d%% OF %d CORES  LOAD %.2f  PEAK %d%%" % (
                int(cpu.get("pct", 0)), cpu.get("n", 0),
                (data.get("load") or [0])[0], int(max(cores)))
        if view == "mem":
            return "%s OF %s  WIRED %s  COMP %s" % (
                fmt_bytes(mem.get("used")), fmt_bytes(mem.get("total")),
                fmt_bytes(mem.get("wired")), fmt_bytes(mem.get("comp")))
        if view == "net":
            return "TOP TALKERS BY THROUGHPUT"
        if view == "disk":
            dk = data.get("disk", {})
            rv, ru = fmt_rate(dk.get("r"))
            wv, wu = fmt_rate(dk.get("w"))
            return "%s OF %s  READ %s%s  WRITE %s%s" % (
                fmt_bytes(dk.get("used")), fmt_bytes(dk.get("total")),
                rv, ru, wv, wu)
        gpu = data.get("gpu", {})
        return "%d%%  VRAM %s" % (int(gpu.get("pct", 0)),
                                  fmt_bytes(gpu.get("vram")))

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


Dashboard._GEOM = {
    "cpu": Dashboard._gauge_geom,
    "gpu": Dashboard._gauge_geom,
    "mem": Dashboard._gauge_geom,
    "disk": Dashboard._gauge_geom,
    "net": Dashboard._net_geom,
}

Dashboard._DRAW = {
    "cpu": Dashboard._cpu,
    "gpu": Dashboard._gpu,
    "mem": Dashboard._mem,
    "disk": Dashboard._disk,
    "net": Dashboard._net,
}
