#!/usr/bin/env bash
# Build a disk image containing both apps, ready to hand to someone.
#
#   tools/make_dmg.sh            -> build/MacStatP-<version>.dmg
#   VERSION=1.2 tools/make_dmg.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
VERSION="${VERSION:-$(cd "$ROOT" && git describe --tags --always 2>/dev/null \
                       || date +%Y.%m.%d)}"
VOL="MacStatP"
DMG="$ROOT/build/MacStatP-$VERSION.dmg"
STAGE="$ROOT/build/dmg-stage"

"$HERE/build_app.sh"

rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$ROOT/build/MacStatP.app" "$STAGE/"
cp -R "$ROOT/build/MacStatP Control.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

# The apps are ad-hoc signed, not notarised, so the first launch needs
# right-click > Open. Say so where it will actually be read.
cat > "$STAGE/READ ME FIRST.txt" <<'TXT'
MacStatP — status display for the Pimoroni Presto

To install
----------
1. Drag both apps onto the Applications folder in this window.
2. Open Applications, RIGHT-CLICK MacStatP and choose Open, then
   confirm. This is only needed the first time.
3. The settings page opens in your browser.
4. Plug the Presto in with a USB-C cable that carries data.
5. On the "Presto" tab, press "Install to the Presto". It takes about
   twenty seconds and the board restarts into the dashboard.
6. On the "App" tab, turn on "Start at login" if you want it to come
   back by itself.

MacStatP Control is the menu bar item: status, settings, and stopping
or restarting the agent. Open it the same way the first time.

Why right-click > Open?
-----------------------
These apps are signed ad-hoc rather than with a paid Apple Developer
certificate, so macOS does not recognise the signature and refuses a
normal double-click. Right-click > Open tells it you meant to.

If macOS still refuses, clear the download flag from a terminal:

    xattr -dr com.apple.quarantine "/Applications/MacStatP.app"
    xattr -dr com.apple.quarantine "/Applications/MacStatP Control.app"

Source, and the rest of the documentation:
https://github.com/vwillcox/MacStatP
TXT

hdiutil create -volname "$VOL" -srcfolder "$STAGE" -ov -format UDZO \
  -quiet "$DMG"
rm -rf "$STAGE"

echo "built $DMG"
echo "  $(du -h "$DMG" | cut -f1)  volume: $VOL  version: $VERSION"
hdiutil verify -quiet "$DMG" && echo "  image verifies"
