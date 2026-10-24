"""CardCrop corner editor: the photo view with draggable corners and the card-shape tool."""
from __future__ import annotations

import cv2
import engine
import math
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QFrame, QGraphicsEllipseItem, QGraphicsItem, QGraphicsPixmapItem, QGraphicsPolygonItem, QGraphicsScene, QGraphicsView, QWidget
import ui_base as TH

class CropView(QWidget):
    """The card with the close-up window on it: drag to move, scroll to resize."""

    def __init__(self, img_bgr, crop, on_change):
        super().__init__()
        self.img = to_qimage(img_bgr)
        self.shape = img_bgr.shape
        self.crop = list(crop)
        self.on_change = on_change
        self._drag = None
        self.setMinimumSize(320, 420)
        self.setCursor(Qt.SizeAllCursor)

    def _frame(self):
        h, w = self.shape[:2]
        k = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * k) / 2, (self.height() - h * k) / 2, w * k, h * k), k

    def _rect(self):
        r, k = self._frame()
        x, y, w, h = engine.ig_crop_rect(self.shape, self.crop)
        return QRectF(r.x() + x * k, r.y() + y * k, w * k, h * k)

    def _clamp(self):
        h, w = self.shape[:2]
        x, y, cw, ch = engine.ig_crop_rect(self.shape, self.crop)
        self.crop = [x / w, y / h, cw / w]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(TH.BG))
        r, _ = self._frame()
        p.drawImage(r, self.img)
        c = self._rect()
        shade = QPainterPath(); shade.addRect(r)
        hole = QPainterPath(); hole.addRect(c)
        p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 150))
        p.setPen(QPen(QColor(ACCENT), 3)); p.setBrush(Qt.NoBrush); p.drawRect(c)
        p.setPen(QPen(QColor(ACCENT), 2, Qt.DashLine))
        p.drawLine(QPointF(c.center().x(), c.top()), QPointF(c.center().x(), c.bottom()))   # the swipe seam

    def mousePressEvent(self, e):
        self._drag = (e.position(), list(self.crop))

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        (p0, c0), (_, k) = self._drag, self._frame()
        h, w = self.shape[:2]
        d = e.position() - p0
        self.crop = [c0[0] + d.x() / k / w, c0[1] + d.y() / k / h, c0[2]]
        self._clamp()
        self.update()
        self.on_change()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def set_width(self, fw):
        h, w = self.shape[:2]
        x, y, cw, ch = engine.ig_crop_rect(self.shape, self.crop)
        cx, cy = x + cw / 2, y + ch / 2               # resize about the centre
        nw = fw * w
        nh = nw * engine.IG_H / (2 * engine.IG_W)
        self.crop = [(cx - nw / 2) / w, (cy - nh / 2) / h, fw]
        self._clamp()
        self.update()

    def wheelEvent(self, e):
        f = self.crop[2] * (0.95 if e.angleDelta().y() > 0 else 1.05)
        self.set_width(min(1.0, max(0.2, f)))
        self.on_change(from_wheel=True)


def shape_corners(cx, cy, w, a):
    """Corners of an upright-ratio card of width w, centred, rotated by a."""
    h = w / engine.CARD_RATIO
    u = np.array([math.cos(a), math.sin(a)])
    v = np.array([-math.sin(a), math.cos(a)])
    c = np.array([cx, cy])
    return np.array([c + sx * w / 2 * u + sy * h / 2 * v for sx, sy in SIGNS], np.float32)


def fit_shape(quad):
    """Closest card-proportioned rectangle to an arbitrary quad."""
    q = np.asarray(quad, np.float64)
    c = q.mean(axis=0)
    top, bottom = q[1] - q[0], q[2] - q[3]
    d = top / (np.linalg.norm(top) + 1e-9) + bottom / (np.linalg.norm(bottom) + 1e-9)
    a = math.atan2(d[1], d[0])
    w = (np.linalg.norm(top) + np.linalg.norm(bottom)) / 2
    h = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    w = max(20.0, (w + h * engine.CARD_RATIO) / 2)
    return (float(c[0]), float(c[1]), float(w), float(a))


