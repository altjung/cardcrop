"""Level: how far the surface sits from parallel with the camera's sensor, measured with the phone.

A phone lying on the mat reads the mat against gravity, which says nothing on its own, since a stand on
a sloped desk slopes with it and the photo is then square. So two things are read the same way, the mat
and the camera's rear screen (parallel to the sensor), and the difference between them is the tilt that
matters: it puts one edge of a card off the focal plane and tips the light.

Each of the two is read twice, the second time with the phone turned 180 degrees where it lies, and the
two are differenced, which cancels the phone's own lean (the camera bump rocks a phone by a degree or more).
The two halves of that lean, one from the mat and one from the camera, should agree, which checks that the
phone was turned cleanly and did not shift.

Readings are the browser's deviceorientation beta and gamma in degrees, the phone's top pointed at the far
edge of the mat every first reading. Slopes are (right edge high, far edge high), in degrees.

Geometry is already removed from every crop by the card's own four edges (engine.warp_card), so nothing
here warps an image: the tilt measured from a detected card is shown beside the phone's as a cross-check."""
from __future__ import annotations

import json
import math
import os
import time

import numpy as np

GOOD, OK = 0.3, 0.8          # degrees of relative tilt: level, fine near the middle, re-shim
LEAN_GAP = 0.6               # degrees the phone's own lean may differ between the two pairs
SPAN_MM = 300.0              # across the shooting area, for the shim heights


def _path() -> str:
    import identify
    return os.path.join(identify._cache_dir(), "level.json")


def slope(beta: float, gamma: float) -> np.ndarray:
    """One phone reading as the surface's slope under it: gamma positive tips the right edge down,
    beta positive raises the top edge (the W3C deviceorientation frame)."""
    return np.array([-float(gamma), float(beta)])


def pair(first, turned) -> tuple[np.ndarray, np.ndarray]:
    """A reading and the same spot with the phone turned 180 degrees: the slope, in the first
    reading's frame, and the phone's own lean."""
    a, b = slope(*first), slope(*turned)
    return (a - b) / 2, (a + b) / 2


def measure(reads, span_mm: float = SPAN_MM) -> dict:
    """reads: four [beta, gamma] readings, mat, mat turned, camera, camera turned."""
    if len(reads) != 4 or any(len(r) != 2 for r in reads):
        return {"on": False, "error": "Four readings are needed: the mat twice and the camera twice"}
    if any(abs(float(v)) > 15 for r in reads for v in r):
        return {"on": False, "error": "A reading was more than 15° from flat: lay the phone down on its back"}
    surf, lean_s = pair(reads[0], reads[1])
    cam, lean_c = pair(reads[2], reads[3])
    rel = surf - cam
    deg = float(np.hypot(*rel))
    gap = float(np.hypot(*(lean_s - lean_c)))
    span = max(50.0, float(span_mm or SPAN_MM))
    rep = {"on": True, "deg": round(deg, 2), "rel": [round(float(v), 3) for v in rel],
           "surface": [round(float(v), 3) for v in surf], "camera": [round(float(v), 3) for v in cam],
           "lean_gap": round(gap, 2), "span_mm": span, "at": time.time()}
    rep["state"] = "good" if deg <= GOOD else "ok" if deg <= OK else "bad"
    rep["shim"] = shim(rel, span)
    rep["advice"] = advice(rep)
    return rep


def shim(rel, span_mm: float) -> list[dict]:
    """What to raise, per axis, so the mat comes parallel to the sensor: the low side of each axis
    by span x tan(angle). Under 0.2 mm is left alone."""
    out = []
    for v, hi, lo in ((rel[0], "right", "left"), (rel[1], "far", "near")):
        mm = span_mm * math.tan(math.radians(abs(float(v))))
        if mm >= 0.2:
            out.append({"edge": lo if v > 0 else hi, "mm": round(mm, 1)})
    return out


def advice(rep: dict) -> str:
    if rep["lean_gap"] > LEAN_GAP:
        return ("The two pairs disagree about the phone itself, so it moved or was not turned a clean 180°. "
                "Read again with the phone's top on the far edge each first time.")
    if rep["state"] == "good":
        return "Level with the camera."
    s = " and its ".join(f"{x['edge']} edge {x['mm']} mm" for x in rep["shim"])
    tail = "Fine for cards kept near the middle." if rep["state"] == "ok" else "Edges of a card will soften at a wide aperture."
    return f"Raise the mat's {s}. {tail}" if s else tail


def save(rep: dict):
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "w") as f:
        json.dump(rep, f)


def load() -> dict:
    try:
        with open(_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"on": False}


def clear():
    try:
        os.remove(_path())
    except OSError:
        pass


# ------------------------------------------------------------------ the cross-check from a photo
def focal_px(path: str, w: int, h: int) -> float | None:
    """Focal length in pixels from the 35 mm equivalent in the file's EXIF, scaled on the diagonal."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = im.getexif().get_ifd(0x8769)
        f35 = float(ex.get(0xA405) or 0)
    except Exception:  # noqa: BLE001
        return None
    return f35 * math.hypot(w, h) / math.hypot(36, 24) if f35 > 0 else None


def tilt_from_quad(quad, w: int, h: int, f_px: float) -> float:
    """Degrees between the card's plane and the sensor, from where its two pairs of edges converge:
    the vanishing points through the camera's intrinsics give two directions in the plane, and their
    cross product is its normal."""
    q = np.asarray(quad, np.float64).reshape(4, 2)
    P = np.c_[q, np.ones(4)]
    Ki = np.linalg.inv(np.array([[f_px, 0, w / 2], [0, f_px, h / 2], [0, 0, 1]]))
    v1 = np.cross(np.cross(P[0], P[1]), np.cross(P[3], P[2]))     # top and bottom edges
    v2 = np.cross(np.cross(P[0], P[3]), np.cross(P[1], P[2]))     # left and right edges
    d1, d2 = Ki @ v1, Ki @ v2
    n = np.cross(d1 / np.linalg.norm(d1), d2 / np.linalg.norm(d2))
    n /= np.linalg.norm(n)
    return float(math.degrees(math.acos(min(1.0, abs(n[2])))))
