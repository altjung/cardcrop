"""Calibration: teaching the condition report your grading before it reports on anything.

The report measures what one overhead photo shows (centering, light wear at the corners and
edges at several sensitivities, marks on the back) and those numbers mean nothing on their own:
how much whitening a light-played card shows depends on your camera, your light and your eye.
So before the first report, every card you have already given a condition (your exported folders
and your eBay listings, live and sold) is measured, and a small ordinal model is fitted that turns
the measurements into a position on the NM, LP, MP, HP, DMG scale, choosing for itself which
measurements and which sensitivities agree with you. It is checked on cards it was not fitted on,
and that agreement is shown before any report is made."""
from __future__ import annotations

import json
import os
import time

import numpy as np

ORDER = ["NM", "LP", "MP", "HP", "DMG"]
MIN_CARDS = 20          # cards with a condition before reports are allowed
MIN_LOWER = 4           # of which this many below NM, or it cannot learn what wear looks like
VERSION = 1

# feature -> report category it is charged to
CATEGORY = {"centering_front": "Centering", "centering_back": "Centering", "chip_mm": "Edges",
            "surface": "Surface", "surface_soft": "Surface", "surface_spots": "Surface"}


def _cache():
    import identify
    return identify._cache_dir()


def samples_path():
    return os.path.join(_cache(), "calibration_samples.json")


def model_path():
    return os.path.join(_cache(), "calibration.json")


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def load_samples() -> dict:
    return _load(samples_path(), {})


def save_samples(s: dict) -> None:
    _save(samples_path(), s)


def load_model() -> dict | None:
    m = _load(model_path(), None)
    return m if m and m.get("version") == VERSION else None


def ready() -> tuple[bool, str]:
    """Whether reports may run, and if not, why."""
    m = load_model()
    if not m:
        return False, "The condition report has not been calibrated on your graded cards yet."
    return True, ""


# ---------------------------------------------------------------- measurements to features


def features(front: dict | None, back: dict | None) -> dict:
    """The numbers the model sees, from analyze_side results (back with its surface)."""
    f = {}
    for s in (front, back):
        if not s:
            continue
        side = s["side"]
        raw = s.get("raw") or {}
        for k, v in raw.items():
            if k in ("contrast", "border_chroma"):
                continue
            if k == "chip_mm":
                f["chip_mm"] = max(f.get("chip_mm", 0.0), float(v))
                continue
            f[f"{side}_{k}"] = float(v)
        c = s.get("centering") or {}
        if c.get("worst") is not None:
            f[f"centering_{side}"] = float(c["worst"])
    surf = (back or {}).get("surface") or {}
    if surf.get("defect_share") is not None:
        f["surface"] = float(surf["defect_share"])
        f["surface_soft"] = float(surf.get("soft_share", surf["defect_share"]))
        f["surface_spots"] = float(surf.get("spots", 0))
    return f


def category_of(name: str) -> str:
    if name in CATEGORY:
        return CATEGORY[name]
    return "Corners" if "corner" in name else "Edges"


def _transform(name: str, v: float) -> float:
    """Wear shares are tiny and skewed: a log keeps one bad corner from swamping everything."""
    if name.startswith("centering"):
        return max(0.0, v - 50.0) / 10.0           # 55/45 -> 0.5, 70/30 -> 2
    if name in ("chip_mm", "surface_spots"):
        return float(np.log1p(v))
    return float(np.log1p(v * 1000.0))


# ---------------------------------------------------------------- the model


def _matrix(rows, names, fill):
    X = np.array([[_transform(n, r.get(n, fill[n])) for n in names] for r in rows], np.float64)
    return X


