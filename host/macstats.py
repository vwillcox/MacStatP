"""macOS system metrics, collected without sudo.

Every source here is readable by a normal user:
  CPU      host_processor_info() via libSystem
  GPU      IOAccelerator PerformanceStatistics via ioreg
  Memory   vm_stat + sysctl hw.memsize
  Disk     statvfs for capacity, IOBlockStorageDriver for throughput
  Network  netstat -ib byte counters

Counter-based metrics (CPU, disk, network) are rates, so the first
sample after start has nothing to diff against and reads as zero.
"""

import ctypes
import ctypes.util
import os
import re
import subprocess
import time

PAGE_SIZE = 16384  # re-read from vm_stat header at runtime
CPU_STATE_USER, CPU_STATE_SYSTEM, CPU_STATE_IDLE, CPU_STATE_NICE = 0, 1, 2, 3
PROCESSOR_CPU_LOAD_INFO = 2


_PUNCT = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
}


def ascii_only(s):
    """The display font is ASCII; fold smart punctuation, drop the rest."""
    out = []
    for ch in s or "":
        ch = _PUNCT.get(ch, ch)
        out.append(ch if 32 <= ord(ch) < 127 else "")
    return "".join(out).strip()


def _sysctl(name):
    try:
        return subprocess.run(
            ["sysctl", "-n", name], capture_output=True, text=True, timeout=2
        ).stdout.strip()
    except Exception:
        return ""


def _run(cmd, timeout=3):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        ).stdout
    except Exception:
        return ""


class _CPU:
    """Per-core tick counters straight from the Mach kernel."""

    def __init__(self):
        self.lib = ctypes.CDLL(ctypes.util.find_library("System"))
        self.lib.mach_host_self.restype = ctypes.c_uint
        self.host = self.lib.mach_host_self()
        self.prev = None

    def _ticks(self):
        count = ctypes.c_uint(0)
        ncpu = ctypes.c_uint(0)
        info = ctypes.POINTER(ctypes.c_uint32)()
        rc = self.lib.host_processor_info(
            self.host,
            PROCESSOR_CPU_LOAD_INFO,
            ctypes.byref(ncpu),
            ctypes.byref(info),
            ctypes.byref(count),
        )
        if rc != 0:
            return []
        n = ncpu.value
        out = [[info[i * 4 + j] for j in range(4)] for i in range(n)]
        # Hand the kernel's page allocation back rather than leaking it every poll.
        self.lib.vm_deallocate(
            self.lib.mach_task_self(),
            ctypes.cast(info, ctypes.c_void_p),
            count.value * ctypes.sizeof(ctypes.c_uint32),
        )
        return out

    def sample(self):
        cur = self._ticks()
        if not cur:
            return {"percent": 0.0, "cores": [], "count": 0}
        prev, self.prev = self.prev, cur
        if prev is None or len(prev) != len(cur):
            return {"percent": 0.0, "cores": [0.0] * len(cur), "count": len(cur)}

        cores = []
        for a, b in zip(prev, cur):
            busy = (
                (b[CPU_STATE_USER] - a[CPU_STATE_USER])
                + (b[CPU_STATE_SYSTEM] - a[CPU_STATE_SYSTEM])
                + (b[CPU_STATE_NICE] - a[CPU_STATE_NICE])
            )
            idle = b[CPU_STATE_IDLE] - a[CPU_STATE_IDLE]
            total = busy + idle
            cores.append(100.0 * busy / total if total > 0 else 0.0)
        return {
            "percent": sum(cores) / len(cores),
            "cores": cores,
            "count": len(cores),
        }


class _Rate:
    """Turns a monotonic counter into a per-second rate."""

    def __init__(self):
        self.prev = None
        self.prev_t = None

    def update(self, value, now=None):
        now = now if now is not None else time.monotonic()
        if self.prev is None or now <= (self.prev_t or 0):
            self.prev, self.prev_t = value, now
            return 0.0
        # Counters reset when an interface or disk goes away and comes back.
        delta = value - self.prev
        dt = now - self.prev_t
        self.prev, self.prev_t = value, now
        return max(0.0, delta / dt) if delta >= 0 else 0.0


