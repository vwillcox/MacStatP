# MacStatP — technical notes

How the thing is put together, and why it's put together that way. For
installing and using it, see [README.md](README.md).

## How it fits together

```
   Mac                              USB serial                 Presto
   ┌───────────────────────┐                        ┌──────────────────────┐
   │ macstats.py  sample   │  ~540 bytes of JSON    │ link.py    parse     │
   │ agent.py     send  ───┼───────────────────────►│ dashboard.py  draw   │
   │ webui.py     settings │◄───────────────────────┼── stdout tags        │
   └───────────────────────┘   #V: #C: #I: #B:      └──────────────────────┘
```

The Mac samples once per frame and sends one compact JSON object per line.
The board parses it and draws the panel itself. Settings ride along in the
same frame, so there's no second channel to keep in sync.

The board talks back over its stdout, which the agent is already draining:

| Tag | Meaning |
|---|---|
| `#V:` | A panel was opened or closed, so gather (or stop gathering) process detail |
| `#C:` | Settings the board actually applied |
| `#I:` | What this board has and can do: whether the desk pet is installed, and whether the firmware can rotate |
| `#B:` | The desk pet levelled up |

`#C:` exists because a setting that silently fails to apply is very hard to
diagnose. Working it out from screenshots once cost an afternoon: a stale
capture looked exactly like a setting being ignored.

## Why the board draws, not the Mac

Streaming rendered pixels from the Mac was built and measured, and lost:

| | measured |
|---|---|
| USB serial throughput | 237 KB/s |
| Panel `update()` (DMA to screen) | 23.5 ms → ~42 fps ceiling |
| On-device render, 200 MHz stock | 166 ms → 6.0 fps |
| On-device render, 264 MHz overclock | 138 ms → 7.2 fps |
| Same, on firmware v2.0.0 (MicroPython 1.29) | 124 ms → **8.1 fps** |
| Full 480×480 RGB565 frame | 460,800 B → 1.9 s |

Frames only get small if the artwork is flat-shaded: a delta-encoded frame
compresses to ~5 KB, but the same frame rendered with antialiasing is ~5×
larger, and zlib is a dead end because the board inflates at only 1.7 MB/s
(270 ms per frame). Pushing pixels also stalled the USB link in practice.

Sending ~540 bytes of JSON and letting the board draw is simpler, more
robust, and leaves the board able to run standalone.

WiFi was considered and rejected for the same reason: at ~540 bytes a frame
the transport is nowhere near the bottleneck — the panel's own 24 ms update
and the ~138 ms render are. WiFi would only matter if pixels were streamed.

The RP2350 is overclocked from its stock 200 MHz to 264 MHz in
`device/main.py`. Rendering is entirely CPU-bound, so that's a
proportional gain. If Bluetooth misbehaves with the desk pet installed,
put `CLOCK_HZ` back to `200_000_000` and compare before blaming the
bridge — the radio is driven over PIO SPI.

## Firmware

Built against Pimoroni's Presto firmware. v2.0.0 moved from MicroPython
1.26 to 1.29, which is worth having: the same render dropped from 138 ms
to 124 ms, about 11% for free. It also fixed a PIO stall in
`start_frame_xfer` that could leave the panel blank, and made the FT6236
touch controller survive transient I2C failures instead of raising —
both of which this project was carrying its own defences against.

Two things to know if you are on an older build:

- **Rotation** (`rotate=ROTATE_180`) arrived in v2.0.0. `device/main.py`
  imports it defensively and falls back to no rotation, so the code runs
  unchanged on v1.0.0; the settings page disables the option and says
  why.
- `tools/recover.sh` fetches v2.0.0. Change `FW_VERSION` in it to flash
  something else.

`@micropython.native` is worth a note: `hasattr(micropython, "native")`
is False on 1.29, which looks alarming, but the decorator is handled by
the compiler rather than resolved at runtime and still works. Test it by
compiling something, not by asking the module.

## Collecting the metrics

Everything is readable by a normal user, no `sudo` anywhere:

| Metric | Source |
|---|---|
| CPU | `host_processor_info()` via ctypes |
| GPU | `IOAccelerator` performance statistics from `ioreg` |
| Memory | `vm_stat` plus `sysctl hw.memsize` |
| Disk | `statvfs` for capacity, `IOBlockStorageDriver` for throughput |
| Network | `netstat -ibn` byte counters |
| Per-process | `ps`, and `nettop -n -P` for per-process network |

The `-n` on `netstat` and `nettop` is essential, not cosmetic. Without it
they reverse-resolve addresses, and with the network down those lookups
block until DNS gives up: `netstat -ib` took 5 s instead of 10 ms, which
emptied the interface list and dragged a 29 ms sample out to 3 s. Working
DNS had been hiding that for weeks.

Process listings are only gathered while a detail panel is actually open —
they're about ten times the size of a summary frame and cost ~25 ms — which
is what the `#V:` tag is for.

## Layout engine

Nothing assumes a fixed grid. `pack()` in `device/dashboard.py` takes the
enabled panels, in the order chosen in the settings, and lays them out:
pairs share a row, the network takes a full-width row, and row heights are
shared out by weight with the last row stretched to the bottom margin so
rounding can't leave a gap.

Each panel then works out its contents from the box it's handed, so the
same code draws a half-width card and a full-screen one. Gauges and text
scale, value columns are measured against the labels beside them, and
where there's more room than the contents need the surplus goes into the
gaps with the remainder centred, rather than stretching everything.

Panels drop their least important parts rather than overflowing when a
box is short: the plots go first, then a meter, then rows of figures.
Every panel is also clipped to its own card while it draws — the geometry
is careful, but a panel that gets its arithmetic wrong should draw itself
badly rather than scribble over its neighbour.

That was not always true. Five panels with the network in the middle
makes four rows, and at that height the fixed minimum sizes ran past the
bottom edge: CPU's cores, GPU's history, MEMORY's rows and DISK's
throughput all drew over the panel below, which looked exactly like the
display corrupting.

All 31 on/off combinations and all 325 orderings are checked by the
tests, and `host/test_layout.py` sweeps every box size the packer can
produce, asserting nothing lands past an edge and that a real render
leaves the gaps between cards untouched.

## Pages

`device/pages.py` holds the full-screen views: a list of sparklines, the
cores as bars or as a heatmap, and a network graph. Each owns the whole
screen, draws its own header and works from `History`, which accumulates
what arrives — the host sends a snapshot per frame, not a series.

The page list rides with every frame in the same compact form the panels
use: `dials|glance:cpu,gpu|cores_bars`. A pipe between pages, an optional
colon-separated argument list.

One thing to know if you add a page type: **`font.width()` returns a
float**, and PicoGraphics rejects float coordinates. Anything derived
from a text measurement has to be made whole before it is drawn. This
went unnoticed because the preview shim happily accepted floats while the
board raised `TypeError` on exactly the same code — so the shim now
refuses them too, and a preview fails where the hardware would.

### The network curve

The network page draws a Catmull-Rom curve rather than joining the
samples with straight segments. Sixty samples across 373 pixels is six
pixels a sample, which as bars or chords reads as a staircase.

Evaluating the cubic per pixel cost 79 ms a frame, which misses the
frame rate on its own. Two changes brought it to 30 ms with no visible
difference:

- the cubic's coefficients change once per segment, not once per pixel,
  so they are computed 59 times instead of 373
- the cubic is evaluated every third pixel and the gaps are walked in a
  straight line — over three pixels a cubic and a chord are the same
  picture

The curve passes through every sample, so it smooths the *line* and not
the data: a spike stays exactly as tall as it measured. Catmull-Rom
overshoots around a sharp corner, so the result is clamped to the plot
rather than allowed to escape it.

Whole page: 120 ms against the dials' 94 ms, both inside the 143 ms that
the default 7 fps allows. `clear()` alone is 34 ms of that.

## The font