def _fit(X, y, k, l2=0.3, iters=3000):
    """Cumulative-logit ordinal regression, weights kept non-negative (a flaw never helps).
    P(y > j) = sigmoid(X w - b_j). Returns w, b (k-1 increasing cut points)."""
    n, d = X.shape
    w = np.zeros(d)
    b = np.linspace(0.5, 0.5 + (k - 2), k - 1)
    mw, vw, mb, vb = np.zeros(d), np.zeros(d), np.zeros(k - 1), np.zeros(k - 1)
    lr, eps = 0.05, 1e-8
    Y = (y[:, None] > np.arange(k - 1)[None, :]).astype(np.float64)        # n x (k-1)
    cw = np.bincount(y, minlength=k).astype(np.float64)
    sw = (n / (k * np.maximum(cw, 1)))[y]                                   # balance the rare bands
    sw = sw / sw.mean()
    for t in range(1, iters + 1):
        z = X @ w
        p = 1.0 / (1.0 + np.exp(-(z[:, None] - b[None, :])))
        g = (p - Y) * sw[:, None]                                           # d loss / d (z - b)
        gw = X.T @ g.sum(1) / n + l2 * w / n * 4
        gb = -g.sum(0) / n
        mw = 0.9 * mw + 0.1 * gw
        vw = 0.999 * vw + 0.001 * gw * gw
        mb = 0.9 * mb + 0.1 * gb
        vb = 0.999 * vb + 0.001 * gb * gb
        w -= lr * (mw / (1 - 0.9 ** t)) / (np.sqrt(vw / (1 - 0.999 ** t)) + eps)
        b -= lr * (mb / (1 - 0.9 ** t)) / (np.sqrt(vb / (1 - 0.999 ** t)) + eps)
        w = np.maximum(w, 0.0)
        b = np.maximum.accumulate(np.maximum(b, b[0]) + np.arange(k - 1) * 1e-3) - np.arange(k - 1) * 1e-3
    return w, b


def _predict(X, w, b):
    z = X @ w
    return (z[:, None] > b[None, :]).sum(1)


def fit(samples: dict, progress=None) -> dict:
    """Fits the model on every sample with a condition; returns the saved model (or raises)."""
    rows, labels, keys = [], [], []
    for key, s in samples.items():
        c = (s.get("condition") or "").upper()
        if c in ORDER and s.get("features"):
            rows.append(s["features"])
            labels.append(c)
            keys.append(key)
    counts = {c: labels.count(c) for c in ORDER if labels.count(c)}
    lower = sum(v for c, v in counts.items() if c != "NM")
    if len(rows) < MIN_CARDS:
        raise ValueError(f"Only {len(rows)} cards with a condition could be measured; calibration needs "
                         f"at least {MIN_CARDS}.")
    if lower < MIN_LOWER:
        raise ValueError(f"Only {lower} of your measured cards are below Near Mint; calibration needs at least "
                         f"{MIN_LOWER} so it can learn what wear looks like on your photos.")
    present = [c for c in ORDER if counts.get(c)]
    idx = {c: i for i, c in enumerate(present)}
    y = np.array([idx[c] for c in labels])
    k = len(present)
    # features most cards have; a missing one (a card with no back photo) is taken as clean
    names = sorted({n for r in rows for n in r if sum(1 for q in rows if n in q) >= 0.6 * len(rows)})
    fill = {n: (50.0 if n.startswith("centering") else 0.0) for n in names}
    X = _matrix(rows, names, fill)
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Xs = (X - mu) / sd

    # honest agreement: each card predicted by a model that never saw it (5 folds)
    rng = np.random.default_rng(7)
    folds = rng.permutation(len(rows)) % 5
    pred = np.zeros(len(rows), int)
    for f in range(5):
        tr, te = folds != f, folds == f
        if te.sum() == 0 or len(set(y[tr])) < k:
            w_, b_ = _fit(Xs[tr], y[tr], k) if len(set(y[tr])) == k else _fit(Xs, y, k)
        else:
            w_, b_ = _fit(Xs[tr], y[tr], k)
        pred[te] = _predict(Xs[te], w_, b_)
        if progress:
            progress(f + 1, 6)
    w, b = _fit(Xs, y, k)
    if progress:
        progress(6, 6)
    agree = int((pred == y).sum())
    within = int((np.abs(pred - y) <= 1).sum())
    misses = [{"key": keys[i], "title": samples[keys[i]].get("title", keys[i]), "yours": labels[i],
               "model": present[pred[i]]} for i in range(len(rows)) if pred[i] != y[i]]
    model = {"version": VERSION, "date": time.strftime("%Y-%m-%d %H:%M"), "n": len(rows), "counts": counts,
             "bands": present, "names": names, "fill": fill, "mu": mu.tolist(), "sd": sd.tolist(),
             "w": w.tolist(), "b": b.tolist(), "agree": agree, "within": within, "misses": misses,
             "weights_by_category": _cat_weights(names, w)}
    _save(model_path(), model)
    return model


