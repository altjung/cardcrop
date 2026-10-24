"""Draws the 1024 px app icon to match the app's mark: a lime card outline on an
ink tile, on Apple's icon grid (an 824 px rounded square with a soft shadow).
Run by build_mac_app.sh."""
import sys

import cv2
import numpy as np

S = 1024
K = 4                                                  # draw at 4x, then shrink: clean edges
s = S * K
img = np.zeros((s, s, 4), np.float32)


def rounded_rect_mask(x0, y0, x1, y1, r):
    m = np.zeros((s, s), np.uint8)
    cv2.rectangle(m, (x0 + r, y0), (x1 - r, y1), 255, -1)
    cv2.rectangle(m, (x0, y0 + r), (x1, y1 - r), 255, -1)
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x1 - r, y1 - r), (x0 + r, y1 - r)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return m.astype(np.float32) / 255


# tile: 824 px square on the 1024 canvas, corner radius about 22.5% of its size
t0, t1 = 100 * K, 924 * K
tile = rounded_rect_mask(t0, t0, t1, t1, int(185 * K))

# soft shadow under the tile, as macOS icons carry
shadow = cv2.GaussianBlur(np.roll(tile, 12 * K, axis=0), (0, 0), 18 * K) * 0.45
img[..., 3] = shadow
img[..., :3] = 0

# ink fill with a faint top-to-bottom lift so it does not read as flat black
grad = np.linspace(1.0, 0.0, s, dtype=np.float32)[:, None]
ink = np.stack([18 + 10 * grad, 17 + 10 * grad, 17 + 10 * grad], -1)       # BGR, #111112 to #1B1B1C
ink = np.broadcast_to(ink, (s, s, 3))
a = tile[..., None]
img[..., :3] = img[..., :3] * (1 - a) + ink * a
img[..., 3] = np.maximum(img[..., 3], tile)

# the mark: a 63 x 88 card outline in lime, rounded like a real card
lime = np.array([75, 242, 214], np.float32)           # BGR of #D6F24B
ch = int(430 * K)
cw = int(ch * 63 / 88)
cx0, cy0 = (s - cw) // 2, (s - ch) // 2
stroke = int(46 * K)
outer = rounded_rect_mask(cx0, cy0, cx0 + cw, cy0 + ch, int(46 * K))
inner = rounded_rect_mask(cx0 + stroke, cy0 + stroke, cx0 + cw - stroke, cy0 + ch - stroke, int(18 * K))
ring = np.clip(outer - inner, 0, 1)[..., None]
img[..., :3] = img[..., :3] * (1 - ring) + lime * ring

out = cv2.resize(img, (S, S), interpolation=cv2.INTER_AREA)
out = np.clip(out * np.array([1, 1, 1, 255], np.float32), 0, 255).astype(np.uint8)
cv2.imwrite(sys.argv[1] if len(sys.argv) > 1 else "icon_1024.png", out)
