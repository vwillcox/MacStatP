# Mac Status Display — Pimoroni Presto

A 480×480 hardware system monitor for macOS. A small agent on the Mac
samples CPU, GPU, memory, disk and network and sends them to a Pimoroni
Presto over USB; the board draws an AIDA64-style panel with radial gauges,
bar meters, per-core activity and per-interface network traffic.

![the panel](docs/dashboard.png)

## Requirements

- A Pimoroni Presto (RP2350) running the Pimoroni MicroPython build
- macOS, with the system Python 3
- `pyserial` (`pip3 install --user pyserial`) and `mpremote` for deploying
- `pillow` and `numpy`, only for the Mac-side preview renderer

```bash
tools/deploy.sh --run    # copy the device modules and restart the board
```

## Running it

```bash
python3 host/agent.py
```

The board shows a standby card until the agent connects.

**Tap any panel** to open a full-screen breakdown of it; tap again to go
back. **Hold** anywhere on the dashboard to cycle the backlight — the level
is remembered on the SD card. **Swipe down from the top edge** to switch to
the desk pet, if it's installed.

The panel runs at its full 480×480 (`Presto(full_res=True)`) and the RP2350
is overclocked from its stock 200 MHz to 264 MHz in `device/main.py`, which
takes a frame from 166 ms to 138 ms. Rendering is CPU-bound, so the agent
defaults to sending 6 frames a second — roughly what the board can draw.

To start it automatically at login:

```bash
tools/install_agent.sh
```

On this Mac `~/Library/LaunchAgents` is owned by root, so that needs one
`sudo chown` first — the script prints the exact command.

## What's on screen

| Panel | Shows |
|---|---|
| CPU | overall %, 1-minute load, busiest core, per-core bars |
| GPU | utilisation %, VRAM in use, recent peak, history plot |
| MEMORY | pressure %, used/total, wired, compressed, swap |
| DISK | boot volume capacity, read and write throughput |
| NETWORK | Wi-Fi and the live wired link, each with down/up and a sparkline |

Everything is collected without `sudo`: CPU from `host_processor_info()`
via ctypes, GPU from `IOAccelerator` in `ioreg`, memory from `vm_stat`,
disk from `statvfs` plus `IOBlockStorageDriver`, network from `netstat -ib`.

### Tap for detail

| Tap | Full-screen view |
|---|---|
| CPU | top processes by CPU share, with PIDs |
| GPU | device / renderer / tiler utilisation, VRAM in use vs allocated |
| MEMORY | largest processes by resident memory |
| DISK | mounted volumes, biggest consumer first |
| NETWORK | top talkers, per process, with down and up rates |

| | |
|---|---|
| ![CPU](docs/detail-cpu.png) | ![Memory](docs/detail-memory.png) |
| ![Network](docs/detail-network.png) | ![Disk](docs/detail-disk.png) |

Per-process figures come from `ps` and from `nettop -P`, which reports
cumulative bytes per process and — usefully — needs no elevated privileges;
two samples give a rate.

The board prints `#V:<panel>` on its serial line when a panel is opened and
`#V:none` when it closes. The agent watches for that and only then gathers
the process listing, refreshing it about once a second: a listing is roughly
ten times the size of the summary frame and costs ~25 ms to collect, so it
is not worth carrying while nothing is looking at it.

## The second face

