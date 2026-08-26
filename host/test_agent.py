"""Tests for the agent's link handling.

    python3 host/test_agent.py

The board gets unplugged, reset by a deploy, and carried off overnight,
and the agent has to sit through all of it and pick up again on its own.
That path is easy to break and awkward to exercise by hand — pulling a USB
cable at the right moment isn't a repeatable test — so it's driven here
with a fake serial port instead.
"""

import json
import os
import shutil
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agent  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("ok  " if condition else "FAIL", name,
                         "" if condition else "  <- " + str(detail)))


class FakePort:
    """A serial port that can be yanked out from under the agent."""

    def __init__(self, name, fail_after=None, fail_on_read=False):
        self.name = name
        self.writes = []
        self.closed = False
        self.read_data = b""       # what the board says back to us
        self._fail_after = fail_after
        self._fail_on_read = fail_on_read

    def write(self, data):
        if self._fail_after is not None and len(self.writes) >= self._fail_after:
            raise OSError(6, "Device not configured")
        self.writes.append(data)
        return len(data)

    def flush(self):
        pass

    def read(self, _n):
        if self._fail_on_read:
            raise OSError(6, "Device not configured")
        out, self.read_data = self.read_data, b""
        return out

    def close(self):
        self.closed = True


class FakeSerial:
    """Stands in for the pyserial module."""

    def __init__(self, ports):
        self._ports = dict(ports)   # device name -> FakePort
        self.opened = []

    def Serial(self, port, baud, timeout=0, write_timeout=5):
        self.opened.append(port)
        if port not in self._ports:
            raise OSError(2, "No such file or directory")
        return self._ports[port]


class FakeCollector:
    def __init__(self, raise_times=()):
        self.samples = 0
        self._raise_at = set(raise_times)

    def sample(self):
        self.samples += 1
        if self.samples in self._raise_at:
            raise ValueError("ioreg said something strange")
        return {"cpu": {"pct": 12}}

    def detail(self, _view):
        return []


class Args:
    port = None
    hz = None


class FakeWatcher:
    """Settings that never change, so stream() uses them as given."""

    def __init__(self, **over):
        import config
        self.cfg = dict(config.DEFAULTS)
        self.cfg.update(over)
        self.cfg["hz"] = 100.0      # the sleep is stubbed out anyway

    def poll(self):
        return False


def status():
    import webui
    return webui.Status()


def harness():
    """Silence the agent's sleeps and capture what it logs."""
    logged = []
    agent.time.sleep = lambda _s: None
    real_print = agent.print if hasattr(agent, "print") else print

    def capture(*a, **kw):
        logged.append(" ".join(str(x) for x in a))

    agent.print = capture
    return logged, real_print


def test_waits_for_a_missing_board():
    print("no board present")
    logged, _ = harness()
    agent.find_port = lambda explicit=None: None
    col = FakeCollector()

    agent.stream(Args(), col, FakeSerial({}), FakeWatcher(), status(), limit=25)

    waits = [line for line in logged if "waiting" in line]
    check("does not exit when there's no port", True)
    check("says so once, not once per poll", len(waits) == 1, logged[:4])
    check("collects nothing while disconnected", col.samples == 0, col.samples)


def test_reconnects_after_an_unplug():
    print("unplug and replug")
    logged, _ = harness()
    port = FakePort("/dev/cu.usbmodem3101", fail_after=3)
    serial = FakeSerial({"/dev/cu.usbmodem3101": port})

    # Present, then yanked, then back under a different device name —
    # which is what a re-enumeration after a reset actually looks like.
    names = (["/dev/cu.usbmodem3101"] * 6 + [None] * 4
             + ["/dev/cu.usbmodem1201"] * 10)
    seen = iter(names)
    agent.find_port = lambda explicit=None: next(seen, "/dev/cu.usbmodem1201")
    port2 = FakePort("/dev/cu.usbmodem1201")
    serial._ports["/dev/cu.usbmodem1201"] = port2

    col = FakeCollector()
    agent.stream(Args(), col, serial, FakeWatcher(), status(), limit=20)

    check("wrote frames before the unplug", len(port.writes) == 3, port.writes)
    check("closed the dead port", port.closed)
    check("logged the link error",
          any("link error" in line for line in logged), logged)
    check("came back on the new device name",
          "/dev/cu.usbmodem1201" in serial.opened, serial.opened)
    check("resumed sending", len(port2.writes) > 0, len(port2.writes))
    check("reported how long it was gone",
          any("connected to /dev/cu.usbmodem1201 after" in line
              for line in logged),
          [line for line in logged if "connected" in line])


def test_primes_rates_on_reconnect():
    print("rate priming")
    harness()
    port = FakePort("/dev/cu.usbmodem3101")
    serial = FakeSerial({"/dev/cu.usbmodem3101": port})
    agent.find_port = lambda explicit=None: "/dev/cu.usbmodem3101"
    col = FakeCollector()

    agent.stream(Args(), col, serial, FakeWatcher(), status(), limit=1)
    # One throwaway sample to re-prime the deltas, one that gets sent. The
    # first frame after a nine-hour gap must not be a nine-hour average.
    check("discards one sample on connect", col.samples == 2, col.samples)
    # The hello asking what the board has is a control message, not a
    # frame, so count frames rather than writes.
    frames = [w for w in port.writes if b'"cmd"' not in w]
    check("sends only the second", len(frames) == 1, port.writes)
    check("and asks the board what it has", any(
        b'"cmd":"hello"' in w for w in port.writes), port.writes)


