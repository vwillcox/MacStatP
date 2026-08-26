#!/usr/bin/env bash
# Refresh the prebuilt apps committed in dist/.
#
# They exist so the menu bar item can be installed without a Swift
# compiler. Run this after changing anything under host/ or packaging/,
# or the committed copies drift from the source.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"

"$HERE/build_app.sh"

rm -rf "$ROOT/dist"
mkdir -p "$ROOT/dist"
cp -R "$ROOT/build/MacStatP.app" "$ROOT/dist/"
cp -R "$ROOT/build/MacStatP Control.app" "$ROOT/dist/"

BIN="$ROOT/dist/MacStatP Control.app/Contents/MacOS/MacStatP Control"
cat > "$ROOT/dist/BUILD.txt" <<TXT
Prebuilt MacStatP apps.

built from: $(cd "$ROOT" && git rev-parse --short HEAD 2>/dev/null || echo unknown)
built on:   $(date -u '+%Y-%m-%d %H:%M UTC')
menu bar:   $(lipo -archs "$BIN" 2>/dev/null || echo 'scripted fallback') (Apple Silicon)

These are a convenience, not the source of truth. If you have changed
anything under host/ or packaging/, run tools/make_dist.sh again or
install from source with tools/install_app.sh.
TXT

echo
echo "dist/ refreshed:"
du -sh "$ROOT/dist/MacStatP.app" "$ROOT/dist/MacStatP Control.app"
cat "$ROOT/dist/BUILD.txt"