def gpu():
    """GPU utilisation from IOAccelerator. Returns percent + VRAM bytes in use."""
    out = _run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"])
    util = 0.0
    inuse = 0
    alloc = 0
    for m in re.finditer(r'"PerformanceStatistics"\s*=\s*\{([^}]*)\}', out):
        blk = m.group(1)

        def num(key):
            g = re.search(r'"%s"\s*=\s*(\d+)' % re.escape(key), blk)
            return int(g.group(1)) if g else 0

        # Several accelerators can be present; the busiest one is the real GPU.
        u = max(num("Device Utilization %"), num("Renderer Utilization %"))
        if u >= util:
            util = float(u)
        inuse = max(inuse, num("In use system memory"))
        alloc = max(alloc, num("Alloc system memory"))
    return {"percent": util, "vram_used": inuse, "vram_alloc": alloc}


def memory():
    """Memory split the way Activity Monitor reports it."""
    out = _run(["vm_stat"])
    page = PAGE_SIZE
    m = re.search(r"page size of (\d+) bytes", out)
    if m:
        page = int(m.group(1))

    vals = {}
    for line in out.splitlines():
        mm = re.match(r'"?([^":]+)"?:\s+(\d+)\.', line)
        if mm:
            vals[mm.group(1).strip()] = int(mm.group(2))

    total = int(_sysctl("hw.memsize") or 0)
    wired = vals.get("Pages wired down", 0) * page
    active = vals.get("Pages active", 0) * page
    inactive = vals.get("Pages inactive", 0) * page
    compressed = vals.get("Pages occupied by compressor", 0) * page
    free = vals.get("Pages free", 0) * page
    speculative = vals.get("Pages speculative", 0) * page
    filebacked = vals.get("File-backed pages", 0) * page

    # "App memory" ~= anonymous pages that aren't file-backed.
    app = max(0, active + inactive - filebacked)
    used = app + wired + compressed
    used = min(used, total) if total else used
    return {
        "total": total,
        "used": used,
        "wired": wired,
        "compressed": compressed,
        "cached": filebacked + speculative,
        "free": free,
        "percent": (100.0 * used / total) if total else 0.0,
        "swap": _swap(),
    }


def _swap():
    out = _sysctl("vm.swapusage")
    m = re.search(r"used\s*=\s*([\d.]+)([MGK])", out)
    if not m:
        return 0
    n = float(m.group(1))
    return int(n * {"K": 1024, "M": 1024**2, "G": 1024**3}[m.group(2)])


def disk_capacity(path="/"):
    """Real used/total for the boot volume, accounting for APFS purgeable space."""
    try:
        st = os.statvfs(path)
    except Exception:
        return {"total": 0, "used": 0, "free": 0, "percent": 0.0}
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = total - (st.f_bfree * st.f_frsize)
    return {
        "total": total,
        "used": used,
        "free": free,
        "percent": (100.0 * used / total) if total else 0.0,
    }


def _disk_counters():
    """Cumulative bytes read/written across physical block devices."""
    out = _run(["ioreg", "-c", "IOBlockStorageDriver", "-r", "-d", "1", "-w", "0"])
    read = write = 0
    for m in re.finditer(r'"Statistics"\s*=\s*\{([^}]*)\}', out):
        blk = m.group(1)
        r = re.search(r'"Bytes \(Read\)"\s*=\s*(\d+)', blk)
        w = re.search(r'"Bytes \(Write\)"\s*=\s*(\d+)', blk)
        read += int(r.group(1)) if r else 0
        write += int(w.group(1)) if w else 0
    return read, write


