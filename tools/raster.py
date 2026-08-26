"""Tiny scanline polygon rasteriser + PNG writer.

Exists so the dashboard and font can be previewed on the Mac without a
round trip to the device. It mirrors what PicoGraphics does on hardware:
flat-filled convex polygons, no antialiasing.
"""

import struct
import zlib


class Canvas:
    def __init__(self, w, h, bg=(0, 0, 0)):
        self.w, self.h = w, h
        self.px = bytearray(w * h * 3)
        # Matches PicoGraphics' clip rectangle, so a preview shows the
        # same thing the panel does.
        self.clip = None
        self.fill_all(bg)

    def set_clip(self, x, y, w, h):
        self.clip = (x, y, x + w, y + h)

    def remove_clip(self):
        self.clip = None

    def _bounds(self):
        if self.clip is None:
            return 0, 0, self.w, self.h
        x0, y0, x1, y1 = self.clip
        return (max(0, x0), max(0, y0), min(self.w, x1), min(self.h, y1))

    def fill_all(self, c):
        self.px[:] = bytes(c) * (self.w * self.h)

    def pixel(self, x, y, c):
        cx0, cy0, cx1, cy1 = self._bounds()
        if cx0 <= x < cx1 and cy0 <= y < cy1:
            o = (y * self.w + x) * 3
            self.px[o:o + 3] = bytes(c)

    def rect(self, x, y, w, h, c):
        cx0, cy0, cx1, cy1 = self._bounds()
        x0, x1 = max(cx0, x), min(cx1, x + w)
        if x1 <= x0:
            return
        row = bytes(c) * (x1 - x0)
        for yy in range(max(cy0, y), min(cy1, y + h)):
            o = (yy * self.w + x0) * 3
            self.px[o:o + len(row)] = row

    def polygon(self, pts, c):
        """Even-odd scanline fill, matching a simple convex filler."""
        if len(pts) < 3:
            return
        cx0, cy0, cx1, cy1 = self._bounds()
        ys = [p[1] for p in pts]
        y0, y1 = int(min(ys)), int(max(ys)) + 1
        col = bytes(c)
        for y in range(max(cy0, y0), min(cy1, y1)):
            yc = y + 0.5
            xs = []
            n = len(pts)
            for i in range(n):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % n]
                if (ay <= yc < by) or (by <= yc < ay):
                    xs.append(ax + (yc - ay) * (bx - ax) / (by - ay))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                xa, xb = int(round(xs[i])), int(round(xs[i + 1]))
                if xb <= xa:
                    continue
                xa, xb = max(cx0, xa), min(cx1, xb)
                if xb > xa:
                    o = (y * self.w + xa) * 3
                    self.px[o:o + (xb - xa) * 3] = col * (xb - xa)

    def circle(self, cx, cy, r, c):
        for y in range(max(0, cy - r), min(self.h, cy + r + 1)):
            dy = y - cy
            dx = int((r * r - dy * dy) ** 0.5) if abs(dy) <= r else 0
            self.rect(cx - dx, y, 2 * dx, 1, c)

    def save(self, path):
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)
            raw += self.px[y * self.w * 3:(y + 1) * self.w * 3]

        def chunk(tag, data):
            body = tag + data
            return (struct.pack(">I", len(data)) + body
                    + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
               + chunk(b"IEND", b""))
        with open(path, "wb") as f:
            f.write(png)
