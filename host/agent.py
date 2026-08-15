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
import subprocess
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

# The desk pet prints this when it levels up (and once at boot). We keep
# the figures and rebuild its trophy page. Doing it from this stream is
# what makes it possible at all: the page generator would otherwise want
# the serial port, and we are holding it.
LEVEL_TAG = b"#B:"
BUDDY_REPO = os.environ.get(
    "BUDDY_REPO", os.path.join(HERE, "..", "..", "BuddyPresto"))


def find_port(explicit=None):
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for pattern in PATTERNS:
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return None


def parse_level(line):
    """Pull the JSON out of a `#B:` announcement, or None if it's junk.

    The board's stdout also carries MicroPython's own chatter, so this has
    to be forgiving: anything unparseable is simply not a level-up.
    """
    try:
        body = line.split(LEVEL_TAG, 1)[1].strip()
        payload = json.loads(body.decode("utf-8", "ignore"))
    except (ValueError, IndexError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


def on_level_up(payload, repo=None):
    """Save the pet's figures and kick off a rebuild of its trophy page.

    Fire and forget: rendering the page takes a second or so and this is
    called from the frame loop, so the subprocess is not waited on. If the
    pet's project isn't checked out next door, nothing happens.
    """
    repo = repo or BUDDY_REPO
    generator = os.path.join(repo, "tools", "level_page.py")
    if not os.path.exists(generator):
        return None

    state_path = os.path.join(repo, "build", "buddy_state.json")
    # The board repeats its announcement periodically so a missed line
    # self-heals; ignore the ones that say nothing new, or we'd rebuild the
    # page every ten minutes for nothing.
    try:
        with open(state_path) as f:
            if json.load(f) == payload:
                return None
    except (OSError, ValueError):
        pass

    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as f:
            json.dump(payload, f)
    except OSError as e:
        print("buddy: could not save state: %s" % e, flush=True)
        return None

    print("buddy: level %s%s — rebuilding the page"
          % (payload.get("level"),
             " (%s)" % payload["reward"] if payload.get("reward") else ""),
          flush=True)
    try:
        return subprocess.Popen(
            [sys.executable, generator, "--state", state_path,
             "--out", os.path.join(repo, "build", "buddy.html")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        print("buddy: rebuild failed to start: %s" % e, flush=True)
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

    return stream(args, col, serial, period)


def _describe_gap(seconds):
    seconds = int(seconds)
    if seconds < 90:
        return "%ds" % seconds
    if seconds < 5400:
        return "%dm" % (seconds // 60)
    return "%dh%02dm" % (seconds // 3600, (seconds % 3600) // 60)


def stream(args, col, serial, period, limit=None):
    """Send frames until interrupted, reconnecting as the board comes and
    goes. `limit` caps the iterations, for tests.

    The board is a thing on a desk: it gets unplugged, reset by a deploy,
    or carried off overnight. None of that should end the agent — it drops
    back to scanning for the port and picks up whenever it returns.
    """
    ser = None
    port = None
    waiting = False
    view = None
    detail = None
    detail_at = 0.0
    chatter = b""
    lost_at = None
    rounds = 0

    while limit is None or rounds < limit:
        rounds += 1
        start = time.time()
        try:
            if ser is None:
                port = find_port(args.port)
                if port is None:
                    if not waiting:
                        print("waiting for the Presto...", flush=True)
                        waiting = True
                        lost_at = lost_at or time.time()
                    time.sleep(2)
                    continue
                ser = serial.Serial(port, BAUD, timeout=0, write_timeout=5)
                waiting = False
                view, detail, chatter = None, None, b""
                gap = ("" if lost_at is None
                       else " after %s" % _describe_gap(time.time() - lost_at))
                lost_at = None
                print("connected to %s%s" % (port, gap), flush=True)
                time.sleep(0.5)
                # Rates come from the delta between two samples. After an
                # outage the previous one is however old the outage was, so
                # throw a sample away here: the first frame the board sees
                # is then a half-second rate, not a nine-hour average.
                try:
                    col.sample()
                except Exception as e:
                    print("priming failed: %s" % e, flush=True)

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
            except (OSError, IOError):
                raise           # the port has gone; reconnect below
            except Exception:
                chatter = b""
            if VIEW_TAG in chatter or LEVEL_TAG in chatter:
                lines = chatter.split(b"\n")
                # A level announcement can be long; keep enough of a
                # partial line to finish it on the next read.
                chatter = lines[-1][-1024:]
                for line in lines[:-1]:
                    if VIEW_TAG in line:
                        want = line.split(VIEW_TAG, 1)[1].strip().decode(
                            "ascii", "ignore")
                        want = want if want in VIEWS else None
                        if want != view:
                            view, detail, detail_at = want, None, 0.0
                    if LEVEL_TAG in line:
                        payload = parse_level(line)
                        if payload is not None:
                            on_level_up(payload)
            elif len(chatter) > 4096:
                chatter = chatter[-1024:]

        except (OSError, IOError) as e:
            # Unplugged, reset by a deploy, or the port renamed itself.
            print("link error on %s: %s" % (port, e), flush=True)
            try:
                if ser:
                    ser.close()
            except Exception:
                pass
            ser = None
            lost_at = time.time()
            time.sleep(2)
            continue
        except Exception as e:
            # A metric collector tripping over odd output from ioreg or
            # nettop shouldn't take the agent down — launchd would restart
            # it, but a persistent one would become a restart loop, and the
            # board would blink between standby and live the whole time.
            print("sampling error: %s: %s" % (type(e).__name__, e), flush=True)
            time.sleep(1)
            continue

        delay = period - (time.time() - start)
        if delay > 0:
            time.sleep(delay)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        pass
