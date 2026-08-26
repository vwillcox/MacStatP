"""Render the dashboard for several panel combinations.

Panels can be switched off, so the layout has to hold up for every
combination rather than just the full set.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "device"))

import preview
import dashboard
import theme

COMBOS = {
    "all": ("cpu", "gpu", "mem", "disk", "net"),
    "cpu-only": ("cpu",),
    "cpu-net": ("cpu", "net"),
    "no-gpu": ("cpu", "mem", "disk", "net"),
    "mem-disk": ("mem", "disk"),
    "net-only": ("net",),
}


def main():
    out_dir = os.path.join(HERE, "..", "build")
    os.makedirs(out_dir, exist_ok=True)
    data = preview.sample_data()
    for name, panels in COMBOS.items():
        d = preview.ShimDisplay()
        db = dashboard.Dashboard(d, theme.Pens(d))
        db.set_panels(panels)
        db.links["EN1"] = [3e5] * 64
        db.links["EN11"] = [8e6] * 64
        db.gpu_hist = [40.0] * 64
        db.render(data, full=True)
        path = os.path.join(out_dir, "panels_%s.png" % name)
        d.save(path)
        print("wrote", os.path.basename(path))


if __name__ == "__main__":
    main()
