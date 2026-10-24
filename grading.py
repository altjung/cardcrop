"""Condition report: an estimate of how a card would grade, from the photos alone.

Only what one even, overhead photo can show is graded:
  Centering  the printed border on each side, against the limits graders publish
  Corners    whitening at the four corners (light specks where the border colour should be)
  Edges      whitening and chipping along the four edges
  Surface    backs only: every back of a game is the same print, so each one is compared
             with a clean reference made from your own backs; creases, dents and scuffs stand out

Cut squareness, print quality and fine holo scratches need other light or tools and are
left out rather than guessed. Every figure carries a confidence, and a card that cannot be
read well says so."""
from __future__ import annotations

import json
import os

import cv2
import numpy as np

W_STD = 1600                      # analysis width: about 25 px per mm on a 63 mm card
CARD_RADIUS = 3.0 / 63.0          # factory corner radius as a share of the width
CATEGORIES = ("Centering", "Corners", "Edges", "Surface")

# ---------------------------------------------------------------- scales


def _interp(x, pts):
    """Piecewise-linear lookup through (x, score) points, x ascending."""
    xs, ys = zip(*pts)
    return float(np.interp(x, xs, ys))


# the larger share of the worse axis, e.g. 60 for 60/40, against the limits graders publish
FRONT_CENTERING = [(50, 10), (55, 10), (60, 9), (65, 8), (70, 7), (75, 6), (80, 5), (85, 4), (90, 3), (100, 1)]
BACK_CENTERING = [(50, 10), (75, 10), (90, 9), (95, 7), (100, 4)]
# share of the corner's or edge's outer band that shows wear
WEAR_SCALE = [(0.0, 10), (0.004, 10), (0.012, 9.5), (0.025, 9), (0.05, 8), (0.09, 7), (0.15, 6), (0.25, 5),
              (0.4, 4), (1.0, 2)]
# share of the back's surface that differs from the clean reference
SURFACE_SCALE = [(0.0, 10), (0.0004, 10), (0.0015, 9), (0.004, 8), (0.01, 7), (0.02, 6), (0.04, 5), (0.08, 4),
                 (1.0, 2)]


def condition_for(overall: float) -> str:
    """eBay's ungraded condition from the estimate (CardCrop's NM, LP, MP, HP, DMG)."""
    for lim, code in ((8.5, "NM"), (7.0, "LP"), (5.0, "MP"), (3.0, "HP")):
        if overall >= lim:
            return code
    return "DMG"


# ---------------------------------------------------------------- per side


def _prep(core: np.ndarray) -> np.ndarray:
    from engine import to8
    c = to8(core)
    if c.ndim == 2:
        c = cv2.cvtColor(c, cv2.COLOR_GRAY2BGR)
    if c.shape[1] > c.shape[0]:            # a card is portrait; a sideways export is turned upright
        c = np.ascontiguousarray(np.rot90(c, -1))
    k = W_STD / c.shape[1]
    return cv2.resize(c, (W_STD, int(round(c.shape[0] * k))), interpolation=cv2.INTER_AREA)