def test_survives_a_bad_sample():
    print("collector hiccup")
    logged, _ = harness()
    port = FakePort("/dev/cu.usbmodem3101")
    serial = FakeSerial({"/dev/cu.usbmodem3101": port})
    agent.find_port = lambda explicit=None: "/dev/cu.usbmodem3101"
    col = FakeCollector(raise_times=(3,))   # the second published frame

    agent.stream(Args(), col, serial, FakeWatcher(), status(), limit=6)

    check("keeps going after a sampling error", col.samples >= 5, col.samples)
    check("logged it", any("sampling error" in line for line in logged), logged)
    check("kept the port open", not port.closed)
    check("carried on sending", len(port.writes) >= 3, len(port.writes))


def test_read_failure_is_a_disconnect():
    print("read-side disconnect")
    logged, _ = harness()
    port = FakePort("/dev/cu.usbmodem3101", fail_on_read=True)
    serial = FakeSerial({"/dev/cu.usbmodem3101": port})
    agent.find_port = lambda explicit=None: "/dev/cu.usbmodem3101"

    agent.stream(Args(), FakeCollector(), serial, FakeWatcher(), status(), limit=4)

    check("a dead read reconnects rather than spinning", port.closed)
    check("logged the link error",
          any("link error" in line for line in logged), logged)


def test_level_announcements():
    """The pet announces a level-up on stdout and we rebuild its page.

    This is the whole reason it goes over stdout rather than the page
    generator reading the board directly: we are holding the serial port.
    """
    print("level announcements")
    import tempfile

    good = b'#B:{"level": 8, "reward": "HEADPHONES", "tokens": 400000}'
    check("parses an announcement",
          agent.parse_level(good) == {"level": 8, "reward": "HEADPHONES",
                                      "tokens": 400000})
    check("survives the board's other chatter",
          agent.parse_level(b"MPY: soft reboot") is None)
    check("ignores a truncated line", agent.parse_level(b'#B:{"level": 8') is None)
    check("ignores a bare value", agent.parse_level(b"#B:42") is None)
    check("takes the tag anywhere on the line",
          agent.parse_level(b'noise #B:{"level": 3}')["level"] == 3)

    repo = tempfile.mkdtemp()
    try:
        # No generator next door: nothing happens, and nothing raises.
        check("no pet project, no rebuild",
              agent.on_level_up({"level": 2}, repo=repo) is None)

        os.makedirs(os.path.join(repo, "tools"))
        with open(os.path.join(repo, "tools", "level_page.py"), "w") as f:
            f.write("import sys; sys.exit(0)\n")
        proc = agent.on_level_up({"level": 9, "reward": "PARTY HAT"}, repo=repo)
        check("rebuild started", proc is not None)
        if proc:
            proc.wait(timeout=20)
        saved = os.path.join(repo, "build", "buddy_state.json")
        check("figures saved for the generator", os.path.exists(saved))
        with open(saved) as f:
            check("...with the level in them", json.load(f)["level"] == 9)

        # The board repeats itself so a lost line heals; a repeat that says
        # nothing new must not spawn a rebuild every ten minutes.
        check("an identical announcement is ignored",
              agent.on_level_up({"level": 9, "reward": "PARTY HAT"},
                                repo=repo) is None)
        again = agent.on_level_up({"level": 10, "reward": "VIOLET COAT"},
                                  repo=repo)
        check("a changed one rebuilds", again is not None)
        if again:
            again.wait(timeout=20)
    finally:
        shutil.rmtree(repo)


def test_stream_reacts_to_a_level_up():
    print("level-up through the loop")
    logged, _ = harness()
    port = FakePort("/dev/cu.usbmodem3101")
    port.read_data = b'#B:{"level": 5, "reward": "MINT COAT"}\n'
    serial = FakeSerial({"/dev/cu.usbmodem3101": port})
    agent.find_port = lambda explicit=None: "/dev/cu.usbmodem3101"

    seen = []
    real = agent.on_level_up
    agent.on_level_up = lambda payload, repo=None: seen.append(payload)
    try:
        agent.stream(Args(), FakeCollector(), serial, FakeWatcher(), status(), limit=3)
    finally:
        agent.on_level_up = real

    check("the loop noticed the level-up", len(seen) == 1, seen)
    check("and read it correctly", seen and seen[0]["reward"] == "MINT COAT")


def test_backlight_goes_to_the_board():
    """device/main.py cannot be imported here — it pulls in the Presto
    hardware — so this reads the source. Worth having anyway: the Display
    wrapper forwards unknown attributes to PicoGraphics, and both it and
    the Presto expose set_backlight. Forwarding this one lands on the
    PicoGraphics version, which does nothing on this hardware, so the
    brightness setting silently had no effect."""
    print("backlight routing")
    src = open(os.path.join(HERE, "..", "device", "main.py")).read()
    body = src[src.index("class Display"):src.index("def cycle_brightness")]
    check("Display defines set_backlight rather than forwarding it",
          "def set_backlight" in body)
    fn = body[body.index("def set_backlight"):]
    check("and sends it to the Presto, not the graphics object",
          "self._p.set_backlight" in fn, fn.splitlines()[-1])
    check("no silently swallowed backlight failures",
          "except Exception:\n                            pass" not in src)


def test_gap_wording():
    print("gap wording")
    check("seconds", agent._describe_gap(45) == "45s")
    check("minutes", agent._describe_gap(600) == "10m")
    check("hours", agent._describe_gap(35_071) == "9h44m")


for test in (test_waits_for_a_missing_board, test_reconnects_after_an_unplug,
             test_backlight_goes_to_the_board,
             test_primes_rates_on_reconnect, test_survives_a_bad_sample,
             test_read_failure_is_a_disconnect, test_level_announcements,
             test_stream_reacts_to_a_level_up, test_gap_wording):
    test()

sys.modules["builtins"].print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
sys.exit(1 if FAILED else 0)
