"""Stream Mac metrics to the Presto over USB serial.

One compact JSON object per line, ~600 bytes, which the board renders
itself. The port comes and goes when the board resets, so the agent
reconnects on its own rather than exiting.

    python3 host/agent.py                 stream to the first Presto found
    python3 host/agent.py --hz 5          send faster or slower
    python3 host/agent.py --stdout        print frames instead of sending
    python3 host/agent.py --preview p.png render one frame with the board's
                                          own layout code, for design work
"""

import argparse
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import macstats

BAUD = 115200   # ignored by USB CDC, but pyserial wants a value
PATTERNS = ("/dev/cu.usbmodem*", "/dev/cu.usbserial*")

VIEW_TAG = b"#V:"        # the board prints this when a panel is opened
VIEWS = ("cpu", "gpu", "mem", "disk", "net")
DETAIL_PERIOD = 1.0      # seconds between process listings while open


def find_port(explicit=None):
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for pattern in PATTERNS:
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return None


def preview(path, scale=3):
    """Render one frame on the Mac using the device's own layout modules.

    Handy for iterating on the design without deploying: pass --scale for
    a supersampled, antialiased version of what the board draws.
    """
    sys.path.insert(0, os.path.join(HERE, "..", "device"))
    import builtins

    class _Shim:
        @staticmethod
        def native(fn):
            return fn

    builtins.micropython = _Shim

    import dashboard
    import theme
    from pilshim import PILDisplay

    col = macstats.Collector()
    time.sleep(1.0)
    d = PILDisplay(scale=scale)
    db = dashboard.Dashboard(d, theme.Pens(d))
    data = col.sample()
    db.push(data)
    db.render(data, full=True)
    d.resolve().save(path)
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser(description="Mac -> Presto status feed")
    ap.add_argument("--port", help="serial device (default: first usbmodem)")
    ap.add_argument("--hz", type=float, default=6.0,
                    help="frames per second to send (default 6; the board "
                         "renders at ~7.2 fps overclocked to 264 MHz)")
    ap.add_argument("--stdout", action="store_true",
                    help="print frames instead of writing to serial")
    ap.add_argument("--preview", help="render one frame to this PNG and exit")
    ap.add_argument("--scale", type=int, default=3,
                    help="supersampling for --preview only")
    args = ap.parse_args()

    if args.preview:
        preview(args.preview, args.scale)
        return 0

    col = macstats.Collector()
    period = 1.0 / max(0.1, args.hz)
    time.sleep(0.3)   # let the rate counters settle

    if args.stdout:
        while True:
            sys.stdout.write(json.dumps(col.sample(), separators=(",", ":")) + "\n")
            sys.stdout.flush()
            time.sleep(period)

    try:
        import serial
    except ImportError:
        print("pyserial is required: pip3 install --user pyserial",
              file=sys.stderr)
        return 1

    ser = None
    port = None
    waiting = False
    view = None
    detail = None
    detail_at = 0.0
    chatter = b""

    while True:
        start = time.time()
        try:
            if ser is None:
                port = find_port(args.port)
                if port is None:
                    if not waiting:
                        print("waiting for the Presto...", flush=True)
                        waiting = True
                    time.sleep(2)
                    continue
                ser = serial.Serial(port, BAUD, timeout=0, write_timeout=5)
                waiting = False
                view, detail, chatter = None, None, b""
                print("connected to %s" % port, flush=True)
                time.sleep(0.5)

            frame = col.sample()
            # Process listings cost ~25 ms and are an order of magnitude
            # larger than the summary, so they are gathered only while a
            # panel is open, and at a slower cadence than the frame rate.
            if view:
                if time.time() - detail_at >= DETAIL_PERIOD or detail is None:
                    detail = col.detail(view)
                    detail_at = time.time()
                if detail:
                    frame["det"] = detail
            ser.write((json.dumps(frame, separators=(",", ":"))
                       + "\n").encode())
            ser.flush()

            # Drain the board's output so its buffer cannot back up, and
            # watch it for which breakdown the screen is showing.
            try:
                chatter += ser.read(8192)
            except Exception:
                chatter = b""
            if VIEW_TAG in chatter:
                lines = chatter.split(b"\n")
                chatter = lines[-1][-256:]
                for line in lines[:-1]:
                    if VIEW_TAG in line:
                        want = line.split(VIEW_TAG, 1)[1].strip().decode(
                            "ascii", "ignore")
                        want = want if want in VIEWS else None
                        if want != view:
                            view, detail, detail_at = want, None, 0.0
            elif len(chatter) > 4096:
                chatter = chatter[-256:]

        except (OSError, IOError) as e:
            print("link error on %s: %s" % (port, e), flush=True)
            try:
                if ser:
                    ser.close()
            except Exception:
                pass
            ser = None
            time.sleep(2)
            continue

        delay = period - (time.time() - start)
        if delay > 0:
            time.sleep(delay)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        pass
