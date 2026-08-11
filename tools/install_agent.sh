#!/usr/bin/env bash
# Install the host agent as a per-user launchd job so the display keeps
# updating after a reboot or logout/login.
#
#   tools/install_agent.sh            install and start
#   tools/install_agent.sh --uninstall
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
LABEL="local.statusdisplay.agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$HOME/Library/Logs/StatusDisplay"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "uninstalled $LABEL"
  exit 0
fi

mkdir -p "$LOGDIR"

# On this Mac ~/Library/LaunchAgents is owned by root, so the per-user job
# cannot be written without fixing that first.
if ! mkdir -p "$(dirname "$PLIST")" 2>/dev/null || [[ ! -w "$(dirname "$PLIST")" ]]; then
  cat >&2 <<MSG
$(dirname "$PLIST") is not writable (it is owned by $(stat -f '%Su' "$(dirname "$PLIST")" 2>/dev/null || echo root)).

Give it back to your user, then re-run this script:

    sudo chown -R "$(id -u):staff" "$(dirname "$PLIST")"
    tools/install_agent.sh

Until then you can just run the agent yourself:

    python3 $ROOT/host/agent.py
MSG
  exit 1
fi

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$ROOT/host/agent.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>$LOGDIR/agent.log</string>
    <key>StandardErrorPath</key>
    <string>$LOGDIR/agent.err</string>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"

echo "installed $LABEL"
echo "  logs: $LOGDIR/agent.log"
echo "  stop: tools/install_agent.sh --uninstall"
