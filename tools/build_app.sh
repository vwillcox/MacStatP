#!/usr/bin/env bash
# Assemble build/MacStatP.app — a background agent with a settings page.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
OUT="$ROOT/build/MacStatP.app"
VERSION="$(cd "$ROOT" && git describe --tags --always 2>/dev/null || date +%Y.%m.%d)"

rm -rf "$OUT"
mkdir -p "$OUT/Contents/MacOS" "$OUT/Contents/Resources/host"

# The agent and everything it imports at runtime.
for f in agent.py macstats.py config.py webui.py; do
  cp "$ROOT/host/$f" "$OUT/Contents/Resources/host/"
done
cp "$ROOT/packaging/launch.py" "$OUT/Contents/Resources/"

sed "s/__VERSION__/$VERSION/g" "$ROOT/packaging/Info.plist" \
  > "$OUT/Contents/Info.plist"

if [[ ! -f "$ROOT/build/AppIcon.icns" ]]; then
  /usr/bin/python3 "$HERE/make_icon.py" >/dev/null
fi
cp "$ROOT/build/AppIcon.icns" "$OUT/Contents/Resources/AppIcon.icns"

cat > "$OUT/Contents/MacOS/MacStatP" <<'STUB'
#!/bin/sh
# Resolve the bundle, then hand over to the Python entry point. The
# executable path is exported so the settings page can write a launch
# agent that points back at this bundle.
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
MACSTATP_EXE="$(cd "$(dirname "$0")" && pwd)/MacStatP"
export MACSTATP_EXE
exec /usr/bin/python3 "$DIR/launch.py" "$@"
STUB
chmod +x "$OUT/Contents/MacOS/MacStatP"

# Ad-hoc signature: unsigned bundles get harsher treatment from Gatekeeper.
codesign --force --sign - "$OUT" >/dev/null 2>&1 \
  && echo "signed (ad-hoc)" || echo "codesign unavailable, continuing"

echo "built $OUT  (version $VERSION)"
