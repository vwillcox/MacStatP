"""Configuration page for the status display.

Runs inside the agent process on the loopback interface only. There is no
authentication, so it must never be bound to anything but 127.0.0.1 —
anyone who can reach it can read what the machine is doing.
"""

import glob
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config

LABEL = "local.statusdisplay.agent"
PLIST = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % LABEL)


class Status:
    """Live figures the agent updates and the page displays."""

    def __init__(self):
        self.lock = threading.Lock()
        self.port = None
        self.connected = False
        self.frames = 0
        self.started = 0.0
        self.last_error = ""
        self.view = None
        self.sample_ms = 0.0

    def snapshot(self):
        with self.lock:
            return {
                "port": self.port,
                "connected": self.connected,
                "frames": self.frames,
                "started": self.started,
                "last_error": self.last_error,
                "view": self.view,
                "sample_ms": round(self.sample_ms, 1),
            }

    def set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)


def serial_ports():
    found = []
    for pattern in ("/dev/cu.usbmodem*", "/dev/cu.usbserial*"):
        found.extend(sorted(glob.glob(pattern)))
    return found


def login_item_enabled():
    return os.path.exists(PLIST)


def choices():
    """Everything the page offers as a dropdown, discovered live."""
    import macstats
    ports = macstats.hardware_ports()
    wifi, wired = [], []
    for dev, name in sorted(ports.items()):
        (wifi if ("Wi-Fi" in name or "AirPort" in name) else wired).append(
            {"dev": dev, "name": name})
    try:
        vols = [{"mount": v["mount"], "label": v["n"]}
                for v in macstats.volume_mounts()]
    except Exception:
        vols = [{"mount": "/", "label": "SYSTEM"}]
    return {"serial": serial_ports(), "wifi": wifi, "wired": wired,
            "volumes": vols}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MacStatP</title>
