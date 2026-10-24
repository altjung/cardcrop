"""Layers: a card's face split into frame, background and subject, so the 3D view can light,
foil and move each on its own, the way immersive digital cards are shown.

The subject (the Pokémon or the trainer) is found by a segmentation model trained on anime-style
art, run once per card on this Mac with onnxruntime and remembered. The background behind the
subject is filled in, so when the subject moves forward the art behind it is there to see. The
frame is the card's printed border, a ring of a width you can set."""
from __future__ import annotations

import hashlib
import os
import urllib.request

import numpy as np

# two models, like Photoshop's Select Subject leaning on more than one detector: one trained on
# anime-style art (trainers, most Pokémon art), one general salient-object model (items, painted
# and 3D-rendered Pokémon). Their selections are merged, then the edge is refined on the image.
MODELS = {
    "isnet-anime": dict(url="https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-anime.onnx",
                        bytes=176_069_933, size=1024, std=(1.0, 1.0, 1.0)),
    "u2net": dict(url="https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
                  bytes=175_997_641, size=320, std=(0.229, 0.224, 0.225)),
}
MODEL_URL = MODELS["isnet-anime"]["url"]
MODEL_NAME = "isnet-anime.onnx"
MODEL_BYTES = sum(m["bytes"] for m in MODELS.values())
VERSION = 3


def _cache_dir():
    import identify
    d = os.path.join(identify._cache_dir(), "layers")
    os.makedirs(d, exist_ok=True)
    return d


def model_path(name="isnet-anime"):
    return os.path.join(_cache_dir(), f"{name}.onnx")


def available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def have_model() -> bool:
    return all(os.path.exists(model_path(n)) and os.path.getsize(model_path(n)) > 0.9 * m["bytes"]
               for n, m in MODELS.items())


def download_model(progress=None):
    """About 350 MB in all, once. progress(done, total) may return False to stop."""
    total = MODEL_BYTES
    done0 = 0
    for name, m in MODELS.items():
        p = model_path(name)
        if os.path.exists(p) and os.path.getsize(p) > 0.9 * m["bytes"]:
            done0 += m["bytes"]
            continue
        tmp = p + ".part"
        with urllib.request.urlopen(m["url"], timeout=60) as r, open(tmp, "wb") as f:
            done = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and progress(done0 + done, total) is False:
                    raise RuntimeError("cancelled")
        os.replace(tmp, p)
        done0 += m["bytes"]


_sessions = {}


def _sess(name):
    if name not in _sessions:
        import onnxruntime as ort
        _sessions[name] = ort.InferenceSession(model_path(name), providers=["CPUExecutionProvider"])
    return _sessions[name]


