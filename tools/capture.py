"""Screenshot the Presto's actual framebuffer over USB.

Renders a frame on the board, RLE-encodes the RGB565 framebuffer there,
ships it back base64 and writes a PNG. This is how the dashboard gets
verified on real hardware rather than only in the software preview.

    python3 tools/capture.py                 # live Mac metrics
    python3 tools/capture.py --splash        # the standby screen
    python3 tools/capture.py -o build/x.png
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "host"))

from raster import Canvas

W = H = 480

# Runs on the device. RENDER is substituted with the drawing calls.
REMOTE = '''
import binascii, time
from presto import Presto
import theme, dashboard

presto = Presto(full_res=True)

class D:
    def __init__(self, p):
        self._p = p; self._g = p.display
    def __getattr__(self, n):
        return getattr(self._g, n)
    def update(self):
        self._p.update()

d = D(presto)
W, H = d.get_bounds()
buf = bytearray(W * H * 2)
d.set_framebuffer(buf)
pens = theme.Pens(d)
db = dashboard.Dashboard(d, pens)
DATA = %(data)s
HIST = %(hist)s
db.seed(HIST["rx"], HIST["tx"])
db.gpu_hist = HIST["gpu"]
%(render)s
d.update()

@micropython.native
def rle(b, n):
    out = bytearray(); ap = out.append; i = 0
    while i < n:
        lo = b[i]; hi = b[i + 1]; j = i + 2
        while j < n and b[j] == lo and b[j + 1] == hi:
            j += 2
        run = (j - i) >> 1
        while run > 65535:
            ap(255); ap(255); ap(lo); ap(hi); run -= 65535
        ap(run & 255); ap(run >> 8); ap(lo); ap(hi)
        i = j
    return out

enc = rle(buf, len(buf))
b = binascii.b2a_base64(enc).strip()
print("<<<START>>>")
for i in range(0, len(b), 2048):
    print(b[i:i + 2048].decode())
print("<<<END>>>")
'''


def find_port(explicit=None):
    import glob
    if explicit:
        return explicit
    found = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not found:
        sys.exit("no Presto serial port found")
    return found[0]


def decode(text, out_path):
    start = text.index("<<<START>>>") + len("<<<START>>>")
    end = text.index("<<<END>>>")
    data = base64.b64decode("".join(text[start:end].split()))

    cv = Canvas(W, H)
    o = 0
    for i in range(0, len(data), 4):
        run = data[i] | (data[i + 1] << 8)
        # The panel stores RGB565 big-endian.
        v = (data[i + 2] << 8) | data[i + 3]
        r = ((v >> 11) & 0x1F) * 255 // 31
        g = ((v >> 5) & 0x3F) * 255 // 63
        b = (v & 0x1F) * 255 // 31
        px = bytes((r, g, b))
        cv.px[o:o + run * 3] = px * run
        o += run * 3

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    cv.save(out_path)
    return o // 3


def live_data():
    import macstats
    import time
    col = macstats.Collector()
    time.sleep(1.0)
    return col.sample()


FETCH = '''
import binascii
p = "/sd/status/shot.rle"
import os, machine
try:
    os.listdir("/sd")
except OSError:
    import sdcard
    spi = machine.SPI(0, sck=machine.Pin(34), mosi=machine.Pin(35),
                      miso=machine.Pin(36))
    os.mount(sdcard.SDCard(spi, machine.Pin(39)), "/sd")
data = open(p, "rb").read()
b = binascii.b2a_base64(data).strip()
print("<<<START>>>")
for i in range(0, len(b), 2048):
    print(b[i:i + 2048].decode())
print("<<<END>>>")
'''


def capture_live(port, out_path, seconds=8):
    """Drive the running main.py over the real serial link, then pull the
    screenshot it wrote to the SD card."""
    import time

    import serial

    import agent
    import config
    import macstats

    col = macstats.Collector()
    cfg = config.load()
    agent.apply_config(col, cfg)

    # Pulling the last screenshot uses mpremote, which leaves the board
    # at the REPL with main.py stopped. Without this the next capture
    # feeds frames to a prompt that just echoes them, and returns the
    # previous screenshot — which looks exactly like a change that did
    # not take effect. It cost hours before it was spotted.
    print("resetting the board so main.py is running...")
    subprocess.run(["mpremote", "connect", port, "reset"],
                   capture_output=True, timeout=60)
    time.sleep(9)
    time.sleep(0.5)

    print("feeding %s for %ds..." % (port, seconds))
    with serial.Serial(port, 115200, timeout=0, write_timeout=3) as ser:
        for _ in range(seconds):
            # Carry the real settings, so a capture shows the display as
            # it is actually configured rather than however the board was
            # last left.
            sample = col.sample()
            sample["cfg"] = agent.device_config(cfg)
            frame = json.dumps(sample, separators=(",", ":")) + "\n"
            ser.write(frame.encode())
            ser.flush()
            try:
                ser.read(4096)
            except Exception:
                pass
            time.sleep(1.0)
        # Remove any previous capture first: reading a stale file back
        # looks exactly like a successful capture, and once did.
        ser.write(b'{"cmd":"unshot"}\n')
        time.sleep(0.5)
        ser.write(b'{"cmd":"shot"}\n')
        ser.flush()
        time.sleep(4.0)

    proc = subprocess.run(["mpremote", "connect", port, "exec", FETCH],
                          capture_output=True, text=True, timeout=180)
    if "<<<START>>>" not in proc.stdout:
        sys.stderr.write(proc.stdout + "\n" + proc.stderr + "\n")
        sys.exit("live capture failed - is main.py running on the board?")
    n = decode(proc.stdout, out_path)
    print("wrote %s (%d px)" % (os.path.normpath(out_path), n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=os.path.join(HERE, "..", "build",
                                                        "device.png"))
    ap.add_argument("--port")
    ap.add_argument("--splash", action="store_true")
    ap.add_argument("--stale", action="store_true",
                    help="render with the link shown as dead")
    ap.add_argument("--live", action="store_true",
                    help="drive the running main.py over serial and pull "
                         "the screenshot it saves to the SD card")
    ap.add_argument("--seconds", type=int, default=8,
                    help="frames to feed in --live mode (default 8)")
    args = ap.parse_args()

    if args.live:
        capture_live(find_port(args.port), args.out, args.seconds)
        return

    import math
    hist = {
        "rx": [round(abs(math.sin(i * 0.21)) * 8e6 + 2e5) for i in range(64)],
        "tx": [round(abs(math.cos(i * 0.13)) * 2e6 + 1e5) for i in range(64)],
        "gpu": [round(abs(math.sin(i * 0.17)) * 70 + 5) for i in range(64)],
    }

    if args.splash:
        data = {}
        render = ('db.splash("WAITING FOR MAC", ["RUN THE HOST AGENT ON YOUR MAC",'
                  ' "PYTHON3 HOST/AGENT.PY"])')
    else:
        data = live_data()
        render = "db.render(DATA, linked=%s)" % (not args.stale)

    script = REMOTE % {
        "data": json.dumps(data),
        "hist": json.dumps(hist),
        "render": render,
    }

    port = find_port(args.port)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(script)
        tmp = f.name
    try:
        proc = subprocess.run(["mpremote", "connect", port, "run", tmp],
                              capture_output=True, text=True, timeout=180)
    finally:
        os.unlink(tmp)

    if "<<<START>>>" not in proc.stdout:
        sys.stderr.write(proc.stdout + "\n" + proc.stderr + "\n")
        sys.exit("capture failed")

    n = decode(proc.stdout, args.out)
    print("wrote %s (%d px)" % (os.path.normpath(args.out), n))


if __name__ == "__main__":
    main()
