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

import font
from buddy.app import BuddyApp
from buddy.lights import Lights
from buddy.sound import Sound
from buddy.typo import Type
from buddy.ui import UI

# The transfer protocol is lock-step — one ack per chunk — and a full
# 480x480 frame costs ~140 ms here, so while a folder push is running we
# redraw rarely and give the time to the BLE tasks instead.
XFER_FRAME_SKIP = 8


class BuddyMode:
    def __init__(self, presto, display, pens, store=None):
        self.store = store
        self.app = BuddyApp(lights=Lights(presto), sound=Sound())
        width, height = display.get_bounds()
        self.ui = UI(display, pens, Type(display, font=font), width, height)
        self._frame = 0

    # --- lifecycle --------------------------------------------------------

    def tasks(self):
        """The coroutines main.py needs to keep running — the BLE bridge
        runs whichever mode is on screen, so a prompt can pull the pet up
        while you're looking at the dashboard."""
        return (self.app.bridge.run(),)

    def name(self):
        return self.app.bridge.name

    # --- per-frame --------------------------------------------------------

    def tick(self):
        """Moods, LEDs and sound. Runs in both modes."""
        self.app.tick()

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