def _run(name, rgb):
    import cv2
    m = MODELS[name]
    h, w = rgb.shape[:2]
    x = cv2.resize(rgb, (m["size"], m["size"]), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(m["std"], np.float32)
    s = _sess(name)
    out = s.run(None, {s.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
    out = (out - out.min()) / max(1e-6, out.max() - out.min())
    return cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)


def _boxy(m: np.ndarray) -> bool:
    """A selection that is just the art panel (a big rectangle), not a subject."""
    import cv2
    b = (m > 0.5).astype(np.uint8)
    if b.mean() < 0.55:
        return False
    cs, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return False
    c = max(cs, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(c)
    return cv2.contourArea(c) > 0.88 * w * h


def _guided(guide_bgr, p, r=10, eps=2e-3):
    """Edge refinement: the soft selection snaps to the image's own edges (hair, outlines)."""
    import cv2
    I = cv2.cvtColor(guide_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    box = lambda a: cv2.boxFilter(a, -1, (r, r))  # noqa: E731
    mI, mp = box(I), box(p)
    a = (box(I * p) - mI * mp) / (box(I * I) - mI * mI + eps)
    b = mp - a * mI
    return np.clip(box(a) * I + box(b), 0, 1)


def subject_matte(bgr: np.ndarray) -> np.ndarray:
    """0..1 selection of the subject in the art (BGR uint8), like Select Subject: both models,
    a model that only found the art panel is ignored, the rest are merged and the edge refined."""
    import cv2
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    picks = [m for m in (_run(n, rgb) for n in MODELS) if not _boxy(m)]
    if not picks:
        return np.zeros(bgr.shape[:2], np.float32)
    m = np.max(np.stack(picks), axis=0)
    m = np.clip((m - 0.2) / 0.6, 0, 1)
    # keep the main pieces only: specks the models half-see become noise in parallax
    b = (m > 0.5).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b)
    if n > 1:
        keep = np.zeros(n, bool)
        big = st[1:, cv2.CC_STAT_AREA].max()
        keep[1:] = st[1:, cv2.CC_STAT_AREA] >= max(0.04 * big, 0.002 * b.size)
        m = m * cv2.dilate(keep[lab].astype(np.uint8), np.ones((9, 9), np.uint8))
    return _guided(bgr, m.astype(np.float32))


def surface_mask(bgr: np.ndarray) -> np.ndarray:
    """What is printed on the card's surface rather than in the art: every line of text the
    reader finds (name, attacks, rule box, credits), padded a little. 0..1, full size."""
    import cv2
    h, w = bgr.shape[:2]
    m = np.zeros((h, w), np.float32)
    try:
        import identify
        res, _ = identify._engine()(bgr)
    except Exception:  # noqa: BLE001
        res = None
    pad = int(0.012 * w)
    for item in res or []:
        pts = np.array(item[0], np.float32)
        x0, y0 = pts.min(0)
        x1, y1 = pts.max(0)
        cv2.rectangle(m, (int(x0) - pad, int(y0) - pad), (int(x1) + pad, int(y1) + pad), 1.0, -1)
    return cv2.GaussianBlur(m, (0, 0), max(1.0, pad * 0.5))


def frame_mask(h: int, w: int, width: float) -> np.ndarray:
    """The printed border as a ring, width a share of the card's width."""
    import cv2
    m = np.zeros((h, w), np.float32)
    b = max(1, int(round(width * w)))
    m[:b] = m[-b:] = 1
    m[:, :b] = m[:, -b:] = 1
    return cv2.GaussianBlur(m, (0, 0), max(0.6, b * 0.08))


def build(front_bgr: np.ndarray, frame_width: float = 0.045) -> dict:
    """Matte and filled-in background for a card face (8-bit BGR). Cached by content."""
    import cv2
    img = front_bgr if front_bgr.dtype == np.uint8 else (front_bgr // 257).astype(np.uint8)
    h, w = img.shape[:2]
    if max(h, w) > 2048:                                   # textures are at most 2048 tall
        s = 2048 / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    key = hashlib.sha1(cv2.resize(img, (64, 90)).tobytes() + f"{frame_width:.3f}v{VERSION}".encode()).hexdigest()[:16]
    cm, cb = os.path.join(_cache_dir(), f"{key}_matte.png"), os.path.join(_cache_dir(), f"{key}_bg.jpg")
    if os.path.exists(cm) and os.path.exists(cb):
        mm = cv2.imread(cm)
        bg = cv2.imread(cb)
        if mm is not None and bg is not None and mm.shape[:2] == (h, w):
            return {"matte": mm[..., 2].astype(np.float32) / 255.0, "surface": mm[..., 1].astype(np.float32) / 255.0,
                    "bg": bg, "img": img}
    # the models are shown the art only: inside the border, below the name bar, above the rule
    # box; shown the whole card, they select the card or the art panel itself
    ix, it, ib = int(round(w * (frame_width + 0.035))), int(round(h * 0.11)), int(round(h * 0.10))
    matte = np.zeros((h, w), np.float32)
    matte[it:h - ib, ix:w - ix] = subject_matte(img[it:h - ib, ix:w - ix])
    fm = frame_mask(h, w, frame_width)
    surface = np.clip(surface_mask(img), 0, 1)
    matte = np.clip(matte * (1 - fm), 0, 1)        # text stays on the surface in the shader instead
    # the background with the subject removed, filled from around it, so parallax reveals art
    # the subject and the printed text both come out of the backdrop, so neither is seen twice
    # when the backdrop slides behind them
    hole = (cv2.dilate(((matte > 0.08) | (surface > 0.3)).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
            ).astype(np.uint8)
    small = 512 / max(h, w)
    sm_img = cv2.resize(img, (int(w * small), int(h * small)), interpolation=cv2.INTER_AREA)
    sm_hole = cv2.resize(hole, (sm_img.shape[1], sm_img.shape[0]), interpolation=cv2.INTER_NEAREST)
    filled = cv2.inpaint(sm_img, sm_hole, 9, cv2.INPAINT_TELEA)
    filled = cv2.GaussianBlur(filled, (0, 0), 2.0)
    filled = cv2.resize(filled, (w, h), interpolation=cv2.INTER_CUBIC)
    soft = cv2.GaussianBlur(hole.astype(np.float32), (0, 0), 6)[..., None]
    bg = (img * (1 - soft) + filled * soft).astype(np.uint8)
    cv2.imwrite(cm, (np.dstack([np.zeros_like(matte), surface, matte]) * 255).astype(np.uint8))
    cv2.imwrite(cb, bg, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return {"matte": matte, "surface": surface, "bg": bg, "img": img}


# ---------------------------------------------------------------- your own layers
ROLES = {
    "subject": ("subject", "foreground", "fg", "character", "pokemon", "hero"),
    "frame": ("frame", "border", "surface", "overlay", "text", "card"),
    "backdrop": ("backdrop", "background", "bg", "back_art", "scene", "art"),
}
CANVAS = 2048          # the long side the layers are put together at (enough for 4K video)


def _role_of(fname: str):
    stem = os.path.splitext(fname)[0].lower().replace("-", "_").replace(" ", "_")
    parts = set(stem.split("_")) | {stem}
    for role, words in ROLES.items():
        if any(w in parts or stem.endswith(w) for w in words):
            return role
    return None


def find_layer_files(folder: str) -> dict:
    """Every PNG in a folder by role: {'frame': [card.png, border.png], 'subject': [...], 'backdrop': [...]}.
    Several frame files are stacked (a card face and its border, say), in name order."""
    out = {}
    try:
        files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".png") and not f.startswith("."))
    except OSError:
        return out
    for f in files:
        r = _role_of(f)
        if r:
            out.setdefault(r, []).append(os.path.join(folder, f))
    return out


def find_pngs(folder: str) -> dict:
    """The first PNG for each role (what older callers want)."""
    return {r: v[0] for r, v in find_layer_files(folder).items()}


_CACHE: dict = {}
_FRAME_CACHE: dict = {}


def _load(p: str) -> np.ndarray:
    """A PNG as 8-bit BGRA, at most twice the canvas size, kept while the file is unchanged
    (the arrange sliders rebuild the layers many times; your PNGs are read once)."""
    import cv2
    key = (p, os.path.getmtime(p))
    if key in _CACHE:
        return _CACHE[key]
    im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
    if im is None:
        raise ValueError(f"Could not read {os.path.basename(p)}")
    if im.dtype != np.uint8:
        im = (im // 257).astype(np.uint8)
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    elif im.shape[2] == 3:
        im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
    k = min(1.0, 2 * CANVAS / max(im.shape[:2]))
    if k < 1:
        im = cv2.resize(im, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    for old in [x for x in _CACHE if x[0] == p]:
        _CACHE.pop(old, None)
    _CACHE[key] = (im, k)
    return _CACHE[key]


def _bbox(alpha: np.ndarray, thr: int = 8):
    """Where a layer's picture is: the bounds of its biggest solid piece, so stray specks and dust
    left around a cut-out (common on scanned borders) do not stretch or shift it."""
    import cv2
    m = (alpha > max(thr, 96)).astype(np.uint8)
    if not m.any():
        return 0, 0, alpha.shape[1], alpha.shape[0]
    k = max(1, int(round(min(alpha.shape) / 1500)))
    if k > 1:
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        ys, xs = np.nonzero(alpha > thr)
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = st[i, 0], st[i, 1], st[i, 2], st[i, 3]
    # keep any other big pieces that touch that box (a card face can be several solid parts)
    x0, y0, x1, y1 = x, y, x + w, y + h
    for j in range(1, n):
        if j != i and st[j, cv2.CC_STAT_AREA] > 0.01 * st[i, cv2.CC_STAT_AREA]:
            jx, jy, jw, jh = st[j, :4]
            x0, y0, x1, y1 = min(x0, jx), min(y0, jy), max(x1, jx + jw), max(y1, jy + jh)
    return int(x0), int(y0), int(x1), int(y1)


def _window(alpha: np.ndarray):
    """The art window: the biggest transparent area inside the frame (not touching its edge)."""
    import cv2
    hole = (alpha < 128).astype(np.uint8)
    n, lab, st, _c = cv2.connectedComponentsWithStats(hole, 8)
    h, w = alpha.shape
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if x == 0 or y == 0 or x + bw >= w or y + bh >= h:
            continue                                # the transparent corners outside the card
        if area > 0.04 * w * h and (best is None or area > best[4]):
            best = (x, y, bw, bh, area)
    if best is None:
        return 0, 0, w, h
    x, y, bw, bh, _a = best
    return int(x), int(y), int(x + bw), int(y + bh)


DEFAULT_FIT = {"subject": (1.0, 0.0, 0.0), "backdrop": (1.0, 0.0, 0.0)}   # frame files are keyed by file name
MAX_STACK = 6                   # layer textures the shader takes, the backdrop not counted


def pinned(kind: str, a: np.ndarray) -> bool:
    """A frame that reaches the card's outer edge is the card itself: it stays on the surface, since
    sliding it would open a gap along the card's edge."""
    if kind != "frame":
        return False
    h, w = a.shape
    b = max(2, int(min(h, w) * 0.015))
    rim = np.concatenate([a[:b].ravel(), a[-b:].ravel(), a[:, :b].ravel(), a[:, -b:].ravel()])
    return float(rim.mean()) > 0.8


def default_depths(stack) -> dict:
    """How deep each layer sits, 1 being the backdrop and 0 the card's surface: the loose layers
    spread out from just in front of the backdrop to floating above the surface, in stack order, so
    each one slides at its own speed as the card turns."""
    loose = [n for n, k, _rgb, a in stack if not (n == "edge" or pinned(k, a))]
    m = len(loose)
    out = {n: 0.0 for n, *_ in stack}
    for r, n in enumerate(loose):
        out[n] = round(1.0 - 1.55 * (r + 1) / m, 3)
    return out


def parallax_stack(stack, depths=None) -> list:
    """The layers over the backdrop, bottom to top, each as BGRA with its depth, for the shader.
    More than it can take and the lowest ones are merged, keeping the depth of the upper."""
    d = {**default_depths(stack), **{k: float(v) for k, v in (depths or {}).items()}}
    items = [[n, k, rgb.astype(np.float32), a.astype(np.float32), d.get(n, 0.0)] for n, k, rgb, a in stack]
    while len(items) > MAX_STACK:
        lo, hi = items[0], items[1]
        ah = hi[3][..., None]
        a = hi[3] + lo[3] * (1 - hi[3])
        rgb = (hi[2] * ah + lo[2] * lo[3][..., None] * (1 - ah)) / np.maximum(a[..., None], 1e-4)
        items[:2] = [[hi[0], hi[1], rgb, a, hi[4]]]
    out = []
    for n, k, rgb, a, dep in items:
        bgra = np.dstack([np.clip(rgb, 0, 255), np.clip(a * 255, 0, 255)]).astype(np.uint8)
        out.append({"name": n, "kind": k, "depth": dep, "bgra": bgra})
    return out


def from_pngs(folder: str, fit: dict | None = None, size: int = CANVAS, order: list | None = None,
              depths: dict | None = None) -> dict:
    """Layers from your own PNGs: the backdrop at the back, the subject over it, the frame on top.

    The frame sets the card: its opaque area is the card, and the biggest transparent area inside it
    is the art window. A backdrop of any size is fitted to fill the window (and continued past it,
    so parallax never shows an edge); a subject of any size is fitted inside the window, standing on
    its bottom edge. fit = {role: (scale, dx, dy)} then sizes and moves each, dx and dy in fractions of
    the window. PNGs made on the frame's own canvas (the same size as the frame file) stay exactly
    where they were drawn. Any layer can be missing."""
    import cv2
    files = find_layer_files(folder)
    if not files:
        raise ValueError("No PNG named subject, frame or backdrop in that folder.")
    fit = {**DEFAULT_FIT, **(fit or {})}
    frames = [_load(p) for p in files.get("frame", [])]
    fkey = (tuple((p, os.path.getmtime(p)) for p in files.get("frame", [])), size)
    if fkey in _FRAME_CACHE:
        (f0, k0, x0, y0, s, W, H) = _FRAME_CACHE[fkey][:7]
    else:
        # the card: the first frame's opaque area, at the canvas size
        if frames:
            f0, k0 = frames[0]
            x0, y0, x1, y1 = _bbox(f0[..., 3])
            cw, ch = x1 - x0, y1 - y0
        else:
            f0, k0, x0, y0, cw, ch = None, 1.0, 0, 0, 1260, 1760
        s = size / max(cw, ch)
        W, H = max(8, int(round(cw * s))), max(8, int(round(ch * s)))

    def on_canvas(im, kk, ref_shape, k_ref):
        """A layer drawn on the frame's own canvas: the same crop and scale as the frame."""
        M = np.float32([[s * k_ref / kk, 0, -x0 * s], [0, s * k_ref / kk, -y0 * s]])
        return cv2.warpAffine(im, M, (W, H), flags=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))

    def same_canvas(im, kk):
        if f0 is None:
            return False
        a = (im.shape[1] / kk, im.shape[0] / kk)
        b = (f0.shape[1] / k0, f0.shape[0] / k0)
        return abs(a[0] - b[0]) <= 0.01 * b[0] and abs(a[1] - b[1]) <= 0.01 * b[1]

    if fkey not in _FRAME_CACHE:
        flayers = []                                   # each frame file on the card canvas
        allv = np.zeros((H, W), np.float32)
        for p, (im, kk) in zip(files.get("frame", []), frames):
            if same_canvas(im, kk):
                c = on_canvas(im, kk, None, k0)
            else:                                      # a frame of its own size: stretched to the card
                bx0, by0, bx1, by1 = _bbox(im[..., 3])
                c = cv2.resize(im[by0:by1, bx0:bx1], (W, H), interpolation=cv2.INTER_AREA)
            a = c[..., 3].astype(np.float32) / 255
            flayers.append((os.path.basename(p), c[..., :3].astype(np.float32), a))
            allv = np.maximum(allv, a)
        win = _window((allv * 255).astype(np.uint8)) if frames else (0, 0, W, H)
        edge_rgb, edge_a = np.zeros((H, W, 3), np.float32), np.zeros((H, W), np.float32)
        if frames:
            # outside the card's rounded corners: the frame's own edge colour, so no art shows there
            outside = (allv < 0.5).astype(np.uint8)
            n, lab, st, _c = cv2.connectedComponentsWithStats(outside, 8)
            edge = np.zeros_like(outside)
            for i in range(1, n):
                x, y, bw, bh, _ar = st[i]
                if x == 0 or y == 0 or x + bw >= W or y + bh >= H:
                    edge[lab == i] = 1
            if edge.any():
                src = np.zeros((H, W, 3), np.float32)
                for _n, rgb, a in flayers:
                    src = src * (1 - a[..., None]) + rgb * a[..., None]
                edge_rgb = cv2.inpaint(np.clip(src, 0, 255).astype(np.uint8), edge, 5,
                                       cv2.INPAINT_TELEA).astype(np.float32)
                edge_a = edge.astype(np.float32)
        while len(_FRAME_CACHE) >= 3:             # the preview size and the full size, kept together
            _FRAME_CACHE.pop(next(iter(_FRAME_CACHE)))
        _FRAME_CACHE[fkey] = (f0, k0, x0, y0, s, W, H, flayers, edge_rgb, edge_a, win)
    (f0, k0, x0, y0, s, W, H, flayers, edge_rgb, edge_a, win) = _FRAME_CACHE[fkey]
    wx0, wy0, wx1, wy1 = win
    ww, wh = wx1 - wx0, wy1 - wy0

    def placed(im, kk, role):
        if same_canvas(im, kk):
            c = on_canvas(im, kk, None, k0)
            sc, dx, dy = fit[role]
            if (sc, dx, dy) == (1.0, 0.0, 0.0):
                return c
            M = cv2.getRotationMatrix2D((W / 2, H / 2), 0, sc)
            M[0, 2] += dx * ww
            M[1, 2] += dy * wh
            return cv2.warpAffine(c, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                  borderValue=(0, 0, 0, 0))
        sc, dx, dy = fit[role]
        if role == "backdrop":
            ih, iw = im.shape[:2]
            base = max(ww / iw, wh / ih)            # fill the window
            k = base * sc
            cx, cy = wx0 + ww / 2 + dx * ww, wy0 + wh / 2 + dy * wh
            M = np.float32([[k, 0, cx - iw * k / 2], [0, k, cy - ih * k / 2]])
            # continued past its edges, so a deep parallax never reveals the end of the picture
            return cv2.warpAffine(im, M, (W, H), flags=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_REFLECT)
        bx0, by0, bx1, by1 = _bbox(im[..., 3])
        bw_, bh_ = bx1 - bx0, by1 - by0
        base = min(0.92 * wh / bh_, 0.96 * ww / bw_)    # fits the window, standing on its bottom
        k = base * sc
        cx = wx0 + ww / 2 + dx * ww
        bottom = wy1 + dy * wh
        M = np.float32([[k, 0, cx - (bx0 + bw_ / 2) * k], [0, k, bottom - by1 * k]])
        return cv2.warpAffine(im, M, (W, H), flags=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))

    def layer(role):
        ps = files.get(role, [])
        if not ps:
            return None
        im, kk = _load(ps[0])
        return placed(im, kk, role)

    bgl, sbl = layer("backdrop"), layer("subject")
    sub = sbl[..., :3].astype(np.float32) if sbl is not None else np.zeros((H, W, 3), np.float32)
    sa = sbl[..., 3].astype(np.float32) / 255 if sbl is not None else np.zeros((H, W), np.float32)
    if bgl is not None:
        bg = bgl[..., :3].astype(np.float32)
    else:                                           # no backdrop: the subject's surroundings, blurred
        bg = cv2.GaussianBlur(sub, (0, 0), 25)
    art = bg * (1 - sa[..., None]) + sub * sa[..., None]
    # the stack, top to bottom: your order when you set one, else the subject under every frame
    # with later frame files on top; the backdrop is always at the bottom
    names = [n for n, _r, _a in flayers]
    order = [x for x in (order or []) if x == "subject" or x in names]
    order += [n for n in reversed(names) if n not in order]
    if "subject" not in order:
        order.append("subject")
    face, frames_img = bg.copy(), bg.copy()
    above, below = np.zeros((H, W), np.float32), np.zeros((H, W), np.float32)
    seen_subject = False
    stack = []                                      # bottom to top: (name, kind, rgb, alpha) for parallax
    for item in reversed(order):                    # bottom to top
        if item == "subject":
            face = face * (1 - sa[..., None]) + sub * sa[..., None]
            seen_subject = True
            if sbl is not None:
                stack.append(("subject", "subject", sub, sa))
            continue
        _n, rgb, a = next(t for t in flayers if t[0] == item)
        sc, dx, dy = fit.get(item, (1.0, 0.0, 0.0))
        if (sc, dx, dy) != (1.0, 0.0, 0.0):
            # a frame file moved or sized by hand: around the card's centre, dx and dy in card widths
            M = cv2.getRotationMatrix2D((W / 2, H / 2), 0, sc)
            M[0, 2] += dx * W
            M[1, 2] += dy * H
            rgb = cv2.warpAffine(rgb, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            a = cv2.warpAffine(a, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        face = face * (1 - a[..., None]) + rgb * a[..., None]
        frames_img = frames_img * (1 - a[..., None]) + rgb * a[..., None]
        stack.append((item, "frame", rgb, a))
        if seen_subject:
            above = np.maximum(above, a)
        else:
            below = np.maximum(below, a)
    face = face * (1 - edge_a[..., None]) + edge_rgb * edge_a[..., None]
    frames_img = frames_img * (1 - edge_a[..., None]) + edge_rgb * edge_a[..., None]
    above = np.maximum(above, edge_a)
    if edge_a.any():
        stack.append(("edge", "frame", edge_rgb, edge_a))
    found = {r: os.path.basename(v[0]) if len(v) == 1 else ", ".join(os.path.basename(x) for x in v)
             for r, v in files.items()}
    return {"matte": sa, "surface": above, "surface_below": below, "bg": bg.astype(np.uint8),
            "art": art.astype(np.uint8), "frames": frames_img.astype(np.uint8), "img": face.astype(np.uint8),
            "manual": True, "files": found, "window": win, "order": order,
            "stack": parallax_stack(stack, depths),
            "frame_names": names,
            # the card's own shape: transparent outside its rounded corners, for flat previews
            "shape": ((1 - edge_a) * 255).astype(np.uint8),
            "aligned": {r: same_canvas(*_load(v[0])) for r, v in files.items() if r != "frame"}}
