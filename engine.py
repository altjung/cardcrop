"""Card detection, perspective correction and corner cropping.

Everything here is deterministic OpenCV, so it runs offline, costs nothing
per image, and gives the same answer twice.
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field

import cv2
import numpy as np

# Standard trading card (Pokemon, MTG, sports) is 63 x 88 mm.
CARD_RATIO = 63.0 / 88.0


# ---------------------------------------------------------------- settings
# Output formats. Everything except "jpg" is lossless.
FORMATS = {
    "png":    ("PNG  lossless 8-bit", ".png"),
    "png16":  ("PNG  lossless 16-bit", ".png"),
    "png32":  ("PNG  32-bit, 8-bit + transparency", ".png"),
    "png64":  ("PNG  64-bit, 16-bit + transparency", ".png"),
    "tiff16": ("TIFF lossless 16-bit", ".tif"),
    "tiff32": ("TIFF 32-bit float", ".tif"),
    "jpg":    ("JPEG max quality 4:4:4", ".jpg"),
}

EDIT_KEYS = ("exposure", "contrast", "highlights", "shadows", "saturation", "warmth", "sharpen")

RAW_EXTS = {".arw", ".srf", ".sr2", ".cr2", ".cr3", ".nef", ".raf", ".rw2", ".orf", ".dng"}


@dataclass
class Settings:
    lens_k1: float = 0.0          # barrel (+) / pincushion (-) correction
    lens_profile: str = ""        # key into LENS_PROFILES, applied before lens_k1
    lens_raw_only: bool = True    # camera JPEGs are usually corrected in-camera already
    lens_fit: str = ""            # JSON of a distortion measured from your own shots (lens_profile "measured")
    flatten: bool = True          # follow each side's own curve, so a curled card comes out with straight sides
    corner_frac: float = 0.30     # corner crop side as a fraction of card width
    corner_px: int = 1600         # corner output size; 0 keeps native pixels
    lock_ratio: bool = True       # force 63x88 output instead of measured shape
    out_long_edge: int = 0        # 0 = native resolution
    corners: bool = True          # write the four corner close-ups with each side
    ig: bool = False              # Instagram carousel for named fronts (the app turns this on)
    ig_crop: tuple = (0.0, 0.10, 1.0)   # default close-up: left, top, width as card fractions
    margin_px: int = 20           # extra photo kept outside the detected edge, all sides
    auto_portrait: bool = True    # a card shot sideways comes out upright
    hero: bool = True             # write a front + back first photo for named cards
    grade: bool = False           # measure condition at export (off: reports are made on request)
    hero_bg: str = "light"
    hero_sides: str = "both"        # the hero shows: "both" sides, the "front" alone or the "back" alone
    # tone and detail edits, all 0 = untouched; ranges are -1..1 (sharpen 0..1)
    exposure: float = 0.0         # 1.0 = +2 stops; the slider runs -2.5..2.5, i.e. +-5 EV
    contrast: float = 0.0
    highlights: float = 0.0
    shadows: float = 0.0
    saturation: float = 0.0
    warmth: float = 0.0
    sharpen: float = 0.0
    # lens detail: deconvolution that undoes the lens's and the sensor's own blur at export
    # (0 off, 1 strong); separate from the tone edits, so it never counts as an edit
    detail: float = 0.5

    def has_edits(self) -> bool:
        return any(abs(getattr(self, k)) > 1e-4 for k in EDIT_KEYS)
    out_format: str = "png"
    corner_names: tuple = ("TL", "TR", "BL", "BR")   # reading order: top row, then bottom row


# ---------------------------------------------------------------- io
def _read_raw(path: str) -> np.ndarray:
    """Sony .ARW and other camera RAW files, demosaiced by LibRaw at 16 bits."""
    import rawpy
    with rawpy.imread(path) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,      # the white balance you shot with
            output_bps=16,           # keep the full bit depth through the warp
            no_auto_bright=True,     # auto-bright lifts the whole frame when a card sits on a dark mat
            bright=1.0,
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
            output_color=rawpy.ColorSpace.sRGB,
            # a blown foil highlight is rebuilt from the channels that did not clip, so it fades to
            # white like real shine instead of turning flat or pink
            highlight_mode=rawpy.HighlightMode.Blend,
        )                            # LibRaw applies the camera's rotation flag
    return raw_finish(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def raw_finish(img: np.ndarray, amount: float = 0.45, radius: float = 0.8) -> np.ndarray:
    """What a raw converter does by default and LibRaw does not: capture sharpening on brightness
    only (the softness the sensor's filters add, not a look), and the false-colour speckle that
    demosaicing leaves on fine print cleaned from the colour channels. Tested on a real a6700 shot:
    colour speckle on print edges down about 45%, no change to brightness detail. 16-bit throughout,
    about half a second for a 26 MP photo."""
    ycc = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    y, cr, cb = cv2.split(ycc)
    cr, cb = cv2.medianBlur(cr, 3), cv2.medianBlur(cb, 3)
    y = cv2.addWeighted(y, 1 + amount, cv2.GaussianBlur(y, (0, 0), radius), -amount, 0)
    return cv2.cvtColor(cv2.merge([y, cr, cb]), cv2.COLOR_YCrCb2BGR)


def imread(path: str) -> np.ndarray:
    """Read JPEG/PNG/TIFF/WebP, HEIC, or camera RAW. May return uint8 or uint16."""
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS:
        return _read_raw(path)
    data = np.fromfile(path, dtype=np.uint8)
    # ANYDEPTH keeps 16-bit PNG/TIFF at 16 bits; EXIF orientation is still applied
    img = cv2.imdecode(data, cv2.IMREAD_COLOR | cv2.IMREAD_ANYDEPTH)
    if img is None and ext in (".heic", ".heif"):
        try:  # iPhone photos
            from PIL import Image, ImageOps
            import pillow_heif
            pillow_heif.register_heif_opener()
            pil = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            img = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        except Exception:
            img = None
    if img is None:
        raise ValueError(f"Could not read image: {path}")
    return img


def to_float(img: np.ndarray) -> np.ndarray:
    """0..1 float32 from any supported depth."""
    if img.dtype == np.uint8:
        return img.astype(np.float32) / 255.0
    if img.dtype == np.uint16:
        return img.astype(np.float32) / 65535.0
    return img.astype(np.float32)


def to8(img: np.ndarray) -> np.ndarray:
    if img.dtype == np.uint8:
        return img
    if img.dtype == np.uint16:
        return (img >> 8).astype(np.uint8)
    return (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)


def to16(img: np.ndarray) -> np.ndarray:
    if img.dtype == np.uint16:
        return img
    if img.dtype == np.uint8:
        return img.astype(np.uint16) * 257          # 0..255 -> 0..65535 exactly
    return (np.clip(img, 0, 1) * 65535 + 0.5).astype(np.uint16)


ALPHA_FORMATS = ("png32", "png64")      # RGBA: 8 or 16 bits a channel, 32 or 64 a pixel


def with_alpha(img: np.ndarray, alpha=None) -> np.ndarray:
    """BGRA at the image's depth: alpha 0..1 float (transparent to opaque), or fully opaque without one."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return img
    top = 65535 if img.dtype == np.uint16 else 255
    a = (np.full(img.shape[:2], top, img.dtype) if alpha is None
         else (np.clip(alpha, 0, 1) * top + 0.5).astype(img.dtype))
    return np.dstack([img, a])


def card_alpha(card: np.ndarray, m: int) -> np.ndarray:
    """Transparency for a flattened card with an m-pixel band of the photo around it: the band and
    the corners past the card's own rounding are clear, the card opaque with an anti-aliased edge."""
    h, w = card.shape[:2]
    a = np.zeros((h, w), np.float32)
    core = card[m:h - m, m:w - m] if m else card
    ch, cw = core.shape[:2]
    a[m:m + ch, m:m + cw] = _rounded_mask(ch, cw, corner_frac(core))
    return a


def imwrite(path: str, img: np.ndarray, fmt: str = "png", alpha=None) -> None:
    if fmt == "jpg":
        img = to8(img)
        params = [cv2.IMWRITE_JPEG_QUALITY, 100,
                  # no chroma subsampling: colour edges and holo stay crisp
                  cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444,
                  cv2.IMWRITE_JPEG_OPTIMIZE, 1]
        ext = ".jpg"
    elif fmt == "png":
        img, params, ext = to8(img), [cv2.IMWRITE_PNG_COMPRESSION, 3], ".png"
    elif fmt == "png16":
        img, params, ext = to16(img), [cv2.IMWRITE_PNG_COMPRESSION, 3], ".png"
    elif fmt == "png32":
        img, params, ext = with_alpha(to8(img), alpha), [cv2.IMWRITE_PNG_COMPRESSION, 3], ".png"
    elif fmt == "png64":
        img, params, ext = with_alpha(to16(img), alpha), [cv2.IMWRITE_PNG_COMPRESSION, 3], ".png"
    elif fmt == "tiff16":
        # LZW is lossless; keeps 16-bit files a reasonable size
        img, params, ext = to16(img), [cv2.IMWRITE_TIFF_COMPRESSION, 5], ".tif"
    elif fmt == "tiff32":
        # float 0..1, uncompressed; opens as 32 bpc in Photoshop and Lightroom
        img, params, ext = to_float(img), [cv2.IMWRITE_TIFF_COMPRESSION, 1], ".tif"
    else:
        raise ValueError(fmt)
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        raise ValueError(f"Could not encode {path}")
    buf.tofile(path)


# ---------------------------------------------------------------- lens
# Measured profiles from the Lensfun database (lensfun.github.io), Hugin
# coordinates: r = 1 is half the image's shorter side. "ptlens" distortion maps
# a corrected radius to the radius in the photo; "tca" moves red and blue onto
# green (lateral chromatic aberration). Calibrated at the lens's focal length on
# a 1.534 crop (APS-C) sensor, which is what the a6700 is.
LENS_PROFILES = {
    "sel30m35": dict(name="Sony E 30mm F3.5 Macro (SEL30M35)",
                     a=0.00105, b=-0.00352, c=0.00057,
                     tca=dict(br=-0.0000797, vr=1.0005827, bb=0.0000655, vb=0.9997635)),
}


def _fit_dict(fit) -> dict | None:
    if isinstance(fit, dict):
        return fit
    try:
        return json.loads(fit) if fit else None
    except ValueError:
        return None


def lens_correct(img: np.ndarray, key: str, fit=None) -> np.ndarray:
    """Apply a measured lens profile: distortion, then lateral colour fringing. With a fit measured from
    your own shots (key "measured"), its distortion replaces the profile's and the base profile's colour
    fringing still applies."""
    fit = _fit_dict(fit) if key == "measured" else None
    if key == "measured" and not fit:
        return img
    p = LENS_PROFILES.get(fit.get("base", "") if fit else (key or ""))
    if p is None and fit is None:
        return img
    p = p or dict(a=0.0, b=0.0, c=0.0, tca=None)
    h, w = img.shape[:2]
    cx, cy, R = (w - 1) / 2.0, (h - 1) / 2.0, min(w, h) / 2.0
    a, b, c = p["a"], p["b"], p["c"]
    d = 1.0 - a - b - c
    tca = p.get("tca")
    colour = img.ndim == 3 and img.shape[2] >= 3 and tca is not None
    out = np.empty_like(img)
    chans = [np.ascontiguousarray(img[:, :, i]) for i in range(3)] if colour else None
    xs = (np.arange(w, dtype=np.float32) - cx) / R
    band = 256                                   # rows at a time keeps 24 MP RAWs in a few hundred MB
    for y0 in range(0, h, band):
        y1 = min(h, y0 + band)
        ys = ((np.arange(y0, y1, dtype=np.float32) - cy) / R)[:, None]
        x = np.broadcast_to(xs[None, :], (y1 - y0, w))
        if fit:
            xd, yd = _fit_distort(x, ys, fit["k1"], fit["k2"])
        else:
            r = np.sqrt(x * x + ys * ys)
            f = ((a * r + b) * r + c) * r + d
            xd, yd = x * f, ys * f
        if not colour:
            out[y0:y1] = cv2.remap(img, (xd * R + cx).astype(np.float32), (yd * R + cy).astype(np.float32),
                                   cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            continue
        rd2 = xd * xd + yd * yd
        for ch, k in ((1, 1.0), (2, tca["br"] * rd2 + tca["vr"]), (0, tca["bb"] * rd2 + tca["vb"])):
            mx = (xd * k * R + cx).astype(np.float32)
            my = (yd * k * R + cy).astype(np.float32)
            # the shifts are a few pixels at most, so cubic is as sharp as Lanczos here
            out[y0:y1, :, ch] = cv2.remap(chans[ch], mx, my, cv2.INTER_CUBIC,
                                          borderMode=cv2.BORDER_REPLICATE)
        for ch in range(3, img.shape[2]):
            out[y0:y1, :, ch] = cv2.remap(img[:, :, ch], (xd * R + cx).astype(np.float32),
                                          (yd * R + cy).astype(np.float32), cv2.INTER_LINEAR)
    return out


def correct_lens(img: np.ndarray, path: str, s: "Settings") -> np.ndarray:
    """The full lens pipeline for one file: profile (if it applies), then the manual slider. A measured
    fit applies to the kind of file it was measured on (RAW or the camera's JPEGs), since the camera may
    already have corrected its JPEGs."""
    raw = os.path.splitext(path)[1].lower() in RAW_EXTS
    if s.lens_profile == "measured":
        fit = _fit_dict(getattr(s, "lens_fit", ""))
        if fit and (fit.get("kind") == "raw") == raw:
            img = lens_correct(img, "measured", fit)
    elif s.lens_profile and (not s.lens_raw_only or raw):
        img = lens_correct(img, s.lens_profile)
    return undistort(img, s.lens_k1)


# ---------------------------------------------------------------- lens, measured from your own shots
# Lensfun calibrates at infinity focus; a macro lens a few inches from a card distorts differently. A card's
# four sides are straight, so the photo's own bowing of them measures the lens at the distance you shoot.
# Model, in Hugin's coordinates (r = 1 is half the shorter side): a point in the photo p_d sits at
# p_u = p_d (1 + k1 r_d^2 + k2 r_d^4) once straightened.
def _fit_distort(xu, yu, k1, k2, iters=4):
    """Where a straightened point sits in the photo: the model inverted by fixed-point iteration."""
    xd, yd = xu, yu
    for _ in range(iters):
        r2 = xd * xd + yd * yd
        g = 1 + k1 * r2 + k2 * r2 * r2
        xd, yd = xu / g, yu / g
    return xd, yd


def _subpixel_edge(gray: np.ndarray, a, b, n=64, reach=0.025):
    """Points on the true (possibly bowed) edge between corners a and b: across the side's middle stretch,
    the strongest step in brightness along a short line perpendicular to it, to a fraction of a pixel."""
    a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
    L = float(np.linalg.norm(b - a))
    if L < 60:
        return None
    u = (b - a) / L
    nrm = np.array([-u[1], u[0]], np.float32)
    half = max(6, int(reach * L))
    offs = np.arange(-half, half + 1, dtype=np.float32)
    pts = []
    for t in np.linspace(0.1, 0.9, n):            # past the rounded corners
        c = a + (b - a) * t
        xs = (c[0] + nrm[0] * offs).astype(np.float32)[None, :]
        ys = (c[1] + nrm[1] * offs).astype(np.float32)[None, :]
        prof = cv2.remap(gray, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[0].astype(np.float32)
        if prof.ndim == 2:                         # a colour picture: its channels averaged
            prof = prof[:, :3].mean(1)
        if gray.dtype == np.uint16:
            prof = prof * (255.0 / 65535.0)
        prof = cv2.GaussianBlur(prof[None, :], (0, 0), 1.2)[0]
        g = np.abs(np.diff(prof))
        i = int(np.argmax(g))
        if g[i] < 6 or i == 0 or i >= len(g) - 1:
            continue
        den = g[i - 1] - 2 * g[i] + g[i + 1]
        sub = 0.5 * (g[i - 1] - g[i + 1]) / den if abs(den) > 1e-6 else 0.0
        pts.append(c + nrm * (offs[i] + 0.5 + sub))
    return np.array(pts, np.float32) if len(pts) >= n // 2 else None


def edge_samples(img: np.ndarray) -> list[np.ndarray]:
    """The four sides of the card in one uncorrected photo, as point lists in Hugin coordinates."""
    q, conf = detect_card(img)
    if q is None or conf < 0.6:
        return []
    q = order_quad(q)
    g = cv2.cvtColor(to8(img)[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = g.shape
    cx, cy, R = (w - 1) / 2.0, (h - 1) / 2.0, min(w, h) / 2.0
    out = []
    for i in range(4):
        pts = _subpixel_edge(g, q[i], q[(i + 1) % 4])
        if pts is not None:
            out.append(np.c_[(pts[:, 0] - cx) / R, (pts[:, 1] - cy) / R])
    return out


def clean_sides(sides, R: float, limit_px: float = 1.0) -> list:
    """Sides whose points sit on a smooth curve to within a pixel: a sleeve, a holder or a shadow read as
    the edge scatters far more and would swamp the fit."""
    out = []
    for p in sides:
        c0 = p.mean(0)
        _, _, vt = np.linalg.svd(p - c0, full_matrices=False)
        u, r = (p - c0) @ vt[0], (p - c0) @ vt[1]
        if np.std(r - np.polyval(np.polyfit(u, r, 2), u)) * R < limit_px:
            out.append(p)
    return out


def _line_resid(sides, k1, k2) -> np.ndarray:
    """Each straightened edge point's distance from its side's best line, in photo units (divided by the
    local stretch, so a model cannot look better by simply shrinking the picture)."""
    res = []
    for p in sides:
        r2 = (p * p).sum(1)
        g = 1 + k1 * r2 + k2 * r2 * r2
        u = p * g[:, None]
        c = u.mean(0)
        _, _, vt = np.linalg.svd(u - c, full_matrices=False)
        res.append(((u - c) @ vt[1]) / g)
    return np.concatenate(res)


def _line_rms(sides, k1, k2) -> float:
    r = _line_resid(sides, k1, k2)
    return float(np.sqrt((r * r).mean()))


def fit_distortion(sides: list[np.ndarray], iters: int = 25) -> dict:
    """k1, k2 that straighten every card edge given: Gauss-Newton on the points' distances from their
    sides' lines, each line refitted at every step so it cannot soak up the bow."""
    sides = [p for p in sides if p is not None and len(p) >= 8]
    if len(sides) < 8:
        return {"ok": False, "error": "Not enough card edges: shoot or load at least a few cards"}
    # cards kept near the middle cannot tell the fourth-power term from the second: fit k1 alone then
    reach = float(max(np.sqrt((p * p).sum(1)).max() for p in sides))
    npar = 2 if reach >= 0.7 else 1
    k = np.zeros(2)
    h = 1e-4
    for _ in range(iters):
        r0 = _line_resid(sides, *k)
        J = np.empty((len(r0), npar))
        for i in range(npar):
            e = np.zeros(2)
            e[i] = h
            J[:, i] = (_line_resid(sides, *(k + e)) - _line_resid(sides, *(k - e))) / (2 * h)
        step, *_ = np.linalg.lstsq(J, -r0, rcond=None)
        k[:npar] += step
        if np.abs(step).max() < 1e-7:
            break
    before, after = _line_rms(sides, 0, 0), _line_rms(sides, *k)
    if after > before:                               # never hand back something worse than nothing
        k[:] = 0
        after = before
    return {"ok": True, "k1": float(k[0]), "k2": float(k[1]), "rms_before": before, "rms_after": after,
            "reach": reach, "sides": len(sides)}


def undistort(img: np.ndarray, k1: float) -> np.ndarray:
    """Radial lens correction with a synthetic camera matrix.

    Phone main cameras are already corrected, so this mostly matters for
    wide/ultrawide lenses or shooting very close.
    """
    if abs(k1) < 1e-6:
        return img
    h, w = img.shape[:2]
    f = max(h, w)
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], dtype=np.float64)
    dist = np.array([-k1, 0, 0, 0, 0], dtype=np.float64)
    return cv2.undistort(img, K, dist)


# ---------------------------------------------------------------- geometry
def order_quad(pts: np.ndarray) -> np.ndarray:
    """Return points ordered TL, TR, BR, BL."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]          # clockwise in image coords, starting near -pi
    # rotate so the point with smallest x+y is first
    start = int(np.argmin(pts.sum(axis=1)))
    return np.roll(pts, -start, axis=0)


def _line_intersect(l1, l2):
    (vx1, vy1, x1, y1), (vx2, vy2, x2, y2) = l1, l2
    A = np.array([[vx1, -vx2], [vy1, -vy2]], dtype=np.float64)
    if abs(np.linalg.det(A)) < 1e-9:
        return None
    t = np.linalg.solve(A, np.array([x2 - x1, y2 - y1], dtype=np.float64))
    return np.array([x1 + t[0] * vx1, y1 + t[0] * vy1], dtype=np.float32)


def _refine_with_edges(contour: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Fit a straight line to each side of the contour and intersect them.

    Cards have rounded corners, so polygon approximation lands slightly
    inside the true corner. Fitting the straight runs of each edge and
    intersecting recovers the sharp virtual corner that defines the
    rectangle, which is what the perspective warp needs.
    """
    cnt = contour.reshape(-1, 2).astype(np.float32)
    lines = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        ab = b - a
        L = float(np.linalg.norm(ab))
        if L < 1:
            return quad
        u = ab / L
        n = np.array([-u[1], u[0]])
        rel = cnt - a
        t = rel @ u
        d = np.abs(rel @ n)
        # middle 70% of the edge, close to the side line: skips the rounded corners
        m = (t > 0.15 * L) & (t < 0.85 * L) & (d < max(4.0, 0.03 * L))
        pts = cnt[m]
        if len(pts) < 10:
            return quad
        lines.append(cv2.fitLine(pts, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel())
    out = []
    for i in range(4):
        p = _line_intersect(lines[(i - 1) % 4], lines[i])
        if p is None:
            return quad
        out.append(p)
    out = np.array(out, dtype=np.float32)
    # sanity: refined corners should not wander far from the rough ones
    span = float(np.linalg.norm(quad[0] - quad[2]))
    if np.max(np.linalg.norm(out - quad, axis=1)) > 0.08 * span:
        return quad
    return order_quad(out)


def _candidate_masks(small: np.ndarray):
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))

    # 1. edges
    v = float(np.median(blur))
    e = cv2.Canny(blur, int(max(0, 0.66 * v)), int(min(255, 1.33 * v)))
    for edges in (e, cv2.Canny(blur, 30, 90)):
        m = cv2.morphologyEx(cv2.dilate(edges, k, iterations=2), cv2.MORPH_CLOSE, k, iterations=3)
        # fill the outline, then erode back the thickness the dilation added
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(m)
        cv2.drawContours(filled, cnts, -1, 255, -1)
        yield cv2.erode(filled, k, iterations=2)

    # 2. Otsu on gray, both polarities (light card on dark mat and vice versa)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    for m in (th, 255 - th):
        yield cv2.morphologyEx(m, cv2.MORPH_OPEN, k, iterations=2)

    # 3. distance from the border colour: robust when card and mat differ in hue
    h, w = small.shape[:2]
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    border = np.concatenate([lab[:6].reshape(-1, 3), lab[-6:].reshape(-1, 3),
                             lab[:, :6].reshape(-1, 3), lab[:, -6:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(lab - bg, axis=2)
    dist = cv2.GaussianBlur(dist, (7, 7), 0)
    d8 = np.clip(dist * (255.0 / max(1.0, dist.max())), 0, 255).astype(np.uint8)
    _, th2 = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield cv2.morphologyEx(th2, cv2.MORPH_CLOSE, k, iterations=3)

    # 4. saturation (colourful card on neutral mat)
    _, ths = cv2.threshold(hsv[:, :, 1], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield cv2.morphologyEx(ths, cv2.MORPH_CLOSE, k, iterations=3)


class _Grad:
    """Per-channel Sobel gradients, sampled along arbitrary lines.

    Colour gradients matter: a blue card on brown wood can have almost the
    same brightness as the table and still have a hard hue edge.
    """

    def __init__(self, img8: np.ndarray):
        sm = cv2.GaussianBlur(img8, (3, 3), 0).astype(np.float32)
        self.gx = cv2.split(cv2.Sobel(sm, cv2.CV_32F, 1, 0, ksize=3))
        self.gy = cv2.split(cv2.Sobel(sm, cv2.CV_32F, 0, 1, ksize=3))
        self.h, self.w = img8.shape[:2]

    def across(self, pts: np.ndarray, n: np.ndarray) -> np.ndarray:
        """Gradient magnitude in direction n at points pts[..., 2]."""
        xs = np.clip(pts[..., 0], 0, self.w - 1).astype(np.float32)
        ys = np.clip(pts[..., 1], 0, self.h - 1).astype(np.float32)
        if xs.ndim == 1:
            xs, ys = xs[None, :], ys[None, :]
        g = np.zeros(xs.shape, np.float32)
        for gx, gy in zip(self.gx, self.gy):
            g += np.abs(cv2.remap(gx, xs, ys, cv2.INTER_LINEAR) * n[0]
                        + cv2.remap(gy, xs, ys, cv2.INTER_LINEAR) * n[1])
        return g.reshape(pts.shape[:-1])


EDGE_T = 40.0   # summed-channel Sobel response that counts as a real edge


def _edge_support(grad: _Grad, quad: np.ndarray, slop: float = 1.5) -> float:
    """Fraction of the outline that lies on a sharp edge (within +-slop px)."""
    hits = total = 0
    offs = np.arange(-slop, slop + 0.01, 0.5, dtype=np.float32)
    ts = np.linspace(0.1, 0.9, 60, dtype=np.float32)
    for i in range(4):
        a, b = quad[i].astype(np.float32), quad[(i + 1) % 4].astype(np.float32)
        ab = b - a
        L = float(np.linalg.norm(ab))
        if L < 2:
            return 0.0
        n = np.array([-ab[1], ab[0]], np.float32) / L
        pts = a + ts[:, None, None] * ab + offs[None, :, None] * n
        g = grad.across(pts, n).max(axis=1)
        hits += int((g > getattr(grad, "edge_t", EDGE_T)).sum())
        total += len(ts)
    return hits / total


def _score_quad(quad: np.ndarray, area_img: float, shape=None) -> float:
    area = cv2.contourArea(quad)
    if shape is not None:
        h, w = shape[:2]
        m = 0.004 * max(h, w)
        touching = sum(1 for x, y in quad if x < m or y < m or x > w - 1 - m or y > h - 1 - m)
        if touching >= 2:       # almost always the frame or the table, not a card
            return -1
    if area < 0.03 * area_img or area > 0.98 * area_img:
        return -1
    if not cv2.isContourConvex(quad.astype(np.int32)):
        return -1
    s = [np.linalg.norm(quad[i] - quad[(i + 1) % 4]) for i in range(4)]
    w, h = (s[0] + s[2]) / 2, (s[1] + s[3]) / 2
    r = min(w, h) / max(w, h)
    ratio_err = abs(r - CARD_RATIO)               # 0 for a perfect card
    opp = abs(s[0] - s[2]) / max(s[0], s[2]) + abs(s[1] - s[3]) / max(s[1], s[3])
    return (area / area_img) * (1.0 - min(1.0, ratio_err * 2.5)) * (1.0 - min(0.9, opp))


def _rough_candidates(small: np.ndarray):
    """Coarse quads from several segmentations of a ~1000 px preview."""
    area_img = small.shape[0] * small.shape[1]
    out = []
    for mask in _candidate_masks(small):
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:4]:
            if cv2.contourArea(c) < 0.03 * area_img:
                break
            hull = cv2.convexHull(c)
            peri = cv2.arcLength(hull, True)
            quad = None
            for eps in (0.01, 0.02, 0.03, 0.04, 0.06):
                ap = cv2.approxPolyDP(hull, eps * peri, True)
                if len(ap) == 4:
                    quad = order_quad(ap)
                    break
            if quad is None:
                quad = order_quad(cv2.boxPoints(cv2.minAreaRect(hull)))
            if _score_quad(quad, area_img, small.shape) <= 0:
                continue
            quad = _refine_with_edges(c, quad)
            diag = np.linalg.norm(quad[0] - quad[2])
            if any(np.abs(quad - q).max() < 0.01 * diag for q in out):
                continue
            out.append(quad)
    return out


def card_outline(W: int, H: int, fill: float = 0.7) -> np.ndarray:
    """A centred upright 63 x 88 outline, the starting point when nothing is found."""
    h = fill * H
    w = h * CARD_RATIO
    if w > fill * W:
        w = fill * W
        h = w / CARD_RATIO
    x0, y0 = (W - w) / 2, (H - h) / 2
    return np.array([[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]], dtype=np.float32)


class _MapGrad(_Grad):
    """_Grad over a single prepared map (here: colour distance from the background)."""

    def __init__(self, m: np.ndarray):
        sm = cv2.GaussianBlur(m.astype(np.float32), (3, 3), 0)
        self.gx = [cv2.Sobel(sm, cv2.CV_32F, 1, 0, ksize=3)]
        self.gy = [cv2.Sobel(sm, cv2.CV_32F, 0, 1, ksize=3)]
        self.h, self.w = m.shape[:2]
        self.edge_t = 15.0      # the map is clean, so a soft (slightly defocused) step still counts


def _background_distance(img8: np.ndarray) -> np.ndarray | None:
    """How far each pixel's colour is from the background, in Lab, scaled so a clear
    step reads like a strong edge. A navy card border on black is nearly invisible
    to brightness but stands well apart in colour. None when the frame of the photo
    is not one even colour (a busy background), where this would only add noise."""
    lab = cv2.cvtColor(img8, cv2.COLOR_BGR2LAB).astype(np.float32)
    H, W = lab.shape[:2]
    b = max(4, int(0.035 * min(H, W)))
    frame = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                            lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
    med = np.median(frame, axis=0)
    w = np.array([0.6, 1.0, 1.0], np.float32)   # the same weighting as below: a vignette's falloff is not texture
    spread = np.percentile(np.linalg.norm((frame - med) * w, axis=1), 90)
    if spread > 18:                       # textured or uneven background
        return None
    d = lab - med
    d[..., 0] *= 0.6                      # weigh colour above brightness: shadows are darker, not bluer
    dist = np.linalg.norm(d, axis=2)
    return np.clip(dist / max(6.0, spread * 2.5) * 60.0, 0, 255)


def _square_corners(q: np.ndarray, deg: float = 5.0) -> bool:
    """Every corner within deg of a right angle: the camera looks straight down, so a card's
    outline is close to a rectangle, while a quad stitched from unrelated edges is not."""
    for i in range(4):
        a, b, c = q[i - 1], q[i], q[(i + 1) % 4]
        u, v = a - b, c - b
        nu, nv = np.linalg.norm(u), np.linalg.norm(v)
        if nu < 1 or nv < 1:
            return False
        ang = np.degrees(np.arccos(np.clip(float(u @ v) / (nu * nv), -1, 1)))
        if abs(ang - 90.0) > deg:
            return False
    return True


def _card_shaped(q: np.ndarray, tol: float = 0.05) -> bool:
    w = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    h = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    if min(w, h) < 1:
        return False
    return abs(min(w, h) / max(w, h) - CARD_RATIO) <= tol


def _silhouette(img8: np.ndarray, small: np.ndarray, scale: float):
    """The card as everything that is not background, its four sides fitted to the silhouette's
    straight runs (rounded corners left out) and settled on the colour-distance map.
    Works on a 2000 px copy, where sensor noise on a black mat no longer reads as texture.
    Returns (quad in full-res pixels, support) or None."""
    H, W = img8.shape[:2]
    ms = min(1.0, 2000.0 / max(H, W))
    mid = cv2.resize(img8, (round(W * ms), round(H * ms)), interpolation=cv2.INTER_AREA) if ms < 1 else img8
    dm = _background_distance(mid)
    if dm is None:
        return None
    m = (dm > 30).astype(np.uint8) * 255  # 1.25x the background's own spread: dim, vignetted border corners still count
    k = max(3, int(0.006 * max(mid.shape[:2])) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3 * k, 3 * k)))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    area_img = mid.shape[0] * mid.shape[1]
    if cv2.contourArea(c) < 0.03 * area_img:
        return None
    hull = cv2.convexHull(c)
    quad = None
    peri = cv2.arcLength(hull, True)
    for eps in (0.01, 0.02, 0.03, 0.04):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            quad = order_quad(ap)
            break
    if quad is None:
        quad = order_quad(cv2.boxPoints(cv2.minAreaRect(hull)))
    quad = quad.astype(np.float32)
    # Each side from the contour's own points along its middle stretch, so a rounded corner,
    # which approxPolyDP cuts across, does not tilt it.
    pts = c.reshape(-1, 2).astype(np.float32)
    diag = float(np.linalg.norm(quad[0] - quad[2]))
    lines = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        L = float(np.linalg.norm(b - a))
        if L < 8:
            return None
        u = (b - a) / L
        n = np.array([-u[1], u[0]], np.float32)
        t = (pts - a) @ u / L
        d = np.abs((pts - a) @ n)
        sel = pts[(t > 0.15) & (t < 0.85) & (d < 0.03 * diag)]
        if len(sel) < 20:
            return None
        lines.append(cv2.fitLine(sel, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel())
    fitted = []
    for i in range(4):
        p = _line_intersect(lines[(i - 1) % 4], lines[i])
        if p is None:
            return None
        fitted.append(p)
    q = np.array(fitted, np.float32)
    g = _MapGrad(dm)
    tb = max(3.0, 0.006 * diag)
    q = _fit_edges(g, q, tb, tb, "strongest")
    q = order_quad(q)
    full_q = (q / ms).astype(np.float32)
    if _score_quad(full_q, H * W, img8.shape) <= 0 or not _card_shaped(full_q):
        return None
    return full_q, _edge_support(g, q)


def _inside(inner: np.ndarray, outer: np.ndarray, slack: float) -> bool:
    poly = outer.reshape(-1, 1, 2).astype(np.float32)
    return all(cv2.pointPolygonTest(poly, (float(x), float(y)), True) >= -slack for x, y in inner)


# Bumped when detection finds cards differently: corners an older version found, and you never
# touched, are found again when the session comes back.
DETECT_VERSION = 2


# ---------------------------------------------------------------- the surface, calibrated
# A photo of the empty surface the cards are shot on, from the same camera position. A card is then
# whatever differs from it, which finds a dark border on a dark mat where edges alone are too faint.
SURFACE: dict = {}
SURFACE_SIDE = 1000


def surface_path() -> str:
    import identify
    return os.path.join(identify._cache_dir(), "surface.png")


def set_surface(img, save: bool = True) -> dict:
    """Keeps a small copy of the empty surface and reports how even its light is: the brightness of
    each corner region against the middle, in percent (negative is darker)."""
    x = to8(img)
    if x.ndim == 2:
        x = cv2.cvtColor(x, cv2.COLOR_GRAY2BGR)
    H, W = x.shape[:2]
    k = SURFACE_SIDE / max(H, W)
    small = cv2.resize(x, (round(W * k), round(H * k)), interpolation=cv2.INTER_AREA)
    if save:
        os.makedirs(os.path.dirname(surface_path()), exist_ok=True)
        cv2.imwrite(surface_path(), small)
    SURFACE.clear()
    SURFACE.update(img=small, lab=cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32), aspect=W / H)
    return surface_report()


def load_surface() -> bool:
    im = cv2.imread(surface_path()) if os.path.isfile(surface_path()) else None
    if im is None:
        return False
    set_surface(im, save=False)
    return True


def clear_surface():
    SURFACE.clear()
    try:
        os.remove(surface_path())
    except OSError:
        pass


def surface_report() -> dict:
    if not SURFACE:
        return {"on": False}
    L = cv2.GaussianBlur(SURFACE["lab"][..., 0], (0, 0), 9)
    h, w = L.shape
    mid = float(L[h * 2 // 5:h * 3 // 5, w * 2 // 5:w * 3 // 5].mean()) or 1.0
    q = lambda ys, xs: round(100 * (float(L[ys, xs].mean()) - mid) / mid)  # noqa: E731
    a, b = slice(0, h // 5), slice(h * 4 // 5, h)
    c, d = slice(0, w // 5), slice(w * 4 // 5, w)
    corners = {"tl": q(a, c), "tr": q(a, d), "bl": q(b, c), "br": q(b, d)}
    return {"on": True, "corners": corners, "worst": min(corners.values()), "w": w, "h": h,
            "level": round(float(L.mean()) / 255 * 100)}


def _plate_quad(img: np.ndarray, small: np.ndarray, scale: float):
    """The card as what differs from the calibrated surface: the largest changed region, boxed. None
    without a surface, or when the photo is not from the same framing (another aspect)."""
    if not SURFACE or abs(SURFACE["aspect"] - img.shape[1] / img.shape[0]) > 0.01:
        return None
    ref = SURFACE["lab"]
    cur = cv2.resize(small, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_AREA)
    cur = cv2.cvtColor(cur, cv2.COLOR_BGR2LAB).astype(np.float32)
    diff = np.linalg.norm(cv2.GaussianBlur(cur - ref, (0, 0), 1.2) * (0.6, 1.0, 1.0), axis=2)
    # changed by more than the surface's own noise (the median change is noise: the card is the smaller
    # part of the frame), and by at least 6 Lab units; no Otsu split, which falls between the mat and a
    # bright artwork and drops a dark border
    t = max(6.0, 3.0 * float(np.median(diff)))
    m = (diff > t).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    m = cv2.morphologyEx(cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, iterations=2), cv2.MORPH_OPEN, k)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.02 * m.size:
        return None
    hull = cv2.convexHull(c)
    box = None
    for eps in (0.01, 0.02, 0.03, 0.05):              # the hull's four corners, a tilted shot's trapezoid
        ap = cv2.approxPolyDP(hull, eps * cv2.arcLength(hull, True), True)
        if len(ap) == 4:
            box = ap.reshape(4, 2).astype(np.float32)
            break
    if box is None:
        box = cv2.boxPoints(cv2.minAreaRect(c)).astype(np.float32)
    f = img.shape[1] / ref.shape[1]
    return order_quad(box * f)


def detect_card(img: np.ndarray) -> tuple[np.ndarray, float]:
    """Find the card. Returns (quad TL,TR,BR,BL in full-res pixels, confidence 0-1).

    Confidence is the fraction of the outline sitting on a sharp edge. If
    nothing convincing turns up it returns an inset rectangle with
    confidence 0 so handles start somewhere sane.
    """
    img = to8(img)
    H, W = img.shape[:2]
    scale = min(1.0, 1000.0 / max(H, W))
    small = cv2.resize(img, (round(W * scale), round(H * scale)), interpolation=cv2.INTER_AREA) \
        if scale < 1 else img
    rough = _rough_candidates(small)
    try:
        pq = _plate_quad(img, small, scale)
    except Exception:  # noqa: BLE001
        pq = None
    if pq is not None:                             # the calibrated surface's finding joins the candidates
        rough = list(rough) + [pq * scale]
    if not rough:
        return card_outline(W, H), 0.0

    grad = _Grad(img)
    results = []   # (quad, support, area)
    for r in rough:
        q0 = (r / scale).astype(np.float32)
        for variant in ("outermost", "strongest"):
            q = _subpixel(grad, q0, variant)
            if _score_quad(q, H * W, img.shape) <= 0:
                continue
            results.append((q, _edge_support(grad, q), cv2.contourArea(q)))
    if not results:
        return order_quad(rough[0] / scale), 0.0

    # Only card-shaped outlines compete when there are any: the letters of a card back's logo are
    # small sharp boxes with near-perfect edges, and judged on sharpness alone they won over the card.
    shaped = [k for k in results if _card_shaped(k[0], 0.06) and _square_corners(order_quad(k[0]))]
    pool = shaped or results
    # Printed borders inside the card are sharp rectangles too, so among the
    # quads that sit cleanly on edges the outermost one is the card itself.
    top = max(k[1] for k in pool)
    good = [k for k in pool if k[1] >= max(0.5, top - 0.03)] or pool
    quad, support, _ = max(good, key=lambda k: k[2])
    quad = order_quad(quad)
    # A dark border on a dark background (a Pokémon back's navy on black) is too faint for
    # the brightness edges above, which then stop at the artwork inside it. On an even
    # background the card's silhouette in colour catches the true edge; it wins when it is
    # card-shaped, holds the found outline, and is at most a border's width larger, or when
    # what was found does not even look like a card (the Poké Ball circle, say).
    try:
        sil = _silhouette(img, small, scale)
    except Exception:  # noqa: BLE001
        sil = None
    if sil is not None:
        sq, ssup = sil
        a_found, a_sil = cv2.contourArea(quad), cv2.contourArea(sq)
        diag = float(np.linalg.norm(sq[0] - sq[2]))
        inside = _inside(quad, sq, 0.01 * diag)
        # A sleeve or toploader round a cleanly found card is the one case the silhouette is wrong.
        sleeve = inside and a_sil > 1.3 * a_found and support >= 0.6 \
            and _card_shaped(quad, 0.06) and _square_corners(quad)
        if ssup >= 0.6 and not sleeve and (ssup >= support - 0.05 or (inside and a_sil > a_found * 1.002)):
            return sq, float(min(1.0, max(ssup, support)))
    return quad, float(support)




def _subpixel(grad: _Grad, quad: np.ndarray, variant: str) -> np.ndarray:
    """Re-fit each edge at full resolution: a wide pass to escape shadows and
    soft masks, then a tight pass for sub-pixel placement."""
    diag = float(np.linalg.norm(quad[0] - quad[2]))
    if variant == "strongest":
        # rough masks usually err outward (shadows), so look mostly outward
        q = _fit_edges(grad, quad, max(4.0, 0.02 * diag), max(3.0, 0.006 * diag), "strongest")
    else:
        w = max(4.0, 0.018 * diag)
        q = _fit_edges(grad, quad, w, w, "outermost")
    t = max(3.0, 0.004 * diag)
    return _fit_edges(grad, q, t, t, "outermost")


def _fit_edges(grad: _Grad, quad: np.ndarray, out_band: float, in_band: float,
               mode: str) -> np.ndarray:
    band = max(out_band, in_band)
    lines = []
    offs = np.arange(-out_band, in_band + 0.25, 0.5, dtype=np.float32)
    ts = np.linspace(0.12, 0.88, 90, dtype=np.float32)
    rows = np.arange(len(ts))
    for i in range(4):
        a, b = quad[i].astype(np.float32), quad[(i + 1) % 4].astype(np.float32)
        ab = b - a
        L = float(np.linalg.norm(ab))
        if L < 4:
            return quad
        u = ab / L
        n = np.array([-u[1], u[0]], dtype=np.float32)     # points into the card
        samp = a + ts[:, None, None] * ab + offs[None, :, None] * n
        g = grad.across(samp, n)
        gmax = g.max(axis=1)
        if mode == "strongest":
            j0 = np.argmax(g, axis=1)
            keep = gmax > getattr(grad, "edge_t", EDGE_T)
        else:
            # first strong edge coming in from outside = the silhouette
            strong = (g >= 0.35 * gmax[:, None]) & (g > getattr(grad, "edge_t", EDGE_T))
            j0 = np.argmax(strong, axis=1)
            keep = strong[rows, j0]
        # climb to that edge's peak, then parabolic sub-pixel interpolation
        idx = np.clip(j0[:, None] + np.arange(6)[None, :], 0, g.shape[1] - 1)
        j = idx[rows, np.argmax(g[rows[:, None], idx], axis=1)]
        jl, jr = np.clip(j - 1, 0, g.shape[1] - 1), np.clip(j + 1, 0, g.shape[1] - 1)
        gl, gc, gr = g[rows, jl], g[rows, j], g[rows, jr]
        den = gl - 2 * gc + gr
        safe = np.where(np.abs(den) > 1e-6, den, 1.0)
        frac = np.where(np.abs(den) > 1e-6, 0.5 * (gl - gr) / safe, 0.0).clip(-0.5, 0.5)
        off = offs[j] + frac * 0.5
        pts = (a + ts[:, None] * ab + off[:, None] * n)[keep]
        if len(pts) < 20:
            return quad
        lines.append(cv2.fitLine(pts.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel())
    out = []
    for i in range(4):
        p = _line_intersect(lines[(i - 1) % 4], lines[i])
        if p is None:
            return quad
        out.append(p)
    out = np.array(out, np.float32)
    if np.max(np.linalg.norm(out - quad, axis=1)) > 3 * band:
        return quad
    return out


# ---------------------------------------------------------------- adjustments
def _srgb_to_lin(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _lin_to_srgb(x):
    x = np.maximum(x, 0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def _smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def adjust(img: np.ndarray, s: Settings, scale: float = 1.0) -> np.ndarray:
    """Light RAW-style edits, done in 32-bit float. Returns float32 0..1, or the
    input untouched when every slider is at zero.

    scale is the preview downscale factor, so sharpening on the small preview
    looks like it will at full size.
    """
    if not s.has_edits():
        return img
    x = to_float(img)

    # exposure and warmth in linear light, the way a raw converter applies them
    if s.exposure or s.warmth:
        lin = _srgb_to_lin(x)
        if s.exposure:
            lin = lin * (2.0 ** (2.0 * s.exposure))
        if s.warmth:
            w = 0.18 * s.warmth                   # BGR order
            lin = lin * np.array([1 - w, 1.0, 1 + w], np.float32)
        x = _lin_to_srgb(lin).astype(np.float32)

    # highlights / shadows / contrast act on luminance and scale RGB by the
    # same ratio, so hues stay put while tones move
    if s.highlights or s.shadows or s.contrast:
        L = (0.0722 * x[..., 0] + 0.7152 * x[..., 1] + 0.2126 * x[..., 2]).clip(0, None)
        Lc = np.minimum(L, 1.0)
        L2 = L.copy()
        if s.shadows:
            L2 += 0.30 * s.shadows * (1 - _smoothstep(0.0, 0.55, Lc)) * np.sqrt(Lc + 1e-6)
        if s.highlights:
            L2 += 0.30 * s.highlights * _smoothstep(0.45, 1.0, Lc) * (1.0 - 0.5 * Lc)
        if s.contrast:
            # anchored S-curve: black and white stay put, mid-tones spread
            t = np.clip(L2, 0, 1)
            L2 = L2 + 0.16 * s.contrast * np.sin(2 * np.pi * (t - 0.5))
        ratio = np.where(L > 1e-5, np.maximum(L2, 0) / np.maximum(L, 1e-5), 1.0)
        x = x * ratio[..., None]

    if s.saturation:
        L = (0.0722 * x[..., 0] + 0.7152 * x[..., 1] + 0.2126 * x[..., 2])[..., None]
        x = L + (x - L) * (1.0 + s.saturation)

    if s.sharpen > 0:
        # unsharp mask with a small radius: crisps print dots and edges
        # without the halo look of a big radius
        sigma = max(0.4, 1.2 * scale)
        blur = cv2.GaussianBlur(x, (0, 0), sigma)
        x = x + (x - blur) * (1.6 * s.sharpen)

    return np.clip(x, 0, 1).astype(np.float32)


# ---------------------------------------------------------------- warp
def output_size(quad: np.ndarray, s: Settings) -> tuple[int, int]:
    w = (np.linalg.norm(quad[1] - quad[0]) + np.linalg.norm(quad[2] - quad[3])) / 2
    h = (np.linalg.norm(quad[3] - quad[0]) + np.linalg.norm(quad[2] - quad[1])) / 2
    if s.lock_ratio:
        if h >= w:
            h = max(h, w / CARD_RATIO)
            w = h * CARD_RATIO
        else:
            w = max(w, h / CARD_RATIO)
            h = w * CARD_RATIO
    if s.out_long_edge:
        k = s.out_long_edge / max(w, h)
        w, h = w * k, h * k
    return int(round(w)), int(round(h))


def margin_for(quad: np.ndarray, s: Settings, margin_scale: float = 1.0) -> int:
    """Margin in output pixels. It is defined at native resolution, so it
    shrinks with the output when a long edge is set or a preview proxy is used."""
    k = margin_scale
    if s.out_long_edge:
        s0 = Settings(lock_ratio=s.lock_ratio)
        k *= s.out_long_edge / max(output_size(quad / margin_scale, s0))
    return int(round(s.margin_px * k))


def warp_card(img: np.ndarray, quad: np.ndarray, s: Settings, rotate: int = 0,
              margin_scale: float = 1.0) -> np.ndarray:
    """Flatten the card. The detected edge maps margin_px inside the output, so
    the straightened card keeps a band of the surrounding photo on every side
    and a corner placed a hair inside the true edge never shaves the card."""
    w, h = output_size(quad, s)
    m = margin_for(quad, s, margin_scale)
    dst = np.array([[m, m], [m + w - 1, m], [m + w - 1, m + h - 1], [m, m + h - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(quad.astype(np.float32), dst)
    bows = side_bows(img, quad, M, w, h, m) if getattr(s, "flatten", False) else None
    if bows is None:
        card = cv2.warpPerspective(img, M, (w + 2 * m, h + 2 * m), flags=cv2.INTER_LANCZOS4,
                                   borderMode=cv2.BORDER_REPLICATE)
    else:
        card = _warp_curved(img, M, w, h, m, bows)
    r = (rotate // 90) % 4
    # auto-portrait only until the user turns the view by hand; after that the
    # output follows exactly what the editor shows
    if s.auto_portrait and w > h and r == 0:
        r = 1
    if r:
        card = np.ascontiguousarray(np.rot90(card, k=-r))
    return card


# ---------------------------------------------------------------- curled cards
# Measured on the a6700 and SEL30M35 at card distance: the lens bows a frame-filling card's edges by about a
# pixel, while the cards themselves curl, caving or bulging their sides by up to 10 px, differently every card.
# A four-corner warp keeps that curve, so each side's own curve is measured after it and straightened out.
def _bow_fit(t, off):
    """A side's curve relative to the straight line between its ends, from points along it: a cubic in t
    fitted twice, the second time without the points the first left far out, minus its chord. None when
    the points are too few or too ragged to trust."""
    keep = np.ones(len(t), bool)
    for _ in range(2):
        if keep.sum() < 24:
            return None
        c = np.polyfit(t[keep], off[keep], 3)
        res = off - np.polyval(c, t)
        mad = np.median(np.abs(res[keep])) * 1.4826 + 1e-6
        keep = np.abs(res) < max(3 * mad, 0.6)
    if keep.sum() < 24 or np.std(res[keep]) > 1.2:
        return None
    e0, e1 = np.polyval(c, 0.0), np.polyval(c, 1.0)
    return c - np.array([0.0, 0.0, e1 - e0, e0])                    # zero at both ends


def side_bows(img, quad, M, w, h, m):
    """Each side's leftover curve in the flattened card, in output pixels, as polynomials in 0..1 along it
    (top, right, bottom, left); None when every side is straight to half a pixel or none can be read."""
    q = order_quad(np.asarray(quad, np.float32))
    Mi = M.astype(np.float64)
    out, any_bow = [], False
    for i in range(4):
        pts = _subpixel_edge(img, q[i], q[(i + 1) % 4])
        if pts is None:
            out.append(None)
            continue
        r = cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float64), Mi).reshape(-1, 2)
        if i in (0, 2):                            # top and bottom: offset in y along x
            t, off = (r[:, 0] - m) / max(1, w - 1), r[:, 1] - (m if i == 0 else m + h - 1)
            L = w
        else:                                      # right and left: offset in x along y
            t, off = (r[:, 1] - m) / max(1, h - 1), r[:, 0] - (m + w - 1 if i == 1 else m)
            L = h
        c = _bow_fit(t, off)
        if c is not None:
            peak = float(np.abs(np.polyval(c, np.linspace(0, 1, 41))).max())
            if peak > 0.03 * L:                     # more than a curl: something else was read as the edge
                c = None
            elif peak >= 0.5:
                any_bow = True
        out.append(c)
    return out if any_bow else None


def _warp_curved(img, M, w, h, m, bows):
    """The four-corner warp with each side's curve blended across the card (a Coons-style linear blend of
    the four sides), so every side comes out straight and the inside follows smoothly."""
    W, H = w + 2 * m, h + 2 * m
    xs = np.arange(W, dtype=np.float32)
    zero = np.zeros(1)
    top, right, bottom, left = [b if b is not None else zero for b in bows]
    Mi = np.linalg.inv(M.astype(np.float64))
    mapx = np.empty((H, W), np.float32)
    mapy = np.empty((H, W), np.float32)
    u = np.clip((xs - m) / max(1, w - 1), 0, 1)
    dt, db = np.polyval(top, u).astype(np.float32), np.polyval(bottom, u).astype(np.float32)
    band = 512
    for y0 in range(0, H, band):
        y1 = min(H, y0 + band)
        ys = np.arange(y0, y1, dtype=np.float32)[:, None]
        v = np.clip((ys - m) / max(1, h - 1), 0, 1)
        dl, dr = np.polyval(left, v).astype(np.float32), np.polyval(right, v).astype(np.float32)
        X = xs[None, :] + (1 - u[None, :]) * dl + u[None, :] * dr
        Y = ys + (1 - v) * dt[None, :] + v * db[None, :]
        den = Mi[2, 0] * X + Mi[2, 1] * Y + Mi[2, 2]
        mapx[y0:y1] = (Mi[0, 0] * X + Mi[0, 1] * Y + Mi[0, 2]) / den
        mapy[y0:y1] = (Mi[1, 0] * X + Mi[1, 1] * Y + Mi[1, 2]) / den
    return cv2.remap(img, mapx, mapy, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)


@dataclass
class Centering:
    left: float
    right: float
    top: float
    bottom: float

    @property
    def lr(self) -> tuple[int, int]:
        a = round(100 * self.left / (self.left + self.right))
        return a, 100 - a

    @property
    def tb(self) -> tuple[int, int]:
        a = round(100 * self.top / (self.top + self.bottom))
        return a, 100 - a

    def text(self) -> str:
        return "Centering L/R %d/%d, T/B %d/%d" % (*self.lr, *self.tb)


def _border_width(strips: np.ndarray, skip: int, refw: int) -> float | None:
    """strips: (lines, depth, 3) Lab samples running from the card edge inward.
    Returns the median depth where the border colour ends, or None."""
    ref = np.median(strips[:, skip:skip + refw], axis=1, keepdims=True)
    dist = np.linalg.norm(strips - ref, axis=2)
    noise = float(np.median(dist[:, skip:skip + refw].std(axis=1)))
    thr = max(14.0, 4.0 * noise)
    over = dist > thr
    # must stay changed for a few pixels, so print specks inside the border do not count
    k = 3
    run = over[:, : over.shape[1] - k + 1].copy()
    for i in range(1, k):
        run &= over[:, i: over.shape[1] - k + 1 + i]
    run[:, : skip + refw] = False
    found = run.any(axis=1)
    if found.mean() < 0.6:
        return None
    depths = run.argmax(axis=1)[found].astype(np.float32)
    med = float(np.median(depths))
    # a straight printed frame gives nearly the same depth on every line
    if np.percentile(np.abs(depths - med), 75) > max(2.0, 0.15 * med):
        return None
    return med


def measure_centering(core: np.ndarray) -> Centering | None:
    """Border widths of a flattened card (no margin). Finds where the outer
    border colour gives way to the printed frame on each side. Full-art and
    borderless cards return None rather than a made-up number."""
    x = to8(core)
    h, w = x.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(x, (3, 3), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    short = min(w, h)
    maxd = int(0.22 * short)
    skip = max(2, int(0.012 * short))      # step past the cut edge and any margin bleed
    refw = max(3, int(0.012 * short))
    n = 60
    ys = np.linspace(0.25 * h, 0.75 * h, n).astype(int)
    xs = np.linspace(0.25 * w, 0.75 * w, n).astype(int)
    strips = {
        "left": lab[ys][:, :maxd],
        "right": lab[ys][:, ::-1][:, :maxd],
        "top": lab[:maxd, xs].transpose(1, 0, 2),
        "bottom": lab[::-1][:maxd, xs].transpose(1, 0, 2),
    }
    out = {}
    for side, st in strips.items():
        d = _border_width(st, skip, refw)
        if d is None or d < 1:
            return None
        out[side] = d
    return Centering(out["left"], out["right"], out["top"], out["bottom"])


def deconvolve(img: np.ndarray, amount: float = 0.5, sigma: float = 0.9) -> np.ndarray:
    """Lens detail: Richardson-Lucy deconvolution of the brightness, with a Gaussian of sigma pixels
    standing in for the blur the lens, its aperture and the sensor's filters put on every photo. It
    puts back sharpness that was captured and spread out; it does not invent any (unlike an AI
    upscaler, which paints in texture, wrong for photos a buyer judges condition from). Colour is
    left alone, so no colour fringes are sharpened, and the change per pixel is capped so noise and
    hard edges do not ring. amount 0 returns the photo untouched."""
    if amount <= 0:
        return img
    x = to_float(img)
    Y = (0.0722 * x[..., 0] + 0.7152 * x[..., 1] + 0.2126 * x[..., 2]).astype(np.float32)
    eps = 1e-4
    obs = np.maximum(Y, eps)
    est = obs.copy()
    for _ in range(int(round(4 + 8 * min(1.0, amount)))):
        conv = cv2.GaussianBlur(est, (0, 0), sigma)
        est *= cv2.GaussianBlur(obs / np.maximum(conv, eps), (0, 0), sigma)
    k = min(1.0, amount * 1.25)
    # only where there is structure: print edges and lettering take the detail, flat areas (where
    # deconvolution would only sharpen the grain) are left as they were. The noise level is measured
    # from the photo itself, so a dark, grainy shot gets a stricter mask than a clean one.
    sm = cv2.GaussianBlur(Y, (0, 0), 1.2)
    grad = np.sqrt(cv2.Sobel(sm, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(sm, cv2.CV_32F, 0, 1) ** 2)
    lap = cv2.Laplacian(Y, cv2.CV_32F)
    noise = float(np.median(np.abs(lap - np.median(lap)))) * 1.4826 + 1e-5
    mask = np.clip((grad - 1.5 * noise) / (3.0 * noise), 0.0, 1.0)
    mask = cv2.GaussianBlur(mask, (0, 0), 1.0)
    gain = np.clip((Y + (est - Y) * k * mask + eps) / (Y + eps), 0.6, 1.6)
    out = np.clip(x * gain[..., None], 0, 1)
    if img.dtype == np.uint8:
        return to8(out)
    if img.dtype == np.uint16:
        return to16(out)
    return out.astype(np.float32)


def exposure_under(src: np.ndarray, quad: np.ndarray | None) -> float:
    """How many stops darker than a good exposure the card is: its brightest print (the 99.5th
    percentile of brightness inside the card, so a specular glint does not count) against a white
    that sits a little under clipping. 0 or less means fine. The photo is read as it comes out of the
    RAW converter, before any tone edits, so this is the exposure the camera actually made."""
    x = src
    k = 800 / max(x.shape[:2])
    small = cv2.resize(x, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else x
    f = to_float(small)
    Y = 0.0722 * f[..., 0] + 0.7152 * f[..., 1] + 0.2126 * f[..., 2]
    if quad is not None:
        m = np.zeros(Y.shape, np.uint8)
        cv2.fillConvexPoly(m, np.round(np.asarray(quad, np.float32) * (k if k < 1 else 1)).astype(np.int32), 1)
        vals = Y[m > 0]
    else:
        vals = Y.ravel()
    if vals.size < 100:
        return 0.0
    p = float(np.percentile(vals, 99.5))
    lin = ((p + 0.055) / 1.055) ** 2.4 if p > 0.04045 else p / 12.92      # sRGB to linear light
    target = 0.62                                                           # about 0.8 in sRGB
    return float(np.log2(target / max(lin, 1e-4)))


def upscale_corner(c: np.ndarray, px: int) -> np.ndarray:
    """Enlarge a corner with Lanczos so eBay shows it at full size instead of
    stretching a small file with its own softer resampling. This cannot invent
    detail that was never captured; it only controls how the enlargement looks."""
    if not px or c.shape[0] >= px:
        return c
    k = px / c.shape[0]
    x = to_float(c)
    up = cv2.resize(x, (px, px), interpolation=cv2.INTER_LANCZOS4)
    # restore edge crispness lost to the enlargement, scaled to the zoom
    blur = cv2.GaussianBlur(up, (0, 0), max(0.6, 0.5 * k))
    up = np.clip(up + (up - blur) * 0.45, 0, 1)
    if c.dtype == np.uint8:
        return to8(up)
    if c.dtype == np.uint16:
        return to16(up)
    return up.astype(np.float32)


def corner_crops(card: np.ndarray, frac: float) -> list[np.ndarray]:
    """Four square crops in reading order: TL, TR, BL, BR, so uploads show the
    bottom left before the bottom right."""
    h, w = card.shape[:2]
    side = int(round(min(w, h) * frac))
    side = max(16, min(side, min(w, h)))
    return [card[:side, :side], card[:side, w - side:],
            card[h - side:, :side], card[h - side:, w - side:]]


# ---------------------------------------------------------------- hero image
HERO_SIDES = {"both": "Front and back", "front": "Front only", "back": "Back only"}
HERO_BGS = {
    # top and bottom of a soft vertical gradient, BGR 0..1
    "light": ((0.955, 0.955, 0.955), (0.85, 0.85, 0.86)),
    "dark": ((0.16, 0.16, 0.17), (0.06, 0.06, 0.065)),
    "black": ((0.02, 0.02, 0.02), (0.0, 0.0, 0.0)),
}


CORNER_FRAC = 0.048        # real cards have about a 3 mm corner radius on 63 mm, so 4.8% of width


def corner_frac(img) -> float:
    """The card's own corner radius as a fraction of its width, read from an upright picture of it whose
    corners still show the background: along each corner's diagonal, how far the background reaches before
    the card starts (a circle of radius r leaves r(1 - 1/sqrt 2) of it), against the card's own colour on
    its edges just past the curve. Background left along the edges by a loose crop is taken off. The rounder
    corners decide, since a corner cut too square shows the background. 0.0 when nothing can be read
    (a square-cut photo, or a card whose corners match the background)."""
    if img is None:
        return 0.0
    a = to8(img)
    if a.ndim == 2:
        a = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
    a = a[..., :3]
    k = 880 / a.shape[0]
    if k < 1:                                     # print dots and grain read as edges at full size
        a = cv2.resize(a, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    a = a.astype(np.float32)
    h, w = a.shape[:2]
    span = int(0.12 * min(h, w))
    if span < 8:
        return 0.0
    found = []
    for sy, sx in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        y0, x0 = (1 if sy > 0 else h - 2), (1 if sx > 0 else w - 2)
        ref = a[y0, x0]
        q = span // 4
        far = (a[y0 + sy * q, x0 + sx * span] + a[y0 + sy * span, x0 + sx * q]) / 2
        full = float(np.linalg.norm(far - ref))
        if full < 40:                                 # the corner is the card itself: nothing to read
            continue

        def walk(dy, dx, oy=0, ox=0):
            for i in range(1, span):
                if np.linalg.norm(a[y0 + oy + dy * i, x0 + ox + dx * i] - ref) > 0.75 * full:
                    return i
            return None
        t = walk(sy, sx)
        mt, ml = walk(sy, 0, 0, sx * span), walk(0, sx, sy * span, 0)
        m = (mt + ml) / 2 - 1 if mt and ml else 0
        if t:
            found.append(max(0.0, t - m) / (1 - 1 / np.sqrt(2)) / w)
    if len(found) < 2:
        return 0.0
    return min(0.25, float(np.percentile(found, 75)) * 1.06)


def _rounded_mask(h: int, w: int, frac: float = CORNER_FRAC) -> np.ndarray:
    r = max(2, int(round(max(CORNER_FRAC, frac) * w)))
    m = np.zeros((h * 4, w * 4), np.uint8)       # 4x supersampled for smooth edges
    R = r * 4
    cv2.rectangle(m, (R, 0), (w * 4 - R, h * 4), 255, -1)
    cv2.rectangle(m, (0, R), (w * 4, h * 4 - R), 255, -1)
    for cx, cy in ((R, R), (w * 4 - R, R), (w * 4 - R, h * 4 - R), (R, h * 4 - R)):
        cv2.circle(m, (cx, cy), R, 255, -1, lineType=cv2.LINE_AA)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


def make_hero(cards: list[np.ndarray], bg: str = "light", size: int = 2000) -> np.ndarray:
    """A square first photo: the real card photos, cut to their rounded shape,
    side by side on a clean gradient with a soft shadow.

    No text, borders, logos or artwork are added, because eBay's picture policy
    prohibits them."""
    top, bottom = HERO_BGS.get(bg, HERO_BGS["light"])
    g = np.linspace(0, 1, size, dtype=np.float32)[:, None, None]
    canvas = (np.array(top, np.float32) * (1 - g) + np.array(bottom, np.float32) * g) * np.ones((1, size, 1), np.float32)
    n = len(cards)
    if n == 0:
        return canvas
    gap = 0.045 * size
    card_h = 0.80 * size
    card_w = card_h * CARD_RATIO
    total_w = n * card_w + (n - 1) * gap
    if total_w > 0.9 * size:                       # keep a pair inside the frame
        k = 0.9 * size / total_w
        card_w, card_h, gap, total_w = card_w * k, card_h * k, gap * k, total_w * k
    x0 = (size - total_w) / 2
    y0 = (size - card_h) / 2 - 0.01 * size
    cw, ch = int(round(card_w)), int(round(card_h))
    dark_bg = bg != "light"
    for i, c in enumerate(cards):
        f = to_float(c)
        frac = corner_frac(c)                      # a rounder card (Carddass, old promos) keeps its own corners
        f = cv2.resize(f, (cw, ch), interpolation=cv2.INTER_AREA)
        a = _rounded_mask(ch, cw, frac)
        x = int(round(x0 + i * (card_w + gap)))
        y = int(round(y0))
        # shadow: the card silhouette, blurred and pushed down, multiplied in
        pad = int(0.06 * size)
        sh = np.zeros((size, size), np.float32)
        sh[y:y + ch, x:x + cw] = a
        sh = cv2.GaussianBlur(sh, (0, 0), 0.018 * size)
        sh = np.roll(sh, int(0.012 * size), axis=0)
        strength = 0.55 if not dark_bg else 0.8
        canvas *= (1 - strength * sh)[..., None]
        _ = pad
        region = canvas[y:y + ch, x:x + cw]
        canvas[y:y + ch, x:x + cw] = region * (1 - a[..., None]) + f * a[..., None]
    return np.clip(canvas, 0, 1)


# ---------------------------------------------------------------- job
@dataclass(eq=False)   # identity: `job in jobs` compared numpy fields and raised
class Job:
    path: str
    quad: np.ndarray | None = None
    confidence: float = 0.0
    settings: Settings = field(default_factory=Settings)   # usually shared by all jobs
    rotate: int = 0
    edited: bool = False        # handles moved by hand
    done: bool = False
    error: str = ""
    card_name: str = ""         # set -> numbered listing files in a folder of that name
    side: str = "front"         # "front" or "back"
    condition: str = ""         # NM / LP / MP / HP / DMG, set on the back, shown in back filenames
    centering: "Centering | None" = None
    card_info: dict | None = None   # identified card (name, set, number, rarity...)
    grade_side: dict | None = None  # condition measurements for this side (grading.py)
    hero_core: np.ndarray | None = None
    ig_crop: tuple | None = None    # this card's own close-up, else the default
    ig_core: np.ndarray | None = None   # full-size upright card waiting for its Instagram slides
    ig_only: bool = False           # an already edited photo: make the carousel, nothing else

    _src: np.ndarray | None = None
    _src_k1: tuple | None = None

    @property
    def stem(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    def source(self) -> np.ndarray:
        """Original image with lens correction applied (cached)."""
        key = (self.settings.lens_k1, self.settings.lens_profile, self.settings.lens_raw_only,
               getattr(self.settings, "lens_fit", ""))
        if self._src is None or self._src_k1 != key:
            self._src = correct_lens(imread(self.path), self.path, self.settings)
            self._src_k1 = key
        return self._src

    def release(self) -> None:
        """Drop the cached pixels (RAW files are ~150 MB decoded)."""
        self._src = None
        self._src_k1 = None

    def detect(self, force: bool = False) -> None:
        """Finds the card's corners. Corners you set by hand win: without force (Detect again), a photo
        you have edited is left alone, including when you edited it while this was still working in
        the background, which used to put the found corners back over yours after you exported."""
        if self.edited and not force and self.quad is not None:
            return
        src = self.source()
        quad, conf = detect_card(src)
        # a dark or flat shot: look again with your tone edits on (exposure, shadows, contrast), which can
        # lift a black border off a dark mat; whichever finding is surer wins
        if conf < 0.9 and self.settings is not None and self.settings.has_edits():
            try:
                q2, c2 = detect_card(to8(adjust(src, self.settings)))
                if c2 > conf:
                    quad, conf = q2, c2
            except Exception:  # noqa: BLE001
                pass
        try:
            self.expo_under = exposure_under(src, quad)
        except Exception:  # noqa: BLE001
            self.expo_under = 0.0
        if self.edited and not force and self.quad is not None:
            return                                  # you set the corners while this was working
        self.quad, self.confidence = quad, conf
        self.edited = False
        self.det = DETECT_VERSION

    def render(self):
        if self.quad is None:
            self.detect()
        card = warp_card(self.source(), self.quad, self.settings, self.rotate)
        m = margin_for(self.quad, self.settings)
        raw_core = card[m:card.shape[0] - m, m:card.shape[1] - m] if m else card
        self.centering = measure_centering(raw_core)
        self.grade_side = None
        if self.settings.grade:
            try:                       # measured before tone edits, so sliders never change a grade
                import grading
                self.grade_side = grading.analyze_side(raw_core, self.side, self.centering)
            except Exception:  # noqa: BLE001
                self.grade_side = None
        card = deconvolve(card, float(getattr(self.settings, "detail", 0.0) or 0.0))   # after grading reads it
        card = adjust(card, self.settings)
        core = card[m:card.shape[0] - m, m:card.shape[1] - m] if m else card
        k = min(1.0, 1800 / core.shape[0])
        small = cv2.resize(to_float(core), None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        # 8-bit is plenty for a JPEG or 8-bit PNG hero; keep 16 for deep formats
        self.hero_core = to8(small) if self.settings.out_format in ("png", "png32", "jpg") else to16(small)
        # kept only while the carousel is on: a copy left from a render made with it on was written later
        # by an export made with it off
        self.ig_core = (to8(core).copy() if self.settings.ig and self.side == "front" and self.card_name.strip()
                        else None)
        corners = [upscale_corner(c, self.settings.corner_px)
                   for c in corner_crops(card, self.settings.corner_frac)] if self.settings.corners else []
        return card, corners

    def export(self, out_dir: str, prefix: str = "") -> list[str]:
        """Without a card name: source-stem files, as before. With one: a folder
        per card and files numbered in eBay listing order, so dragging the folder's
        contents into a listing lands them in sequence:
        01 hero (front and back together), 02 front, 03 back,
        04-07 front corners, 08-11 back corners."""
        card, corners = self.render()
        fmt = self.settings.out_format
        ext = FORMATS[fmt][1]
        if self.card_name.strip():
            name = safe_name(self.card_name)
            folder = os.path.join(out_dir, name)
            os.makedirs(folder, exist_ok=True)
            first, corner0 = (2, 4) if self.side == "front" else (3, 8)
            # the back carries the condition in its filenames, so it shows while uploading
            cond = f"_{self.condition}" if self.side == "back" and self.condition else ""
            for n in [first] + [corner0 + i for i in range(4)]:   # a re-export with a new grade
                for old in glob.glob(os.path.join(glob.escape(folder), f"{glob.escape(name)}_{n:02d}_{self.side}*")):
                    try:
                        os.remove(old)
                    except OSError:
                        pass
            main = os.path.join(folder, f"{name}_{first:02d}_{self.side}{cond}{ext}")
            cpaths = [os.path.join(folder, f"{name}_{corner0 + i:02d}_{self.side}_{c}{cond}{ext}")
                      for i, c in enumerate(self.settings.corner_names)] if corners else []
        else:
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.join(out_dir, f"{prefix}{self.stem}")
            main = base + ext
            cpaths = [f"{base}_{c}{ext}" for c in self.settings.corner_names] if corners else []
        # the transparent formats clear the band of photo around the card and the corners past its rounding
        imwrite(main, card, fmt, card_alpha(card, margin_for(self.quad, self.settings)) if fmt in ALPHA_FORMATS else None)
        for p, c in zip(cpaths, corners):
            imwrite(p, c, fmt)
        if self.card_name.strip() and self.centering is not None:
            with open(os.path.join(os.path.dirname(main), f"{name}_{self.side}_centering.txt"), "w") as f:
                f.write(self.centering.text() + "\n")
        if self.card_name.strip() and self.grade_side is not None:
            try:
                import grading
                if self.side == "back":
                    game = (self.card_info or {}).get("game") or "pokemon"
                    grading.remember_back(self.grade_side["_img"], game)
                    self.grade_side["surface"] = grading.back_surface(self.grade_side, game)
                grading.save_side(os.path.dirname(main), name, self.grade_side)
            except Exception:  # noqa: BLE001
                pass
            try:
                import grading
                grading.keep_tiles(self.grade_side)     # keep the corner close-ups, drop the big picture
            except Exception:  # noqa: BLE001
                pass
        self.done = True
        return [main] + cpaths

    def carousel(self, out_dir: str) -> list[str]:
        """Only the Instagram slides (to out_dir/instagram): the card found, flattened with your
        crop and rotation, and with your tone edits when you have made any. A photo edited
        elsewhere, with every slider at zero, is left exactly as it is."""
        if self.quad is None:
            self.detect()
        s = Settings(lock_ratio=self.settings.lock_ratio, margin_px=0,
                     auto_portrait=self.settings.auto_portrait)
        core = warp_card(self.source(), self.quad, s, self.rotate)
        if self.settings.has_edits():
            core = (to16 if core.dtype == np.uint16 else to8)(adjust(core, self.settings))
        name = safe_name(self.card_name) if self.card_name.strip() else self.stem
        paths = write_ig(out_dir, name, core, self.ig_crop or self.settings.ig_crop)
        self.done = True
        return paths

    def write_instagram(self, out_dir: str) -> list[str]:
        """The carousel for this card, from the copy kept by the last export."""
        if self.ig_core is None or not self.card_name.strip():
            return []
        name = safe_name(self.card_name)
        try:
            return write_ig(os.path.join(out_dir, name), name, self.ig_core,
                            self.ig_crop or self.settings.ig_crop)
        finally:
            self.ig_core = None


def write_hero(out_dir: str, card_name: str, front, back, s: Settings) -> str | None:
    """Write <name>_01_hero from whichever sides are available."""
    # one side asked for and missing: the other stands in, so a card always gets its hero
    pick = {"front": (front,) if front is not None else (back,),
            "back": (back,) if back is not None else (front,)}.get(s.hero_sides, (front, back))
    cards = [c for c in pick if c is not None]
    if not cards or not card_name.strip():
        return None
    name = safe_name(card_name)
    folder = os.path.join(out_dir, name)
    os.makedirs(folder, exist_ok=True)
    ext = FORMATS[s.out_format][1]
    p = os.path.join(folder, f"{name}_01_hero{ext}")
    imwrite(p, make_hero(cards, s.hero_bg), s.out_format)
    return p


def safe_name(s: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("-" if ch in bad else ch for ch in s.strip())
    return out.strip(". ") or "card"


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"} | RAW_EXTS


def expand_paths(paths) -> list[str]:
    out = []
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                    out.append(os.path.join(p, name))
        elif os.path.splitext(p)[1].lower() in IMAGE_EXTS:
            out.append(p)
    return out


# ---------------------------------------------------------------- Instagram carousel
# Slide 1: the whole card on #F2F2F2, centred, at exactly the size and position
# of the hand-made template. Slides 2 and 3: one close-up cut in half, so the
# swipe reads as one seamless image. All slides are 4:5, 300 dpi.
IG_W, IG_H = 9374, 11718
IG_CARD_W, IG_CARD_H = 5074, 7071
IG_CARD_X, IG_CARD_Y = 2155, 2323    # measured from the template artboard, not computed
IG_BG = (242, 242, 242)
IG_RADIUS = 195               # corner radius in template pixels, measured from the artboard
IG_DEFAULT_CROP = (0.0, 0.10, 1.0)   # close-up: left, top, width as fractions of the card


def ig_crop_rect(core_shape, crop) -> tuple[float, float, float, float]:
    """The close-up window in card pixels (x, y, w, h); always the 8:5 shape of two
    4:5 slides side by side, clamped inside the card."""
    h, w = core_shape[:2]
    x0, y0, fw = crop
    cw = max(0.05, min(1.0, fw)) * w
    ch = cw * IG_H / (2 * IG_W)
    if ch > h:
        ch, cw = h, h * 2 * IG_W / IG_H
    x = min(max(0.0, x0 * w), w - cw)
    y = min(max(0.0, y0 * h), h - ch)
    return x, y, cw, ch


def _ig_rounded_mask(w, h, r):
    """Anti-aliased rounded rectangle, 0..1 float."""
    m = np.ones((h, w), np.float32)
    r = max(1.0, r)
    k = int(np.ceil(r))
    yy, xx = np.mgrid[0:k, 0:k].astype(np.float32) + 0.5
    d = np.sqrt((r - xx) ** 2 + (r - yy) ** 2)
    corner = np.clip(r - d + 0.5, 0, 1)
    corner[(xx > r) | (yy > r)] = 1
    m[:k, :k] = np.minimum(m[:k, :k], corner)
    m[:k, w - k:] = np.minimum(m[:k, w - k:], corner[:, ::-1])
    m[h - k:, :k] = np.minimum(m[h - k:, :k], corner[::-1, :])
    m[h - k:, w - k:] = np.minimum(m[h - k:, w - k:], corner[::-1, ::-1])
    return m


def _resample(src, M, size):
    """Affine resample with Lanczos when enlarging and area-style smoothing when shrinking."""
    scale = abs(M[0, 0])
    if scale < 1:      # shrinking: pre-blur so detail does not alias
        sigma = 0.5 / max(scale, 1e-3)
        src = cv2.GaussianBlur(src, (0, 0), sigma * 0.6)
    return cv2.warpAffine(src, M, size, flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)


def ig_slides(core: np.ndarray, crop=IG_DEFAULT_CROP, scale: float = 1.0) -> list[np.ndarray]:
    """Three 8-bit BGR slides from an upright card with no margin. scale < 1 makes
    quick previews with the same layout."""
    img = to8(core)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    frac = corner_frac(img)                        # read before the shave, while the corners show the background
    # shave a hair off every edge so no sliver of the background (black, a mat)
    # can show as a dark halo against the light slide
    t = max(1, round(0.004 * min(img.shape[:2])))
    img = img[t:img.shape[0] - t, t:img.shape[1] - t]
    W, H = max(1, round(IG_W * scale)), max(1, round(IG_H * scale))
    cw, ch = max(1, round(IG_CARD_W * scale)), max(1, round(IG_CARD_H * scale))
    # slide 1
    s1 = np.empty((H, W, 3), np.uint8)
    s1[:] = IG_BG
    sy, sx = ch / img.shape[0], cw / img.shape[1]
    M = np.array([[sx, 0, 0], [0, sy, 0]], np.float32)
    card = _resample(img, M, (cw, ch))
    a = _ig_rounded_mask(cw, ch, max(IG_RADIUS * scale, frac * cw))[..., None]
    x0, y0 = round(IG_CARD_X * scale), round(IG_CARD_Y * scale)
    roi = s1[y0:y0 + ch, x0:x0 + cw].astype(np.float32)
    s1[y0:y0 + ch, x0:x0 + cw] = (card * a + roi * (1 - a) + 0.5).astype(np.uint8)
    # slides 2 and 3: one mapping for the whole panorama, rendered half by half so the seam is exact
    x, y, w, h = ig_crop_rect(img.shape, crop)
    k = (2 * W) / w
    halves = []
    for i in range(2):
        M = np.array([[k, 0, -x * k - i * W], [0, k, -y * k]], np.float32)
        halves.append(_resample(img, M, (W, H)))
    return [s1] + halves


def write_ig(folder: str, name: str, core: np.ndarray, crop=IG_DEFAULT_CROP) -> list[str]:
    """Saves name_IG_1..3.jpg in an 'instagram' folder beside the listing photos,
    so the eBay folder stays clean."""
    out = os.path.join(folder, "instagram")
    os.makedirs(out, exist_ok=True)
    paths = []
    for i, slide in enumerate(ig_slides(core, crop), 1):
        p = os.path.join(out, f"{name}_IG_{i}.jpg")
        ok, buf = cv2.imencode(".jpg", slide, [cv2.IMWRITE_JPEG_QUALITY, 95,
                                               cv2.IMWRITE_JPEG_SAMPLING_FACTOR,
                                               cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444])
        if not ok:
            raise IOError(f"could not encode {p}")
        buf = _jpeg_dpi(buf.tobytes(), 300)
        with open(p, "wb") as f:
            f.write(buf)
        paths.append(p)
    return paths


def _jpeg_dpi(data: bytes, dpi: int) -> bytes:
    """Stamp the JFIF header with a pixel density, so design apps open it at 300 dpi."""
    i = data.find(b"JFIF\x00")
    if i < 0:
        return data
    b = bytearray(data)
    j = i + 7                      # after 'JFIF\0' and the 2 version bytes
    b[j] = 1                       # units: dots per inch
    b[j + 1:j + 3] = dpi.to_bytes(2, "big")
    b[j + 3:j + 5] = dpi.to_bytes(2, "big")
    return bytes(b)


def guess_backs(thumbs) -> list[bool]:
    """Which of these straightened card pictures are backs. A game's backs are all one printed design,
    so they look alike, while fronts differ card to card; Pokemon backs also carry a blue border. A
    picture is a back when it closely matches two others (turned either way up), or one other with a
    blue border, or has a blue border all round. thumbs: BGR arrays, None where there is no picture."""
    def desc(t):
        g = cv2.cvtColor(cv2.resize(to8(t), (18, 25), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        g = g.astype(np.float32)
        return (g - g.mean()) / (g.std() + 1e-6)

    def blue(t):
        t = to8(t)
        h, w = t.shape[:2]
        m = np.zeros((h, w), bool)
        b = max(3, int(0.07 * min(h, w)))
        m[:b] = m[-b:] = True
        m[:, :b] = m[:, -b:] = True
        hsv = cv2.cvtColor(t, cv2.COLOR_BGR2HSV)
        H, S, V = hsv[..., 0][m], hsv[..., 1][m], hsv[..., 2][m]
        return float(np.mean((H >= 95) & (H <= 130) & (S > 70) & (V > 30)))

    n = len(thumbs)
    D = [desc(t) if t is not None else None for t in thumbs]
    B = [blue(t) if t is not None else 0.0 for t in thumbs]
    out = []
    for i in range(n):
        if D[i] is None:
            out.append(False)
            continue
        alike = [k for k in range(n) if k != i and D[k] is not None and
                 max(float((D[i] * D[k]).mean()), float((D[i] * np.rot90(D[k], 2)).mean())) > 0.8]
        out.append(B[i] > 0.6 or len(alike) >= 2 or (len(alike) == 1 and max(B[i], B[alike[0]]) > 0.3))
    return out


def pair_backs(sides, manual=None) -> dict:
    """Which front each back belongs to, by position in the list: the pairs you made by hand first
    (back index -> front index), then each remaining back with the nearest front before it that has no
    back yet. Backs with no such front are left out."""
    manual = {b: f for b, f in (manual or {}).items()
              if 0 <= b < len(sides) and 0 <= f < len(sides) and sides[b] == "back" and sides[f] == "front"}
    taken = set(manual.values())
    out = dict(manual)
    last = None
    for i, sd in enumerate(sides):
        if sd == "front":
            last = i
        elif i not in out and last is not None and last not in taken:
            out[i] = last
            taken.add(last)
    return out

