"""Tests that panels stay inside their own cards.

    python3 host/test_layout.py

Panels are handed a box and lay themselves out inside it. When a box got
short — five panels with the network in the middle makes four rows — they
carried on drawing past the bottom edge and over the panel below. It
looked like the display was corrupt.

Two kinds of check: the geometry never puts anything past the edge, and a
real render leaves the gaps between cards untouched.
"""

import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "..", "device"))

import preview          # installs the micropython shim
import dashboard as D
import theme

PASSED, FAILED = [], []


def check(label, ok, detail=None):
    (PASSED if ok else FAILED).append(label)
    print("  %-4s %s%s" % ("ok" if ok else "FAIL", label,
                           "" if ok or detail is None else "  -> %r" % (detail,)))


def geometry_fits(key, x, y, w, h):
    """Every element the geometry describes must sit inside the card."""
    g = D.Dashboard._GEOM[key](x, y, w, h)
    bottom, right = y + h, x + w
    bad = []

    def below(name, edge):
        if edge > bottom:
            bad.append("%s ends at %d, card ends at %d" % (name, edge, bottom))

    if key in ("cpu", "gpu", "mem", "disk"):
        # A dial and nothing else, so it just has to fit inside the card
        # below the title. A radius of zero means the card is too short
        # to show one at all, which is a valid answer.
        if g["r"]:
            if g["cy"] - g["r"] < y + D.TITLE_H - 2:
                bad.append("dial reaches above the title")
            below("dial", g["cy"] + g["r"])
            if g["cx"] - g["r"] < x or g["cx"] + g["r"] > right:
                bad.append("dial runs past the sides")
    elif key == "net":
        below("second row", g["top"] + 2 * g["row_h"])
        below("sparkline", g["top"] + g["row_h"] + g["sh"])
    return bad


def test_every_box_size():
    print("geometry stays inside the card")
    problems = []
    for key in D.PANEL_ORDER:
        # Every width and height the packer can actually produce.
        for w in (231, 468):
            for h in range(70, 470, 7):
                problems += ["%s %dx%d: %s" % (key, w, h, b)
                             for b in geometry_fits(key, 6, 6, w, h)]
    check("no element runs past its card, at any size",
          not problems, problems[:3])


def test_every_arrangement():
    print("every arrangement the settings can produce")
    problems = []
    count = 0
    for n in range(1, len(D.PANEL_ORDER) + 1):
        for combo in itertools.permutations(D.PANEL_ORDER, n):
            count += 1
            rects = D.pack(combo)
            for key, (x, y, w, h) in rects.items():
                problems += ["%s in %s: %s" % (key, combo, b)
                             for b in geometry_fits(key, x, y, w, h)]
                # Anything the settings can actually produce must be
                # readable, not merely inside its box.
                if key != "net":
                    g = D.Dashboard._GEOM[key](x, y, w, h)
                    if g["r"] < 20:
                        problems.append("%s in %s: dial only r=%d"
                                        % (key, combo, g["r"]))
    check("%d arrangements, none overflowing" % count, not problems,
          problems[:3])


def gaps_are_clean(order):
    """Render, then look at the space between cards.

    Anything other than the background there means a panel drew outside
    itself — which is exactly what the corruption was.
    """
    d = preview.ShimDisplay()
    db = dashboard_for(d)
    db.set_panels(order)
    db.render(preview.sample_data(), full=True)

    rects = D.pack(order)
    bg = theme.BG
    stray = 0
    for px in range(D.SCREEN):
        for py in range(D.SCREEN):
            inside = any(x <= px < x + w and y <= py < y + h
                         for (x, y, w, h) in rects.values())
            if inside:
                continue
            o = (py * D.SCREEN + px) * 3
            if tuple(d.cv.px[o:o + 3]) != bg:
                stray += 1
    return stray


def dashboard_for(d):
    db = D.Dashboard(d, theme.Pens(d))
    db.links["EN1"] = [3e5] * 64
    db.links["EN11"] = [8e6] * 64
    db.gpu_hist = [40.0] * 64
    return db


def test_nothing_paints_between_cards():
    print("nothing paints between the cards")
    # The reported one: everything on, disk moved to the bottom.
    for order in (("cpu", "gpu", "mem", "net", "disk"),
                  ("cpu", "gpu", "mem", "disk", "net"),
                  ("net", "cpu", "gpu", "mem", "disk"),
                  ("disk", "net", "cpu")):
        stray = gaps_are_clean(order)
        check("%s leaves the gaps alone" % ",".join(order), stray == 0,
              "%d stray pixels" % stray)


for t in (test_every_box_size, test_every_arrangement,
          test_nothing_paints_between_cards):
    t()

print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
sys.exit(1 if FAILED else 0)
