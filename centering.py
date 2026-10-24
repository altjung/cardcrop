"""Centering for grading: guide lines on a card photo and what they measure.

A side's guides are two rectangles in the photo's pixels, each turned by its own small angle: the outer
one on the card's cut edge, the inner one on the printed frame. The border on each side is the distance
from the middle of an inner line to the outer line facing it, so a card shot a hair crooked, or printed
a hair crooked on its stock, still measures true. Grades follow PSA's published centering limits."""
from __future__ import annotations

import json
import math
import os

import numpy as np

SIDES = ("top", "bottom", "left", "right")
# grade, worst front split, worst back split (the larger share, in percent)
LIMITS = ((10, 55, 75), (9, 60, 90), (8, 65, 90), (7, 70, 90), (6, 80, 90), (5, 85, 90), (4, 85, 90),
          (3, 90, 90), (2, 90, 90), (1, 100, 100))
PRISTINE = 52.0                 # 52/48 or better: as centred as a card is cut


def rect(l, t, r, b, rot=0.0) -> dict:
    return {"l": float(l), "t": float(t), "r": float(r), "b": float(b), "rot": float(rot)}


def corners(R: dict) -> dict:
    """The rectangle's corners, turned about its middle: tl, tr, br, bl as (x, y)."""
    cx, cy = (R["l"] + R["r"]) / 2, (R["t"] + R["b"]) / 2
    a = math.radians(R["rot"])
    c, s = math.cos(a), math.sin(a)

    def turn(x, y):
        dx, dy = x - cx, y - cy
        return cx + dx * c - dy * s, cy + dx * s + dy * c
    return {"tl": turn(R["l"], R["t"]), "tr": turn(R["r"], R["t"]), "br": turn(R["r"], R["b"]),
            "bl": turn(R["l"], R["b"])}


def line(R: dict, side: str):
    """One side of a turned rectangle as its two end points."""
    k = corners(R)
    return {"top": (k["tl"], k["tr"]), "bottom": (k["bl"], k["br"]),
            "left": (k["tl"], k["bl"]), "right": (k["tr"], k["br"])}[side]


def _dist(p, a, b) -> float:
    """Distance from p to the infinite line through a and b."""
    (x, y), (x1, y1), (x2, y2) = p, a, b
    L = math.hypot(x2 - x1, y2 - y1) or 1e-9
    return abs((x2 - x1) * (y1 - y) - (x1 - x) * (y2 - y1)) / L


def borders(g: dict) -> dict:
    """Border width on each side, in pixels: from the middle of the inner line to the outer line."""
    out = {}
    for side in SIDES:
        a, b = line(g["inner"], side)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        out[side] = _dist(mid, *line(g["outer"], side))
    return out


def splits(g: dict) -> dict:
    """{'tb': (top %, bottom %), 'lr': (left %, right %)}."""
    w = borders(g)

    def pair(a, b):
        s = a + b
        return (50.0, 50.0) if s <= 0 else (100 * a / s, 100 * b / s)
    return {"tb": pair(w["top"], w["bottom"]), "lr": pair(w["left"], w["right"])}


def grade_for(worst: float, side: str) -> int:
    col = 1 if side == "front" else 2
    for row in LIMITS:
        if worst <= row[col] + 1e-9:
            return row[0]
    return 1


def axis(split: tuple, side: str) -> dict:
    """One direction's verdict: its worse share, the grade it allows, and a word for it."""
    worst = max(split)
    g = grade_for(worst, side)
    word = "Pristine" if worst <= PRISTINE else ("Pass" if g == 10 else f"Caps at {g}")
    return {"worst": worst, "grade": g, "word": word}


def expected(g: dict, side: str) -> int:
    s = splits(g)
    return min(axis(s["tb"], side)["grade"], axis(s["lr"], side)["grade"])


def overall(sides: dict) -> int | None:
    """Both sides measured: the lower of the two; one side: that side's."""
    got = [expected(g, sd) for sd, g in sides.items() if g]
    return min(got) if got else None


def auto(img) -> dict:
    """Guides found in a photo: the outer on the card's edge (found as the main view finds it), the inner
    on the printed frame (where the border colour gives way), both following the card's tilt. A card
    with no border (full art) gets its inner guides a typical border's width in, for you to place."""
    import cv2
    import engine
    x = engine.to8(img)
    H, W = x.shape[:2]
    try:
        q, conf = engine.detect_card(x)
    except Exception:  # noqa: BLE001
        q, conf = None, 0.0
    if q is None or conf < 0.3:
        m = 0.02 * min(W, H)
        q = np.float32([[m, m], [W - m, m], [W - m, H - m], [m, H - m]])
    q = engine.order_quad(np.asarray(q, np.float32))
    top, bot = q[1] - q[0], q[2] - q[3]
    rot = math.degrees((math.atan2(top[1], top[0]) + math.atan2(bot[1], bot[0])) / 2)
    w = (np.linalg.norm(top) + np.linalg.norm(bot)) / 2
    h = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    cx, cy = float(q[:, 0].mean()), float(q[:, 1].mean())
    outer = rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, rot)
    meas = None
    try:
        dst = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
        core = cv2.warpPerspective(x, cv2.getPerspectiveTransform(q, dst), (int(round(w)), int(round(h))))
        meas = engine.measure_centering(core)
    except Exception:  # noqa: BLE001
        meas = None
    if meas is not None:
        bl, br, bt, bb = meas.left, meas.right, meas.top, meas.bottom
    else:
        bl = br = bt = bb = 0.045 * w
    inner = rect(outer["l"] + bl, outer["t"] + bt, outer["r"] - br, outer["b"] - bb, rot)
    return {"outer": outer, "inner": inner, "found": meas is not None}


# ------------------------------------------------------------------ saved with the card
def path_for(folder: str, slug: str) -> str:
    return os.path.join(folder, f"{slug}_centering.json")


def load(folder: str, slug: str) -> dict:
    try:
        with open(path_for(folder, slug), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(folder: str, slug: str, data: dict) -> str:
    os.makedirs(folder, exist_ok=True)
    p = path_for(folder, slug)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)
    return p
