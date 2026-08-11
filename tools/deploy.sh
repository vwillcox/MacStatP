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

FILES=(font_data.py font.py theme.py widgets.py dashboard.py link.py storage.py main.py)

echo "deploying to $PORT"
for f in "${FILES[@]}"; do
  echo "  $f"
  mpremote connect "$PORT" cp "$ROOT/device/$f" ":$f" >/dev/null
done

if [[ "${1:-}" == "--run" ]]; then
  echo "resetting board"
  mpremote connect "$PORT" reset
fi
echo "done"