class Handle(QGraphicsEllipseItem):
    R = 16

    def __init__(self, idx, editor):
        super().__init__(-self.R, -self.R, 2 * self.R, 2 * self.R)
        self.idx, self.editor = idx, editor
        self.setBrush(QBrush(QColor(0, 0, 0, 90)))
        self.setPen(QPen(QColor(ACCENT), 4))
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges
                      | QGraphicsItem.ItemIgnoresTransformations | QGraphicsItem.ItemIsSelectable)
        self.setCursor(Qt.SizeAllCursor)
        self.setZValue(10)

    def boundingRect(self):
        r = self.R + 10
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(self, painter, option, widget=None):
        """Ring plus a crosshair whose centre is the exact corner point. The arms
        reach past the ring and carry a dark outline so they read on any card."""
        painter.setRenderHint(QPainter.Antialiasing)
        col = QColor("#FFFFFF" if self.isSelected() else ACCENT)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 160), 7))
        painter.drawEllipse(QPointF(0, 0), self.R, self.R)
        painter.setPen(QPen(col, 3.5))
        painter.drawEllipse(QPointF(0, 0), self.R, self.R)
        arm, gap = self.R + 8, 4
        for pen in (QPen(QColor(0, 0, 0, 200), 4), QPen(col, 1.6)):
            painter.setPen(pen)
            painter.drawLine(QPointF(-arm, 0), QPointF(-gap, 0))
            painter.drawLine(QPointF(gap, 0), QPointF(arm, 0))
            painter.drawLine(QPointF(0, -arm), QPointF(0, -gap))
            painter.drawLine(QPointF(0, gap), QPointF(0, arm))
        painter.setPen(Qt.NoPen)
        painter.setBrush(col)
        painter.drawEllipse(QPointF(0, 0), 1.3, 1.3)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.editor.handle_moved(self.idx)
        return super().itemChange(change, value)

    def mousePressEvent(self, e):
        self.editor.about_to_change.emit()
        self.editor.drag_idx = self.idx
        self.editor.set_lit(True)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.editor.mode == "shape":
            # rigid card: the editor moves all four corners together
            self.editor.shape_drag(self.idx, e.scenePos(), e.modifiers())
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.editor.drag_idx = None
        self.editor.set_lit(False)
        self.editor.viewport().update()
        self.editor.committed.emit()


