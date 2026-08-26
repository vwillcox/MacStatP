#!/usr/bin/env bash
# Build MacStatP.app and install it so it runs at login.
#
#   tools/install_app.sh              build, install, start
#   tools/install_app.sh --uninstall  stop and remove
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
LABEL="local.statusdisplay.agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$HOME/Library/Logs/StatusDisplay"
TARGET="gui/$(id -u)/$LABEL"

stop_agent() {
  launchctl bootout "$TARGET" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
  stop_agent
  rm -f "$PLIST"
  rm -rf "/Applications/MacStatP.app" "$HOME/Applications/MacStatP.app" \
         "/Applications/MacStatP Control.app" \
         "$HOME/Applications/MacStatP Control.app"
  echo "removed MacStatP (settings kept in ~/Library/Application Support/MacStatP)"
  exit 0
fi

# The agent cannot talk to the board without pyserial.
if ! /usr/bin/python3 -c "import serial" 2>/dev/null; then
  echo "installing pyserial..."
  /usr/bin/pip3 install --user --quiet pyserial
fi

"$HERE/build_app.sh"

# Prefer /Applications, fall back to the user's own when it is not writable.
DEST="/Applications"
[[ -w "$DEST" ]] || DEST="$HOME/Applications"
mkdir -p "$DEST" "$LOGDIR"

# Stop the running copy before replacing the bundle it is executing from.
stop_agent
sleep 1
rm -rf "$DEST/MacStatP.app" "$DEST/MacStatP Control.app"
cp -R "$ROOT/build/MacStatP.app" "$DEST/"
cp -R "$ROOT/build/MacStatP Control.app" "$DEST/"
APP="$DEST/MacStatP.app/Contents/MacOS/MacStatP"
echo "installed to $DEST/MacStatP.app"
echo "installed to $DEST/MacStatP Control.app"

cat > "$PLIST" <<PLEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$APP</string><string>--no-browser</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOGDIR/agent.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/agent.err</string>
</dict></plist>
PLEOF

launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "$TARGET" 2>/dev/null || true

PORT="$(/usr/bin/python3 -c "
import json,os
p=os.path.expanduser('~/Library/Application Support/MacStatP/config.json')
try: print(json.load(open(p))['web_port'])
except Exception: print(8765)
")"

echo
echo "MacStatP is installed and will start at login."
echo "  settings:  http://127.0.0.1:$PORT/"
echo "  control:   $DEST/MacStatP Control.app — drag it to the Dock"
echo "  logs:      $LOGDIR/agent.log"
echo "  uninstall: tools/install_app.sh --uninstall"
