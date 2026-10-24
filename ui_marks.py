"""CardCrop status pieces, drawn natively after the React Bits micro components Anthony picked:

StatusMark  a ring that is dashed while waiting, spins as an arc while working, fills as a
            progress arc when the work counts, and draws a check (or a cross) when it ends.
Lattice     a 3 by 3 grid whose cells brighten in a wave while work runs, then settle into a
            check or a cross.
PipelineHud the lattice beside a thought line: a shimmering label with a live clock while the
            background pipeline reads cards, folding to one line ("Read 6 cards in 12.4s") when
            it is done, with the steps underneath on a click.
Chip        the call chip: an upload's step with a wash that fills as it goes, its clock, a check
            when it lands and a shake when it fails.
BorderGlow  a soft glow around a widget's rounded edge, brightest on the side the pointer is
            nearest, for the one action that matters on a screen.

All of them paint with QPainter and run their clocks only while something is moving."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPointF, QRectF, QSize, QTimer, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

import ui_base as TH
import ui_motion as motion

DONE, FAIL = "#2BB673", "#E5484D"


def _ease_io(x):           # cubic-bezier(.77,0,.175,1), close enough
    x = max(0.0, min(1.0, x))
    return 4 * x * x * x if x < 0.5 else 1 - pow(-2 * x + 2, 3) / 2


# ------------------------------------------------------------------ status mark
def paint_status_mark(p, c: QPointF, size: float, state: str, color: QColor, since: float,
                      progress: float | None = None, now: float | None = None):
    """state: pending, running, done, failed, need. since: when the state began (for the draw-on)."""
    now = time.time() if now is None else now
    r = size / 2 - 1.2
    w = max(1.4, size / 9)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    age = now - since if motion.enabled() else 10.0
    if state in ("done", "failed"):
        k = _ease_io(age / 0.3)
        fill = QColor(color)
        fill.setAlphaF(0.16 * k)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawEllipse(rect)
        p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(rect)
        s = size / 24.0
        path = QPainterPath()
        if state == "done":
            pts = [(7.5, 12.25), (10.5, 15.25), (16.75, 8.75)]
        else:
            pts = [(8.5, 8.5), (15.5, 15.5)]
        path.moveTo(c.x() + (pts[0][0] - 12) * s, c.y() + (pts[0][1] - 12) * s)
        for x, y in pts[1:]:
            path.lineTo(c.x() + (x - 12) * s, c.y() + (y - 12) * s)
        if state == "failed":
            path.moveTo(c.x() + 3.5 * s, c.y() - 3.5 * s)
            path.lineTo(c.x() - 3.5 * s, c.y() + 3.5 * s)
        draw = _ease_io((age - 0.06) / 0.24)
        if draw > 0:
            pen = QPen(color, w * 1.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            if draw < 1:
                L = path.length() / pen.widthF()
                pen.setDashPattern([L * draw, L + 1])
            p.setPen(pen)
            p.drawPath(path)
    elif state == "running":
        p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap))
        if progress is not None:
            track = QColor(color)
            track.setAlphaF(0.18)
            p.setPen(QPen(track, w))
            p.drawEllipse(rect)
            p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, 90 * 16, int(-360 * 16 * max(0.04, min(1.0, progress))))
        else:
            spin = (now % 1.1) / 1.1 * 360
            p.drawArc(rect, int((90 - spin) * 16), int(-0.68 * 360 * 16))
    else:                                   # pending or need: a dashed ring that breathes
        col = QColor(color)
        if motion.enabled():
            col.setAlphaF(0.55 + 0.45 * (0.5 + 0.5 * math.cos(now * 2 * math.pi / 2.2)))
        pen = QPen(col, w, Qt.SolidLine, Qt.FlatCap)
        circ = 2 * math.pi * r / pen.widthF()
        per = circ / 8
        pen.setDashPattern([per * 0.3, per * 0.7])
        p.setPen(pen)
        p.drawEllipse(rect)
        if state == "need":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(c, w * 0.9, w * 0.9)
    p.restore()


class StatusMark(QWidget):
    """The mark as a widget, for rows: set_state animates between states."""

    def __init__(self, size=16, parent=None):
        super().__init__(parent)
        self.setFixedSize(size + 4, size + 4)
        self.size_ = size
        self.state, self.color, self.progress, self.since = "pending", QColor(TH.T["muted"]), None, 0.0
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self._tick)

    def set_state(self, state, color=None, progress=None):
        color = QColor(color) if color else QColor(TH.T["muted"])
        if state != self.state:
            self.since = time.time()
        self.state, self.color, self.progress = state, color, progress
        self._tick()

    def _tick(self):
        self.update()
        moving = motion.enabled() and (self.state in ("running", "pending", "need")
                                       or time.time() - self.since < 0.5)
        if moving and not self.timer.isActive() and self.isVisible():
            self.timer.start()
        elif not moving:
            self.timer.stop()

    def showEvent(self, e):
        self._tick()

    def hideEvent(self, e):
        self.timer.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        paint_status_mark(p, QPointF(self.width() / 2, self.height() / 2), self.size_, self.state,
                          self.color, self.since, self.progress)


# ------------------------------------------------------------------ lattice
ORBIT = [0, 1, 2, 7, None, 3, 6, 5, 4]          # the order the wave travels round the 3 by 3
MARKS = {"done": [2, 3, 5, 7, 6], "error": [0, 2, 4, 6, 8]}


def paint_lattice(p, rect: QRectF, state: str, color: QColor, now: float, since: float, cell_gap=0.28):
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    n = 3
    cell = rect.width() / (n + (n - 1) * cell_gap)
    gap = cell * cell_gap
    loop = 8 * 0.11
    for i in range(9):
        x = rect.x() + (i % 3) * (cell + gap)
        y = rect.y() + (i // 3) * (cell + gap)
        if state == "working":
            k = ORBIT[i]
            if k is None:
                a = 0.12
            else:
                ph = ((now / loop) * 8 - k) % 8
                a = 0.15 + 0.85 * max(0.0, 1 - ph / 3.0) ** 2 if motion.enabled() else 0.5
        else:
            on = i in MARKS["done" if state == "done" else "error"]
            k = min(1.0, (now - since) / 0.3) if motion.enabled() else 1.0
            a = (0.15 + 0.85 * k) if on else 0.12 * (1 - k) + 0.08
        col = QColor(color)
        col.setAlphaF(a)
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, cell, cell), cell * 0.28, cell * 0.28)
        p.fillPath(path, col)
    p.restore()


def shimmer_text(p, rect: QRectF, text: str, color: QColor, now: float, on=True, align=Qt.AlignLeft | Qt.AlignVCenter):
    """Text with a light passing along it while work runs."""
    if not on or not motion.enabled():
        p.setPen(color)
        p.drawText(rect, align, text)
        return
    w = rect.width()
    t = (now % 1.8) / 1.8
    x = rect.x() - w * 0.5 + 2 * w * t
    g = QLinearGradient(x - 40, 0, x + 40, 0)
    dim = QColor(color)
    dim.setAlphaF(0.55)
    g.setColorAt(0, dim)
    g.setColorAt(0.5, color)
    g.setColorAt(1, dim)
    p.setPen(QPen(g, 1))
    p.drawText(rect, align, text)


class PipelineHud(QWidget):
    """Lattice and thought line for the background pipeline, made to sit in a live-view HUD.
    start(label) while working, step(text) as each card lands, finish(summary) when it is done."""

    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state, self.label, self.steps = "idle", "", []
        self.t0 = self.since = 0.0
        self.open = False
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self.update)
        self.fold = QTimer(self, singleShot=True, interval=6000)
        self.fold.timeout.connect(self._fade)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.hide()

    def sizeHint(self):
        f = QFont(TH.SANS, TH.BASE_PT)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        w = 20 + 14 + fm.horizontalAdvance(self._line() + "   00.0s") + 14
        rows = len(self.steps[-6:]) if self.open else 0
        return QSize(max(220, min(460, w)), 30 + rows * (fm.height() + 4) + (6 if rows else 0))

    def _line(self):
        return self.label

    def start(self, label):
        if self.state != "working":
            self.t0 = time.time()
            self.steps = []
        self.state, self.label, self.since = "working", label, time.time()
        self.fold.stop()
        box = self.parentWidget()
        if box is not None:
            box.setGraphicsEffect(None)
        self._grow()
        if not self.isVisible():
            self.show()
            motion.fade(self, motion.FAST)
        self.timer.start()

    def step(self, text):
        self.steps.append(text)
        self._grow()

    def finish(self, label, ok=True):
        self.state, self.label, self.since = ("done" if ok else "error"), label, time.time()
        self.open = False
        self._grow()
        QTimer.singleShot(600, self.timer.stop)
        self.fold.start()

    def _fade(self):
        """Gone a few seconds after it settles, along with the HUD it sits in."""
        if self.state != "working":
            box = self.parentWidget() or self

            def gone():
                if self.state != "working":
                    box.hide()
                    box.setGraphicsEffect(None)
            motion.fade(box, motion.MID, start=1.0, end=0.0, done=gone)

    def _grow(self):
        self.updateGeometry()
        self.adjustSize()
        if self.parentWidget() is not None and hasattr(self.parentWidget(), "adjustSize"):
            self.parentWidget().adjustSize()
        self.update()

    def mousePressEvent(self, e):
        if self.steps:
            self.open = not self.open
            self.fold.stop()
            if not self.open and self.state != "working":
                self.fold.start()
            self._grow()
            self.toggled.emit(self.open)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        now = time.time()
        hud = QColor(TH.HUD_TEXT)
        col = {"working": QColor(TH.LIME), "done": QColor(DONE), "error": QColor(FAIL)}.get(self.state, hud)
        paint_lattice(p, QRectF(6, 8, 14, 14), "working" if self.state == "working" else
                      ("done" if self.state == "done" else "error"), col, now, self.since)
        f = QFont(TH.SANS, TH.BASE_PT)
        p.setFont(f)
        fm = p.fontMetrics()
        el = (self.since if self.state != "working" else now) - self.t0
        clock = f"{el:.1f}s" if el < 60 else f"{int(el // 60)}m {el % 60:.0f}s"
        cw = fm.horizontalAdvance(clock)
        tr = QRectF(30, 0, self.width() - 30 - cw - 12, 30)
        shimmer_text(p, tr, fm.elidedText(self.label, Qt.ElideRight, int(tr.width())), hud, now,
                     on=self.state == "working")
        mf = QFont(TH.MONO, TH.BASE_PT - 1)
        p.setFont(mf)
        faint = QColor(hud)
        faint.setAlphaF(0.6)
        p.setPen(faint)
        p.drawText(QRectF(self.width() - cw - 10, 0, cw + 6, 30), Qt.AlignRight | Qt.AlignVCenter, clock)
        if self.open:
            p.setFont(f)
            y = 32
            for s in self.steps[-6:]:
                p.setPen(faint)
                p.drawText(QRectF(30, y, self.width() - 40, fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                           fm.elidedText(s, Qt.ElideRight, self.width() - 40))
                y += fm.height() + 4


# ------------------------------------------------------------------ call chip
class Chip(QWidget):
    """One upload's step as a chip: a wash fills toward 90% over the step's expected time (all
    the way when it counts photos), the clock runs, and the chip checks or shakes at the end."""

    HOLD = 0.9

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)                    # a chip, whatever the height of the row it sits in
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.text, self.frac, self.state = "", 0.0, "idle"
        self.t0 = time.time()
        self.shake = 0.0
        self.an = QVariantAnimation(self)
        self.an.valueChanged.connect(self._set_frac)
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self.update)

    def _set_frac(self, v):
        self.frac = float(v)
        self.update()

    def _go(self, to, ms, curve=QEasingCurve.OutCubic):
        self.an.stop()
        if not motion.enabled():
            self._set_frac(to)
            return
        self.an.setStartValue(self.frac)
        self.an.setEndValue(float(to))
        self.an.setDuration(int(ms))
        self.an.setEasingCurve(curve)
        self.an.start()

    def run(self, text, n=None, total=None, expected_ms=2500):
        if self.state != "running":
            self.t0 = time.time()
            self.frac = 0.0
        self.state, self.text = "running", text
        if n is not None and total:
            self._go(max(self.frac, n / total * self.HOLD), 260)
        else:
            self._go(self.HOLD, expected_ms, QEasingCurve.OutQuad)
        self.timer.start()
        self.update()

    def done(self, text):
        self.state, self.text = "done", text
        self._go(1.0, 200)
        self.since = time.time()
        QTimer.singleShot(400, self.timer.stop)

    def fail(self, text):
        self.state, self.text = "error", text
        self.since = time.time()
        if motion.enabled():
            seq = QVariantAnimation(self)
            seq.setDuration(360)
            seq.setStartValue(0.0)
            seq.setEndValue(1.0)
            seq.valueChanged.connect(lambda t: (setattr(self, "shake", math.sin(t * math.pi * 6) * 6 * (1 - t)),
                                                self.update()))
            seq.start()
        self.timer.stop()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1 + self.shake, 1, -1 + self.shake, -1)
        rad = r.height() / 2
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.fillPath(path, QColor(TH.T["pill"]))
        ink = QColor({"done": DONE, "error": FAIL}.get(self.state, TH.T["text"]))
        wash = QColor(ink)
        wash.setAlphaF(0.14 if self.state != "running" else 0.10)
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(r.x(), r.y(), r.width() * self.frac, r.height()), wash)
        p.restore()
        st = {"running": "running", "done": "done", "error": "failed"}.get(self.state, "pending")
        ms = 12.0
        paint_status_mark(p, QPointF(r.x() + 8 + ms / 2, r.center().y()), ms, st, ink,
                          getattr(self, "since", 0.0))
        f = QFont(TH.SANS, TH.BASE_PT - 1)
        p.setFont(f)
        fm = p.fontMetrics()
        el = time.time() - self.t0
        clock = f"{el:.1f}s" if self.state == "running" else ""
        cw = fm.horizontalAdvance(clock) + (10 if clock else 0)
        if clock and fm.horizontalAdvance(self.text) > r.width() - (8 + 12 + 7) - cw - 12:
            clock, cw = "", 0                       # the words matter more than the clock in a narrow chip
        p.setPen(QColor(TH.T["text"]))
        tr = QRectF(r.x() + 8 + ms + 7, r.y(), r.width() - (8 + ms + 7) - cw - 8, r.height())
        p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(self.text, Qt.ElideRight, int(tr.width())))
        if clock:
            p.setFont(QFont(TH.MONO, TH.BASE_PT - 2))
            p.setPen(QColor(TH.T["muted"]))
            p.drawText(QRectF(r.right() - cw - 6, r.y(), cw, r.height()), Qt.AlignRight | Qt.AlignVCenter, clock)


# ------------------------------------------------------------------ border glow
class BorderGlow(QObject):
    """Installs on a widget: a lime glow hugs its rounded edge, gathering on the side the pointer is
    nearest and brightening as it comes close, and breathing softly when the pointer is away."""

    def __init__(self, target: QWidget, radius=None, color=None):
        super().__init__(target)
        self.w = target
        self.radius = radius
        self.color = QColor(color or TH.LIME)
        self.ang, self.near = -90.0, 0.0
        self.ov = _GlowOverlay(self)
        target.installEventFilter(self)
        target.setMouseTracking(True)
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self.ov.update)
        self.timer.start()

    def eventFilter(self, o, e):
        t = e.type()
        if t in (QEvent.Resize, QEvent.Show, QEvent.Move, QEvent.Hide):
            self.ov.place()
        elif t == QEvent.MouseMove:
            c = QPointF(o.width() / 2, o.height() / 2)
            d = e.position() - c
            self.ang = math.degrees(math.atan2(d.y(), d.x()))
            ex = min(e.position().x(), o.width() - e.position().x(), e.position().y(), o.height() - e.position().y())
            self.near = max(0.0, 1.0 - ex / max(8.0, o.height() * 0.6))
        elif t == QEvent.Leave:
            self.near = 0.0
        return False


class _GlowOverlay(QWidget):
    PAD = 4

    def __init__(self, glow):
        super().__init__(glow.w.parentWidget())
        self.g = glow
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.place()

    def place(self):
        w = self.g.w
        if self.parentWidget() is not w.parentWidget():
            self.setParent(w.parentWidget())
        if self.parentWidget() is None:
            return
        g = w.geometry().adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD)
        self.setGeometry(g)
        self.setVisible(w.isVisible())
        self.stackUnder(w)

    def paintEvent(self, e):
        if not motion.enabled() or not self.g.w.isEnabled():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.g.w
        r = QRectF(self.PAD, self.PAD, w.width(), w.height())
        rad = self.g.radius if self.g.radius is not None else r.height() / 2
        breathe = 0.5 + 0.5 * math.sin(time.time() * 2 * math.pi / 3.2)
        base = 0.30 + 0.12 * breathe
        hot = base + 0.45 * self.g.near
        cx = r.center().x() + math.cos(math.radians(self.g.ang)) * r.width() / 2
        cy = r.center().y() + math.sin(math.radians(self.g.ang)) * r.height() / 2
        for i, (grow, a) in enumerate(((2.5, 0.16), (1.0, 0.5))):
            path = QPainterPath()
            rr = r.adjusted(-grow, -grow, grow, grow)
            path.addRoundedRect(rr, rad + grow, rad + grow)
            g = QRadialGradient(QPointF(cx, cy), max(r.width(), r.height()) * 0.75)
            c1 = QColor(self.g.color)
            c1.setAlphaF(min(1.0, a * hot * 2.2))
            c2 = QColor(self.g.color)
            c2.setAlphaF(a * base * 0.6)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.setPen(QPen(g, 1.2 if i == 1 else 2.0))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)


# ------------------------------------------------------------------ marker
class Marker(QWidget):
    """A separator with its label in the middle, lines either side: a day heading in a list."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
        self.setFixedHeight(30)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(TH.SANS, TH.BASE_PT - 1)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(self.text) + 24
        cy = self.height() / 2
        line = QColor(TH.T["line"])
        p.setPen(QPen(line, 1))
        x0 = (self.width() - tw) / 2
        p.drawLine(QPointF(8, cy), QPointF(x0, cy))
        p.drawLine(QPointF(x0 + tw, cy), QPointF(self.width() - 8, cy))
        p.setPen(QColor(TH.T["muted"]))
        p.drawText(QRectF(x0, 0, tw, self.height()), Qt.AlignCenter, self.text)
