"""Mac status display for Pimoroni Presto.

The Mac sends one small JSON object per frame (~600 bytes) over USB serial
and the board draws the dashboard itself. Streaming rendered pixels instead
was tried and abandoned: a frame only compresses well while the artwork is
flat-shaded, and pushing tens of KB per frame through USB CDC stalled the
link far more than local drawing costs.

The board runs standalone — with no host connected it shows a standby card
rather than a blank screen.

The board has a second face: swipe down from the top edge to switch between
this dashboard and the Claude desk pet (device/buddy_mode.py), which talks
to the Claude desktop app over BLE. The pet's bridge runs in both modes, so
a permission prompt can pull it to the front on its own.
"""

import asyncio
import gc
import time

import machine

# Overclock before anything else initialises: the RP2350 boots at 200 MHz
# and 264 is the usual safe step for the Presto. Rendering is entirely
# CPU-bound here, so this buys a proportional jump in frame rate.
CLOCK_HZ = 264_000_000
try:
    machine.freq(CLOCK_HZ)
except Exception as _e:      # fall back to the stock clock rather than fail
    print("overclock rejected:", _e)

from presto import Presto  # noqa: E402  (must follow the clock change)

import dashboard
import storage
import theme
from link import Link

SAVE_EVERY = 30      # seconds between history writes to the SD card
IDLE_LIMIT = 5       # seconds without data before the link reads as dead
HOLD_MS = 700        # press longer than this is a hold, not a tap
VIEW_TAG = "#V:"     # prefix the agent watches for on our stdout

DASH, BUDDY = 0, 1   # the two faces
SHADE_TOP = 60       # a swipe starting this high up is the mode switch
SHADE_PULL = 70      # ...and has to travel this far down to count


class Display:
    """Routes PicoGraphics drawing through the panel's update()."""

    def __init__(self, presto):
        self._p = presto
        self._g = presto.display

    def __getattr__(self, name):
        return getattr(self._g, name)

    def update(self):
        self._p.update()


def cycle_brightness(level):
    for step in (0.25, 0.55, 0.85, 1.0):
        if level < step - 0.01:
            return step
    return 0.25


def start_buddy(presto, display, pens, store):
    """Bring up the desk pet, if its package is on the board.

    A missing or broken buddy must never cost us the dashboard, so this
    swallows anything that goes wrong and reports it instead.
    """
    try:
        from buddy_mode import BuddyMode
    except ImportError:
        store.log("buddy: package not installed")
        return None
    try:
        buddy = BuddyMode(presto, display, pens, store)
    except Exception as e:
        store.log("buddy: init failed: %s" % e)
        return None
    for task in buddy.tasks():
        asyncio.create_task(task)
    store.log("buddy: advertising as %s" % buddy.name())
    buddy.announce_now()
    return buddy


