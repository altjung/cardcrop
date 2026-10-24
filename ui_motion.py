"""CardCrop motion: stage cross-fades, the sliding rail marker, press ripples, toast entrances,
row cascades, skeleton loaders, the indeterminate loading bar, filmstrip pop-ins and the shutter
flash.

Everything here is drawn on small overlays or animates an opacity effect that is removed again
when the animation ends, so nothing keeps costing time after it has played, and the live view
is never put under an effect. Settings > App > Motion turns all of it off (set_motion)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPointF, QPropertyAnimation, QRect, QRectF,
                            QTimer, Qt, QVariantAnimation)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QPushButton, QToolButton, QWidget

import ui_base as TH

MOTION = True          # Settings > App > Motion
FAST, MID, SLOW = 160, 240, 420


def set_motion(on):
    global MOTION
    MOTION = bool(on)


def enabled():
    return MOTION


def _alive(w):
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


# ------------------------------------------------------------------ fades
def fade(w, ms=MID, start=0.0, end=1.0, delay=0, done=None, curve=QEasingCurve.OutCubic):
    """Fades a widget between two opacities, then removes the effect (it costs nothing after)."""
    if not MOTION or w is None:
        if done:
            done()
        return None
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(start)
    w.setGraphicsEffect(eff)
    an = QPropertyAnimation(eff, b"opacity", w)
    an.setDuration(ms)
    an.setStartValue(start)
    an.setEndValue(end)
    an.setEasingCurve(curve)

    def fin():
        if _alive(w) and end >= 1.0:
            try:
                w.setGraphicsEffect(None)
            except RuntimeError:
                pass
        if done:
            done()
    an.finished.connect(fin)
    if delay:
        QTimer.singleShot(delay, an.start)
    else:
        an.start()
    return an


def cascade(widgets, step=26, ms=MID, limit=14):
    """Rows arrive one after another from the top instead of all at once; past the first screenful
    they simply appear, so a long list never waits on its own entrance."""
    if not MOTION:
        return
    for i, w in enumerate(widgets[:limit]):
        fade(w, ms, delay=i * step)


# ------------------------------------------------------------------ stage cross-fade
class _Snapshot(QLabel):
    def __init__(self, parent, pm, rect):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setPixmap(pm)
        self.setGeometry(rect)
        self.show()
        self.raise_()


def crossfade(stack, index, skip=()):
    """Switches a stacked widget, laying a picture of the old page over the new one and fading
    it out while it drifts a few points, so pages dissolve into each other."""
    old = stack.currentWidget()
    if (not MOTION or not stack.isVisible() or old is None or stack.currentIndex() == index
            or old in skip or stack.widget(index) in skip):
        stack.setCurrentIndex(index)
        return
    try:
        pm = old.grab()
    except RuntimeError:
        stack.setCurrentIndex(index)
        return
    stack.setCurrentIndex(index)
    snap = _Snapshot(stack, pm, QRect(0, 0, stack.width(), stack.height()))
    eff = QGraphicsOpacityEffect(snap)
    snap.setGraphicsEffect(eff)
    an = QVariantAnimation(snap)
    an.setDuration(220)
    an.setStartValue(0.0)
    an.setEndValue(1.0)
    an.setEasingCurve(QEasingCurve.OutCubic)

    def step(t):
        eff.setOpacity(1.0 - t)
        snap.move(0, int(-10 * t))
    an.valueChanged.connect(step)
    an.finished.connect(snap.deleteLater)
    an.start()
    # never left over the page: if the fade is held up (a busy moment), the picture still goes
    QTimer.singleShot(900, lambda: _drop(snap))


def _drop(w):
    try:
        w.deleteLater()
    except RuntimeError:
        pass


# ------------------------------------------------------------------ rail marker
class RailPill(QWidget):
    """The rounded marker behind the current stage in the rail. It glides to the button you
    pick rather than jumping, so the eye follows where you went."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.target = None
        self.an = QPropertyAnimation(self, b"geometry", self)
        self.an.setDuration(320)
        self.an.setEasingCurve(QEasingCurve.OutBack)
        self.lower()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 16, 16)
        p.fillPath(path, QColor(TH.T["pill"]))

    def move_to(self, button, animate=True):
        self.target = button
        if button is None or not button.isVisible():
            self.hide()
            return
        r = button.geometry()
        if self.parent() is not button.parent():
            tl = button.mapTo(self.parent(), button.rect().topLeft())
            r = QRect(tl, button.size())
        self.show()
        self.lower()
        if not MOTION or not animate or self.geometry().isEmpty() or not self.isVisible():
            self.an.stop()
            self.setGeometry(r)
            return
        self.an.stop()
        self.an.setStartValue(self.geometry())
        self.an.setEndValue(r)
        self.an.start()

    def follow(self):
        """Keeps the marker on its button after a resize or the rail turning compact."""
        if self.target is not None and self.an.state() != QPropertyAnimation.Running:
            self.move_to(self.target, animate=False)


