"""Installing the dashboard onto the board from the settings page.

The agent holds the serial port continuously, so an install has to borrow
it: the page asks, the stream loop lets go and waits, the files go across,
and then the loop reconnects on its own. All of that is coordinated here
rather than being spread through the agent.
"""

import glob
import os
import threading
import time

import pushcode

# Where the device's .py files live. Set at startup: in a checkout it is
# ../device, and inside the app bundle it is Resources/device.
DEVICE_DIR = None


def find_device_dir(start):
    for candidate in (os.path.join(start, "device"),
                      os.path.join(start, "..", "device")):
        if os.path.exists(os.path.join(candidate, "main.py")):
            return os.path.abspath(candidate)
    return None


class Installer:
    """Owns the borrow-the-port handshake and the running install's log."""

    def __init__(self):
        self.lock = threading.Lock()
        self.wanted = threading.Event()    # the page wants the port
        self.released = threading.Event()  # the stream loop has let go
        self.running = False
        self.log_lines = []
        self.finished = False
        self.ok = False
        self.started_at = 0.0

    # ── seen by the stream loop ───────────────────────────────────────
    def pause_requested(self):
        return self.wanted.is_set()

    def confirm_released(self):
        self.released.set()

    # ── seen by the web page ──────────────────────────────────────────
    def status(self):
        with self.lock:
            return {"running": self.running, "finished": self.finished,
                    "ok": self.ok, "log": list(self.log_lines),
                    "elapsed": round(time.time() - self.started_at, 1)
                    if self.started_at else 0.0}

    def _say(self, message):
        with self.lock:
            self.log_lines.append(message)
        print("install: %s" % message, flush=True)

    def start(self, port=None, with_buddy=False, buddy_src=None):
        with self.lock:
            if self.running:
                return False, "an install is already running"
            if DEVICE_DIR is None:
                return False, "device files not found next to the app"
            self.running = True
            self.finished = False
            self.ok = False
            self.log_lines = []
            self.started_at = time.time()
        threading.Thread(target=self._run,
                         args=(port, with_buddy, buddy_src),
                         daemon=True).start()
        return True, ""

    def _run(self, port, with_buddy, buddy_src):
        try:
            port = port or (pushcode.find_ports() or [None])[0]
            if not port:
                raise pushcode.PushError(
                    "No Presto found. Connect it by USB and try again.")

            self._say("Asking the display agent to release %s" % port)
            self.wanted.set()
            self.released.clear()
            # The loop checks between frames, so this is quick; if the
            # agent isn't running there is nothing to wait for.
            self.released.wait(timeout=8)
            time.sleep(0.4)

            extra = {}
            if with_buddy and buddy_src and os.path.isdir(buddy_src):
                extra["buddy"] = buddy_src
                self._say("Including the desk pet from %s" % buddy_src)

            pushcode.push(port, DEVICE_DIR, extra=extra, log=self._say)
            with self.lock:
                self.ok = True
        except Exception as e:
            self._say("Failed: %s" % e)
        finally:
            self.wanted.clear()
            self.released.clear()
            with self.lock:
                self.running = False
                self.finished = True
            self._say("The display agent is reconnecting.")


def board_present():
    return bool(pushcode.find_ports())


def buddy_source(root):
    """Where the optional desk pet package might be, if it is around."""
    for candidate in (os.path.join(root, "..", "BuddyPresto", "buddy"),
                      os.path.join(root, "..", "..", "BuddyPresto", "buddy")):
        if glob.glob(os.path.join(candidate, "*.py")):
            return os.path.abspath(candidate)
    return None


# One installer per agent process; the web handlers and the stream loop
# both talk to this.
INSTALLER = Installer()
