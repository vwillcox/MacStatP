"""Render the real dashboard code to a PNG on the Mac.

Implements just enough of the PicoGraphics surface for device/dashboard.py
to run unmodified, so layout can be iterated without flashing the board.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "device"))

from raster import Canvas


class _MicroPythonShim:
    """device/font.py is decorated with @micropython.native; under CPython
    the decorator just needs to return the function unchanged."""

    @staticmethod
    def native(fn):
        return fn

    @staticmethod
    def viper(fn):
        return fn


import builtins
builtins.micropython = _MicroPythonShim


def _whole(*values):
    """PicoGraphics rejects float coordinates; the shim used not to.

    That difference hid a whole class of bug: previews rendered
    perfectly and the board raised TypeError on the same code. The shim
    is strict now, so a preview fails where the hardware would.
    """
    for v in values:
        if isinstance(v, float) and v != int(v):
            raise TypeError(
                "PicoGraphics needs whole pixels, got %r — round it before "
                "drawing" % (v,))


class ShimDisplay:
    """PicoGraphics-compatible façade over the software rasteriser."""

    def __init__(self, w=480, h=480):
        self.cv = Canvas(w, h)
        self._pen = (255, 255, 255)
        self._w, self._h = w, h

    def get_bounds(self):
        return self._w, self._h

    def create_pen(self, r, g, b):
        return (r, g, b)

    def set_pen(self, pen):
        self._pen = pen

    def clear(self):
        self.cv.fill_all(self._pen)

    def set_clip(self, x, y, w, h):
        self.cv.set_clip(int(x), int(y), int(w), int(h))

    def remove_clip(self):
        self.cv.remove_clip()

    def rectangle(self, x, y, w, h):
        _whole(x, y, w, h)
        self.cv.rect(int(x), int(y), int(w), int(h), self._pen)

    def polygon(self, pts):
        self.cv.polygon([(float(a), float(b)) for a, b in pts], self._pen)

    def circle(self, x, y, r):
        _whole(x, y, r)
        self.cv.circle(int(x), int(y), int(r), self._pen)

    def line(self, x0, y0, x1, y1, t=1):
        self.cv.rect(int(min(x0, x1)), int(min(y0, y1)),
                     max(int(abs(x1 - x0)), t), max(int(abs(y1 - y0)), t),
                     self._pen)

    def save(self, path):
        self.cv.save(path)


def sample_data():
    import math
    cores = [round(50 + 45 * math.sin(i * 0.9), 1) for i in range(10)]
    return {
        "host": "MAC MINI",
        "model": "Apple M4",
        "uptime": 88336,
        "load": [3.33, 2.60, 2.33],
        "cpu": {"pct": 62.4, "cores": cores, "n": 10},
        "gpu": {"pct": 38.0, "vram": 832241664},
        "mem": {"pct": 76.5, "used": 13145079808, "total": 17179869184,
                "wired": 2624241664, "comp": 4248993792, "swap": 0},
        "disk": {"pct": 90.4, "used": 221593337856, "total": 245107195904,
                 "r": 436441.0, "w": 1395920.0},
        "net": {"rx": 6711157.0, "tx": 1671869.0, "links": [
            {"n": "WI-FI", "d": "EN1", "rx": 1240, "tx": 880, "up": 1},
            {"n": "LAN", "d": "EN11", "rx": 6711157, "tx": 1671869, "up": 1},
        ]},
    }


def main():
    import math
    import dashboard
    import theme

    d = ShimDisplay()
    pens = theme.Pens(d)
    db = dashboard.Dashboard(d, pens)

    data = sample_data()
    # Fill the sparklines with plausible traffic so the plots are meaningful.
    db.links["EN1"] = [abs(math.cos(i * 0.13)) * 3e5 for i in range(dashboard.HISTORY)]
    db.links["EN11"] = [abs(math.sin(i * 0.21)) * 8e6 + 2e5
                        for i in range(dashboard.HISTORY)]
    for i in range(dashboard.HISTORY):
        db.gpu_hist.append(abs(math.sin(i * 0.17)) * 70 + 5)
    db.render(data)

    out = os.path.join(HERE, "..", "build", "preview.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    d.save(out)
    print("wrote", os.path.normpath(out))

    if "--splash" in sys.argv:
        d2 = ShimDisplay()
        db2 = dashboard.Dashboard(d2, theme.Pens(d2))
        db2.splash("WAITING FOR MAC", ["START THE HOST AGENT",
                                       "USB LINK IDLE"])
        out2 = os.path.join(HERE, "..", "build", "preview_splash.png")
        d2.save(out2)
        print("wrote", os.path.normpath(out2))


if __name__ == "__main__":
    main()