def _net_counters():
    """Per-interface cumulative (rx, tx) byte counters, loopback excluded."""
    out = _run(["netstat", "-ib"])
    per = {}
    for line in out.splitlines()[1:]:
        f = line.split()
        if len(f) < 11 or "<Link#" not in line:
            continue
        name = f[0].rstrip("*")
        if name in per or name.startswith("lo"):
            continue
        try:
            per[name] = (int(f[6]), int(f[9]))
        except (ValueError, IndexError):
            continue
    return per


def _totals(per):
    return sum(v[0] for v in per.values()), sum(v[1] for v in per.values())


def _primary_interface():
    out = _run(["route", "-n", "get", "default"])
    m = re.search(r"interface:\s*(\S+)", out)
    return m.group(1) if m else ""


_PORTS = None


def hardware_ports():
    """device -> hardware port name, e.g. {'en1': 'Wi-Fi'}. Cached."""
    global _PORTS
    if _PORTS is None:
        out = _run(["networksetup", "-listallhardwareports"], timeout=8)
        ports = {}
        name = None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Hardware Port:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("Device:") and name is not None:
                ports[line.split(":", 1)[1].strip()] = name
                name = None
        _PORTS = ports
    return _PORTS


def _is_up(dev):
    out = _run(["ifconfig", dev])
    return "status: active" in out and re.search(r"\binet\s", out) is not None


class _NetPicker:
    """Chooses which Wi-Fi and wired interface to publish.

    Re-evaluated occasionally rather than every sample, since cables and
    Wi-Fi state change far more slowly than the 1 Hz frame rate.
    """

    RECHECK = 15.0

    def __init__(self):
        self._picked = []
        self._at = 0.0

    def pick(self, per):
        now = time.monotonic()
        if self._picked and (now - self._at) < self.RECHECK:
            return self._picked
        self._at = now

        ports = hardware_ports()
        primary = _primary_interface()

        def is_wifi(dev):
            p = ports.get(dev, "")
            return "Wi-Fi" in p or "AirPort" in p

        candidates = [d for d in per if d in ports and not d.startswith("bridge")]
        wifi = next((d for d in candidates if is_wifi(d)), None)

        wired_all = [d for d in candidates if not is_wifi(d)]
        # Prefer whichever wired link actually carries the default route.
        wired = primary if (primary in wired_all) else None
        if wired is None:
            wired = next((d for d in wired_all if _is_up(d)), None)
        if wired is None and wired_all:
            wired = max(wired_all, key=lambda d: per[d][0] + per[d][1])

        picked = []
        if wifi:
            picked.append(("WI-FI", wifi))
        if wired:
            picked.append(("LAN", wired))
        self._picked = picked
        return picked


def proc_name(path):
    """Friendly, display-safe name for a process command path."""
    name = path.strip().rsplit("/", 1)[-1] or path.strip()
    return ascii_only(name).upper()[:24]


def top_cpu(n=9):
    """Busiest processes by CPU share."""
    out = _run(["ps", "-Ao", "pid,pcpu,comm", "-r"])
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pct = float(parts[1])
        except ValueError:
            continue
        if pct <= 0.0:
            break            # ps -r is already sorted; nothing below matters
        rows.append({"n": proc_name(parts[2]), "p": int(parts[0]),
                     "v": round(pct, 1)})
        if len(rows) >= n:
            break
    return rows


def top_mem(n=9):
    """Largest processes by resident set size."""
    out = _run(["ps", "-Ao", "pid,rss,comm", "-m"])
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            rss = int(parts[1]) * 1024
        except ValueError:
            continue
        rows.append({"n": proc_name(parts[2]), "p": int(parts[0]), "v": rss})
        if len(rows) >= n:
            break
    return rows


