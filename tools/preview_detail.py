"""Render every drill-down screen to build/detail_<view>.png."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "device"))
sys.path.insert(0, os.path.join(HERE, "..", "host"))

import preview  # installs the micropython shim and ShimDisplay
import dashboard
import theme
import macstats
import time

col = macstats.Collector()
time.sleep(1.2)
data = col.sample()
col.detail("net")
time.sleep(1.0)

os.makedirs(os.path.join(HERE, "..", "build"), exist_ok=True)
for view in ("cpu", "mem", "net", "disk", "gpu"):
    d = preview.ShimDisplay()
    db = dashboard.Dashboard(d, theme.Pens(d))
    det = col.detail(view)
    db.detail(view, data, det)
    out = os.path.join(HERE, "..", "build", "detail_%s.png" % view)
    d.save(out)
    print("wrote", os.path.normpath(out))