async def main():
    print("Status display: starting")
    presto = Presto(full_res=True)
    d = Display(presto)
    # Owning the framebuffer lets the board screenshot itself on request,
    # which is how the layout gets verified without looking at the panel.
    fb = bytearray(480 * 480 * 2)
    d.set_framebuffer(fb)
    pens = theme.Pens(d)

    store = storage.Storage()
    db = dashboard.Dashboard(d, pens)

    db.splash("MAC STATUS", ["STARTING UP"])
    d.update()

    if store.available:
        links = store.load_history()
        db.seed(links)
        store.log("boot: sd ok, history for %d links" % len(links))
    else:
        store.log("boot: no sd card")

    brightness = float(store.config.get("brightness", 0.85))
    try:
        d.set_backlight(brightness)
    except Exception:
        pass

    link = Link()
    try:
        touch = presto.touch
    except Exception:
        touch = None

    buddy = start_buddy(presto, d, pens, store)
    mode = DASH
    if buddy and store.config.get("mode") == "buddy":
        mode = BUDDY
    pulled_by_buddy = False   # the pet interrupted us; go back when it's done

    data = None
    detail = None
    view = None          # None = dashboard, otherwise the open panel
    last_rx = 0.0
    last_save = time.time()
    was_linked = None
    touch_down = False
    swiped = False       # this gesture already fired as a swipe
    press_at = 0
    press_xy = (0, 0)
    last_xy = (0, 0)
    frames = 0

    while True:
        incoming = link.read()
        shot = False
        if incoming:
            if incoming.get("cmd") == "shot":
                shot = True
            else:
                data = incoming
                detail = incoming.get("det")
                db.push(data)
                last_rx = time.time()

        linked = data is not None and (time.time() - last_rx) < IDLE_LIMIT

        # The pet's moods, LEDs and chirps run in both modes — it's an
        # ambient status light while the dashboard is on screen.
        if buddy:
            buddy.tick()
            if buddy.wants_attention():
                if mode == DASH:
                    mode = BUDDY
                    pulled_by_buddy = True
                    buddy.invalidate()
            elif pulled_by_buddy:
                mode = DASH
                pulled_by_buddy = False

        # Tap a panel to open its breakdown, tap again to close. Holding
        # anywhere on the dashboard cycles the backlight instead. A swipe
        # down from the top edge switches between the two faces.
        if touch is not None:
            try:
                touch.poll()
                pressed = bool(touch.state)
                if pressed:
                    last_xy = (touch.x, touch.y)
                if pressed and not touch_down:
                    press_at = time.ticks_ms()
                    press_xy = last_xy
                    swiped = False
                    if mode == BUDDY and buddy:
                        buddy.press(press_xy[0], press_xy[1])
                elif pressed and touch_down:
                    # Mid-drag. A frame is ~140 ms, so a flick is only
                    # sampled two or three times and the position at
                    # release has usually lost most of the travel — decide
                    # the swipe here, as soon as it's gone far enough.
                    if (not swiped and buddy is not None
                            and press_xy[1] <= SHADE_TOP
                            and last_xy[1] - press_xy[1] >= SHADE_PULL):
                        swiped = True
                        mode = BUDDY if mode == DASH else DASH
                        pulled_by_buddy = False
                        store.config["mode"] = "buddy" if mode == BUDDY else "dash"
                        store.save_config()
                        buddy.cancel()
                        buddy.invalidate()   # the other face owns the buffer
                        if view is not None:
                            view = None
                            print(VIEW_TAG + "none")
                    elif not swiped and mode == BUDDY and buddy:
                        buddy.drag(last_xy[0], last_xy[1])
                elif touch_down and not pressed:
                    held = time.ticks_diff(time.ticks_ms(), press_at)
                    if swiped:
                        pass  # the gesture already did its work
                    elif mode == BUDDY and buddy:
                        buddy.release(last_xy[0], last_xy[1])
                    elif view is not None:
                        view = None
                        print(VIEW_TAG + "none")
                    elif held >= HOLD_MS:
                        brightness = cycle_brightness(brightness)
                        store.config["brightness"] = brightness
                        store.save_config()
                        try:
                            d.set_backlight(brightness)
                        except Exception:
                            pass
                    else:
                        hit = db.hit_test(press_xy[0], press_xy[1])
                        if hit:
                            view = hit
                            detail = None
                            # Tell the agent which breakdown to collect;
                            # it only gathers process lists on demand.
                            print(VIEW_TAG + view)
                touch_down = pressed
            except Exception:
                pass

        drew = True
        if mode == BUDDY and buddy:
            drew = buddy.render()
        elif data is None:
            db.splash("WAITING FOR MAC", ["RUN HOST/AGENT.PY",
                                          "ON YOUR MAC"])
        elif view is not None:
            db.detail(view, data, detail)
        else:
            db.render(data, linked=linked)
        if drew:
            d.update()

        if shot and store.available:
            try:
                store.log("screenshot %d bytes" % storage.screenshot(fb))
            except Exception as e:
                store.log("screenshot failed: %s" % e)

        frames += 1

        if was_linked != linked:
            store.log("link %s" % ("up" if linked else "down"))
            was_linked = linked

        now = time.time()
        if store.available and now - last_save >= SAVE_EVERY:
            store.save_history(db.links)
            last_save = now
            gc.collect()

        # Hand the loop over so the BLE tasks can run. A frame here costs
        # ~140 ms, so this is the granularity the bridge is serviced at —
        # fine for a 10 s heartbeat, and buddy_mode drops frames while a
        # folder push needs the bandwidth. When the pet's screen is a
        # still picture there's no frame to pace against, so idle properly
        # instead of spinning the touch bus flat out.
        await asyncio.sleep_ms(1 if drew else 20)


try:
    asyncio.run(main())
except KeyboardInterrupt:
    # Fall through to the REPL so the board always stays serviceable.
    print("interrupted")
except Exception as exc:
    import sys
    sys.print_exception(exc)
    # Also put it on the SD card. Printing alone goes to a serial line
    # nobody is reading — the agent drains and discards it — so a crash
    # that resets the board leaves no trace of why.
    try:
        import io
        buf = io.StringIO()
        sys.print_exception(exc, buf)
        storage.Storage().log("crash: " + buf.getvalue()[-500:])
    except Exception:
        pass
    time.sleep(10)
    machine.reset()