class _NetProcs:
    """Per-process network rates, from differences in nettop's counters.

    nettop reports cumulative bytes per process and runs without sudo, so
    two samples give a usable rate without elevated privileges.
    """

    def __init__(self):
        self.prev = {}
        self.prev_t = None

    def sample(self, n=9):
        out = _run(["nettop", "-P", "-L", "1", "-x", "-J",
                    "bytes_in,bytes_out"], timeout=6)
        now = time.monotonic()
        cur = {}
        for line in out.splitlines():
            f = line.strip().split(",")
            if len(f) < 3 or "." not in f[0]:
                continue
            key = f[0]
            try:
                cur[key] = (int(f[1]), int(f[2]))
            except ValueError:
                continue

        rows = []
        dt = (now - self.prev_t) if self.prev_t else 0
        if dt > 0:
            for key, (bi, bo) in cur.items():
                old = self.prev.get(key)
                if not old:
                    continue
                din = max(0, bi - old[0]) / dt
                dout = max(0, bo - old[1]) / dt
                if din + dout < 1:
                    continue
                name, _, pid = key.rpartition(".")
                rows.append({"n": ascii_only(name).upper()[:24],
                             "p": int(pid) if pid.isdigit() else 0,
                             "i": round(din), "o": round(dout)})
            rows.sort(key=lambda r: r["i"] + r["o"], reverse=True)

        self.prev, self.prev_t = cur, now
        return rows[:n]


MIN_VOLUME = 4 * 1024 ** 3   # hide the small firmware/preboot volumes


def _volume_label(mount):
    if mount == "/":
        return "SYSTEM"
    if mount == "/System/Volumes/Data":
        return "DATA"
    return mount.rsplit("/", 1)[-1] or mount


def volumes(n=6):
    """Real mounted volumes, biggest consumer first.

    macOS splits the boot disk into several APFS volumes that all report
    the same container size, so the small firmware ones are dropped and
    the rest are labelled by what they actually are.
    """
    out = _run(["df", "-k"])
    rows = []
    for line in out.splitlines()[1:]:
        f = line.split()
        if len(f) < 9:
            continue
        # Skip devfs, autofs maps and anything without a real device.
        if not (f[0].startswith("/dev/") or f[0].startswith("//")):
            continue
        mount = " ".join(f[8:])
        try:
            total = int(f[1]) * 1024
            used = int(f[2]) * 1024
        except ValueError:
            continue
        if total < MIN_VOLUME:
            continue
        rows.append({"n": ascii_only(_volume_label(mount)).upper()[:24],
                     "u": used, "t": total,
                     "v": round(100.0 * used / total, 1)})
    rows.sort(key=lambda r: r["u"], reverse=True)
    return rows[:n]


def gpu_detail():
    """The individual GPU engine counters behind the summary figure."""
    out = _run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"])
    best = {}
    for m in re.finditer(r'"PerformanceStatistics"\s*=\s*\{([^}]*)\}', out):
        blk = m.group(1)

        def num(key):
            g = re.search(r'"%s"\s*=\s*(\d+)' % re.escape(key), blk)
            return int(g.group(1)) if g else 0

        cand = {
            "device": num("Device Utilization %"),
            "render": num("Renderer Utilization %"),
            "tiler": num("Tiler Utilization %"),
            "inuse": num("In use system memory"),
            "alloc": num("Alloc system memory"),
            "pb": num("Allocated PB Size"),
        }
        if cand["alloc"] >= best.get("alloc", -1):
            best = cand
    return best