<style>
:root{color-scheme:dark;--bg:#06080c;--card:#131720;--line:#2c3544;
--txt:#e8eef8;--mut:#707e96;--cyan:#00c2ff;--grn:#36de8a;--red:#ff485c;
--amb:#ffb228}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;padding:28px 18px 60px}
.wrap{max-width:720px;margin:0 auto}
h1{font-size:20px;letter-spacing:.14em;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:18px;margin-bottom:16px}
.card h2{font-size:12px;letter-spacing:.18em;color:var(--mut);
margin:0 0 14px;font-weight:600}
.row{display:flex;align-items:center;gap:12px;padding:9px 0;
border-bottom:1px solid rgba(255,255,255,.05);flex-wrap:wrap}
.row:last-child{border-bottom:0}
.row label{flex:1 1 220px;min-width:180px}
.hint{display:block;color:var(--mut);font-size:12px}
input[type=text],input[type=number],select{background:#0b0f16;
color:var(--txt);border:1px solid var(--line);border-radius:6px;
padding:7px 9px;font:inherit;font-size:14px;min-width:190px}
input[type=range]{min-width:190px;accent-color:var(--cyan)}
input:focus,select:focus{outline:2px solid var(--cyan);outline-offset:1px}
.stat{display:flex;justify-content:space-between;gap:12px;padding:6px 0;
font-size:14px}
.stat span:first-child{color:var(--mut)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;
margin-right:7px;vertical-align:middle}
.on{background:var(--grn)}.off{background:var(--red)}
button{background:var(--cyan);color:#04121a;border:0;border-radius:7px;
padding:10px 20px;font:inherit;font-weight:700;cursor:pointer}
button.ghost{background:transparent;color:var(--txt);
border:1px solid var(--line);font-weight:400}
button:disabled{opacity:.5;cursor:default}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#msg{color:var(--grn);font-size:13px;min-height:18px;margin-left:2px}
#msg.err{color:var(--red)}
.err{color:var(--red)}
code{color:var(--amb)}
</style></head><body><div class="wrap">
<h1>MACSTATP</h1>
<div class="sub">Status display for the Pimoroni Presto</div>

<div class="card"><h2>STATUS</h2><div id="status"></div></div>

<form id="f">
<div class="card"><h2>CONNECTION</h2>
<div class="row"><label>Serial port<span class="hint">Blank auto-detects
the board</span></label><select id="port" name="port"></select></div>
<div class="row"><label>Update rate<span class="hint">Frames per second.
The board renders about 7</span></label>
<input type="number" id="hz" name="hz" min="0.2" max="15" step="0.1"></div>
</div>

<div class="card"><h2>DISPLAY</h2>
<div class="row"><label>Brightness<span class="hint">Backlight level</span>
</label><input type="range" id="brightness" name="brightness" min="0.1"
max="1" step="0.05"><span id="bval" class="hint"></span></div>
<div class="row"><label>Network units<span class="hint">Show throughput in
bits instead of bytes</span></label>
<input type="checkbox" id="net_bits" name="net_bits"></div>
<div class="row"><label>Detail refresh<span class="hint">Seconds between
process listings while a panel is open</span></label>
<input type="number" id="detail_period" name="detail_period" min="0.25"
max="10" step="0.25"></div>
</div>

<div class="card"><h2>WHAT TO MEASURE</h2>
<div class="row"><label>Disk volume<span class="hint">Which volume the DISK
panel shows</span></label><select id="disk_path" name="disk_path"></select>
</div>
<div class="row"><label>Choose interfaces automatically</label>
<input type="checkbox" id="net_auto" name="net_auto"></div>
<div class="row"><label>Wi-Fi interface</label>
<select id="net_wifi" name="net_wifi"></select></div>
<div class="row"><label>Wired interface</label>
<select id="net_wired" name="net_wired"></select></div>
</div>

<div class="card"><h2>APPLICATION</h2>
<div class="row"><label>Start at login<span class="hint">Runs in the
background from /Applications</span></label>
<input type="checkbox" id="login" name="login"></div>
<div class="row"><label>Configuration page port<span class="hint">Takes
effect next start</span></label>
<input type="number" id="web_port" name="web_port" min="1024" max="65535">
</div>
</div>

<div class="bar"><button type="submit">Save</button>
<button type="button" class="ghost" id="reset">Reset to defaults</button>
<span id="msg"></span></div>
</form>
</div>
<script>
const $=i=>document.getElementById(i);
let choices={};
function opts(sel,list,cur,blank){
  sel.innerHTML='';
  if(blank!==undefined){const o=document.createElement('option');
    o.value='';o.textContent=blank;sel.appendChild(o);}
  for(const it of list){const o=document.createElement('option');
    o.value=it.v;o.textContent=it.t;sel.appendChild(o);}
  sel.value=cur||'';
}
function ago(t){if(!t)return '-';const s=Math.max(0,Date.now()/1000-t);
  if(s<90)return Math.round(s)+'s';if(s<5400)return Math.round(s/60)+'m';
  return Math.floor(s/3600)+'h'+String(Math.floor(s%3600/60)).padStart(2,'0')+'m';}
async function refresh(){
  let d;
  try{d=await (await fetch('/api/state')).json();}
  catch(e){$('status').innerHTML='<div class="stat err">agent not responding</div>';return;}
  choices=d.choices;
  const s=d.status;
  $('status').innerHTML=
    '<div class="stat"><span>Board</span><span><i class="dot '+
      (s.connected?'on':'off')+'"></i>'+
      (s.connected?'connected':'waiting')+'</span></div>'+
    '<div class="stat"><span>Port</span><span>'+(s.port||'-')+'</span></div>'+
    '<div class="stat"><span>Frames sent</span><span>'+s.frames+'</span></div>'+
    '<div class="stat"><span>Running for</span><span>'+ago(s.started)+'</span></div>'+
    '<div class="stat"><span>Sample time</span><span>'+s.sample_ms+' ms</span></div>'+
    '<div class="stat"><span>Panel open</span><span>'+(s.view||'dashboard')+'</span></div>'+
    (s.last_error?'<div class="stat"><span>Last error</span><span class="err">'+
      s.last_error+'</span></div>':'');
  if(document.activeElement&&document.activeElement.form)return;
  fill(d.config,d.login);
}
function fill(c,login){
  opts($('port'),choices.serial.map(p=>({v:p,t:p})),c.port,'Auto-detect');
  opts($('disk_path'),choices.volumes.map(v=>({v:v.mount,t:v.label+'  ('+v.mount+')'})),c.disk_path);
  opts($('net_wifi'),choices.wifi.map(w=>({v:w.dev,t:w.dev+'  '+w.name})),c.net_wifi,'None');
  opts($('net_wired'),choices.wired.map(w=>({v:w.dev,t:w.dev+'  '+w.name})),c.net_wired,'None');
  $('hz').value=c.hz;$('brightness').value=c.brightness;
  $('bval').textContent=Math.round(c.brightness*100)+'%';
  $('net_bits').checked=c.net_bits;$('detail_period').value=c.detail_period;
  $('net_auto').checked=c.net_auto;$('web_port').value=c.web_port;
  $('login').checked=login;toggleNet();
}
function toggleNet(){const a=$('net_auto').checked;
  $('net_wifi').disabled=a;$('net_wired').disabled=a;}
$('net_auto').addEventListener('change',toggleNet);
$('brightness').addEventListener('input',e=>{
  $('bval').textContent=Math.round(e.target.value*100)+'%';});
$('f').addEventListener('submit',async e=>{
  e.preventDefault();
  const body={hz:+$('hz').value,port:$('port').value,
    web_port:+$('web_port').value,disk_path:$('disk_path').value,
    net_auto:$('net_auto').checked,net_wifi:$('net_wifi').value,
    net_wired:$('net_wired').value,brightness:+$('brightness').value,
    net_bits:$('net_bits').checked,detail_period:+$('detail_period').value,
    login:$('login').checked};
  const m=$('msg');
  try{
    const r=await fetch('/api/config',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||'save failed');
    m.className='';m.textContent='Saved'+(d.login_note?' - '+d.login_note:'');
  }catch(err){m.className='err';m.textContent=String(err.message||err);}
  setTimeout(()=>{m.textContent='';},4000);
});
$('reset').addEventListener('click',async()=>{
  if(!confirm('Reset all settings to defaults?'))return;
  await fetch('/api/config',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({reset:true})});
  refresh();
});
refresh();setInterval(refresh,2000);
</script></body></html>
"""


def set_login_item(enable, app_path=None):
    """Install or remove the launch agent. Returns a short note."""
    uid = os.getuid()
    target = "gui/%d/%s" % (uid, LABEL)
    if not enable:
        subprocess.run(["launchctl", "bootout", target],
                       capture_output=True)
        try:
            os.remove(PLIST)
        except OSError:
            pass
        return "will not start at login"

    exe = app_path or os.environ.get("MACSTATP_EXE")
    if not exe or not os.path.exists(exe):
        return "install the app first to enable this"
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    with open(PLIST, "w") as f:
        f.write(_PLIST_TEMPLATE % {"label": LABEL, "exe": exe,
                                   "logs": os.path.expanduser(
                                       "~/Library/Logs/StatusDisplay")})
    subprocess.run(["launchctl", "bootout", target], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", "gui/%d" % uid, PLIST],
                   capture_output=True)
    return "will start at login"


_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>%(label)s</string>
  <key>ProgramArguments</key><array><string>%(exe)s</string>
    <string>--no-browser</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>%(logs)s/agent.log</string>
  <key>StandardErrorPath</key><string>%(logs)s/agent.err</string>
</dict></plist>
"""


