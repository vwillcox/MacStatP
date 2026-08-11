"""Palette and colour helpers for the status dashboard."""

BG = (6, 8, 12)
CARD = (19, 23, 31)
BORDER = (44, 53, 68)
BORDER_HI = (64, 78, 100)
TITLE = (232, 238, 248)
TEXT = (198, 208, 226)
MUTED = (112, 126, 150)
TRACK = (32, 38, 50)

CYAN = (0, 194, 255)
GREEN = (54, 222, 138)
AMBER = (255, 178, 40)
RED = (255, 72, 92)
PURPLE = (154, 100, 255)
WHITE = (255, 255, 255)

# Per-metric accents, used for bars and sparklines.
ACCENT = {
    "cpu": CYAN,
    "gpu": PURPLE,
    "mem": (0, 224, 200),
    "disk": AMBER,
    "rx": CYAN,
    "tx": AMBER,
}


def _mix(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def heat(frac):
    """Green below 55%, through amber, to red at the top of the range."""
    if frac <= 0:
        return GREEN
    if frac >= 1:
        return RED
    if frac < 0.55:
        return _mix(GREEN, AMBER, frac / 0.55)
    if frac < 0.85:
        return _mix(AMBER, RED, (frac - 0.55) / 0.30)
    return RED


def dim(c, f):
    return (int(c[0] * f), int(c[1] * f), int(c[2] * f))


class Pens:
    """Caches created pens so redraws don't churn the palette."""

    def __init__(self, display):
        self.d = display
        self._cache = {}

    def __call__(self, colour):
        p = self._cache.get(colour)
        if p is None:
            p = self.d.create_pen(colour[0], colour[1], colour[2])
            self._cache[colour] = p
        return p

    def set(self, colour):
        self.d.set_pen(self(colour))
