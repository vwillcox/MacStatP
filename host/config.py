"""Settings for the status display.

Kept in Application Support rather than next to the code, because the code
moves: the launch agent once pointed at a checkout that had been moved to
an external drive, and the whole thing sat there failing to start. Config
that outlives the repo location avoids repeating that.

The agent re-reads the file when its mtime changes, so the web UI can
change settings without restarting anything.
"""

import json
import os
import tempfile

APP_NAME = "MacStatP"
SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/" + APP_NAME)
CONFIG_PATH = os.path.join(SUPPORT_DIR, "config.json")

# Every key here is applied somewhere; there are no decorative settings.
DEFAULTS = {
    "hz": 6.0,              # frames per second sent to the board
    "port": "",             # serial device, blank to auto-detect
    "web_port": 8765,       # port the configuration page listens on
    "disk_path": "/",       # which volume the DISK panel measures
    "net_auto": True,       # pick the Wi-Fi and wired links automatically
    "net_wifi": "",         # explicit Wi-Fi interface when net_auto is off
    "net_wired": "",        # explicit wired interface when net_auto is off
    "brightness": 0.85,     # panel backlight, 0.1 - 1.0
    "net_bits": False,      # show network rates in bits rather than bytes
    "detail_period": 1.0,   # seconds between process listings while open
}

# Bounds applied on load, so a hand-edited file cannot wedge the agent.
LIMITS = {
    "hz": (0.2, 15.0),
    "web_port": (1024, 65535),
    "brightness": (0.1, 1.0),
    "detail_period": (0.25, 10.0),
}


def _clamp(key, value):
    lo, hi = LIMITS[key]
    return max(lo, min(hi, value))


def coerce(raw):
    """Merge stored values over the defaults, keeping types sane."""
    cfg = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return cfg
    for key, default in DEFAULTS.items():
        if key not in raw:
            continue
        val = raw[key]
        try:
            if isinstance(default, bool):
                val = bool(val)
            elif isinstance(default, float):
                val = float(val)
            elif isinstance(default, int):
                val = int(val)
            else:
                val = str(val)
        except (TypeError, ValueError):
            continue
        if key in LIMITS:
            val = _clamp(key, val)
        cfg[key] = val
    return cfg


def load():
    try:
        with open(CONFIG_PATH) as f:
            return coerce(json.load(f))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(cfg):
    """Write atomically: a half-written file would be read as defaults."""
    os.makedirs(SUPPORT_DIR, exist_ok=True)
    merged = coerce(cfg)
    fd, tmp = tempfile.mkstemp(dir=SUPPORT_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(merged, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return merged


def mtime():
    try:
        return os.stat(CONFIG_PATH).st_mtime
    except OSError:
        return 0.0


class Watcher:
    """Holds the current settings and reloads them when the file changes."""

    def __init__(self):
        self.cfg = load()
        self._seen = mtime()

    def poll(self):
        """Returns True when the settings just changed."""
        now = mtime()
        if now == self._seen:
            return False
        self._seen = now
        self.cfg = load()
        return True
