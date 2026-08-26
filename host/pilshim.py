"""A PicoGraphics-shaped drawing surface backed by Pillow.

device/dashboard.py is written against a small subset of the PicoGraphics
API. Implementing that subset here lets the exact same layout code run on
the Mac, where it can be supersampled and downscaled for antialiasing the
Presto cannot do itself.
"""

from PIL import Image, ImageDraw


class PILDisplay:
    def __init__(self, w=480, h=480, scale=3):
        self.w, self.h = w, h
        self.scale = scale
        self._img = Image.new("RGB", (w * scale, h * scale), (0, 0, 0))
        self._draw = ImageDraw.Draw(self._img)
        self._pen = (255, 255, 255)

    # ── PicoGraphics surface ──────────────────────────────────────────
    def get_bounds(self):
        return self.w, self.h

    def create_pen(self, r, g, b):
        return (int(r), int(g), int(b))

    def set_pen(self, pen):
        self._pen = pen

    def clear(self):
        self._draw.rectangle([0, 0, self._img.width, self._img.height],
                             fill=self._pen)

    def set_clip(self, x, y, w, h):
        s = self.scale
        self._clip = (x * s, y * s, (x + w) * s, (y + h) * s)

    def remove_clip(self):
        self._clip = None

    def rectangle(self, x, y, w, h):
        s = self.scale
        if w <= 0 or h <= 0:
            return
        self._draw.rectangle(
            [x * s, y * s, (x + w) * s - 1, (y + h) * s - 1], fill=self._pen)

    def polygon(self, pts):
        s = self.scale
        if len(pts) < 3:
            return
        self._draw.polygon([(p[0] * s, p[1] * s) for p in pts], fill=self._pen)

    def circle(self, x, y, r):
        s = self.scale
        self._draw.ellipse([(x - r) * s, (y - r) * s,
                            (x + r) * s, (y + r) * s], fill=self._pen)

    def line(self, x0, y0, x1, y1, t=1):
        s = self.scale
        self._draw.line([x0 * s, y0 * s, x1 * s, y1 * s],
                        fill=self._pen, width=max(1, int(t * s)))

    def update(self):
        """No-op: the frame is collected by resolve() instead."""

    # ── output ────────────────────────────────────────────────────────
    def resolve(self):
        """Downscale the supersampled canvas to the panel's resolution."""
        if self.scale == 1:
            return self._img
        return self._img.resize((self.w, self.h), Image.LANCZOS)

    def save(self, path):
        self.resolve().save(path)
