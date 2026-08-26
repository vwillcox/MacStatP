"""Render each page type to build/page_<name>.png."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "device"))

import preview          # installs the micropython shim
import pages
import theme


def sample_history(data, n=60):
    h = pages.History()
    for i in range(n):
        frame = dict(data)
        frame["cpu"] = dict(data["cpu"])
        frame["cpu"]["pct"] = 45 + 35 * math.sin(i * 0.28)
        frame["cpu"]["cores"] = [
            max(0.0, min(100.0, 50 + 48 * math.sin(i * 0.3 + c * 0.9)))
            for c in range(data["cpu"]["n"])]
        frame["gpu"] = dict(data["gpu"])
        frame["gpu"]["pct"] = 55 + 40 * math.sin(i * 0.19 + 1)
        frame["net"] = dict(data["net"])
        frame["net"]["links"] = [
            {"n": "LAN", "d": "EN11",
             "rx": abs(math.sin(i * 0.22)) * 9e6,
             "tx": abs(math.cos(i * 0.17)) * 2e6, "up": 1}]
        h.push(frame)
    return h


def main():
    data = preview.sample_data()
    data["cpu"]["n"] = 12
    data["cpu"]["cores"] = [31.0, 88.2, 12.5, 74.1, 20.0, 95.5,
                            60.2, 5.0, 44.0, 18.0, 66.0, 9.0]
    hist = sample_history(data)
    host = "workshop-pc"

    out = os.path.join(HERE, "..", "build")
    os.makedirs(out, exist_ok=True)

    renders = {"glance": lambda d, p: pages.glance(d, p, data, hist,
                                                   host=host)}
    for name in ("cores_bars", "cores_heat", "net_graph"):
        fn = getattr(pages, name, None)
        if fn:
            renders[name] = (lambda f: lambda d, p: f(d, p, data, hist,
                                                      host=host))(fn)

    for name, fn in renders.items():
        d = preview.ShimDisplay()
        p = theme.Pens(d)
        p.set(theme.BG)
        d.clear()
        fn(d, p)
        pages.dots(d, p, len(renders), list(renders).index(name))
        path = os.path.join(out, "page_%s.png" % name)
        d.save(path)
        print("wrote", os.path.basename(path))


if __name__ == "__main__":
    main()
