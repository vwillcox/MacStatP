#!/usr/bin/env bash
# Install or remove the BuddyPresto desk pet on the board.
#
# The pet is optional and entirely separate from the dashboard: this puts
# its package on the board, and --uninstall takes it off again. Whether an
# installed pet actually runs is a setting on the configuration page.
#
#   tools/install_buddy.sh              install from ../BuddyPresto/buddy
#   BUDDY_SRC=/path tools/install_buddy.sh
#   tools/install_buddy.sh --uninstall
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
PORT="${PRESTO_PORT:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}"
BUDDY_SRC="${BUDDY_SRC:-$ROOT/../BuddyPresto/buddy}"

if [[ -z "${PORT:-}" ]]; then
  echo "no Presto serial port found (set PRESTO_PORT to override)" >&2
  exit 1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
  echo "removing the desk pet from $PORT"
  mpremote connect "$PORT" exec "
import os
def rm(p):
    try:
        st = os.stat(p)
    except OSError:
        return 0
    n = 0
    if st[0] & 0x4000:
        for e in os.listdir(p):
            n += rm(p + '/' + e)
        os.rmdir(p)
    else:
        os.remove(p)
    return n + 1
n = rm('/buddy') + rm('/buddy_mode.py')
print('removed', n, 'files')
" || true
  echo "done — the dashboard is unaffected"
  echo "turn the setting off too, or the page will keep offering it"
  exit 0
fi

if [[ ! -d "$BUDDY_SRC" ]]; then
  cat >&2 <<MSG
no desk pet package at $BUDDY_SRC

Clone it next to this repo, or point BUDDY_SRC at your checkout:

    git clone https://github.com/vwillcox/BuddyPresto.git
    tools/install_buddy.sh
MSG
  exit 1
fi

echo "installing the desk pet on $PORT"
echo "  buddy_mode.py"
mpremote connect "$PORT" cp "$ROOT/device/buddy_mode.py" :buddy_mode.py >/dev/null
mpremote connect "$PORT" mkdir :buddy >/dev/null 2>&1 || true
for f in "$BUDDY_SRC"/*.py; do
  echo "  buddy/$(basename "$f")"
  mpremote connect "$PORT" cp "$f" ":buddy/$(basename "$f")" >/dev/null
done

echo
echo "installed. It runs only while 'Desk pet' is on in the settings page."
