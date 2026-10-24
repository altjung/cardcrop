"""CardCrop live view: the tethered camera feed, framing overlay and live analysis."""
from __future__ import annotations

import cv2
import engine
import math
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget
import ui_base as TH
import ui_motion as motion

GRIDS = ["Off", "Thirds", "Thirds + diagonals", "Square grid", "Fine grid", "Diagonals", "Centre cross"]
GRID_WIDTHS = {"Thin": 1.0, "Medium": 2.0, "Thick": 3.5}


def qimage_to_bgr(img: QImage) -> np.ndarray:
    q = img.convertToFormat(QImage.Format_RGB888)
    a = np.frombuffer(q.constBits(), np.uint8).reshape(q.height(), q.bytesPerLine())[:, :q.width() * 3]
    return cv2.cvtColor(a.reshape(q.height(), q.width(), 3), cv2.COLOR_RGB2BGR)


def analyze_live(frame: np.ndarray, card: bool, peaking: bool) -> dict:
    """One live view frame, off the UI thread: where the card is and how sure, its centering, a
    small fingerprint to tell one card from the next, and the focus-peaking highlights."""
    out = {"quad": None, "conf": 0.0, "cent": None, "thumb": None, "peak": None,
           "size": (frame.shape[1], frame.shape[0])}
    h, w = frame.shape[:2]
    if card:
        k = min(1.0, 640 / max(w, h))
        small = cv2.resize(frame, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else frame
        q, conf = engine.detect_card(small)
        if q is not None:
            q = np.asarray(q, np.float32) / k
            out["quad"], out["conf"] = q, float(conf)
            if conf >= 0.5:
                st = engine.Settings(margin_px=0, flatten=False)    # live view: speed over the last pixel
                core = engine.warp_card(frame, q, st, 0)
                c = engine.measure_centering(core)
                out["cent"] = (c.lr, c.tb) if c is not None else None
                g = cv2.cvtColor(core, cv2.COLOR_BGR2GRAY) if core.ndim == 3 else core
                g = cv2.resize(engine.to8(g), (32, 44), interpolation=cv2.INTER_AREA).astype(np.float32)
                out["thumb"] = (g - g.mean()) / (g.std() + 1e-6)
    if peaking:
        k = min(1.0, 960 / max(w, h))
        g = cv2.cvtColor(cv2.resize(frame, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else frame,
                         cv2.COLOR_BGR2GRAY).astype(np.float32)
        g = cv2.GaussianBlur(g, (0, 0), 0.8)
        mag = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
        thr = max(90.0, float(np.percentile(mag, 97)))
        m = cv2.dilate((mag > thr).astype(np.uint8), np.ones((2, 2), np.uint8))
        rgba = np.zeros(m.shape + (4,), np.uint8)
        rgba[m > 0] = (255, 40, 120, 235)              # magenta: shows on cards of every colour
        out["peak"] = rgba
    return out


def thumb_change(a, b) -> float:
    """How different two card fingerprints are: about 0.1 for the same card, 0.6+ for another."""
    if a is None or b is None:
        return 1.0
    return float(np.mean(np.abs(a - b))) / 1.6


class LiveView(QWidget):
    """Camera live view with framing aids: grid patterns in a chosen colour,
    the saved card position, 90 degree view rotation and a digital magnifier.
    Everything is drawn over the picture; nothing changes the captured file."""

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.img: QImage | None = None
        self.guide = None            # 4x2 corners, normalised 0..1 in sensor orientation
        self.focus_state = "idle"
        self.message = "Live view is off"
        self.rot = 0                 # view rotation, degrees clockwise
        self.grid = "Thirds + diagonals"
        self.grid_color = QColor(255, 255, 255, 200)
        self.grid_width = "Thin"
        self.zoom = 1.0              # digital magnifier on the live frame
        self.on_zoom = None          # callback(zoom) so the toolbar can show the level
        self.zoom_c = (0.5, 0.5)     # magnifier centre, normalised in the displayed frame
        self._fade = QTimer(self, singleShot=True, interval=1500)
        self._fade.timeout.connect(lambda: self.set_focus("idle"))
        self.show_guide = True
        self.on_guide = None         # callback(corners) when an overlay edit finishes
        self._drag = None            # (kind, corner index, start shape, start point px)
        self.live_quad = None        # the card found in the live frame, sensor-normalised corners
        self.live_conf = 0.0
        self.live_cent = None        # ((l, r), (t, b)) centering of that card
        self.show_edges = True
        self.peak = None             # focus peaking highlights, QImage the size of the frame
        self.loupe = False           # the four card corners, magnified
        self.auto_text = ""          # auto-capture state, shown at the bottom
        self.auto_frac = 0.0         # 0..1 while a card is holding still

    # ---------------------------------------------------------- overlay editing
    def _px_size(self):
        return (self.img.width(), self.img.height()) if self.img is not None else None

    def _widget_to_disp(self, pos):
        r = self._frame_rect()
        u = (pos.x() - r.x()) / r.width()
        v = (pos.y() - r.y()) / r.height()
        cx, cy = self.zoom_c
        return cx + (u - 0.5) / self.zoom, cy + (v - 0.5) / self.zoom

    def _disp_to_sensor(self, u, v):
        if self.rot == 90:
            return v, 1 - u
        if self.rot == 180:
            return 1 - u, 1 - v
        if self.rot == 270:
            return 1 - v, u
        return u, v

    def _widget_to_px(self, pos):
        x, y = self._disp_to_sensor(*self._widget_to_disp(pos))
        iw, ih = self._px_size()
        return np.array([x * iw, y * ih])

    def _guide_widget_pts(self):
        view = self._view(self._frame_rect())
        return [view(*self._to_display(x, y)) for x, y in self.guide]

    def _hit(self, pos):
        """What a press at pos grabs: ('corner', i), ('rotate', i), ('move', -1) or None."""
        if self.guide is None or self.img is None or not self.show_guide:
            return None
        pts = self._guide_widget_pts()
        d = [math.hypot(q.x() - pos.x(), q.y() - pos.y()) for q in pts]
        i = int(np.argmin(d))
        inside = QPolygonF(pts).containsPoint(QPointF(pos), Qt.OddEvenFill)
        if d[i] < 18:
            return ("corner", i)
        if d[i] < 52 and not inside:
            return ("rotate", i)
        if inside:
            return ("move", -1)
        return None

    # the overlay is edited as you see it: in the displayed frame's pixels, so a card shot with the
    # camera turned is still a portrait card on screen and scales both ways
    def _disp_size(self):
        iw, ih = self._px_size()
        return (ih, iw) if self.rot in (90, 270) else (iw, ih)

    def _guide_disp_px(self):
        dw, dh = self._disp_size()
        return np.array([[u * dw, v * dh] for u, v in (self._to_display(x, y) for x, y in self.guide)], np.float64)

    def _widget_to_disp_px(self, pos):
        dw, dh = self._disp_size()
        u, v = self._widget_to_disp(pos)
        return np.array([u * dw, v * dh])

    def _apply_disp(self, corners_disp):
        dw, dh = self._disp_size()
        self.guide = np.asarray([self._disp_to_sensor(x / dw, y / dh) for x, y in corners_disp], np.float32)
        self.update()

    def mousePressEvent(self, e):
        hit = self._hit(e.position())
        if hit is None or e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        corners = self._guide_disp_px()
        shape = fit_shape(corners)
        sc = shape_corners(*shape)
        idx = hit[1]
        if idx >= 0:   # match the grabbed corner to the fitted card's corner order
            idx = int(np.argmin(np.linalg.norm(sc - corners[idx], axis=1)))
        self._drag = (hit[0], idx, shape, self._widget_to_disp_px(e.position()))
        self._snapped = False
        self._apply_disp(sc)
        e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is None:
            hit = self._hit(e.position())
            if hit and hit[0] == "rotate":
                self.setCursor(_rotate_cursor())
            elif hit and hit[0] == "move":
                self.setCursor(Qt.SizeAllCursor)
            elif hit and hit[0] == "corner":
                self.setCursor(Qt.CrossCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return
        kind, idx, (cx, cy, w, a), start = self._drag
        P = self._widget_to_disp_px(e.position())
        mods = e.modifiers()
        r = engine.CARD_RATIO
        dw, dh = self._disp_size()
        # how many frame pixels one screen pixel is, for snapping distances
        k = max(dw, dh) / max(1.0, max(self._frame_rect().width(), self._frame_rect().height())) / self.zoom
        self._snapped = False
        if kind == "move":
            d = P - start
            nx, ny = cx + d[0], cy + d[1]
            if not (mods & Qt.ShiftModifier):          # snap to the centre of the frame; Shift moves freely
                if abs(nx - dw / 2) < 14 * k and abs(ny - dh / 2) < 14 * k:
                    nx, ny = dw / 2, dh / 2
                    self._snapped = True
                elif abs(nx - dw / 2) < 10 * k:
                    nx = dw / 2
                elif abs(ny - dh / 2) < 10 * k:
                    ny = dh / 2
            shape = (nx, ny, w, a)
        elif kind == "rotate":
            a0 = math.atan2(start[1] - cy, start[0] - cx)
            da = math.atan2(P[1] - cy, P[0] - cx) - a0
            if mods & Qt.ShiftModifier:
                da = math.radians(round(math.degrees(a + da))) - a
            elif abs(math.degrees(a + da)) < 1.5:      # snaps square
                da = -a
            shape = (cx, cy, w, a + da)
        else:
            u = np.array([math.cos(a), math.sin(a)])
            v = np.array([-math.sin(a), math.cos(a)])
            sx, sy = SIGNS[idx]
            if mods & (Qt.AltModifier | Qt.ControlModifier | Qt.MetaModifier):
                # Option: scale from the centre
                d = P - np.array([cx, cy])
                nw = max(20.0, 2 * max(abs(d @ u), abs(d @ v) * r))
                shape = (cx, cy, nw, a)
            else:
                opp = shape_corners(cx, cy, w, a)[(idx + 2) % 4]
                d = P - opp
                nw = max(20.0, d @ u * sx, d @ v * sy * r)
                C = opp + sx * nw / 2 * u + sy * nw / r / 2 * v
                shape = (float(C[0]), float(C[1]), nw, a)
        self._apply_disp(shape_corners(*shape))

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            if self.on_guide:
                self.on_guide(self.guide)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def _apply_px(self, corners_px):
        iw, ih = self._px_size()
        self.guide = np.asarray(corners_px, np.float32) / np.array([iw, ih], np.float32)
        self.update()

    # ---------------------------------------------------------- state
    def set_frame(self, img: QImage):
        self.img = img
        self.update()

    def set_focus(self, state):
        self.focus_state = state
        if state in ("focused", "failed"):
            self._fade.start()
        self.update()

    def rotate_view(self, step):
        self.rot = (self.rot + 90 * step) % 360
        self.zoom, self.zoom_c = 1.0, (0.5, 0.5)
        self.update()

    def set_zoom(self, z, centre=None):
        self.zoom = max(1.0, min(4.0, z))
        if centre is not None:
            self.zoom_c = centre
        if self.zoom == 1.0:
            self.zoom_c = (0.5, 0.5)
        if self.on_zoom:
            self.on_zoom(self.zoom)
        self.update()

    # ---------------------------------------------------------- geometry
    def _rotated_size(self):
        iw, ih = self.img.width(), self.img.height()
        return (ih, iw) if self.rot % 180 else (iw, ih)

    def _frame_rect(self):
        """Where the (rotated) frame sits in the widget, before magnification."""
        dw, dh = self._rotated_size()
        k = min(self.width() / dw, self.height() / dh)
        w, h = dw * k, dh * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_display(self, x, y):
        """Sensor-normalised point -> displayed-frame-normalised point."""
        if self.rot == 90:
            return 1 - y, x
        if self.rot == 180:
            return 1 - x, 1 - y
        if self.rot == 270:
            return y, 1 - x
        return x, y

    def _view(self, r):
        """Map displayed-frame-normalised (u, v) to widget coordinates, with zoom."""
        cx, cy = self.zoom_c
        z = self.zoom

        def f(u, v):
            return QPointF(r.x() + ((u - cx) * z + 0.5) * r.width(),
                           r.y() + ((v - cy) * z + 0.5) * r.height())
        return f

    # ---------------------------------------------------------- input
    def wheelEvent(self, e):
        if self.img is None:
            return
        r = self._frame_rect()
        pos = e.position()
        # keep the point under the cursor fixed while zooming
        u = (pos.x() - r.x()) / r.width()
        v = (pos.y() - r.y()) / r.height()
        cx, cy = self.zoom_c
        z = self.zoom
        pu, pv = cx + (u - 0.5) / z, cy + (v - 0.5) / z
        nz = max(1.0, min(4.0, z * (1.25 if e.angleDelta().y() > 0 else 0.8)))
        ncx, ncy = pu - (u - 0.5) / nz, pv - (v - 0.5) / nz
        half = 0.5 / nz
        self.set_zoom(nz, (min(max(ncx, half), 1 - half), min(max(ncy, half), 1 - half)))

    def mouseDoubleClickEvent(self, e):
        hit = self._hit(e.position())
        if hit is not None and hit[0] != "move":
            return
        if self.zoom > 1:
            self.set_zoom(1.0)
            return
        r = self._frame_rect()
        u = (e.position().x() - r.x()) / r.width()
        v = (e.position().y() - r.y()) / r.height()
        self.set_zoom(3.0, (min(max(u, 1 / 6), 5 / 6), min(max(v, 1 / 6), 5 / 6)))

    def _draw_loupe(self, p, r):
        """The card's four corners at three times the live view, top right, to check focus."""
        corners = self.live_quad if (self.live_quad is not None and self.live_conf >= 0.5) else self.guide
        if corners is None or self.img is None:
            return
        iw, ih = self.img.width(), self.img.height()
        px = np.asarray(corners, np.float64) * [iw, ih]
        side = max(24.0, 0.16 * float(np.linalg.norm(px[1] - px[0])))
        disp = [self._to_display(x, y) for x, y in corners]
        cu, cv_ = np.mean([d[0] for d in disp]), np.mean([d[1] for d in disp])
        tile, gap = 132, 6
        box = QRectF(r.right() - (2 * tile + gap) - 16, r.y() + 64, 2 * tile + gap, 2 * tile + gap)
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 200))
        p.drawRoundedRect(box.adjusted(-6, -6, 6, 6), 10, 10)
        for (u, v), (x, y) in zip(disp, px):
            col, row_ = int(u > cu), int(v > cv_)
            src = QRectF(x - side / 2, y - side / 2, side, side).intersected(QRectF(0, 0, iw, ih))
            crop = self.img.copy(src.toRect())
            if self.rot:
                from PySide6.QtGui import QTransform
                crop = crop.transformed(QTransform().rotate(self.rot))
            dst = QRectF(box.x() + col * (tile + gap), box.y() + row_ * (tile + gap), tile, tile)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(dst, crop)
            if self.peak is not None and not self.peak.isNull():
                ks = self.peak.width() / iw
                pc = self.peak.copy(QRectF(src.x() * ks, src.y() * ks, src.width() * ks, src.height() * ks).toRect())
                if self.rot:
                    pc = pc.transformed(QTransform().rotate(self.rot))
                p.drawImage(dst, pc)

    # ---------------------------------------------------------- drawing
    def _grid_lines(self):
        """Lines as pairs of displayed-frame-normalised points."""
        g, L = self.grid, []
        if g in ("Thirds", "Thirds + diagonals"):
            for t in (1 / 3, 2 / 3):
                L += [((t, 0), (t, 1)), ((0, t), (1, t))]
        if g in ("Thirds + diagonals", "Diagonals"):
            L += [((0, 0), (1, 1)), ((1, 0), (0, 1))]
        if g == "Square grid":
            for t in (0.25, 0.5, 0.75):
                L += [((t, 0), (t, 1)), ((0, t), (1, t))]
        if g == "Fine grid":
            for i in range(1, 8):
                t = i / 8
                L += [((t, 0), (t, 1)), ((0, t), (1, t))]
        if g == "Centre cross":
            L += [((0.5, 0), (0.5, 1)), ((0, 0.5), (1, 0.5))]
        return L

    def flash(self):
        """The shutter: a quick white flash over the frame when a photo lands."""
        if not motion.enabled():
            return
        import time as _t
        self._flash_t = _t.time()
        if getattr(self, "_flash_timer", None) is None:
            self._flash_timer = QTimer(self, interval=16)
            self._flash_timer.timeout.connect(self._flash_tick)
        self._flash_timer.start()

    def _flash_tick(self):
        import time as _t
        self.update()
        if _t.time() - getattr(self, "_flash_t", 0) > 0.3:
            self._flash_timer.stop()

    def paintEvent(self, e):
        self._paint_frame(e)
        import time as _t
        age = _t.time() - getattr(self, "_flash_t", 0)
        if age < 0.28:
            p = QPainter(self)
            c = QColor(255, 255, 255)
            c.setAlphaF(0.55 * (1 - age / 0.28) ** 2)
            p.fillRect(self.rect(), c)
            p.end()

    def _paint_frame(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(CANVAS))
        if self.img is None or self.img.isNull():
            p.setPen(QColor("#8A8A90"))
            f = p.font(); f.setPointSize(TH.BASE_PT + 3); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self.message)
            return
        r = self._frame_rect()
        view = self._view(r)
        p.save()
        p.setClipRect(r)
        # the picture: rotate the frame about the displayed rectangle's centre
        tl, br = view(0, 0), view(1, 1)
        shown = QRectF(tl, br)
        p.translate(shown.center())
        p.rotate(self.rot)
        w, h = (shown.height(), shown.width()) if self.rot % 180 else (shown.width(), shown.height())
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(QRectF(-w / 2, -h / 2, w, h), self.img)
        if self.peak is not None and not self.peak.isNull():
            p.drawImage(QRectF(-w / 2, -h / 2, w, h), self.peak)
        p.resetTransform()
        # grid, in the user's colour and weight, over the frame as displayed
        lines = self._grid_lines()
        if lines:
            gw = GRID_WIDTHS.get(self.grid_width, 1.0)
            shadow = QColor(0, 0, 0, min(150, self.grid_color.alpha()))
            for pen in (QPen(shadow, gw + 1.5), QPen(self.grid_color, gw)):
                p.setPen(pen)
                for (u1, v1), (u2, v2) in lines:
                    p.drawLine(view(u1, v1), view(u2, v2))
        # where the card should sit: drag inside to move, corners to resize, outside a corner to rotate
        if self.guide is not None and self.show_guide:
            pts = [view(*self._to_display(x, y)) for x, y in self.guide]
            for pen in (QPen(QColor(0, 0, 0, 170), 5), QPen(QColor(ACCENT), 2.5, Qt.DashLine)):
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(QPolygonF(pts))
            # the card's own centre lines, corner to corner across its middle, turning with it
            mid = [(pts[i] + pts[(i + 1) % 4]) / 2 for i in range(4)]
            for pen in (QPen(QColor(0, 0, 0, 140), 3), QPen(QColor(ACCENT), 1.2)):
                p.setPen(pen)
                p.drawLine(mid[0], mid[2])
                p.drawLine(mid[1], mid[3])
            for pt in pts:
                p.setPen(QPen(QColor(0, 0, 0, 200), 3))
                p.setBrush(QColor(ACCENT))
                p.drawEllipse(pt, 7, 7)
            if self._drag is not None and self._drag[0] == "move":
                # the frame's centre lines while moving; solid once the overlay sits dead centre
                c = view(0.5, 0.5)
                col = QColor(ACCENT) if getattr(self, "_snapped", False) else QColor(255, 255, 255, 120)
                p.setPen(QPen(col, 1.5 if getattr(self, "_snapped", False) else 1, Qt.SolidLine if
                              getattr(self, "_snapped", False) else Qt.DashLine))
                fr = self._frame_rect()
                p.drawLine(QPointF(c.x(), fr.top()), QPointF(c.x(), fr.bottom()))
                p.drawLine(QPointF(fr.left(), c.y()), QPointF(fr.right(), c.y()))
        # the card the camera sees right now, solid when its edges are locked
        if self.show_edges and self.live_quad is not None and self.live_conf >= 0.5:
            pts = [view(*self._to_display(x, y)) for x, y in self.live_quad]
            col = QColor(TH.OK) if self.live_conf >= 0.8 else QColor(TH.WARN)
            for pen in (QPen(QColor(0, 0, 0, 160), 5), QPen(col, 2.5)):
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(QPolygonF(pts))
        p.restore()
        f = p.font(); f.setPointSize(TH.BASE_PT + 1); f.setBold(True); p.setFont(f)
        if self.show_edges and self.live_quad is not None and self.live_conf >= 0.5:
            locked = self.live_conf >= 0.8
            txt = ("Edges locked" if locked else "Finding edges") + (
                "   ·   L/R %d/%d   ·   T/B %d/%d" % (*self.live_cent[0], *self.live_cent[1])
                if self.live_cent else "")
            fm = p.fontMetrics()
            tr = QRectF(r.x() + 16, r.y() + 64, fm.horizontalAdvance(txt) + 32, 40)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 200)); p.drawRoundedRect(tr, 8, 8)
            p.setPen(QColor(TH.OK) if locked else QColor(TH.WARN)); p.drawText(tr, Qt.AlignCenter, txt)
        if self.loupe:
            self._draw_loupe(p, r)
        if self.auto_text:
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(self.auto_text) + 40
            tr = QRectF(r.center().x() - tw / 2, r.bottom() - 120, tw, 44)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 210)); p.drawRoundedRect(tr, 10, 10)
            if self.auto_frac > 0:
                fr = QRectF(tr.x(), tr.bottom() - 5, tr.width() * min(1.0, self.auto_frac), 5)
                p.setBrush(QColor(ACCENT)); p.drawRoundedRect(fr, 2, 2)
            p.setPen(QColor("#FFFFFF")); p.drawText(tr, Qt.AlignCenter, self.auto_text)
        if self.zoom > 1:
            tr = QRectF(r.right() - 190, r.y() + 16, 174, 40)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 190)); p.drawRoundedRect(tr, 8, 8)
            p.setPen(QColor("#FFFFFF")); p.drawText(tr, Qt.AlignCenter, f"Magnified {self.zoom:.1f}x")
        if self.focus_state in ("focused", "failed"):
            col = QColor(TH.OK if self.focus_state == "focused" else TH.WARN)
            p.setPen(QPen(col, 8)); p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(4, 4, -4, -4))
            label = "In focus" if self.focus_state == "focused" else "Focus failed"
            tr = QRectF(r.x() + 16, r.y() + 16, 200, 40)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 190)); p.drawRoundedRect(tr, 8, 8)
            p.setPen(col); p.drawText(tr, Qt.AlignCenter, label)


# names from the other parts, bound once every part has loaded
from ui_base import ACCENT, CANVAS, SIGNS, _rotate_cursor  # noqa: E402
from ui_editor import fit_shape, shape_corners  # noqa: E402