# ------------------------------------------------------------------ press ripple
class _Ripple(QWidget):
    def __init__(self, button, pos, light):
        super().__init__(button)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(button.rect())
        self.c = QPointF(pos)
        self.light = light
        r = self.rect()
        self.reach = max(math.hypot(self.c.x() - x, self.c.y() - y)
                         for x, y in ((0, 0), (r.width(), 0), (0, r.height()), (r.width(), r.height())))
        self.t = 0.0
        self.released = False
        self.an = QVariantAnimation(self)
        self.an.setStartValue(0.0)
        self.an.setEndValue(1.0)
        self.an.setDuration(SLOW)
        self.an.setEasingCurve(QEasingCurve.OutCubic)
        self.an.valueChanged.connect(self._tick)
        self.an.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        self.an.start()

    def _tick(self, t):
        self.t = float(t)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        rad = min(self.height() / 2, 16)
        clip.addRoundedRect(QRectF(self.rect()), rad, rad)
        p.setClipPath(clip)
        a = (1.0 - max(0.0, (self.t - 0.5) / 0.5)) * (0.30 if self.light else 0.20)
        col = QColor(255, 255, 255) if self.light else QColor(TH.T["ink"])
        col.setAlphaF(max(0.0, a))
        p.setBrush(col)
        p.setPen(Qt.NoPen)
        r = 6 + (self.reach - 6) * self.t
        p.drawEllipse(self.c, r, r)


class PressFilter(QObject):
    """App-wide: a soft ripple spreads from where you press any button, so every click answers."""

    LIGHT = {"primary", "accent", "hud", "lime"}

    def eventFilter(self, o, e):
        if MOTION and e.type() == QEvent.MouseButtonPress and isinstance(o, (QPushButton, QToolButton)):
            try:
                if o.isEnabled() and o.width() > 8:
                    light = o.objectName() in self.LIGHT or TH.THEME == "dark"
                    _Ripple(o, e.position() if hasattr(e, "position") else e.pos(), light)
            except RuntimeError:
                pass
        return False


def shake(w, px=6, ms=360):
    """A short side-to-side shake, for something that failed."""
    if not MOTION or w is None:
        return
    base = w.pos()
    an = QVariantAnimation(w)
    an.setDuration(ms)
    an.setStartValue(0.0)
    an.setEndValue(1.0)
    an.valueChanged.connect(lambda t: _alive(w) and w.move(base.x() + int(math.sin(t * math.pi * 6) * px * (1 - t)),
                                                          base.y()))
    an.finished.connect(lambda: _alive(w) and w.move(base))
    an.start()


# ------------------------------------------------------------------ toasts
def toast_in(w):
    """The notice rises a little as it fades up."""
    if not MOTION:
        return
    end = w.pos()
    w.move(end.x(), end.y() + 14)
    an = QPropertyAnimation(w, b"pos", w)
    an.setDuration(300)
    an.setStartValue(w.pos())
    an.setEndValue(end)
    an.setEasingCurve(QEasingCurve.OutBack)
    an.start()
    fade(w, 220)


def toast_out(w, hide):
    if not MOTION or not w.isVisible():
        hide()
        return
    fade(w, FAST, start=1.0, end=0.0, done=lambda: (hide(), _alive(w) and w.setGraphicsEffect(None)),
         curve=QEasingCurve.InCubic)


