"""MacStatP Control — the Dock icon.

The agent itself is a background process with no Dock icon, which leaves
no obvious way to look at it or turn it off. This is a small companion
app: click it, get the current state and a short list of things to do.

It runs, does one thing and quits, so the Dock icon is only lit while the
menu is up. Keep it in the Dock by dragging it there.

Everything is done with osascript, so there is nothing to install.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "host"))

import config  # noqa: E402

LABEL = "local.statusdisplay.agent"
PLIST = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % LABEL)
LOG = os.path.expanduser("~/Library/Logs/StatusDisplay/agent.log")
TARGET = "gui/%d/%s" % (os.getuid(), LABEL)


def osa(*script):
    """Run AppleScript, returning stdout. Cancelling gives ''. """
    args = ["osascript"]
    for line in script:
        args += ["-e", line]
    r = subprocess.run(args, capture_output=True, text=True)
    return r.stdout.strip()


def notify(text, title="MacStatP"):
    osa('display notification %s with title %s'
        % (json.dumps(text), json.dumps(title)))


def agent_state():
    """(loaded, running) from launchd's point of view."""
    r = subprocess.run(["launchctl", "print", TARGET],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, False
    return True, "state = running" in r.stdout


def board_status(port):
    """Ask the agent's own settings page what it can see."""
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/state" % port, timeout=1.5) as r:
            return json.loads(r.read()).get("status", {})
    except (urllib.error.URLError, OSError, ValueError):
        return None


def summary(loaded, running, status):
    if not loaded:
        return "Not installed to run at login."
    if not running:
        return "The agent is installed but not running."
    if status is None:
        return "The agent is running, but its settings page is not answering."
    if not status.get("connected"):
        return "Running. Waiting for the Presto to be plugged in."
    return "Running. Board connected on %s, %s frames sent." % (
        status.get("port", "?"), status.get("frames", 0))


def launchctl(*args):
    return subprocess.run(["launchctl"] + list(args), capture_output=True,
                          text=True).returncode == 0


def main():
    cfg = config.load()
    port = int(cfg["web_port"])
    loaded, running = agent_state()
    status = board_status(port) if running else None

    actions = []
    if running and status is not None:
        actions.append("Open the settings page")
    if running:
        actions += ["Restart the agent", "Stop the agent"]
    else:
        actions.append("Start the agent")
    actions += ["Show the log", "Cancel"]

    # Bring the dialog to the front. osascript is a child process, so a
    # bare `activate` does not always beat whatever the user was looking
    # at; raising our own bundle first is what makes it reliable.
    subprocess.run(["open", "-a", os.path.abspath(
        os.path.join(HERE, "..", ".."))], capture_output=True)
    chosen = osa(
        'activate',
        'set opts to {%s}' % ", ".join(json.dumps(a) for a in actions),
        'set picked to choose from list opts with title "MacStatP" '
        'with prompt %s default items {item 1 of opts}'
        % json.dumps(summary(loaded, running, status)),
        'if picked is false then return ""',
        'return item 1 of picked')

    if not chosen or chosen == "Cancel":
        return 0

    if chosen == "Open the settings page":
        subprocess.run(["open", "http://127.0.0.1:%d/" % port])

    elif chosen == "Stop the agent":
        launchctl("bootout", TARGET)
        notify("Agent stopped. The display will show its standby card.")

    elif chosen == "Start the agent":
        if not os.path.exists(PLIST):
            notify("No login item found — run tools/install_app.sh first.")
            return 1
        launchctl("bootstrap", "gui/%d" % os.getuid(), PLIST)
        notify("Agent started.")

    elif chosen == "Restart the agent":
        launchctl("bootout", TARGET)
        # launchd needs a moment to let go before it will take it back.
        import time
        time.sleep(1.5)
        if os.path.exists(PLIST):
            launchctl("bootstrap", "gui/%d" % os.getuid(), PLIST)
        notify("Agent restarted.")

    elif chosen == "Show the log":
        subprocess.run(["open", "-a", "Console", LOG] if os.path.exists(LOG)
                       else ["open", os.path.dirname(LOG)])

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:          # a broken menu must not be silent
        notify("MacStatP Control failed: %s" % e)
        raise