The board also runs
[BuddyPresto](https://github.com/vwillcox/BuddyPresto), a desk pet that
talks to the Claude desktop app over BLE and lets permission prompts be
answered from the touchscreen. It shares this project's display face and
palette, so the two modes look like one device.

```bash
git clone https://github.com/vwillcox/BuddyPresto.git   # next to this one
tools/deploy.sh --run
```

**Swipe down from the top edge** switches between them, either way, and the
choice is remembered in the SD card config. The BLE bridge runs in both
modes — the LEDs stay an ambient Claude status light while the dashboard is
on screen — and a permission prompt brings the pet to the front by itself,
dropping back to the dashboard once it's answered.

`tools/deploy.sh` picks the package up from `../BuddyPresto/buddy`
automatically; set `BUDDY_SRC` to point elsewhere, or `BUDDY_SRC=none` to
deploy the dashboard on its own. With the package absent, `device/main.py`
logs that and behaves exactly as it did before it existed — nothing here
depends on the pet being installed.

The one thing to watch: this project overclocks the RP2350 to 264 MHz and
the radio is driven over PIO SPI. If BLE misbehaves, put `CLOCK_HZ` back to
`200_000_000` and compare before blaming the bridge.

## Layout

```
host/     agent.py      samples the Mac, sends one JSON line per frame
          macstats.py   all the metric collection
          pilshim.py    PicoGraphics-shaped surface backed by Pillow
device/   main.py       render loop on the board, and the mode switch
          buddy_mode.py glue for the BuddyPresto desk pet
          dashboard.py  the panel layout
          widgets.py    cards, radial gauges, meters, sparklines
          font.py       renderer for the custom display face
          font_data.py  generated glyph table (do not edit)
          link.py       newline-delimited JSON over USB serial
          storage.py    SD card: settings, history, error log
tools/    deploy.sh     copy the device modules to the board
          preview.sh    (preview.py) render the layout to a PNG on the Mac
          capture.py    screenshot the board's real framebuffer over USB
          glyphs.py     font design source
          build_font.py pack glyphs.py into device/font_data.py
          recover.sh    reflash a board stuck in BOOTSEL
```

## The font

The panel uses a purpose-built display face, "Presto Techno" — bold and
squarish to match the reference hardware monitors. Glyphs are defined as
filled polygons on a 20×28 grid in `tools/glyphs.py`, so they scale to any
size. `tools/build_font.py` packs them into a ~1.1 KB table; 78% of strokes
are axis-aligned rectangles, which PicoGraphics fills about four times
faster than the equivalent polygon.

The renderer hints the outlines, which matters on a panel with no
antialiasing: every glyph starts on a whole pixel so repeated letters are
identical, and any stroke drawn at the design stem width is forced to the
same pixel width. Without that, stems alternated between 2px and 3px
depending on where they landed, which is what made small text look soft.

![specimen](docs/font-specimen.png)

```bash
python3 tools/fontpreview.py   # specimen sheet
python3 tools/build_font.py    # rebuild device/font_data.py
```

## Working on the layout

Two ways to see a change without guessing:

```bash
python3 tools/preview.py                      # software render -> build/preview.png
python3 host/agent.py --preview out.png       # same layout, antialiased 3x
python3 tools/capture.py -o shot.png          # real framebuffer off the board
python3 tools/capture.py --live -o shot.png   # drive the running board, then screenshot
```

`device/dashboard.py` runs unmodified on both the board and the Mac, so the
preview is the same code that ships.

## Why the board draws, not the Mac

Streaming rendered pixels from the Mac was built and measured, and it lost:

| | measured |
|---|---|
| USB serial throughput | 237 KB/s |
| Panel `update()` (DMA to screen) | 23.5 ms → ~42 fps ceiling |
| On-device render, 200 MHz stock | 166 ms → 6.0 fps |
| On-device render, 264 MHz overclock | 138 ms → **7.2 fps** |
| Full 480×480 RGB565 frame | 460,800 B → 1.9 s |

Frames only get small if the artwork is flat-shaded: a delta-encoded frame
compresses to ~5 KB, but the same frame rendered with antialiasing is ~5×
larger, and zlib is a dead end because the board inflates at only 1.7 MB/s
(270 ms per frame). Pushing pixels also stalled the USB link in practice.
Sending ~540 bytes of JSON and letting the board draw is simpler, more
robust, and the board runs standalone.

WiFi was considered and rejected for the same reason: at ~540 bytes/frame
the transport is nowhere near the bottleneck — the panel's own 24 ms update
and the ~166 ms render are. WiFi would only matter if pixels were streamed.

## Recovering a wedged board

Binary protocols on USB CDC need `micropython.kbd_intr(-1)`, which disables
Ctrl-C. If that is left on, `mpremote` can no longer interrupt the board and
a reflash is the only way back — this happened once during development. The
shipped `device/main.py` never disables Ctrl-C, so the board always stays
reachable.

If a board ever does get stuck:

1. Unplug USB, hold **BOOT** on the back, plug USB back in, release.
2. `tools/recover.sh` — it waits for the `RP2350` volume, downloads the
   Pimoroni firmware if it isn't already in `firmware/`, and flashes it.
3. `tools/deploy.sh --run`.

## Notes

- `backup-presto-flash/` (local only, gitignored) holds the Immich slideshow
  project that was on the board before this. It contains a WiFi password and
  an API key in plaintext, so it is mode `700` and never committed.
- The SD card was wiped (it held an old Raspberry Pi boot partition) and now
  stores `/sd/status/` — settings, sparkline history across reboots, and a
  small error log.

## Licence

MIT — see [LICENSE](LICENSE).
