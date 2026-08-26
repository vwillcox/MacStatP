"""Tests for the settings page.

    python3 host/test_webui.py

The page is served by the agent itself, which makes it easy to write
something that takes the agent down while answering a request. That is not
hypothetical: saving any setting with "start at login" ticked used to run
launchctl bootout against the agent's own label, so changing the
brightness unloaded the display. These drive a real server over HTTP.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import config
import webui

PASSED, FAILED = [], []


def check(label, ok, detail=None):
    (PASSED if ok else FAILED).append(label)
    print("  %-4s %s%s" % ("ok" if ok else "FAIL", label,
                           "" if ok or detail is None else "  -> %r" % (detail,)))


def post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read())


def sandbox():
    """Point config and the plist at throwaway paths."""
    tmp = tempfile.mkdtemp(prefix="macstatp-test-")
    config.SUPPORT_DIR = tmp
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    webui.PLIST = os.path.join(tmp, "agent.plist")
    return tmp


def main():
    sandbox()
    config.save(config.DEFAULTS)
    status = webui.Status()
    srv, port = webui.serve(status, 0)          # 0 = any free port
    if srv is None:
        print("could not start the server")
        return 1
    base = "http://127.0.0.1:%d" % port

    print("serving")
    code, state = get(base + "/api/state")
    check("state is served", code == 200)
    check("carries the settings", state["config"]["hz"] == 6.0)
    check("carries the status", "connected" in state["status"])

    print("saving a setting")
    code, body = post(base + "/api/config", {"brightness": 0.5})
    check("accepted", code == 200 and body["ok"])
    check("stored", config.load()["brightness"] == 0.5)

    print("the login toggle cannot take the agent down")
    # The invariant that actually encodes the bug: the page is served by
    # the agent, so running launchctl against its own label here unloads
    # the process mid-request. Registering with launchd is the
    # installer's job, from a separate process.
    ran = []
    real_run = subprocess.run
    subprocess.run = lambda *a, **kw: (ran.append(a[0]), real_run(
        ["true"], capture_output=True))[1]
    # Ticking the box, saving repeatedly, and untickng it: none of this
    # may kill the process answering the request.
    os.environ["MACSTATP_EXE"] = sys.executable   # stand in for the bundle
    post(base + "/api/config", {"brightness": 0.6, "login": True})
    check("plist written", os.path.exists(webui.PLIST))
    code, _ = post(base + "/api/config", {"brightness": 0.7, "login": True})
    check("saving again with it already on still answers", code == 200)
    check("and left the plist alone", os.path.exists(webui.PLIST))
    code, state = get(base + "/api/state")
    check("server still alive afterwards", code == 200)
    check("the setting actually landed", state["config"]["brightness"] == 0.7)

    code, _ = post(base + "/api/config", {"login": False})
    check("unticking removes the plist", not os.path.exists(webui.PLIST))
    code, _ = get(base + "/api/state")
    check("server survives that too", code == 200)
    subprocess.run = real_run
    check("never shells out to launchctl",
          not any("launchctl" in str(c) for c in ran), ran)

    print("panels")
    # The order is the running order on the display, so it survives.
    code, body = post(base + "/api/config",
                      {"panels": ["net", "cpu", "bogus"]})
    check("order is kept and unknown names dropped",
          code == 200 and body["config"]["panels"] == ["net", "cpu"],
          body["config"]["panels"])
    code, body = post(base + "/api/config",
                      {"panels": ["disk", "disk", "cpu"]})
    check("repeats collapse to one",
          body["config"]["panels"] == ["disk", "cpu"],
          body["config"]["panels"])
    code, _ = post(base + "/api/config", {"panels": []})
    check("all of them off is allowed", config.load()["panels"] == [])
    code, _ = get(base + "/api/state")
    check("page still fine with none selected", code == 200)
    post(base + "/api/config", {"panels": list(config.PANELS)})

    print("desk pet")
    code, body = post(base + "/api/config", {"buddy": False})
    check("can be switched off", code == 200 and
          config.load()["buddy"] is False)
    code, body = post(base + "/api/config", {"buddy": True})
    check("and back on", config.load()["buddy"] is True)
    code, state = get(base + "/api/state")
    check("page reports what the board has, not a guess",
          "buddy_installed" in state["status"],
          list(state["status"]))
    check("and says nothing until the board tells it",
          state["status"]["buddy_installed"] is None,
          state["status"]["buddy_installed"])

    print("bad input")
    code, body = post(base + "/api/config", {"hz": 9999})
    check("out of range is clamped, not rejected",
          code == 200 and config.load()["hz"] == 15.0)
    req = urllib.request.Request(base + "/api/config", data=b"not json",
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)
        check("malformed body rejected", False)
    except urllib.error.HTTPError as e:
        check("malformed body rejected", e.code == 400, e.code)
    try:
        urllib.request.urlopen(base + "/nope", timeout=5)
        check("unknown path is a 404", False)
    except urllib.error.HTTPError as e:
        check("unknown path is a 404", e.code == 404, e.code)

    print("reset")
    post(base + "/api/config", {"reset": True})
    check("back to defaults", config.load()["hz"] == config.DEFAULTS["hz"])

    print("binding")
    check("loopback only", srv.server_address[0] == "127.0.0.1",
          srv.server_address)

    srv.shutdown()
    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