class Collector:
    """Holds the counter state needed to turn totals into rates."""

    def __init__(self):
        self.cpu = _CPU()
        self.disk_r = _Rate()
        self.disk_w = _Rate()
        self.net_rx = _Rate()
        self.net_tx = _Rate()
        self.picker = _NetPicker()
        self.netprocs = _NetProcs()
        self._if_rates = {}   # (device, direction) -> _Rate
        self._up = {}         # device -> last known link state
        self._up_at = 0.0
        self.host = ascii_only(_run(["scutil", "--get", "ComputerName"]).strip()
                               or os.uname().nodename.split(".")[0])
        self.model = ascii_only(_sysctl("machdep.cpu.brand_string") or "Mac")
        self.boot = self._boot_time()

        # Prime every counter so the first published frame carries real
        # rates instead of a screen full of zeros.
        self.cpu.sample()
        dr, dw = _disk_counters()
        self.disk_r.update(dr)
        self.disk_w.update(dw)
        per = _net_counters()
        nr, nt = _totals(per)
        self.net_rx.update(nr)
        self.net_tx.update(nt)
        for _label, dev in self.picker.pick(per):
            if dev in per:
                self._rate(dev, "rx").update(per[dev][0])
                self._rate(dev, "tx").update(per[dev][1])

    def _rate(self, dev, direction):
        key = (dev, direction)
        r = self._if_rates.get(key)
        if r is None:
            r = _Rate()
            self._if_rates[key] = r
        return r

    def _link_up(self, dev, now):
        """Cached ifconfig status; polling it every frame is wasteful."""
        if now - self._up_at > 10.0:
            self._up = {}
            self._up_at = now
        if dev not in self._up:
            self._up[dev] = _is_up(dev)
        return self._up[dev]

    @staticmethod
    def _boot_time():
        m = re.search(r"sec\s*=\s*(\d+)", _sysctl("kern.boottime"))
        return int(m.group(1)) if m else 0

    def sample(self):
        now = time.monotonic()
        c = self.cpu.sample()
        dr, dw = _disk_counters()
        per = _net_counters()
        nr, nt = _totals(per)
        cap = disk_capacity("/")
        mem = memory()
        g = gpu()

        return {
            "t": time.time(),
            "host": self.host,
            "model": self.model,
            "uptime": int(time.time() - self.boot) if self.boot else 0,
            "load": [round(v, 2) for v in os.getloadavg()],
            "cpu": {
                "pct": round(c["percent"], 1),
                "cores": [round(x, 1) for x in c["cores"]],
                "n": c["count"],
            },
            "gpu": {
                "pct": round(g["percent"], 1),
                "vram": g["vram_used"],
            },
            "mem": {
                "pct": round(mem["percent"], 1),
                "used": mem["used"],
                "total": mem["total"],
                "wired": mem["wired"],
                "comp": mem["compressed"],
                "swap": mem["swap"],
            },
            "disk": {
                "pct": round(cap["percent"], 1),
                "used": cap["used"],
                "total": cap["total"],
                "r": round(self.disk_r.update(dr, now)),
                "w": round(self.disk_w.update(dw, now)),
            },
            "net": {
                "rx": round(self.net_rx.update(nr, now)),
                "tx": round(self.net_tx.update(nt, now)),
                "links": self._links(per, now),
            },
        }

    def detail(self, view, rows=9):
        """Drill-down payload for one panel, gathered only while it is open.

        Kept out of the regular frame because process listings are an order
        of magnitude larger than the summary.
        """
        if view == "cpu":
            return {"v": "cpu", "rows": top_cpu(rows)}
        if view == "mem":
            return {"v": "mem", "rows": top_mem(rows)}
        if view == "net":
            return {"v": "net", "rows": self.netprocs.sample(rows)}
        if view == "disk":
            return {"v": "disk", "rows": volumes(rows)}
        if view == "gpu":
            return {"v": "gpu", "gpu": gpu_detail()}
        return None

    def _links(self, per, now):
        out = []
        for label, dev in self.picker.pick(per):
            rx = tx = 0.0
            if dev in per:
                rx = self._rate(dev, "rx").update(per[dev][0], now)
                tx = self._rate(dev, "tx").update(per[dev][1], now)
            out.append({
                "n": label,
                "d": dev.upper(),
                "rx": round(rx),
                "tx": round(tx),
                "up": 1 if self._link_up(dev, now) else 0,
            })
        return out


if __name__ == "__main__":
    import json

    col = Collector()
    time.sleep(1)
    for _ in range(3):
        print(json.dumps(col.sample()))
        time.sleep(1)
