"""SD card: settings, sparkline history across reboots, and an error log.

Everything here is best-effort. The dashboard runs fine with no card
inserted; failures are swallowed and reported through `available`.
"""

import json
import os

import machine

ROOT = "/sd"
DIR = "/sd/status"
CONFIG = DIR + "/config.json"
HISTORY = DIR + "/history.json"
LOG = DIR + "/log.txt"
LOG_LIMIT = 32768

DEFAULTS = {
    "brightness": 0.85,
    "stale_after": 6,     # seconds without data before the link reads dead
}


class Storage:
    def __init__(self):
        self.available = False
        self.config = dict(DEFAULTS)
        self._mount()
        if self.available:
            self._ensure_dir()
            self._load_config()

    # ── mounting ──────────────────────────────────────────────────────
    def _mount(self):
        try:
            os.listdir(ROOT)
            self.available = True
            return
        except OSError:
            pass
        try:
            import sdcard
            spi = machine.SPI(0, sck=machine.Pin(34), mosi=machine.Pin(35),
                              miso=machine.Pin(36))
            sd = sdcard.SDCard(spi, machine.Pin(39))
            os.mount(sd, ROOT)
            self.available = True
        except Exception as e:
            print("SD unavailable:", e)
            self.available = False

    def _ensure_dir(self):
        try:
            os.listdir(DIR)
        except OSError:
            try:
                os.mkdir(DIR)
            except Exception as e:
                print("SD mkdir failed:", e)
                self.available = False

    # ── config ────────────────────────────────────────────────────────
    def _load_config(self):
        try:
            with open(CONFIG) as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self.config.update(stored)
        except Exception:
            self.save_config()

    def save_config(self):
        if not self.available:
            return
        try:
            with open(CONFIG, "w") as f:
                json.dump(self.config, f)
        except Exception as e:
            print("SD config write failed:", e)

    # ── history ───────────────────────────────────────────────────────
    def load_history(self):
        """Per-interface throughput history; empty when nothing is stored."""
        if not self.available:
            return {}
        try:
            with open(HISTORY) as f:
                h = json.load(f)
            links = h.get("links", {})
            return links if isinstance(links, dict) else {}
        except Exception:
            return {}

    def save_history(self, links):
        if not self.available:
            return
        try:
            with open(HISTORY, "w") as f:
                json.dump({"links": {k: [round(v) for v in vals]
                                     for k, vals in links.items()}}, f)
        except Exception as e:
            print("SD history write failed:", e)

    # ── log ───────────────────────────────────────────────────────────
    def log(self, msg):
        print(msg)
        if not self.available:
            return
        try:
            # Truncate rather than grow without bound on a long-running board.
            try:
                if os.stat(LOG)[6] > LOG_LIMIT:
                    os.remove(LOG)
            except OSError:
                pass
            with open(LOG, "a") as f:
                f.write("%s\n" % msg)
        except Exception:
            pass


SHOT = DIR + "/shot.rle"


@micropython.native
def _rle(b, n):
    """Run-length encode RGB565 pairs: count(LE16) + pixel(2 bytes)."""
    out = bytearray()
    ap = out.append
    i = 0
    while i < n:
        lo = b[i]
        hi = b[i + 1]
        j = i + 2
        while j < n and b[j] == lo and b[j + 1] == hi:
            j += 2
        run = (j - i) >> 1
        while run > 65535:
            ap(255); ap(255); ap(lo); ap(hi)
            run -= 65535
        ap(run & 255); ap(run >> 8); ap(lo); ap(hi)
        i = j
    return out


def screenshot(framebuffer, path=SHOT):
    """Compress the live framebuffer to the card for tools/capture.py."""
    enc = _rle(framebuffer, len(framebuffer))
    with open(path, "wb") as f:
        f.write(enc)
    return len(enc)


def wipe(keep=("status",)):
    """Delete everything on the card except the named top-level entries."""
    removed = 0

    def rm(path):
        nonlocal_removed = 0
        try:
            st = os.stat(path)
        except OSError:
            return 0
        if st[0] & 0x4000:
            for name in os.listdir(path):
                nonlocal_removed += rm(path + "/" + name)
            os.rmdir(path)
        else:
            os.remove(path)
        return nonlocal_removed + 1

    for name in os.listdir(ROOT):
        if name in keep:
            continue
        try:
            removed += rm(ROOT + "/" + name)
        except Exception as e:
            print("could not remove", name, e)
    return removed
