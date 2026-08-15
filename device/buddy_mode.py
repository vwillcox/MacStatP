"""Desk-pet mode: the BuddyPresto package wired into this dashboard.

The buddy is a second face for the same board — it talks to the Claude
desktop app over BLE while the dashboard talks to the agent over USB, and
the two share the display, the touchscreen, the LEDs and the buzzer.

Everything here is glue. The logic lives in the `buddy` package (deployed
to /buddy on the board from the BuddyPresto checkout); this module hands it
our display, our pen cache and our display face so the pet looks like it
belongs to this dashboard rather than to a different device.

If the package isn't on the board, main.py carries on without a buddy.
"""

import json
import time

import font
from buddy.app import BuddyApp
from buddy.lights import Lights
from buddy.sound import Sound
from buddy.typo import Type
from buddy.ui import UI

# Printed on our stdout when the pet levels up, for the agent to pick up.
# The agent is already draining this stream for the #V: panel tags, so an
# announcement here reaches the Mac without anyone needing the serial port
# that the agent itself is holding.
LEVEL_TAG = "#B:"

# Announcements are one short line, and the agent ignores one that says
# nothing new, so repeating them costs almost nothing — and it means a
# level-up that lands while the agent is restarting isn't lost for good.
ANNOUNCE_EVERY_MS = 600_000

# The transfer protocol is lock-step — one ack per chunk — and a full
# 480x480 frame costs ~140 ms here, so while a folder push is running we
# redraw rarely and give the time to the BLE tasks instead.
XFER_FRAME_SKIP = 8


class BuddyMode:
    def __init__(self, presto, display, pens, store=None):
        self.store = store
        self.app = BuddyApp(lights=Lights(presto), sound=Sound(),
                            on_level=self._announce)
        width, height = display.get_bounds()
        self.ui = UI(display, pens, Type(display, font=font), width, height)
        self._frame = 0
        self._announce_at = time.ticks_add(time.ticks_ms(), ANNOUNCE_EVERY_MS)

    # --- lifecycle --------------------------------------------------------

    def tasks(self):
        """The coroutines main.py needs to keep running — the BLE bridge
        runs whichever mode is on screen, so a prompt can pull the pet up
        while you're looking at the dashboard."""
        return (self.app.bridge.run(),)

    def name(self):
        return self.app.bridge.name

    def _announce(self, level, reward, snapshot):
        """Tell the Mac about a level-up on the serial line."""
        snapshot["reward"] = reward[3] if reward else None
        try:
            print(LEVEL_TAG + json.dumps(snapshot))
        except Exception as e:
            print("buddy: announce failed:", e)

    def announce_now(self):
        """Publish the current figures without waiting for a level-up —
        called at startup so the Mac has something to draw straight away."""
        self._announce(self.app.store.level(),
                       None, self.app.snapshot())

    # --- per-frame --------------------------------------------------------

    def tick(self):
        """Moods, LEDs and sound. Runs in both modes."""
        self.app.tick()
        if time.ticks_diff(time.ticks_ms(), self._announce_at) >= 0:
            self._announce_at = time.ticks_ms() + ANNOUNCE_EVERY_MS
            self.announce_now()

    def wants_attention(self):
        """True when something needs a human: a permission prompt you
        haven't deferred, or an incoming folder push."""
        return self.app.prompt_active() or self.app.xfer.active

    def render(self):
        """Returns False if this frame was skipped — either for a transfer,
        or because the screen is a still picture that hasn't changed. The
        caller must skip its update() to match."""
        self._frame += 1
        if self.app.xfer.active and self._frame % XFER_FRAME_SKIP:
            return False
        return self.ui.render(self.app)

    def invalidate(self):
        """The dashboard has drawn over our framebuffer — redraw even if
        nothing about the pet changed."""
        self.ui.invalidate()

    # --- touch ------------------------------------------------------------

    def press(self, x, y):
        self.ui.press(x, y)

    def drag(self, x, y):
        """Every frame the finger is still down — swipes fire here rather
        than on release, because a frame is ~140 ms and the position at
        release is usually stale by most of a flick."""
        self.ui.drag(x, y, self.app)

    def cancel(self):
        """main.py claimed the gesture (a mode switch)."""
        self.ui.cancel()

    def release(self, x, y):
        event = self.ui.release(x, y, self.app)
        if event:
            self.app.event(event)
        return event