class Editor(QGraphicsView):
    """Source photo with a draggable quad, zoom, pan and a magnifier loupe."""

    changed = Signal()          # quad moved (throttled preview)
    committed = Signal()        # drag finished
    about_to_change = Signal()  # snapshot for undo

    LOUPE = 360
    # loupe field radius as a share of card width: about 4, 7.5 and 12 mm
    # on a 63 mm card, so the straight edge runs past the rounded corner show
    FIELDS = (0.065, 0.12, 0.19)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor(CANVAS))
        self.setFrameShape(QFrame.NoFrame)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.pix = QGraphicsPixmapItem()
        self.pix.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.pix)
        self.poly = QGraphicsPolygonItem()
        self.poly.setPen(QPen(QColor(ACCENT), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p = self.poly.pen(); p.setCosmetic(True); self.poly.setPen(p)
        self.poly.setZValue(5)
        self.scene().addItem(self.poly)
        self.handles = [Handle(i, self) for i in range(4)]
        for h in self.handles:
            self.scene().addItem(h)
            h.hide()
        self.qimg: QImage | None = None
        self.drag_idx = None
        self._block = False
        self.field_idx = 1
        self.view_rot = 0           # editor view rotation, matches the output rotation
        self._rot = None            # rotate-zone drag in shape mode
        self.viewport().setMouseTracking(True)
        self._rot_cursor = _rotate_cursor()
        self.mode = "corners"       # "corners": free handles; "shape": locked 63x88 card
        self.shape = None           # (cx, cy, width, angle) in shape mode
        self._body = None           # body-drag start in shape mode

    # --- data
    def set_image(self, qimg: QImage):
        self.qimg = qimg
        self._lit = None                 # the brightened copy, made the first time a corner is grabbed
        self._lit_on = False
        self.pix.setPixmap(QPixmap.fromImage(qimg))
        self.scene().setSceneRect(QRectF(qimg.rect()).adjusted(-400, -400, 400, 400))
        self.fit()

    def lit_image(self):
        """The photo lifted for finding corners in a dark shot: stretched between its darkest and brightest
        tones and opened up in the shadows, so a black border reads against a dark mat."""
        if getattr(self, "_lit", None) is None and self.qimg is not None:
            q = self.qimg.convertToFormat(QImage.Format_RGB888)
            a = np.frombuffer(q.constBits(), np.uint8, q.bytesPerLine() * q.height()).reshape(
                q.height(), q.bytesPerLine())[:, :q.width() * 3].reshape(q.height(), q.width(), 3)
            lo, hi = np.percentile(a[::6, ::6].mean(axis=2), (0.5, 99.7))
            lut = (np.clip((np.arange(256, dtype=np.float32) - lo) / max(8.0, hi - lo), 0, 1) ** 0.55 * 255)
            out = np.ascontiguousarray(cv2.LUT(np.ascontiguousarray(a), lut.astype(np.uint8)))
            self._lit = QImage(out.data, out.shape[1], out.shape[0], out.shape[1] * 3, QImage.Format_RGB888).copy()
        return getattr(self, "_lit", None)

    def set_lit(self, on):
        """Light the photo up while a corner is held, back to the true photo when it is let go."""
        if self.qimg is None or on == getattr(self, "_lit_on", False):
            return
        img = self.lit_image() if on else self.qimg
        if img is None:
            return
        self._lit_on = on
        self.pix.setPixmap(QPixmap.fromImage(img))
        self.viewport().update()

    def clear(self):
        self.qimg = None
        self.pix.setPixmap(QPixmap())
        self.poly.setPolygon(QPolygonF())
        for h in self.handles:
            h.hide()

    def set_quad(self, quad: np.ndarray):
        self._block = True
        for h, (x, y) in zip(self.handles, quad):
            h.setPos(float(x), float(y))
            h.show()
        self._block = False
        if self.mode == "shape":
            self.shape = fit_shape(quad)
            self._apply_shape()
        self._sync_poly()

    # --- card-shape mode
    def set_mode(self, mode: str):
        self.mode = mode
        pen = self.poly.pen()
        pen.setStyle(Qt.DashLine if mode == "shape" else Qt.SolidLine)
        self.poly.setPen(pen)
        if mode == "shape" and self.handles[0].isVisible():
            self.shape = fit_shape(self.quad())
            self._apply_shape()

    def _apply_shape(self):
        q = shape_corners(*self.shape)
        self._block = True
        for h, (x, y) in zip(self.handles, q):
            h.setPos(float(x), float(y))
        self._block = False
        self._sync_poly()
        self.viewport().update()

    def shape_drag(self, idx, p, mods):
        cx, cy, w, a = self.shape
        u = np.array([math.cos(a), math.sin(a)])
        v = np.array([-math.sin(a), math.cos(a)])
        sx, sy = SIGNS[idx]
        P = np.array([p.x(), p.y()])
        C = np.array([cx, cy])
        r = engine.CARD_RATIO
        if mods & Qt.ShiftModifier:
            # rotate about the centre, keeping size
            base = math.atan2(sy * w / r / 2, sx * w / 2)
            a = math.atan2(P[1] - cy, P[0] - cx) - base
        elif mods & (Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier):
            # Cmd (or Alt): grow from the centre
            d = P - C
            w = max(20.0, 2 * max(abs(d @ u), abs(d @ v) * r))
        else:
            # anchored at the opposite corner, card proportions locked
            opp = shape_corners(cx, cy, w, a)[(idx + 2) % 4]
            d = P - opp
            w = max(20.0, d @ u * sx, d @ v * sy * r)
            h = w / r
            C = opp + sx * w / 2 * u + sy * h / 2 * v
            cx, cy = C
        self.shape = (float(cx), float(cy), float(w), float(a))
        self._apply_shape()
        self.changed.emit()

    def mousePressEvent(self, e):
        if self.mode == "shape" and e.button() == Qt.LeftButton and self.handles[0].isVisible():
            sp = self.mapToScene(e.position().toPoint())
            item = self.itemAt(e.position().toPoint())
            if not isinstance(item, Handle) and self._rot_zone(e.position().toPoint()):
                self.about_to_change.emit()
                cx, cy = self.shape[0], self.shape[1]
                self._rot = (math.atan2(sp.y() - cy, sp.x() - cx), self.shape)
                self.setDragMode(QGraphicsView.NoDrag)
                e.accept()
                return
            if not isinstance(item, Handle) and self.poly.polygon().containsPoint(sp, Qt.OddEvenFill):
                self.about_to_change.emit()
                self._body = (sp, self.shape)
                self.setDragMode(QGraphicsView.NoDrag)
                self.viewport().setCursor(Qt.ClosedHandCursor)
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._rot is not None:
            self._rot = None
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.committed.emit()
            e.accept()
            return
        if self._body is not None:
            self._body = None
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.viewport().unsetCursor()
            self.committed.emit()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def quad(self) -> np.ndarray:
        return np.array([[h.pos().x(), h.pos().y()] for h in self.handles], np.float32)

    def fit(self):
        self._zoomed = False
        self.resetTransform()
        self.rotate(self.view_rot)
        if self.qimg is not None:
            self.fitInView(QRectF(self.qimg.rect()).adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)

    def set_view_rotation(self, deg):
        self.view_rot = deg % 360
        self.fit()

    ROT_ZONE = 48   # px outside a corner where dragging rotates the card shape

    def _rot_zone(self, vpos):
        """True when the pointer is just outside a corner of the card shape."""
        if self.mode != "shape" or not self.handles[0].isVisible():
            return False
        sp = self.mapToScene(vpos)
        if self.poly.polygon().containsPoint(sp, Qt.OddEvenFill):
            return False
        for h in self.handles:
            hv = self.mapFromScene(h.pos())
            d = math.hypot(hv.x() - vpos.x(), hv.y() - vpos.y())
            if Handle.R - 2 < d < self.ROT_ZONE:
                return True
        return False

    # --- interaction
    def handle_moved(self, idx):
        if self._block:
            return
        self._sync_poly()
        self.viewport().update()
        self.changed.emit()

    def _sync_poly(self):
        self.poly.setPolygon(QPolygonF([h.pos() for h in self.handles]))

    def wheelEvent(self, e):
        f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        self.scale(f, f)
        self._zoomed = True

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not getattr(self, "_zoomed", False):
            self.fit()

    def keyPressEvent(self, e):
        sel = [h for h in self.handles if h.isSelected()]
        step = 10 if e.modifiers() & Qt.ShiftModifier else 1
        d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0),
             Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}.get(e.key())
        if d and self.mode == "shape" and self.shape is not None:
            # arrows move the whole card in shape mode
            if not e.isAutoRepeat():
                self.about_to_change.emit()
            cx, cy, w, a = self.shape
            self.shape = (cx + d[0], cy + d[1], w, a)
            self._apply_shape()
            self.committed.emit()
            return
        if sel and d:
            if not e.isAutoRepeat():
                self.about_to_change.emit()
            for h in sel:
                h.moveBy(*d)
            self.committed.emit()
            return
        super().keyPressEvent(e)

    def mouseMoveEvent(self, e):
        if self._rot is not None:
            a0, (cx, cy, w, a) = self._rot
            sp = self.mapToScene(e.position().toPoint())
            da = math.atan2(sp.y() - cy, sp.x() - cx) - a0
            if e.modifiers() & Qt.ShiftModifier:      # Shift snaps to whole degrees
                da = math.radians(round(math.degrees(a + da))) - a
            self.shape = (cx, cy, w, a + da)
            self._apply_shape()
            self.changed.emit()
            e.accept()
            return
        if self._body is None and self.drag_idx is None and not (e.buttons() & Qt.LeftButton):
            # hover feedback in shape mode: rotate just outside a corner, move inside
            vpos = e.position().toPoint()
            if self._rot_zone(vpos):
                self.viewport().setCursor(self._rot_cursor)
            elif self.mode == "shape" and self.handles[0].isVisible() and \
                    self.poly.polygon().containsPoint(self.mapToScene(vpos), Qt.OddEvenFill):
                self.viewport().setCursor(Qt.SizeAllCursor)
            else:
                self.viewport().setCursor(Qt.OpenHandCursor)
        if self._body is not None:
            start, (cx, cy, w, a) = self._body
            sp = self.mapToScene(e.position().toPoint())
            self.shape = (cx + sp.x() - start.x(), cy + sp.y() - start.y(), w, a)
            self._apply_shape()
            self.changed.emit()
            e.accept()
            return
        super().mouseMoveEvent(e)
        if self.drag_idx is not None:
            self.viewport().update()

    # --- loupe
    def cycle_loupe(self):
        self.field_idx = (self.field_idx + 1) % len(self.FIELDS)
        return self.FIELDS[self.field_idx]

    def drawForeground(self, painter: QPainter, rect):
        if self.drag_idx is None or self.qimg is None:
            return
        q = self.quad()
        i = self.drag_idx
        c = QPointF(*q[i])
        card_w = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
        src_r = max(12.0, self.FIELDS[self.field_idx] * card_w)
        src = QRectF(c.x() - src_r, c.y() - src_r, 2 * src_r, 2 * src_r)
        painter.save()
        painter.resetTransform()
        # park the loupe in the view corner away from the handle
        vp = self.mapFromScene(c)
        x = 20 if vp.x() > self.viewport().width() / 2 else self.viewport().width() - self.LOUPE - 20
        dst = QRectF(x, 20, self.LOUPE, self.LOUPE)
        k = self.LOUPE / src.width()
        to_l = lambda px, py: QPointF(dst.x() + (px - src.x()) * k, dst.y() + (py - src.y()) * k)  # noqa: E731
        if self.view_rot:
            # show the loupe the same way up as the rotated view
            painter.translate(dst.center())
            painter.rotate(self.view_rot)
            painter.translate(-dst.center())
        path = QPainterPath()
        path.addEllipse(dst)
        painter.setClipPath(path)
        painter.fillRect(dst, QColor("#000"))
        painter.setRenderHint(QPainter.SmoothPixmapTransform, k < 2.5)
        painter.drawImage(dst, self.lit_image() if getattr(self, "_lit_on", False) else self.qimg, src)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # each edge through this corner, extended far past it: line the guides up
        # with the straight runs of the card edge and the crossing is the corner
        for j in ((i + 1) % 4, (i + 3) % 4):
            d = q[j] - q[i]
            d = d / (np.linalg.norm(d) + 1e-9)
            far = 4 * src_r
            a = to_l(*(q[i] - d * far))
            b = to_l(*(q[i] + d * far))
            painter.setPen(QPen(QColor(0, 0, 0, 170), 4))
            painter.drawLine(a, b)
            painter.setPen(QPen(QColor(ACCENT), 1.6, Qt.DashLine))
            painter.drawLine(a, b)
        mid = dst.center()
        for pen in (QPen(QColor(0, 0, 0, 200), 4), QPen(QColor("#FFFFFF"), 1.5)):
            painter.setPen(pen)
            painter.drawLine(QPointF(mid.x() - 30, mid.y()), QPointF(mid.x() - 6, mid.y()))
            painter.drawLine(QPointF(mid.x() + 6, mid.y()), QPointF(mid.x() + 30, mid.y()))
            painter.drawLine(QPointF(mid.x(), mid.y() - 30), QPointF(mid.x(), mid.y() - 6))
            painter.drawLine(QPointF(mid.x(), mid.y() + 6), QPointF(mid.x(), mid.y() + 30))
        painter.setClipping(False)
        painter.resetTransform()
        painter.setPen(QPen(QColor(ACCENT), 4))
        painter.drawEllipse(dst)
        # field size readout under the loupe, large enough to read
        mm = 2 * src_r / max(card_w, 1) * 63
        f = painter.font()
        f.setPointSize(TH.BASE_PT)
        f.setBold(True)
        painter.setFont(f)
        label = f"{mm:.0f} mm across   ·   Z to change"
        tr = QRectF(dst.x() - 40, dst.bottom() + 8, dst.width() + 80, 32)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 190))
        painter.drawRoundedRect(tr, 8, 8)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(tr, Qt.AlignCenter, label)
        painter.restore()


# names from the other parts, bound once every part has loaded
from ui_base import ACCENT, CANVAS, SIGNS, _rotate_cursor, to_qimage  # noqa: E402
