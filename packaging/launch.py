"""Entry point inside the MacStatP.app bundle.

Double-clicking a background agent should not start a second copy of it,
so if one is already serving the configuration page this just opens that
page and exits.
"""

import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "host"))

import config  # noqa: E402


def already_running(port):
    """True when something is serving on the configuration port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    cfg = config.load()
    port = int(cfg["web_port"])
    url = "http://127.0.0.1:%d/" % port

    # Let the settings page install a login item that points back here.
    exe = os.environ.get("MACSTATP_EXE")
    if not exe:
        guess = os.path.abspath(os.path.join(HERE, "..", "MacOS", "MacStatP"))
        if os.path.exists(guess):
            os.environ["MACSTATP_EXE"] = guess

    if already_running(port):
        # A second launch is a request to see the settings, not to run
        # another agent against the same serial port.
        if "--no-browser" not in sys.argv:
            import webbrowser
            webbrowser.open(url)
        return 0

    import agent
    return agent.main() or 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
