#!/usr/bin/env bash
# Reflash the Presto after it has been put into BOOTSEL mode.
#
# Put the board in BOOTSEL: hold the BOOT button on the back while you
# plug in the USB-C cable (or while tapping RESET), then run this. A
# volume called RPI-RP2 appears; copying the UF2 onto it reflashes the
# board, which reboots automatically.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
FW_VERSION="v2.0.0"
FW_NAME="presto-${FW_VERSION}-micropython-with-filesystem.uf2"
FW_URL="https://github.com/pimoroni/presto/releases/download/${FW_VERSION}/${FW_NAME}"
UF2="${1:-$ROOT/firmware/$FW_NAME}"

# The image is ~3 MB, so it is fetched on demand rather than committed.
if [[ ! -f "$UF2" ]]; then
  echo "firmware not present, downloading $FW_NAME"
  mkdir -p "$(dirname "$UF2")"
  if ! curl -fsSL -o "$UF2" "$FW_URL"; then
    echo "download failed: $FW_URL" >&2
    exit 1
  fi
fi

# A truncated download would brick the board rather than fix it.
if [[ "$(head -c 4 "$UF2")" != "UF2"$'\n' ]]; then
  echo "not a valid UF2 image: $UF2" >&2
  exit 1
fi

# RP2040 boards mount as RPI-RP2; the RP2350 in the Presto mounts as RP2350.
echo "waiting for the board to appear in BOOTSEL mode..."
for _ in $(seq 1 240); do
  VOL="$(ls -d /Volumes/RPI-RP2* /Volumes/RP2350* 2>/dev/null | head -1 || true)"
  if [[ -n "$VOL" ]]; then
    echo "found $VOL"
    echo "copying $(basename "$UF2")"
    cp "$UF2" "$VOL/"
    sync
    echo "flashed - the board will reboot on its own"
    echo "wait ~10s, then run: tools/deploy.sh --run"
    exit 0
  fi
  sleep 1
done

echo "timed out: no RPI-RP2 volume appeared" >&2
echo "hold BOOT while plugging the USB-C cable in, then re-run this." >&2
exit 1