class _Handler(BaseHTTPRequestHandler):
    status = None
    server_version = "MacStatP"

    def log_message(self, *a):
        pass          # the agent's own log is the interesting one

    def _send(self, code, body, ctype="application/json"):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if path == "/api/state":
            try:
                ch = choices()
            except Exception as e:
                ch = {"serial": serial_ports(), "wifi": [], "wired": [],
                      "volumes": [{"mount": "/", "label": "SYSTEM"}],
                      "error": str(e)}
            return self._send(200, json.dumps({
                "config": config.load(),
                "status": self.status.snapshot() if self.status else {},
                "choices": ch,
                "login": login_item_enabled(),
            }))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/config":
            return self._send(404, json.dumps({"error": "not found"}))
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 64000:
                raise ValueError("bad length")
            body = json.loads(self.rfile.read(n))
            if not isinstance(body, dict):
                raise ValueError("expected an object")
        except Exception as e:
            return self._send(400, json.dumps({"error": str(e)}))

        if body.get("reset"):
            config.save(config.DEFAULTS)
            return self._send(200, json.dumps({"ok": True}))

        note = ""
        if "login" in body:
            try:
                note = set_login_item(bool(body.pop("login")))
            except Exception as e:
                note = "login item failed: %s" % e
        try:
            saved = config.save({**config.load(), **body})
        except Exception as e:
            return self._send(500, json.dumps({"error": str(e)}))
        return self._send(200, json.dumps({"ok": True, "config": saved,
                                           "login_note": note}))


def serve(status, port):
    """Start the page on loopback. Returns (server, actual_port) or None."""
    handler = type("Handler", (_Handler,), {"status": status})
    try:
        # 127.0.0.1 only: this exposes what the machine is running.
        srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as e:
        print("config page unavailable on port %d: %s" % (port, e),
              flush=True)
        return None, None
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
