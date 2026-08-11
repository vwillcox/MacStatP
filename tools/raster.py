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
        self.fill_all(bg)

    def fill_all(self, c):
        self.px[:] = bytes(c) * (self.w * self.h)

    def pixel(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            o = (y * self.w + x) * 3
            self.px[o:o + 3] = bytes(c)

    def rect(self, x, y, w, h, c):
        row = bytes(c) * max(0, min(w, self.w - x))
        for yy in range(max(0, y), min(self.h, y + h)):
            o = (yy * self.w + max(0, x)) * 3
            self.px[o:o + len(row)] = row

    def polygon(self, pts, c):
        """Even-odd scanline fill, matching a simple convex filler."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0, y1 = int(min(ys)), int(max(ys)) + 1
        col = bytes(c)
        for y in range(max(0, y0), min(self.h, y1)):
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
                xa, xb = max(0, xa), min(self.w, xb)
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
