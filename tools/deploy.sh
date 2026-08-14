#!/usr/bin/env bash
# Copy the device firmware to the Presto and (optionally) reset it.
#
#   tools/deploy.sh            copy files, leave the board at the REPL
#   tools/deploy.sh --run      copy files, then soft-reset into main.py
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
PORT="${PRESTO_PORT:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}"

if [[ -z "${PORT:-}" ]]; then
  echo "no Presto serial port found (set PRESTO_PORT to override)" >&2
  exit 1
fi

FILES=(font_data.py font.py theme.py widgets.py dashboard.py link.py storage.py \
       buddy_mode.py main.py)

# The desk pet lives in its own project; deploy it alongside if it's there.
# Set BUDDY_SRC to point elsewhere, or BUDDY_SRC=none to skip it.
BUDDY_SRC="${BUDDY_SRC:-$ROOT/../BuddyPresto/buddy}"

echo "deploying to $PORT"
for f in "${FILES[@]}"; do
  echo "  $f"
  mpremote connect "$PORT" cp "$ROOT/device/$f" ":$f" >/dev/null
done

if [[ "$BUDDY_SRC" != "none" && -d "$BUDDY_SRC" ]]; then
  mpremote connect "$PORT" mkdir :buddy >/dev/null 2>&1 || true
  for f in "$BUDDY_SRC"/*.py; do
    echo "  buddy/$(basename "$f")"
    mpremote connect "$PORT" cp "$f" ":buddy/$(basename "$f")" >/dev/null
  done
else
  echo "  (no buddy package at $BUDDY_SRC — dashboard only)"
  echo "   git clone https://github.com/vwillcox/BuddyPresto.git next to this"
  echo "   repo for the desk pet, or set BUDDY_SRC=none to silence this."
fi

if [[ "${1:-}" == "--run" ]]; then
  echo "resetting board"
  mpremote connect "$PORT" reset
fi
echo "done"