# ------------------------------------------------------------------ loading states
class LoadingBar(QWidget):
    """A thin bar that sweeps along the top of a page while it is fetching."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.t0 = 0.0
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self.update)
        self.hide()

    def start(self):
        p = self.parentWidget()
        self.setGeometry(0, 0, p.width(), 3)
        self.t0 = time.time()
        self.show()
        self.raise_()
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self.hide()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        t = ((time.time() - self.t0) / 1.1) % 1.0
        seg = w * 0.32
        x = -seg + (w + seg) * QEasingCurve(QEasingCurve.InOutCubic).valueForProgress(t)
        g = QLinearGradient(x, 0, x + seg, 0)
        c = QColor(TH.LIME)
        c0 = QColor(c)
        c0.setAlpha(0)
        g.setColorAt(0, c0)
        g.setColorAt(0.5, c)
        g.setColorAt(1, c0)
        p.fillRect(QRectF(x, 0, seg, self.height()), g)


class Skeleton(QWidget):
    """Grey placeholder rows with a light sweeping across them, laid over a page until its
    first data arrives. It waits a beat before showing, so a fast load never flashes it."""

    def __init__(self, parent, rows=8, row_h=64, top=96):
        super().__init__(parent)
        self.rows, self.row_h, self.top = rows, row_h, top
        self.t0 = time.time()
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self.update)
        self.wait = QTimer(self, singleShot=True, interval=140)
        self.wait.timeout.connect(self._appear)
        self.hide()

    def begin(self):
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setGeometry(self.parentWidget().rect())
        self.wait.start()

    def _appear(self):
        self.setGeometry(self.parentWidget().rect())
        self.t0 = time.time()
        self.show()
        self.raise_()
        self.timer.start()
        fade(self, FAST)

    def finish(self):
        self.wait.stop()
        if not self.isVisible():
            return

        def gone():
            self.timer.stop()
            self.hide()
            if _alive(self):
                self.setGraphicsEffect(None)
        fade(self, MID, start=1.0, end=0.0, done=gone)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, self.top - 12, self.width(), self.height()), QColor(TH.T["ground"]))  # the header stays
        base = QColor(TH.T["hover"])
        hi = QColor(TH.T["island2"])
        w = self.width()
        sweep = ((time.time() - self.t0) / 1.4) % 1.0
        sx = -w * 0.4 + w * 1.8 * sweep
        g = QLinearGradient(sx, 0, sx + w * 0.4, 0)
        g.setColorAt(0, base)
        g.setColorAt(0.5, hi)
        g.setColorAt(1, base)
        y = self.top
        for i in range(self.rows):
            if y > self.height():
                break
            r = QRectF(24, y, w - 48, self.row_h - 10)
            card = QPainterPath()
            card.addRoundedRect(r, 14, 14)
            p.fillPath(card, QColor(TH.T["island"]))
            for rr, rad in ((QRectF(r.x() + 12, r.y() + 8, 40, r.height() - 16), 6),
                            (QRectF(r.x() + 66, r.y() + 12, (r.width() - 90) * (0.55 - 0.07 * (i % 3)), 12), 6),
                            (QRectF(r.x() + 66, r.y() + 32, (r.width() - 90) * 0.28, 10), 5),
                            (QRectF(r.right() - 120, r.y() + 16, 96, 14), 7)):
                path = QPainterPath()
                path.addRoundedRect(rr, rad, rad)
                p.fillPath(path, g)
            y += self.row_h


# ------------------------------------------------------------------ filmstrip pop-in
class StripPulse(QObject):
    """Repaints the filmstrip for a moment after a thumbnail lands, so the tile delegate can
    ease it in (it reads born times from the item data)."""

    def __init__(self, viewport):
        super().__init__(viewport)
        self.vp = viewport
        self.until = 0.0
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self._tick)

    def kick(self, secs=0.45):
        if not MOTION:
            return
        self.until = max(self.until, time.time() + secs)
        self.__dict__.pop("_kept_since", None)       # fresh news: the cap starts again
        if not self.timer.isActive():
            self.timer.start()

    def _tick(self):
        try:
            self.vp.update()
        except RuntimeError:
            self.timer.stop()
            return
        if time.time() > self.until:
            keep = getattr(self, "keep", None)
            if keep is not None and keep() and time.time() - getattr(self, "_kept_since", time.time()) < 90:
                if not hasattr(self, "_kept_since"):
                    self._kept_since = time.time()
                self.until = time.time() + 0.5      # something is still working: keep its mark turning
            else:
                self.timer.stop()
                self.__dict__.pop("_kept_since", None)


def born_progress(t, secs=0.35):
    """0 to 1 over the moments after t, eased; 1 when there is no time or motion is off."""
    if not MOTION or not t:
        return 1.0
    x = (time.time() - t) / secs
    if x >= 1:
        return 1.0
    return QEasingCurve(QEasingCurve.OutCubic).valueForProgress(max(0.0, x))


# ------------------------------------------------------------------ numbers
def count_to(label, value, fmt="{:02d}", ms=520):
    """Big figures count up to their new value instead of snapping."""
    try:
        cur = int("".join(ch for ch in label.text() if ch.isdigit()) or 0)
    except ValueError:
        cur = 0
    value = int(value)
    if not MOTION or cur == value or not label.isVisible():
        label.setText(fmt.format(value))
        return
    an = QVariantAnimation(label)
    an.setDuration(ms)
    an.setStartValue(float(cur))
    an.setEndValue(float(value))
    an.setEasingCurve(QEasingCurve.OutCubic)
    an.valueChanged.connect(lambda v: _alive(label) and label.setText(fmt.format(int(round(v)))))
    old = label.property("_count_an")
    if old is not None:
        try:
            old.stop()
        except RuntimeError:
            pass
    label.setProperty("_count_an", an)
    an.start()