The panel uses a purpose-built display face, "Presto Techno" — bold and
squarish to match the hardware monitors it's modelled on. Glyphs are
defined as filled polygons on a 20×28 grid in `tools/glyphs.py`, so they
scale to any size. `tools/build_font.py` packs them into a ~1.1 KB table;
78% of strokes are axis-aligned rectangles, which PicoGraphics fills about
four times faster than the equivalent polygon.

The renderer hints the outlines, which matters on a panel with no
antialiasing: every glyph starts on a whole pixel so repeated letters are
identical, and any stroke drawn at the design stem width is forced to the
same pixel width. Without that, stems alternated between 2 px and 3 px
depending on where they landed, which is what made small text look soft.

![specimen](docs/font-specimen.png)

```bash
python3 tools/fontpreview.py   # specimen sheet
python3 tools/build_font.py    # rebuild device/font_data.py
```

## Working on the layout

Four ways to see a change without guessing:

```bash
python3 tools/preview.py                      # software render -> build/preview.png
python3 tools/preview_panels.py               # every panel combination
python3 tools/preview_detail.py               # every drill-down screen
python3 host/agent.py --preview out.png       # same layout, antialiased 3x
```

And on the hardware itself:

```bash
python3 tools/capture.py -o shot.png          # real framebuffer off the board
python3 tools/capture.py --live -o shot.png   # drive the running board, then screenshot
```

`device/dashboard.py` runs unmodified on both the board and the Mac, so
the preview is the same code that ships. `tools/capture.py` deletes the previous screenshot before asking for a
new one, and resets the board first. Both matter: pulling a screenshot
uses mpremote, which leaves the board at the REPL with `main.py` stopped,
so the next capture feeds frames to a prompt that echoes them and returns
the previous screenshot. That looks exactly like a setting failing to
apply, and wasted a great deal of time before it was spotted.

## Tests

```bash
python3 host/test_agent.py     # link handling: unplug, replug, bad samples
python3 host/test_webui.py     # settings page, over real HTTP
python3 host/test_pushcode.py  # the raw REPL transfer, against a fake board
```

Both drive the real code paths — a fake serial port for the link, an
actual server for the page.

Two of the assertions are there because the bug they catch actually
happened. The settings page must never run `launchctl` against its own
label: the page is served *by* the agent, so doing that unloaded the
process mid-request and changing the brightness stopped the display. And
`Display.set_backlight` must route to the Presto rather than being
forwarded to PicoGraphics, where it silently does nothing.

## Project layout

```
host/     agent.py         samples the Mac, sends one JSON line per frame
          macstats.py      all the metric collection
          config.py        settings, stored outside the checkout
          webui.py         the settings page, loopback only
          pilshim.py       PicoGraphics-shaped surface backed by Pillow
          test_agent.py    tests for the link
          test_webui.py    tests for the settings page
          installer.py     borrows the port from the stream loop
          pushcode.py      raw REPL file transfer, no mpremote needed
          test_pushcode.py tests for the transfer
device/   main.py          render loop on the board, and the mode switch
          dashboard.py     the dials page, and the packing engine
          pages.py         the other page types, and their history
          widgets.py       cards, radial gauges, meters, sparklines
          font.py          renderer for the custom display face
          font_data.py     generated glyph table (do not edit)
          link.py          newline-delimited JSON over USB serial
          storage.py       SD card: settings, history, error log
          buddy_mode.py    glue for the desk pet (installed separately)
packaging/Launcher.swift   the agent bundle's main executable
          launch.py        the Python entry point it hands over to
          Info.plist       agent bundle metadata
          MenuBar.swift    the menu bar item, compiled at build time
          Control-Info.plist  its bundle metadata
          control.py       scripted fallback where Swift is unavailable
dist/     MacStatP.app     prebuilt, committed so no compiler is needed
          MacStatP Control.app
          BUILD.txt        which commit they came from
tools/    deploy.sh        copy the dashboard to the board
          install_app.sh   build and install MacStatP.app
          install_buddy.sh install or remove the optional desk pet
          build_app.sh     assemble the .app bundles
          make_dist.sh     rebuild and refresh dist/
          make_dmg.sh      build a disk image of both apps
          sign_release.sh  sign, notarise and staple that image
          make_icon.py     render the app icon from the panel's own motif
          recover.sh       reflash a board stuck in BOOTSEL
          capture.py       screenshot the board's real framebuffer over USB
          preview*.py      software renders of the layout
          glyphs.py        font design source
          build_font.py    pack glyphs.py into device/font_data.py
          raster.py        tiny scanline rasteriser behind the previews
```