def _cat_weights(names, w):
    out = {}
    for n, v in zip(names, w):
        c = category_of(n)
        out[c] = round(out.get(c, 0.0) + float(v), 3)
    return out


# ---------------------------------------------------------------- scoring with the model

# where each band starts on the report's 100-point bar
STARTS = {"NM": 85, "LP": 70, "MP": 50, "HP": 30, "DMG": 0}


def score(feats: dict, model: dict | None = None) -> dict | None:
    """Points out of 100, the band, and the points taken off per category, from the model."""
    m = model or load_model()
    if not m or not feats:
        return None
    names = m["names"]
    x = np.array([_transform(n, feats.get(n, m["fill"][n])) for n in names])
    clean = np.array([_transform(n, m["fill"][n]) for n in names])
    mu, sd, w, b = (np.array(m[k]) for k in ("mu", "sd", "w", "b"))
    xs, cs = (x - mu) / sd, (clean - mu) / sd
    contrib = w * np.maximum(0.0, xs - cs)                  # how far each measurement is from a clean card
    z = float(cs @ w + contrib.sum())
    z_clean = float(cs @ w)
    bands = m["bands"]
    # piecewise-linear map from the model's scale to points: a clean card is 100 and each fitted
    # cut point lands where the next band starts on the bar
    knots_z, knots_p = [z_clean], [100.0]
    for j, cut in enumerate(b):
        # the cut between two bands sits where the upper one starts on the bar
        p = STARTS[bands[j]]
        if cut > knots_z[-1] + 1e-6:
            knots_z.append(float(cut))
            knots_p.append(float(p))
    if len(knots_z) == 1:
        knots_z.append(z_clean + 1.0)
        knots_p.append(85.0)
    slope = (knots_p[-1] - knots_p[-2]) / (knots_z[-1] - knots_z[-2])
    if z <= knots_z[-1]:
        pts = float(np.interp(z, knots_z, knots_p))
    else:
        pts = knots_p[-1] + slope * (z - knots_z[-1])
    # the band is the model's call, so the bar always agrees with it
    band = bands[int((z > b).sum())]
    lo = STARTS[band]
    hi = {"NM": 100, "LP": 84, "MP": 69, "HP": 49, "DMG": 29}[band]
    pts = int(round(min(hi, max(lo, pts))))
    total = 100 - pts
    by_cat = {}
    for n, c in zip(names, contrib):
        by_cat[category_of(n)] = by_cat.get(category_of(n), 0.0) + float(c)
    s = sum(by_cat.values())
    ded = {k: round(total * v / s, 1) if s > 0 else 0.0 for k, v in by_cat.items()}
    return {"points": pts, "band": band, "ded": ded}


def summary(m: dict | None = None) -> str:
    m = m or load_model()
    if not m:
        return "Not calibrated yet."
    counts = ", ".join(f"{c} {m['counts'][c]}" for c in ORDER if m["counts"].get(c))
    return (f"Calibrated on {m['n']} of your graded cards ({counts}), {m['date']}. On cards it was not "
            f"fitted on it matched your condition {m['agree']} times in {m['n']} "
            f"({100 * m['agree'] / m['n']:.0f}%) and was within one band {m['within']} times.")


# ---------------------------------------------------------------- gathering your graded cards

FEATURE_VERSION = 2


def _listing_folders(roots, max_depth=4):
    """sku -> (folder, condition or "", title) for every exported card folder under the roots."""
    out = {}
    for root in roots:
        root = os.path.expanduser(root)
        base = root.rstrip(os.sep).count(os.sep)
        for d, dirs, files in os.walk(root):
            if d.count(os.sep) - base >= max_depth:
                dirs[:] = []
            dirs[:] = [x for x in dirs if not x.startswith((".", "_to_delete"))]
            lj = next((f for f in files if f.endswith("_listing.json") and not f.startswith("._")), None)
            if not lj:
                continue
            try:
                with open(os.path.join(d, lj), encoding="utf-8") as f:
                    L = json.load(f) or {}
            except (OSError, ValueError):
                continue
            sku = L.get("sku") or os.path.basename(d)
            out.setdefault(sku, (d, (L.get("condition") or "").upper(), L.get("title") or sku))
    return out


