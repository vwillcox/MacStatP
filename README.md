# MacStatP

A hardware system monitor for macOS. A small app on your Mac samples CPU,
GPU, memory, disk and network and sends them over USB to a
[Pimoroni Presto](https://shop.pimoroni.com/products/presto), which draws
them on its 480×480 touchscreen.

![the panel](docs/dashboard.png)

Tap a panel for a breakdown of what's actually using it.

---

## What you need

- A **Pimoroni Presto** running Pimoroni's MicroPython build.
  [v2.0.0](https://github.com/pimoroni/presto/releases/tag/v2.0.0) or later
  is recommended: it renders about 11% faster and adds screen rotation.
- A **Mac** (Apple silicon), macOS 12 or newer
- A **USB-C cable** between the two — one that carries data, not a
  charge-only lead

That's it. No compiler, no `mpremote`, no Python packages to install.

## Install

Either drag it across from a disk image, or run the installer from a
clone. Both end up in the same place.

### From a disk image

```bash
tools/make_dmg.sh          # builds build/MacStatP-<version>.dmg
open build/MacStatP-*.dmg
```

Drag both apps onto the Applications folder in the window, then
**right-click MacStatP in Applications and choose Open**, and confirm.

That right-click is needed exactly once. These apps are signed ad-hoc
rather than with a paid Apple Developer certificate, so macOS does not
recognise the signature and refuses a plain double-click. See
[signing a release](TECHINFO.md#signing-a-release-so-others-can-just-open-it)
if you want to hand this to other people without that step. If it still
refuses:

```bash
xattr -dr com.apple.quarantine "/Applications/MacStatP.app"
xattr -dr com.apple.quarantine "/Applications/MacStatP Control.app"
```

The settings page opens, and **Start at login** on the App tab makes it
come back by itself. Then carry on from step 2 below.

### From a clone

**1. Get the app.**

```bash
git clone https://github.com/vwillcox/MacStatP.git
cd MacStatP
tools/install_app.sh
```

It installs MacStatP into `/Applications`, sets it to start at login,
adds a menu bar item, and opens the settings page in your browser.

**2. Connect the Presto** with a USB-C cable.

**3. Press "Install to the Presto".** On the **Presto** tab, the page will
say whether it can see the board. One button copies the dashboard onto it —
about twenty seconds, with a running log — and the board restarts into the
dashboard by itself.

**4. Set it up however you like** on the other tabs.

That's the whole thing. The install step talks to the board's own REPL over
USB, so nothing else needs to be installed to make it work.

## Using it

| Gesture | What it does |
|---|---|
| **Tap a panel** | Opens a full-screen breakdown of it |
| **Tap again** | Back to the dashboard |
| **Hold anywhere** | Cycles the backlight brightness |
| **Swipe down from the top** | Switches to the desk pet, if installed |

## Settings

The settings page is organised into tabs. Changes take effect
immediately — nothing needs restarting.

| Tab | What's there |
|---|---|
| **Status** | Whether the board is connected, frames sent, sample time |
| **Panels** | Which panels appear, and in what order |
| **Connection** | Serial port, and how many updates a second to send |
| **Display** | Brightness, orientation, bytes vs bits, detail refresh |
| **Measure** | Which disk volume and which network interfaces to watch |
| **App** | The desk pet switch, start at login, page port |

### Orientation

If the board is mounted upside down — which the USB-C socket often
encourages — set **Orientation** to "Upside down" on the Display tab. The
touchscreen follows, so taps still land where you expect. This needs
firmware v2.0.0 or later; on older builds the page says so and leaves the
option disabled.

Changing it restarts the board, since the panel's orientation is fixed
when it is created.

### Choosing panels

On the **Panels** tab you can switch any panel off, and drag the rows (or
use the arrows) to change their order — that's the order they appear on
the screen. Whatever's left grows to fill the display: two panels to a
row, with a full-width row for the network.

The page is only reachable from your own Mac. It has no password, and it
shows what your machine is running, so it deliberately isn't available to
anything else on the network.

## What's on screen

| Panel | Shows |
|---|---|
| **CPU** | Overall %, 1-minute load, busiest core, per-core bars |
| **GPU** | Utilisation, VRAM in use, recent peak, history plot |
| **MEMORY** | Pressure %, used/total, wired, compressed, swap |
| **DISK** | Volume capacity, read and write throughput |
| **NETWORK** | Wi-Fi and wired links, each with down/up and a sparkline |

### Tap for detail

| Tap | Full-screen view |
|---|---|
| CPU | Top processes by CPU share, with PIDs |
| GPU | Device / renderer / tiler utilisation, VRAM in use vs allocated |
| MEMORY | Largest processes by resident memory |
| DISK | Mounted volumes, biggest consumer first |
| NETWORK | Top talkers per process, with down and up rates |

| | |
|---|---|
| ![CPU](docs/detail-cpu.png) | ![Memory](docs/detail-memory.png) |
| ![Network](docs/detail-network.png) | ![Disk](docs/detail-disk.png) |

Everything is read without `sudo`.

## The desk pet (optional)

The board can also run
[BuddyPresto](https://github.com/vwillcox/BuddyPresto), a desk pet that
talks to the Claude desktop app over Bluetooth and lets permission prompts
be answered from the touchscreen. It shares this project's typeface and
palette, so the two look like one device.

It's entirely optional and completely separate — `tools/deploy.sh` never
touches it:

```bash
git clone https://github.com/vwillcox/BuddyPresto.git   # next to this one
tools/install_buddy.sh              # install it
tools/install_buddy.sh --uninstall  # remove it
```

Once installed, the **Desk pet** switch on the App tab decides whether it
runs. Switching it off restarts the board, which takes a few seconds — the
pet's Bluetooth tasks can't be stopped any other way, and leaving the radio
on while the setting said "off" would be misleading.

## If something goes wrong

**The screen says "waiting for Mac".** The app isn't running. Check
`~/Library/Logs/StatusDisplay/agent.err`, or run
`python3 host/agent.py` in a terminal to see what it says.

**Nothing on the screen at all.** Unplug the USB cable, wait a few
seconds, plug it back in, then press **Install to the Presto** again. If
it's still dead, see
[recovering a wedged board](TECHINFO.md#recovering-a-wedged-board).

**"No Presto found".** Check the cable carries data — a charge-only lead
powers the board but never appears to the Mac.

**A setting didn't seem to apply.** The board reports back what it
actually applied, and the app logs it. Look for `board applied` in
`~/Library/Logs/StatusDisplay/agent.log`.

## Uninstall

```bash
tools/install_app.sh --uninstall      # the agent, the menu bar item, login items
tools/install_buddy.sh --uninstall    # the desk pet, if you installed it
```

Your settings stay in `~/Library/Application Support/MacStatP/` in case
you reinstall; delete that folder to remove them too.

---

## Technical details

How it's put together, why the board does the drawing, the custom
typeface, the tests, and how to work on the layout:

**[TECHINFO.md](TECHINFO.md)**

## Licence

MIT — see [LICENSE](LICENSE).