Settings live in `~/Library/Application Support/MacStatP/config.json`,
deliberately outside the checkout. The launch agent once pointed at a copy
of the repo that had been moved to another disk and simply sat there
failing to start; nothing needed at runtime should live at an address that
can move.

## Installing to the board from the page

The **Presto** tab copies the dashboard onto the board without `mpremote`
or any other tool, by speaking MicroPython's raw REPL over the serial
port (`host/pushcode.py`):

```
\r\x03\x03   interrupt whatever is running
\x01         enter raw REPL   -> "raw REPL; CTRL-B to exit\r\n>"
\x04         soft reset       -> a clean VM, and main.py does not re-run
<code>\x04   run it           -> [OK] stdout \x04 stderr \x04 ">"
\x02         back to the friendly REPL
```

Globals persist between submissions in raw mode, so a file is opened
once and written in chunks of base64.

Three things that had to be right, each of which wedged the board until
it was:

- **The soft reset is not optional.** Ctrl-C stops the running program
  but leaves asyncio tasks scheduled, and the desk pet's Bluetooth tasks
  kept going. Opening a file for writing then blocked and took the board
  with it. Resetting from raw mode clears everything.
- **Flow control is not optional either.** The board's USB receive buffer
  is a couple of hundred bytes, so a single large command overruns it and
  the board simply stops answering. Raw-paste mode (`\x05A\x01`) has the
  board advertise a window and ask for more as it consumes.
- **Anything read past a terminator belongs to the next reply.** Dropping
  it stalled every command after the first, because a whole reply often
  arrives in one chunk.

Chunk size and the serial read timeout dominate the transfer: 512-byte
chunks with a 0.3 s timeout gave 4.3 KB/s, while 4 KB chunks with a
0.05 s timeout give 18.7 KB/s — the whole dashboard in a few seconds.

The agent holds the port continuously, so an install borrows it:
`host/installer.py` raises a flag, the stream loop closes its port and
confirms, the files go across, and the loop reconnects afterwards the way
it would from any other disconnection. The device's own `.py` files are
copied into the app bundle at build time, so this works from
`/Applications` with no checkout present.

## The menu bar item

`MacStatP Control` is a separate bundle from the agent, and deliberately
so: the agent is a long-running background process, and giving it a user
interface would mean running an NSApplication event loop alongside the
frame loop for no good reason. Two processes, each doing one thing.

It's written in Swift because a menu bar item needs a real
`NSStatusItem`, and compiling it means nothing has to be installed
alongside — the system Python has no PyObjC. `tools/build_app.sh`
compiles it with the CommandLineTools SDK.

Where `swiftc` isn't available the build falls back to
`packaging/control.py`, which uses `osascript` for a dialog and needs a
Dock icon rather than a menu bar item. It can do the same things, less
elegantly.

### Disk images

`tools/make_dmg.sh` stages both apps with an Applications symlink and a
plain-text note, and builds a compressed image — about 770 KB. Ad-hoc
signatures survive it, verified by mounting the result and running
`codesign --verify` on what comes out.

What does not survive is Gatekeeper's patience. A downloaded image is
quarantined, and without a Developer ID signature and notarisation macOS
refuses a plain double-click. Right-click and Open clears it for that
app, which is why the note inside the image says so rather than leaving
someone to work it out. Notarising properly needs a paid Apple developer
account.

### Signing a release, so others can just open it

Ad-hoc signing is what you get for free, and it is why a downloaded image
needs right-click > Open. Removing that step needs a paid **Apple
Developer Program** membership (about £79 / $99 a year) — there is no
free route. Gatekeeper accepts exactly one identity for apps distributed
outside the App Store: **Developer ID Application**.

`tools/sign_release.sh` does the whole pipeline once you have one:

```bash
# once
xcrun notarytool store-credentials macstatp \
  --apple-id you@example.com --team-id ABCDE12345 \
  --password xxxx-xxxx-xxxx-xxxx      # app-specific, from appleid.apple.com

# each release
security find-identity -v -p codesigning          # copy the full name
IDENTITY="Developer ID Application: Your Name (ABCDE12345)" \
  tools/sign_release.sh
```

It signs both apps with the hardened runtime and a secure timestamp,
builds the image, signs that too, submits it to Apple's notary service,
waits, and staples the ticket so it validates offline. `notarytool` and
`stapler` ship with the command line tools, so full Xcode is not needed.

**One thing had to change to make this possible at all.** The agent's
main executable used to be a `/bin/sh` stub that ran Python. Notarisation
requires a bundle's main executable to be a Mach-O binary and rejects a
script however it is signed, so `packaging/Launcher.swift` replaced it —
about twenty lines that set `MACSTATP_EXE` and `execv` into
`/usr/bin/python3`. `execv` rather than spawn, so no extra process hangs
around and launchd keeps watching the one doing the work. Both bundles
are now real binaries.

The Python inside the bundle is not a problem: it is data to Apple's own
signed `python3`, which runs as a separate process and is unaffected by
this app's hardened runtime.

What is verified here and what is not: the bundles are Mach-O, ad-hoc
signed and pass `codesign --verify` after a round trip through the disk
image, and `spctl` currently reports "rejected — no usable signature",
which is exactly what an unsigned image should say. The notarisation
steps themselves are written from Apple's documented process and have
**not** been run, because there is no certificate on this machine to run
them with.

### Committed binaries

`dist/` holds both bundles already built. Committing build output is
normally a bad habit — it goes stale, and the binary stops matching the
source that claims to produce it. It earns its place here for one
reason: without a Swift compiler there is no menu bar item at all, and
requiring Xcode's command line tools to get a menu bar icon is a poor
trade.

Two mitigations. `dist/BUILD.txt` records the commit they were built
from, so drift is visible rather than silent, and `tools/make_dist.sh`
refreshes them in one step. `tools/install_app.sh` still builds from
source whenever `swiftc` is present, and only falls back to `dist/`
when it is not.

The bundles are ad-hoc signed. That survives a `git` round trip, since
the signature lives in the file contents rather than in extended
attributes — but a ZIP download picks up `com.apple.quarantine`, which
has to be cleared before macOS will open them.

`LSUIElement` is true in its Info.plist, so it starts in the menu bar.
"Show in Dock" calls `setActivationPolicy(.regular)` at runtime, which
adds the Dock icon without restarting. The preference lives in
`UserDefaults` rather than the shared config file: it belongs to the
control app, and putting it in the config would mean the settings page's
schema had to carry a key it has no business knowing about.

Restarting the agent uses `launchctl kickstart -k`, which is atomic.
Doing it as bootout-then-bootstrap races with launchd letting go of the
label; that path is only the fallback.

## Recovering a wedged board

Binary protocols on USB CDC need `micropython.kbd_intr(-1)`, which
disables Ctrl-C. If that's left on, `mpremote` can no longer interrupt the
board and a reflash is the only way back — which happened once during
development. The shipped `device/main.py` never disables Ctrl-C, so the
board always stays reachable.

If a board does get stuck:

1. Unplug USB, hold **BOOT** on the back, plug USB back in, release.
2. `tools/recover.sh` — it waits for the `RP2350` volume, downloads the
   Pimoroni firmware if it isn't already in `firmware/`, and flashes it.
3. `tools/deploy.sh --run`.

Note that RP2350 boards mount as `RP2350`, not the `RPI-RP2` you may be
expecting from an RP2040.

## Notes

- The SD card holds `/sd/status/` — settings, sparkline history that
  survives reboots, and a small error log. It's worth reading when
  something on the board misbehaves.
- `backup-presto-flash/` (local only, gitignored) holds whatever was on
  the board before this project. If yours contains WiFi credentials or API
  keys, keep it out of version control.