def _sides_from_folder(folder):
    import engine
    import stats
    got = {"front": None, "back": None}
    for f in sorted(os.listdir(folder)):
        mm = stats.MAIN_PHOTO_RE.search(f)
        if not mm or f.startswith(".") or mm.group(2) not in got or got[mm.group(2)] is not None:
            continue
        import grading
        c = grading.card_from_photo(engine.imread(os.path.join(folder, f)))
        if c is not None:
            got[mm.group(2)] = c[0]
    return got["front"], got["back"]


def _sides_from_ebay(db, urls):
    import cv2
    import grading
    imgs = []
    for u in urls[:8]:
        data = db._cached_image(u)
        imgs.append(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None)
    return grading.sides_from_photos(imgs)


def measure(front, back) -> dict:
    import engine
    import grading
    sides = {}
    for side, img in (("front", front), ("back", back)):
        if img is None:
            continue
        sd = grading.analyze_side(img, side, engine.measure_centering(img))
        if side == "back":
            grading.remember_back(sd["_img"])
            sd["surface"] = grading.back_surface(sd)
        sides[side] = sd
    return features(sides.get("front"), sides.get("back"))


def gather(client, db, folders, store, progress=None, cancelled=None, log=None) -> dict:
    """Measures every card you have given a condition and returns the sample set (cached, so a
    second calibration only measures what is new). progress(i, n, text)."""
    samples = load_samples()
    local = _listing_folders(folders)
    todo = []                                      # (key, condition, title, how to get the sides)
    seen_skus = set()
    items = {}
    for a in (store or {}).get("active", []) + (store or {}).get("sold", []):
        if a.get("id"):
            items.setdefault(a["id"], a)
    n_items = len(items)
    for i, (iid, a) in enumerate(items.items()):
        if cancelled and cancelled():
            break
        if progress:
            progress(i, n_items, f"Reading the condition of your eBay listings ({i + 1} of {n_items})")
        key = f"ebay:{iid}"
        cached = samples.get(key)
        try:
            if cached and cached.get("fv") == FEATURE_VERSION and cached.get("condition"):
                cond, sku, title, urls = cached["condition"], cached.get("sku", ""), cached.get("title", ""), None
            else:
                urls, sku, cond, title = client.item_graded(iid)
        except Exception as e:  # noqa: BLE001
            if log:
                log(f"{a.get('title', iid)}: {e}")
            continue
        sku = sku or a.get("sku", "")
        if not cond:
            continue
        seen_skus.add(sku)
        if sku in local:                           # your full-size export beats eBay's copy
            todo.append((key, cond, title or a.get("title", ""), ("folder", local[sku][0], sku)))
        else:
            todo.append((key, cond, title or a.get("title", ""), ("ebay", urls, iid, sku)))
    for sku, (folder, cond, title) in local.items():
        if cond in ORDER and sku not in seen_skus:
            todo.append((f"folder:{folder}", cond, title, ("folder", folder, sku)))

    for i, (key, cond, title, src) in enumerate(todo):
        if cancelled and cancelled():
            break
        if progress:
            progress(i, len(todo), f"Measuring {title[:60]} ({i + 1} of {len(todo)})")
        old = samples.get(key)
        if old and old.get("fv") == FEATURE_VERSION and old.get("features"):
            old["condition"] = cond
            continue
        try:
            if src[0] == "folder":
                front, back = _sides_from_folder(src[1])
            else:
                urls = src[1]
                if urls is None:
                    urls, _sku, _c, _t = client.item_graded(src[2])
                front, back = _sides_from_ebay(db, urls)
            if front is None and back is None:
                raise RuntimeError("no whole-card photo found")
            samples[key] = {"condition": cond, "title": title, "features": measure(front, back),
                            "fv": FEATURE_VERSION, "sku": src[-1],
                            "source": src[0], "t": time.time()}
        except Exception as e:  # noqa: BLE001
            if log:
                log(f"{title}: {e}")
            continue
        if i % 5 == 4:
            save_samples(samples)
    save_samples(samples)
    return samples