def _card_mask(h, w):
    r = int(round(CARD_RADIUS * w))
    m = np.zeros((h, w), np.uint8)
    cv2.rectangle(m, (r, 0), (w - 1 - r, h - 1), 255, -1)
    cv2.rectangle(m, (0, r), (w - 1, h - 1 - r), 255, -1)
    for cx, cy in ((r, r), (w - 1 - r, r), (r, h - 1 - r), (w - 1 - r, h - 1 - r)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return m > 127


def _border_colour(lab, depth0, depth1, skip):
    """Median Lab of the border band on each side, and how even it is."""
    h, w = lab.shape[:2]
    bands = [lab[depth0:depth1, skip:w - skip], lab[h - depth1:h - depth0, skip:w - skip],
             lab[skip:h - skip, depth0:depth1], lab[skip:h - skip, w - depth1:w - depth0]]
    px = np.concatenate([b.reshape(-1, 3) for b in bands])
    med = np.median(px, axis=0)
    spread = float(np.percentile(np.linalg.norm(px - med, axis=1), 75))
    return med, spread


SOFT_LEVELS = (0.45, 0.7)
FADE_LEVELS = (0.7, 1.0, 1.5)


def _clean(m: np.ndarray) -> np.ndarray:
    """Specks of two pixels or more, either way, not single-pixel noise."""
    u = m.astype(np.uint8)
    out = cv2.morphologyEx(u, cv2.MORPH_OPEN, np.ones((2, 1), np.uint8)) & \
        cv2.morphologyEx(u, cv2.MORPH_OPEN, np.ones((1, 2), np.uint8)) | \
        cv2.morphologyEx(u, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return out > 0


def analyze_side(core: np.ndarray, side: str, centering=None) -> dict:
    """Measurements for one straightened side (the card exactly, no margin)."""
    img = _prep(core)
    h, w = img.shape[:2]
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    mask = _card_mask(h, w)
    out = {"side": side, "w": w, "h": h}

    # ---- centering
    if centering is not None:
        lr = max(centering.lr)
        tb = max(centering.tb)
        scale = FRONT_CENTERING if side == "front" else BACK_CENTERING
        out["centering"] = {"lr": list(centering.lr), "tb": list(centering.tb), "worst": max(lr, tb),
                            "score": round(min(_interp(lr, scale), _interp(tb, scale)), 2), "conf": "high"}
    else:
        out["centering"] = {"score": None, "conf": "none", "note": "no printed border found to measure"}

    # ---- wear: pixels in the outer band that are lighter and greyer than the border colour
    band = max(6, int(0.012 * w))                 # about 0.75 mm in from the edge
    skip = int(0.09 * w)
    med, spread = _border_colour(lab, band, band + max(8, int(0.02 * w)), skip)
    L_border = med[0]
    # padded, so the image border counts as outside the card (not only the rounded corners)
    dist_in = cv2.distanceTransform(cv2.copyMakeBorder(mask.astype(np.uint8), 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0),
                                    cv2.DIST_L2, 5)[1:-1, 1:-1]
    outer = mask & (dist_in <= band) & (dist_in >= 1.5)
    # every card shows a thin light line where the cut stock catches the light, mint ones too;
    # wear is what stands brighter than this card's own normal edge at the same depth
    depth = np.rint(dist_in).astype(np.int32)
    L = lab[..., 0]
    edge_zone = outer.copy()
    edge_zone[:skip, :skip] = edge_zone[:skip, w - skip:] = False
    edge_zone[h - skip:, :skip] = edge_zone[h - skip:, w - skip:] = False
    base = np.full(band + 2, L_border, np.float32)
    mad = np.full(band + 2, 4.0, np.float32)
    for k in range(1, band + 1):
        v = L[edge_zone & (depth == k)]
        if v.size > 50:
            base[k] = np.median(v)
            mad[k] = max(3.0, float(np.median(np.abs(v - base[k]))) * 1.4826)
    dk = np.clip(depth, 0, band + 1)
    lift = max(22.0, 2.5 * spread)
    thr = np.maximum(L_border + lift, base[dk] + np.clip(4.0 * mad[dk], 20.0, 30.0))
    worn = _clean(outer & (L > thr))
    # the same test at lower thresholds: faint whitening the fixed test misses, which calibration
    # against your own graded cards decides how much to count
    soft = {m: _clean(outer & (L > base[dk] + m * (thr - base[dk]))) for m in SOFT_LEVELS}
    # on a coloured border (yellow fronts, blue backs) whitening shows first as lost colour,
    # not added brightness: the same per-depth baseline, on chroma
    C = np.hypot(lab[..., 1] - 128.0, lab[..., 2] - 128.0)
    cbase = np.zeros(band + 2, np.float32)
    cmad = np.full(band + 2, 4.0, np.float32)
    lbase = base.copy()
    for k in range(1, band + 1):
        v = C[edge_zone & (depth == k)]
        if v.size > 50:
            cbase[k] = np.median(v)
            cmad[k] = max(2.0, float(np.median(np.abs(v - cbase[k]))) * 1.4826)
    cdrop = cbase[dk] - C
    not_shadow = L > lbase[dk] - 10
    border_chroma = float(np.median(cbase[1:band + 1]))
    fade = {m: _clean(outer & not_shadow & (cdrop > m * np.maximum(10.0, 4.0 * cmad[dk])))
            for m in FADE_LEVELS} if border_chroma > 18 else {}
    # how readable wear is on this border: white on navy is plain, white on yellow or silver is not
    contrast = 255 - L_border
    conf = "high" if contrast > 120 and spread < 20 else ("medium" if contrast > 60 and spread < 35 else "low")
    out["border"] = {"lab": [round(float(x), 1) for x in med], "spread": round(spread, 1)}

    cz = int(0.085 * w)
    corners = {}
    for key, (x0, y0) in {"TL": (0, 0), "TR": (w - cz, 0), "BL": (0, h - cz), "BR": (w - cz, h - cz)}.items():
        zone = outer[y0:y0 + cz, x0:x0 + cz]
        bad = worn[y0:y0 + cz, x0:x0 + cz]
        f = float(bad.sum()) / max(1, int(zone.sum()))
        corners[key] = {"wear": round(f, 4), "score": round(_interp(f, WEAR_SCALE), 2), "box": [x0, y0, cz]}
    out["corners"] = {"each": corners, "conf": conf}

    edges = {}
    for key, sl in {"top": (slice(0, band + 2), slice(cz, w - cz)), "bottom": (slice(h - band - 2, h), slice(cz, w - cz)),
                    "left": (slice(cz, h - cz), slice(0, band + 2)), "right": (slice(cz, h - cz), slice(w - band - 2, w))}.items():
        zone, bad = outer[sl], worn[sl]
        f = float(bad.sum()) / max(1, int(zone.sum()))
        # a long chip reads worse than scattered specks of the same total
        prof = bad.any(axis=1 if key in ("left", "right") else 0)
        run, longest = 0, 0
        for v in prof:
            run = run + 1 if v else 0
            longest = max(longest, run)
        mm = longest / (w / 63.0)
        s = _interp(f, WEAR_SCALE) - (0.5 if mm > 2 else 0) - (0.5 if mm > 5 else 0)
        edges[key] = {"wear": round(f, 4), "longest_mm": round(mm, 1), "score": round(max(1.0, s), 2)}
    out["edges"] = {"each": edges, "conf": conf}
    raw = {"contrast": round(float(contrast), 1), "border_chroma": round(border_chroma, 1)}
    levels = [(f"@{m}", wm) for m, wm in [(1.0, worn)] + sorted(soft.items())]
    levels += [(f"_fade@{m}", wm) for m, wm in sorted(fade.items())]
    for tag, wm in levels:
        cf = [float(wm[y0:y0 + cz, x0:x0 + cz].sum()) / max(1, int(outer[y0:y0 + cz, x0:x0 + cz].sum()))
              for (x0, y0, _c) in (c["box"] for c in corners.values())]
        ef = []
        for sl in ((slice(0, band + 2), slice(cz, w - cz)), (slice(h - band - 2, h), slice(cz, w - cz)),
                   (slice(cz, h - cz), slice(0, band + 2)), (slice(cz, h - cz), slice(w - band - 2, w))):
            ef.append(float(wm[sl].sum()) / max(1, int(outer[sl].sum())))
        raw[f"corner_max{tag}"], raw[f"corner_mean{tag}"] = max(cf), float(np.mean(cf))
        raw[f"edge_max{tag}"], raw[f"edge_mean{tag}"] = max(ef), float(np.mean(ef))
    raw["chip_mm"] = max(e["longest_mm"] for e in edges.values())
    out["raw"] = raw
    out["_worn"] = worn
    out["_img"] = img
    return out


# ---------------------------------------------------------------- back surface against a reference


def _ref_dir():
    import identify
    d = os.path.join(identify._cache_dir(), "back_reference")
    os.makedirs(d, exist_ok=True)
    return d


def _small_gray(img, w=800):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    k = w / g.shape[1]
    return cv2.resize(g, (w, int(round(g.shape[0] * k))), interpolation=cv2.INTER_AREA)


def _same_design(a, b) -> float:
    """Correlation of two small grey backs (1 = the same printed design)."""
    sa, sb = cv2.resize(a, (120, 168)), cv2.resize(b, (120, 168))
    sa = (sa - sa.mean()) / (sa.std() + 1e-6)
    sb = (sb - sb.mean()) / (sb.std() + 1e-6)
    return float((sa * sb).mean())


def remember_back(img: np.ndarray, game: str = "pokemon", keep: int = 15) -> int:
    """Adds a back to the reference set for its game; returns how many there are."""
    d = os.path.join(_ref_dir(), game)
    os.makedirs(d, exist_ok=True)
    g = _small_gray(img)
    files = sorted(f for f in os.listdir(d) if f.endswith(".png"))
    if files:
        first = cv2.imread(os.path.join(d, files[0]), cv2.IMREAD_GRAYSCALE)
        if first is not None:
            g0 = cv2.resize(g, first.shape[::-1])
            g1 = cv2.rotate(g0, cv2.ROTATE_180)
            c0, c1 = _same_design(g0, first), _same_design(g1, first)
            if max(c0, c1) < 0.6:
                return len(files)                 # not this game's back: left out
            if c1 > c0:                           # stored the same way up as the others
                g = cv2.rotate(g, cv2.ROTATE_180)
    n = len(files)
    cv2.imwrite(os.path.join(d, f"back_{n % keep:02d}.png"), g)
    return min(n + 1, keep)


def _reference(game: str, shape) -> np.ndarray | None:
    d = os.path.join(_ref_dir(), game)
    if not os.path.isdir(d):
        return None
    ims = [cv2.imread(os.path.join(d, f), cv2.IMREAD_GRAYSCALE) for f in sorted(os.listdir(d)) if f.endswith(".png")]
    ims = [cv2.resize(i, (shape[1], shape[0]), interpolation=cv2.INTER_AREA) for i in ims if i is not None]
    if len(ims) < 3:
        return None
    return np.median(np.stack(ims), axis=0).astype(np.uint8)   # the median drops any one back's wear


def back_surface(side: dict, game: str = "pokemon") -> dict:
    img = side["_img"]
    g = _small_gray(img)
    ref = _reference(game, g.shape)
    if ref is None:
        return {"score": None, "conf": "none", "note": "needs three or more backs of this game to compare"}
    # a back looks much the same either way up, so both are tried and the closer one kept
    flipped = cv2.rotate(g, cv2.ROTATE_180)
    c0, c1 = _same_design(g, ref), _same_design(flipped, ref)
    if max(c0, c1) < 0.6:
        return {"score": None, "conf": "none", "note": "back design not recognised"}
    if c1 > c0:
        g = flipped
    # fine alignment, then compare structure with brightness and colour levelled out
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        _, warp = cv2.findTransformECC(ref.astype(np.float32), g.astype(np.float32), warp, cv2.MOTION_AFFINE,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5), None, 5)
    except cv2.error:
        pass
    al = cv2.warpAffine(g, warp, (g.shape[1], g.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                        borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    r = ref.astype(np.float32)
    al = (al - al.mean()) / (al.std() + 1e-6) * r.std() + r.mean()
    a_b, r_b = cv2.GaussianBlur(al, (0, 0), 1.6), cv2.GaussianBlur(r, (0, 0), 1.6)
    diff = np.abs(a_b - r_b)
    # where the print itself is busy, small misalignments look like differences: allow for it
    busy = cv2.dilate(cv2.GaussianBlur(np.abs(cv2.Laplacian(r_b, cv2.CV_32F)), (0, 0), 3), np.ones((9, 9), np.uint8))
    # glossy highlights shift with the light: bright areas of the print get extra room
    thr = 38 + 2.5 * busy + 0.12 * r_b
    h, w = diff.shape
    inner = np.zeros_like(diff, bool)
    b = int(0.03 * w)
    inner[b:h - b, b:w - b] = True                 # the edges are graded on their own
    soft_bad = cv2.morphologyEx(((diff > 0.7 * thr) & inner).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    soft_share = float(soft_bad.sum()) / float(inner.sum())
    bad = (diff > thr) & inner
    bad = cv2.morphologyEx(bad.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab_, stats, _ = cv2.connectedComponentsWithStats(bad)
    min_area = (0.9 * w / 63.0) ** 2               # a defect about a millimetre across or more
    keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_area]
    area = sum(int(stats[i, cv2.CC_STAT_AREA]) for i in keep)
    f = area / float(inner.sum())
    marks = [[int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3])] for i in keep[:30]]
    return {"score": round(_interp(f, SURFACE_SCALE), 2), "defect_share": round(f, 5), "spots": len(keep),
            "marks": marks, "scale": w, "conf": "medium",
            "soft_share": round(soft_share, 5)}


# ---------------------------------------------------------------- the card


def _round_half(x):
    return round(x * 2) / 2


def combine(front: dict | None, back: dict | None) -> dict:
    """Subgrades and an overall estimate from whichever sides were measured."""
    sides = [s for s in (front, back) if s]
    sub, detail = {}, {}

    cs = [s["centering"]["score"] for s in sides if s.get("centering", {}).get("score") is not None]
    if cs:
        sub["Centering"] = min(cs)
    cor = [c["score"] for s in sides for c in s["corners"]["each"].values()]
    if cor:
        sub["Corners"] = 0.6 * min(cor) + 0.4 * float(np.mean(cor))
    edg = [e["score"] for s in sides for e in s["edges"]["each"].values()]
    if edg:
        sub["Edges"] = 0.6 * min(edg) + 0.4 * float(np.mean(edg))
    surf = (back or {}).get("surface", {})
    if surf.get("score") is not None:
        sub["Surface"] = surf["score"]
    sub = {k: _round_half(v) for k, v in sub.items()}
    if not sub:
        return {"subgrades": {}, "overall": None}
    vals = list(sub.values())
    # like the graders: the average, but never more than a point above the weakest category
    overall = _round_half(min(float(np.mean(vals)), min(vals) + 1.0))
    confs = [s["corners"]["conf"] for s in sides]
    detail["wear_readability"] = "low" if "low" in confs else ("medium" if "medium" in confs else "high")
    res = {"subgrades": sub, "overall": overall, "condition": condition_for(overall), **detail,
           "sides": [s["side"] for s in sides]}
    # calibrated on your own graded cards: the model's score replaces the fixed scales, and each
    # category's subgrade is restated from the points the model charged to it, so the words agree
    try:
        import calibrate
        cal = calibrate.score(calibrate.features(front, back))
    except Exception:  # noqa: BLE001
        cal = None
    if cal:
        res["calibrated"] = cal
        for k in list(sub) + [k for k in cal["ded"] if k not in sub]:
            sub[k] = _round_half(max(1.0, 10.0 - cal["ded"].get(k, 0.0) / WEIGHTS[k]))
        res["subgrades"] = sub
        res["condition"] = cal["band"]
    return res


def keep_tiles(s: dict) -> None:
    """Swap the full analysis picture for the eight small corner crops the report needs."""
    if "_img" not in s:
        return
    img, worn, tiles = s.pop("_img"), s.pop("_worn"), {}
    k_ = 340 / img.shape[0]
    s["_thumb"] = cv2.resize(img, (int(img.shape[1] * k_), 340), interpolation=cv2.INTER_AREA)
    for k, c in s["corners"]["each"].items():
        x, y, cz = c["box"]
        tiles[k] = (img[y:y + cz, x:x + cz].copy(), worn[y:y + cz, x:x + cz].copy())
    s["_tiles"] = tiles


def side_summary(s: dict) -> dict:
    """What is kept on disk for one side (no pictures)."""
    return {k: v for k, v in s.items() if not k.startswith("_")}


def save_side(folder: str, name: str, s: dict) -> None:
    with open(os.path.join(folder, f"{name}_{s['side']}_grade.json"), "w", encoding="utf-8") as f:
        json.dump(side_summary(s), f, indent=1)


def load_side(folder: str, name: str, side: str) -> dict | None:
    try:
        with open(os.path.join(folder, f"{name}_{side}_grade.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- the report image

LIME = (214, 242, 75)
INK = (14, 16, 18)
TEXT = (238, 238, 234)
MUTED = (150, 154, 160)
RED = (240, 84, 76)


def _font_dir():
    import sys
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "fonts")


def _font(name, size, weight="Regular"):
    from PIL import ImageFont
    try:
        f = ImageFont.truetype(os.path.join(_font_dir(), name), size)
        try:
            f.set_variation_by_name(weight)
        except Exception:  # noqa: BLE001
            pass
        return f
    except OSError:
        return ImageFont.load_default()


def _side_scores(s: dict) -> dict:
    out = {}
    if s.get("centering", {}).get("score") is not None:
        out["Centering"] = s["centering"]["score"]
    cor = [c["score"] for c in s["corners"]["each"].values()]
    out["Corners"] = 0.6 * min(cor) + 0.4 * float(np.mean(cor))
    edg = [e["score"] for e in s["edges"]["each"].values()]
    out["Edges"] = 0.6 * min(edg) + 0.4 * float(np.mean(edg))
    if (s.get("surface") or {}).get("score") is not None:
        out["Surface"] = s["surface"]["score"]
    return out


def status(cat: str, score) -> str:
    """One plain word for a buyer, no numbers."""
    if score is None:
        return "Not assessed"
    if cat == "Centering":
        return "Well centered" if score >= 9 else ("Slightly off-center" if score >= 7 else "Off-center")
    if cat == "Corners" and score >= 9.5:
        return "Sharp"
    return "Clean" if score >= 9.5 else ("Light wear" if score >= 8 else ("Wear" if score >= 6 else "Heavy wear"))


# points off a perfect 100 for each subgrade point below 10, by category
WEIGHTS = {"Centering": 2.0, "Corners": 3.0, "Edges": 2.5, "Surface": 2.5}
BANDS = [("DMG", 0, "Damaged"), ("HP", 30, "Heavily Played"), ("MP", 50, "Moderately Played"),
         ("LP", 70, "Lightly Played"), ("NM", 85, "Near Mint")]


def points(res: dict) -> tuple[int, dict]:
    """A score out of 100, every card starting full, less a deduction per category."""
    cal = res.get("calibrated")
    if cal:
        ded = {k: cal["ded"].get(k, 0.0) for k in (res.get("subgrades") or {})}
        return cal["points"], ded
    ded = {k: round((10 - v) * WEIGHTS[k], 1) for k, v in (res.get("subgrades") or {}).items()}
    return max(0, int(round(100 - sum(ded.values())))), ded


def band_of(score: int):
    code, name = "DMG", "Damaged"
    for c, lo, n in BANDS:
        if score >= lo:
            code, name = c, n
    return code, name


def render_report(title: str, subtitle: str, front: dict | None, back: dict | None, size: int = 1600):
    """A square listing image: the card starts at 100 points and loses some for each flaw found; one
    segmented bar shows where that lands among the conditions (DMG to NM), and a row per category
    shows what was taken off and why. Plain words, no close-up of every speck."""
    from PIL import Image, ImageDraw, ImageFilter
    # the report's typeface has no Greek or card symbols: δ, ♀, ★ written out so none shows as a box
    import listing as _listing
    title = _listing.ebay_safe(title).replace("δ", "Delta").replace("Δ", "Delta")
    subtitle = _listing.ebay_safe(subtitle).replace("δ", "Delta").replace("Δ", "Delta")
    res = combine(front, back)
    sub = res.get("subgrades", {})
    score, ded = points(res)
    code, band_name = band_of(score)
    S = size / 1600.0

    def px(v):
        return int(round(v * S))

    BG, PANEL, LINE = (6, 7, 8), (17, 19, 20), (40, 43, 46)
    ON, OFF = (92, 236, 124), (38, 41, 44)
    im = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(im)
    f_cap = _font("GeistMono.ttf", px(22), "Medium")
    f_title = _font("Geist.ttf", px(50), "SemiBold")
    f_sub = _font("Geist.ttf", px(26))
    f_score = _font("GeistMono.ttf", px(150), "SemiBold")
    f_of = _font("GeistMono.ttf", px(40), "Medium")
    f_band = _font("Geist.ttf", px(44), "SemiBold")
    f_lab = _font("Geist.ttf", px(30), "Medium")
    f_note = _font("Geist.ttf", px(23))
    f_num = _font("GeistMono.ttf", px(34), "SemiBold")
    f_tick = _font("GeistMono.ttf", px(22), "Medium")

    def fit(t, font, room):
        if d.textlength(t, font=font) <= room:
            return t
        while t and d.textlength(t + "…", font=font) > room:
            t = t[:-1]
        return t.rstrip(" ·-") + "…"

    # panel
    X0, X1 = px(56), px(1544)
    d.rounded_rectangle([X0, px(56), X1, px(1544)], px(36), fill=PANEL, outline=LINE, width=max(1, px(2)))
    L, R = px(110), px(1490)

    # header: what this is, the card, its two sides
    d.text((L, px(108)), "CONDITION REPORT", font=f_cap, fill=LIME)
    room = px(1080) - L - px(30)
    d.text((L, px(140)), fit(title, f_title, room), font=f_title, fill=TEXT)
    d.text((L, px(206)), fit(subtitle, f_sub, room), font=f_sub, fill=MUTED)
    tx = R
    for s_ in (back, front):
        if not s_:
            continue
        if "_img" in s_:
            keep_tiles(s_)
        th = s_.get("_thumb")
        if th is None:
            continue
        hh = px(200)
        ww = int(th.shape[1] * hh / th.shape[0])
        t = Image.fromarray(cv2.cvtColor(cv2.resize(th, (ww, hh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
        m = Image.new("L", (ww, hh), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, ww - 1, hh - 1], px(10), fill=255)
        tx -= ww
        im.paste(t, (tx, px(104)), m)
        tx -= px(14)

    # the score, and the condition it lands in
    y = px(350)
    d.text((L, y), "SCORE", font=f_cap, fill=MUTED)
    sc = f"{score}"
    d.text((L - px(6), y + px(22)), sc, font=f_score, fill=TEXT)
    w_sc = d.textlength(sc, font=f_score)
    d.text((L + w_sc + px(6), y + px(118)), "/100", font=f_of, fill=MUTED)
    bx = px(760)
    d.text((bx, y), "LANDS IN", font=f_cap, fill=MUTED)
    d.text((bx, y + px(44)), band_name, font=f_band, fill=LIME)
    d.text((bx, y + px(110)), "Every card starts at 100. Flaws found in the photos take points off.",
           font=f_note, fill=MUTED)

    # the bar: 20 blocks of 5 points, lit up to the score, the five conditions marked along it
    by, bh = px(620), px(44)
    n, gap = 20, px(8)
    bw = (R - L - gap * (n - 1)) / n
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for k in range(n):
        x = L + k * (bw + gap)
        lit = (k + 1) * 5 <= score or (k * 5 < score and score - k * 5 >= 2.5)
        if lit:
            gd.rounded_rectangle([x, by, x + bw, by + bh], px(10), fill=ON + (255,))
        else:
            d.rounded_rectangle([x, by, x + bw, by + bh], px(10), fill=OFF)
    halo = glow.filter(ImageFilter.GaussianBlur(px(12)))
    im.paste(halo, (0, 0), halo)
    im.paste(glow, (0, 0), glow)
    d = ImageDraw.Draw(im)

    def xpos(v):
        return L + (R - L) * v / 100.0

    for c, lo, _n in BANDS:
        hi = next((b[1] for b in BANDS if b[1] > lo), 100)
        cx_ = (xpos(lo) + xpos(hi)) / 2
        here = c == code
        tw = d.textlength(c, font=f_tick)
        d.text((cx_ - tw / 2, by + bh + px(20)), c, font=f_tick, fill=LIME if here else MUTED)
        if lo > 0:
            x = xpos(lo) - gap / 2
            d.line([(x, by - px(14)), (x, by + bh + px(14))], fill=(120, 126, 132), width=max(1, px(2)))
    # where the score sits
    sx = xpos(score)
    d.polygon([(sx - px(10), by - px(30)), (sx + px(10), by - px(30)), (sx, by - px(14))], fill=TEXT)

    # what was taken off, and why
    y = px(790)
    d.text((L, y), "DEDUCTIONS", font=f_cap, fill=MUTED)
    tw = d.textlength("POINTS", font=f_cap)
    d.text((R - tw, y), "POINTS", font=f_cap, fill=MUTED)
    y += px(44)
    cen = [s_ for s_ in (front, back) if s_ and s_.get("centering", {}).get("lr")]

    def per_side(cat):
        words = [(s_["side"].title(), status(cat, _side_scores(s_).get(cat))) for s_ in (front, back) if s_]
        if len({w for _, w in words}) == 1:
            return ("Front and back" if len(words) == 2 else words[0][0]) + (", all four sides" if cat == "Edges" else "")
        return "  ·  ".join(f"{sd} {w.lower()}" for sd, w in words)

    notes = {
        "Centering": "  ·  ".join(f"{s_['side'].title()} {s_['centering']['lr'][0]}/{s_['centering']['lr'][1]} L/R, "
                                  f"{s_['centering']['tb'][0]}/{s_['centering']['tb'][1]} T/B" for s_ in cen)
        or "No printed border to measure",
        "Corners": per_side("Corners"),
        "Edges": per_side("Edges"),
        "Surface": "Back, checked against a clean back" if "Surface" in sub else
        ("Needs a few more backs reported on first" if "three or more" in (((back or {}).get("surface") or {})
                                                                         .get("note", "")) else "Back only"),
    }
    row_h = px(118)
    mini_x, mini_n = px(900), 10
    mini_w = px(380)
    for k in CATEGORIES:
        d.line([(L, y), (R, y)], fill=LINE, width=max(1, px(2)))
        word = status(k, sub.get(k))
        d.text((L, y + px(20)), k, font=f_lab, fill=TEXT)
        good = word in ("Sharp", "Clean", "Well centered")
        wx = L + d.textlength(k, font=f_lab) + px(16)
        d.text((wx, y + px(26)), word, font=f_note, fill=LIME if good else (240, 190, 90) if word != "Not assessed"
               else MUTED)
        d.text((L, y + px(64)), fit(notes[k], f_note, mini_x - L - px(30)), font=f_note, fill=MUTED)
        # the category's own bar: ten blocks, lit for what is left
        v = sub.get(k)
        segw = (mini_w - px(6) * (mini_n - 1)) / mini_n
        for j in range(mini_n):
            x = mini_x + j * (segw + px(6))
            lit = v is not None and j < round(v)
            d.rounded_rectangle([x, y + px(44), x + segw, y + px(70)], px(6), fill=ON if lit else OFF)
        dv = ded.get(k)
        t = "–" if dv is None else ("0" if dv < 0.5 else f"−{dv:.0f}")
        d.text((R - d.textlength(t, font=f_num), y + px(36)), t, font=f_num,
               fill=MUTED if dv is None or dv < 0.5 else TEXT)
        y += row_h
    d.line([(L, y), (R, y)], fill=LINE, width=max(1, px(2)))
    d.text((L, y + px(24)), "Total", font=f_lab, fill=TEXT)
    tot = f"{score} / 100"
    d.text((R - d.textlength(tot, font=f_num), y + px(20)), tot, font=f_num, fill=LIME)

    # footer
    d.text((L, px(1478)), "Measured by CardCrop from the listing photos. Not a professional grade.",
           font=f_note, fill=MUTED)
    return im


# ---------------------------------------------------------------- live listings


def looks_like_back(img: np.ndarray, game: str = "pokemon") -> bool:
    """Is this straightened card a back? Against your reference backs when there are any,
    else, for Pokémon, by the back's blue."""
    g = _small_gray(img if img.shape[0] >= img.shape[1] else np.ascontiguousarray(np.rot90(img, -1)))
    ref = _reference(game, g.shape)
    if ref is not None:
        return max(_same_design(g, ref), _same_design(cv2.rotate(g, cv2.ROTATE_180), ref)) >= 0.6
    if game != "pokemon":
        return False
    hsv = cv2.cvtColor(cv2.resize(img, (100, 140)), cv2.COLOR_BGR2HSV)
    return float(((hsv[..., 0] > 95) & (hsv[..., 0] < 130) & (hsv[..., 1] > 80)).mean()) > 0.35


def _order(pts) -> np.ndarray:
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    s_, d_ = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s_.argmin()], pts[d_.argmin()], pts[s_.argmax()], pts[d_.argmax()]], np.float32)


def _sound_quad(q, w, h, tol=3.0) -> bool:
    """A found outline worth trusting in a listing photo: inside the picture, convex, and with
    opposite sides parallel (a flat card photographed square-on, upright or turned a little).
    A holo pattern that pulls one corner off gives sides that are not."""
    q = _order(q)
    if (q[:, 0] < -3).any() or (q[:, 1] < -3).any() or (q[:, 0] > w + 3).any() or (q[:, 1] > h + 3).any():
        return False
    if not cv2.isContourConvex(q.reshape(-1, 1, 2)):
        return False

    def ang(a, b):
        return np.degrees(np.arctan2(b[1] - a[1], b[0] - a[0]))
    tl, tr, br, bl = q
    for a, b in ((ang(tl, tr), ang(bl, br)), (ang(tl, bl), ang(tr, br))):
        if abs((a - b + 180) % 360 - 180) > tol:
            return False
    return True


def _margin_card(img: np.ndarray):
    """The card out of a photo that is the card on a plain margin, turned with it if it sits
    at a slight angle. Returns (card, sure): sure when a margin was found all round."""
    h, w = img.shape[:2]
    b = max(3, int(0.004 * max(h, w)))
    frame = np.concatenate([img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3),
                            img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3)])
    bg = np.median(frame, axis=0)
    spread = float(np.median(np.abs(frame.astype(np.float32) - bg).max(axis=1)))
    if spread < 18:                               # the edge of the photo is one plain colour
        fg = (np.abs(img.astype(np.int16) - bg.astype(np.int16)).max(axis=2) > 28).astype(np.uint8)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        cs, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cs:
            c = max(cs, key=cv2.contourArea)
            x, y, cw, ch = cv2.boundingRect(c)
            # a card may run to an edge of an export (a tight crop); it is still cut along its own
            # sides, only it counts as less sure than one with margin all round
            inside = x > 1 and y > 1 and x + cw < w - 1 and y + ch < h - 1
            if cv2.contourArea(c) > 0.45 * w * h and cv2.contourArea(c) < 0.985 * w * h:
                box = _order(cv2.boxPoints(cv2.minAreaRect(c)))
                box[:, 0] = np.clip(box[:, 0], 0, w - 1)
                box[:, 1] = np.clip(box[:, 1], 0, h - 1)
                tw = int(round(np.linalg.norm(box[1] - box[0])))
                th = int(round(np.linalg.norm(box[3] - box[0])))
                if tw > 50 and th > 50:
                    M = cv2.getPerspectiveTransform(box, np.float32([[0, 0], [tw, 0], [tw, th], [0, th]]))
                    return cv2.warpPerspective(img, M, (tw, th), flags=cv2.INTER_CUBIC), inside
    m = max(1, int(round(0.004 * h)))
    return img[m:h - m, m:w - m], False


def card_from_photo(img):
    """The whole card out of one photo, and how sure that is (2 a sound outline, 1 a card on a
    plain margin, 0 a photo that only has a card's shape), or None for a wide shot or close-up.
    In a photo that is already about the card (an export, most listing photos) an outline must
    cover most of it: a smaller sound rectangle there is the art window or the text box of a
    holo, not the card."""
    from engine import detect_card, warp_card, Settings, CARD_RATIO
    if img is None:
        return None
    if img.dtype == np.uint16:                     # 16-bit exports: the tests below are in 8-bit levels
        img = (img // 257).astype(np.uint8)
    h, w = img.shape[:2]
    if w > 1.15 * h:                               # two cards side by side, or a wide shot
        return None
    quad, conf = detect_card(img)
    qa = cv2.contourArea(quad.astype(np.float32))
    card_shaped = abs(w / h - CARD_RATIO) <= 0.06
    need = 0.72 if card_shaped else 0.35
    # an export or a scan is flat and square-on: its card's opposite sides are parallel to within
    # a degree, so a looser outline there is a wrong one (a back's swirl, a holo's frame)
    if conf >= 0.5 and qa >= need * w * h and _sound_quad(quad, w, h, 1.0 if card_shaped else 3.0):
        card, q = warp_card(img, _order(quad), Settings(margin_px=0, auto_portrait=True), 0), 2
    elif card_shaped:
        card, sure = _margin_card(img)
        q = 1 if sure else 0
    else:
        return None
    ch, cw = card.shape[:2]
    if abs(min(ch, cw) / max(ch, cw) - CARD_RATIO) > 0.06:   # a corner close-up, not a whole card
        return None
    return card, q


def sides_from_photos(images, game: str = "pokemon"):
    """Front and back from a listing's photos, in listing order. Each photo is judged: a whole
    card found by a sound outline is best, then a card on a plain margin, and last a photo that
    merely has a card's shape (it could be a close-up). Side-by-side pictures and corner
    close-ups are skipped; the best front and the best back are used."""
    cards = []                                     # (quality, order, card)
    for n, img in enumerate(images):
        got = card_from_photo(img)
        if got is not None:
            cards.append((got[1], n, got[0]))
    backs = [c for c in cards if looks_like_back(c[2], game)]
    if not backs and len(cards) > 1 and game == "pokemon":
        # no reference backs yet: the back is the clearly bluest of the listing's cards
        blue = sorted(((_blue(c[2]), i) for i, c in enumerate(cards)), reverse=True)
        if blue[0][0] - blue[1][0] >= 0.08:
            backs = [cards[blue[0][1]]]
    fronts = [c for c in cards if not any(c is b_ for b_ in backs)]

    def best(lst):
        # the best kind of photo there is, and of those the first in the listing
        if not lst:
            return None
        top = max(c[0] for c in lst)
        return min((c for c in lst if c[0] == top), key=lambda c: c[1])[2]
    front, back = best(fronts), best(backs)
    if back is None and len(fronts) > 1:           # a back it cannot tell: the photo after the front
        rest = sorted([c for c in fronts if c[2] is not front], key=lambda c: c[1])
        back = rest[0][2]
    return front, back


def _blue(img) -> float:
    hsv = cv2.cvtColor(cv2.resize(img, (100, 140)), cv2.COLOR_BGR2HSV)
    return float(((hsv[..., 0] > 90) & (hsv[..., 0] < 135) & (hsv[..., 1] > 45)).mean())
