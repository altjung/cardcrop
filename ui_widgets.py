"""CardCrop shared controls: islands, pills, notices, steppers, charts and small helpers."""
from __future__ import annotations

import os
import re
from PySide6.QtCore import QObject, QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QSlider, QSpinBox, QStackedWidget, QStyledItemDelegate, QVBoxLayout, QWidget, QWidgetItem
import ui_base as TH
import ui_motion as motion
from ui_marks import Chip

class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps onto further lines when the
    panel is narrow, so control rows never force a minimum panel width.
    Items added with a stretch soak up the spare width on their line."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []          # (QLayoutItem, stretch)
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # QHBoxLayout-compatible helpers, so existing rows convert in place
    def addWidget(self, w, stretch=0, *_):
        self.addChildWidget(w)
        self._items.append((QWidgetItem(w), stretch))
        self.invalidate()

    def addSpacing(self, *_):
        pass

    def addStretch(self, *_):
        pass

    def addItem(self, item):
        self._items.append((item, 0))

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i][0] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i)[0] if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRectF(0, 0, w, 0), False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(QRectF(rect), True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        from PySide6.QtCore import QSize
        size = QSize()
        for it, _ in self._items:
            if it.widget() is not None and it.widget().isHidden():
                continue
            size = size.expandedTo(it.minimumSize())
        return size

    def _do(self, rect, apply):
        lines, line, used = [], [], 0
        for it, st in self._items:
            w = it.widget()
            if w is not None and w.isHidden():
                continue
            hint = it.sizeHint()
            iw = max(hint.width(), it.minimumSize().width())
            if line and used + self._sp + iw > rect.width():
                lines.append(line)
                line, used = [], 0
            used += (self._sp if line else 0) + iw
            line.append((it, st, iw, hint.height()))
        if line:
            lines.append(line)
        y = rect.y()
        for ln in lines:
            h = max(x[3] for x in ln)
            if apply:
                spare = rect.width() - sum(x[2] for x in ln) - self._sp * (len(ln) - 1)
                total = sum(x[1] for x in ln)
                x = rect.x()
                for it, st, iw, ih in ln:
                    extra = spare * st / total if total and spare > 0 else 0
                    from PySide6.QtCore import QRect
                    it.setGeometry(QRect(int(x), int(y + (h - ih) / 2), int(iw + extra), int(ih)))
                    x += iw + extra + self._sp
            y += h + self._sp
        return int(y - rect.y() - (self._sp if lines else 0))


# ------------------------------------------------------------------ previews
class ImageLabel(QWidget):
    """Paints its image scaled to fit. Unlike a QLabel with a pixmap, its size
    never depends on the image, so previews cannot push the layout around."""

    def __init__(self, min_h=120):
        super().__init__()
        self.setMinimumSize(60, min_h)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._q: QImage | None = None
        self._frame = None      # (x0, y0, x1, y1) as fractions of the image

    def set_frame(self, frame):
        self._frame = frame
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(200, self.minimumHeight())

    def set_q(self, q: QImage | None):
        self._q = q
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        p.fillPath(path, QColor("#0F0F10"))
        if self._q is not None and not self._q.isNull():
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            iw, ih = self._q.width(), self._q.height()
            k = min(self.width() / iw, self.height() / ih)
            w, h = iw * k, ih * k
            ox, oy = (self.width() - w) / 2, (self.height() - h) / 2
            p.drawImage(QRectF(ox, oy, w, h), self._q)
            if self._frame is not None:
                # the printed frame the centering was measured against
                x0, y0, x1, y1 = self._frame
                pen = QPen(QColor(TH.OK), 2, Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(ox + x0 * w, oy + y0 * h, (x1 - x0) * w, (y1 - y0) * h))
        p.end()


def labeled_slider(text, lo, hi, val, fmt):
    lab = QLabel()
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    upd = lambda v: lab.setText(f"{text}  <b>{fmt(v)}</b>")  # noqa: E731
    s.valueChanged.connect(upd)
    upd(val)
    return lab, s


# ------------------------------------------------------------------ window
def has_corner_photos(folder):
    try:
        return any(re.search(r"_(front|back)_(TL|TR|BL|BR)", f) for f in os.listdir(folder))
    except OSError:
        return False


def tick_all(table, on, col=0):
    """Select all / select none for a table whose first column holds tick boxes."""
    for i in range(table.rowCount()):
        it = table.item(i, col)
        if it is not None and it.flags() & Qt.ItemIsUserCheckable:
            it.setCheckState(Qt.Checked if on else Qt.Unchecked)


def tick_buttons(table, col=0):
    b_all, b_none = QPushButton("All"), QPushButton("None")
    b_all.setToolTip("Tick every row")
    b_none.setToolTip("Untick every row")
    b_all.clicked.connect(lambda: tick_all(table, True, col))
    b_none.clicked.connect(lambda: tick_all(table, False, col))
    return b_all, b_none


PROGRESS_RE = re.compile(r"(\d+)\s+of\s+(\d+)")


class ProgressCell(Chip):
    """An upload's current step as a call chip: the wash fills as photos go up (n of total) or
    creeps toward done over the step's usual time, with a clock; the row's mark takes over when
    the step ends."""

    def set(self, msg):
        msg = str(msg or "")
        m = PROGRESS_RE.search(msg)
        short = re.sub(r"\s*…$", "", msg).strip() or "Working"
        if m:
            self.run(short, int(m.group(1)), max(1, int(m.group(2))))
        else:
            self.run(short, expected_ms=4000)
        self.setToolTip(msg)



def is_progress(msg):
    m = str(msg or "")
    return bool(PROGRESS_RE.search(m)) or m.endswith("…")


class PillFilter(QObject):
    """macOS draws buttons a little taller or shorter than Linux, and Qt drops a corner radius
    larger than half the height, which turns a pill into a square. This keeps every text button,
    the toast and the List bar exactly round-ended at whatever height they end up."""

    NAMES = {"", "primary", "accent", "ghost", "cond"}

    def eventFilter(self, o, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.Resize:
            name = o.objectName()
            if (isinstance(o, QPushButton) and name in self.NAMES) or name in ("toast", "actionbar"):
                h = o.height()
                if h > 4 and o.property("_pill_h") != h:
                    base = o.property("_pill_css")
                    if base is None:
                        base = o.styleSheet()
                        o.setProperty("_pill_css", base)
                    o.setProperty("_pill_h", h)
                    rule = f"border-radius:{h // 2}px;"
                    if name in ("toast", "actionbar"):
                        css = base + f" QFrame#{name} {{ {rule} }}"
                    elif "{" in base:
                        css = base + f" QPushButton {{ {rule} }}"
                    else:
                        css = (base.strip().rstrip(";") + "; " if base.strip() else "") + rule
                    o.setStyleSheet(css)
        return False


class Notice(QFrame):
    """A toast that never blocks work: it floats at the bottom of the window, fades
    by itself, and Details shows the long text when there is any. Pop-ups are kept
    for questions that need an answer."""

    KINDS = {"info": "#3B82F6", "ok": "#2BB673", "warn": "#F08C1B", "error": "#E5484D"}

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 6, 6, 6)
        h.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(8, 8)
        h.addWidget(self.dot)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setMaximumWidth(560)
        self.msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        h.addWidget(self.msg, 1)
        self.b_act = QPushButton("")
        self.b_act.clicked.connect(self._act)
        h.addWidget(self.b_act)
        self.b_more = icon_button("info", "Details", role="ink")
        self.b_more.clicked.connect(self._details)
        h.addWidget(self.b_more)
        b_x = icon_button("close", "Dismiss", role="ink")
        b_x.clicked.connect(self.dismiss)
        h.addWidget(b_x)
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self.dismiss)
        self._detail, self._fn, self._leave = "", None, None
        self.hide()

    def dismiss(self):
        """Fades away rather than vanishing; a new message arriving meanwhile keeps it up."""
        tok = object()
        self._leave = tok
        motion.toast_out(self, lambda: self._leave is tok and self.hide())

    def show_msg(self, text, kind="info", details="", action=None, secs=None):
        self.dot.setStyleSheet(f"background:{self.KINDS.get(kind, self.KINDS['info'])}; border-radius:4px;")
        self.msg.setText(text)
        fm = self.msg.fontMetrics()
        self.msg.setMinimumWidth(min(fm.horizontalAdvance(text) + 4, 520))
        self._detail = details
        self.b_more.setVisible(bool(details))
        self._fn = action[1] if action else None
        self.b_act.setText(action[0] if action else "")
        self.b_act.setVisible(bool(action))
        self._leave = None
        arriving = not self.isVisible()
        self.setGraphicsEffect(None)
        self.adjustSize()
        self.show()
        self.raise_()
        if self.parent() is not None and hasattr(self.parent().window(), "_place_floats"):
            self.parent().window()._place_floats()
        if arriving:
            motion.toast_in(self)
        # errors and anything with more to read stay up until dismissed
        if secs is None:
            secs = 0 if (kind == "error" or details or action) else 8
        if secs:
            self.timer.start(int(secs * 1000))
        else:
            self.timer.stop()

    def _act(self):
        fn = self._fn
        self.hide()
        if fn:
            fn()

    def _details(self):
        box = QMessageBox(self.window())
        box.setWindowTitle("Details")
        box.setText(self.msg.text())
        box.setInformativeText(self._detail)
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.exec()


class Island(QFrame):
    """A rounded panel. Overlays added with float_widget() sit on top of its main
    child at an anchor (tl, tr, bl, br, l, r, t, b) and follow it as it resizes."""

    def __init__(self, kind="island", parent=None):
        super().__init__(parent)
        self.setObjectName(kind)
        self._floats = []

    def float_widget(self, w, anchor, mx=16, my=16):
        w.setParent(self)
        self._floats.append((w, anchor, mx, my))
        w.show()
        self._place()
        return w

    def _place(self):
        W, H = self.width(), self.height()
        for w, a, mx, my in self._floats:
            if w.isHidden():
                continue
            w.adjustSize()
            sz = w.sizeHint().expandedTo(w.minimumSizeHint())
            ww, hh = min(sz.width(), W - 2 * mx), sz.height()
            x = mx if a in ("tl", "bl", "l") else (W - ww - mx if a in ("tr", "br", "r") else (W - ww) // 2)
            y = my if a in ("tl", "tr", "t") else (H - hh - my if a in ("bl", "br", "b") else (H - hh) // 2)
            w.setGeometry(int(x), int(y), int(ww), int(hh))
            w.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()


def inspector_style():
    """The 3D inspector: a graphite panel with large, quiet type, one accent for the open tab."""
    pt = TH.BASE_PT
    return f"""
QFrame#inspector {{ background: #141416; border-radius: 22px; }}
QFrame#inspector QWidget#inspage {{ background: transparent; }}
QFrame#inspector QScrollArea, QFrame#inspector QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QFrame#inspector QLabel {{ color: #E8E8EA; font-size: {pt + 1}pt; }}
QLabel#institle {{ font-family: '{SANS}'; font-size: {pt + 6}pt; font-weight: 600; color: #F4F4F2; }}
QLabel#insection {{ font-family: '{MONO}'; font-size: {pt}pt; color: #85858D; letter-spacing: 2px; }}
QLabel#insname {{ font-size: {pt + 1}pt; color: #E8E8EA; }}
QLabel#insval {{ font-family: '{MONO}'; font-size: {pt + 1}pt; color: #A8A8B0; }}
QPushButton#instab {{ background: transparent; color: #85858D; border: none; border-bottom: 2px solid transparent;
                      border-radius: 0; padding: 10px 0; font-size: {pt + 1}pt; }}
QPushButton#instab:hover {{ color: #E8E8EA; }}
QPushButton#instab:checked {{ color: #F4F4F2; border-bottom: 2px solid {LIME}; }}
QFrame#insrule {{ background: rgba(255,255,255,16); border: none; }}
QPushButton#inschip {{ background: rgba(255,255,255,9); color: #E8E8EA; border: 1px solid rgba(255,255,255,20);
                       border-radius: 10px; padding: 9px 8px; font-size: {pt + 1}pt; }}
QPushButton#inschip:hover {{ background: rgba(255,255,255,20); }}
QPushButton#inschip:checked {{ background: #F2F2EF; color: #111114; border-color: #F2F2EF; }}
QPushButton#inschip:disabled {{ color: #5A5A60; }}
QFrame#inspector QSlider {{ min-height: 22px; max-height: 22px; background: transparent; }}
QFrame#inspector QSlider::groove:horizontal {{ height: 22px; background: transparent; border: none; }}
QFrame#inspector QSlider::sub-page:horizontal {{ background: #F2F2EF; margin: 9px 0; border-radius: 2px; }}
QFrame#inspector QSlider::add-page:horizontal {{ background: rgba(255,255,255,40); margin: 9px 0; border-radius: 2px; }}
QFrame#inspector QSlider::handle:horizontal {{ background: #FFFFFF; border: 3px solid #141416; width: 12px; height: 12px;
                                              margin: 2px 0; border-radius: 9px; }}
QFrame#inspector QSlider::sub-page:horizontal:disabled {{ background: rgba(255,255,255,60); }}
QFrame#inspector QSlider::handle:horizontal:disabled {{ background: #77777D; }}
QFrame#inspector QComboBox {{ background: rgba(255,255,255,9); color: #E8E8EA; border: 1px solid rgba(255,255,255,20);
                              border-radius: 10px; padding: 8px 10px; font-size: {pt + 1}pt; }}
QFrame#inspector QSpinBox {{ background: rgba(255,255,255,9); color: #E8E8EA; border: 1px solid rgba(255,255,255,20);
                             border-radius: 10px; padding: 6px 8px; font-family: '{MONO}'; font-size: {pt + 2}pt; }}
QFrame#inspector QSpinBox::up-button, QFrame#inspector QSpinBox::down-button {{ width: 0; border: none; }}
QFrame#inspector QLineEdit {{ background: rgba(255,255,255,9); color: #E8E8EA; border: 1px solid rgba(255,255,255,20);
                              border-radius: 10px; padding: 7px 10px; font-size: {pt + 1}pt; }}
QFrame#inspector QCheckBox {{ color: #E8E8EA; font-size: {pt + 1}pt; spacing: 10px; }}
QFrame#inspector QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; background: rgba(255,255,255,14);
                                         border: 1px solid rgba(255,255,255,40); }}
QFrame#inspector QCheckBox::indicator:checked {{ background: {LIME}; border-color: {LIME}; }}
QFrame#inspector QScrollBar:vertical {{ width: 6px; background: transparent; }}
QFrame#inspector QScrollBar::handle:vertical {{ background: rgba(255,255,255,40); border-radius: 3px; min-height: 30px; }}
QFrame#inspector QScrollBar::add-line, QFrame#inspector QScrollBar::sub-line {{ height: 0; }}
"""


def hud(*widgets, vertical=False, margins=(10, 6, 10, 6), spacing=6):
    """A dark translucent pill for controls that sit on the photo."""
    f = QFrame()
    f.setObjectName("hud")
    lay = QVBoxLayout(f) if vertical else QHBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for w in widgets:
        if w == "|":
            line = QFrame()
            line.setFixedSize(*((24, 1) if vertical else (1, 18)))
            line.setStyleSheet("background: rgba(255,255,255,40);")
            lay.addWidget(line, 0, Qt.AlignCenter)
        elif isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return f


def dot_label(color, size=8):
    d = QLabel()
    d.setFixedSize(size, size)
    d.setStyleSheet(f"background:{color}; border-radius:{size // 2}px;")
    return d


def island_title(text):
    return QLabel(text, objectName="small")


class TileDelegate(QStyledItemDelegate):
    """Filmstrip tiles: thumbnail, side and name, a status dot and line."""

    W, H = 172, 78

    def sizeHint(self, opt, idx):
        from PySide6.QtCore import QSize
        return QSize(self.W, self.H)

    def paint(self, p, opt, idx):
        from PySide6.QtWidgets import QStyle
        d = idx.data(Qt.UserRole) or {}
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        k = motion.born_progress(d.get("row_t"))          # a new tile slides in from the left
        if k < 1:
            p.setOpacity(k)
            p.translate(-18 * (1 - k), 0)
        r = QRectF(opt.rect).adjusted(3, 3, -3, -3)
        sel = bool(opt.state & QStyle.State_Selected)
        if sel:
            path = QPainterPath()
            path.addRoundedRect(r, 18, 18)
            p.fillPath(path, QColor(TH.T["island2"]))
            p.setPen(QPen(QColor(TH.T["ink"]), 2))
            p.drawPath(path)
        elif opt.state & QStyle.State_MouseOver:
            path = QPainterPath()
            path.addRoundedRect(r, 18, 18)
            p.fillPath(path, QColor(TH.T["pill"]))
        th = QRectF(r.x() + 10, r.y() + 8, 42, r.height() - 16)
        clip = QPainterPath()
        clip.addRoundedRect(th, 6, 6)
        pm = d.get("pm")
        if pm is not None and not pm.isNull():
            kp = motion.born_progress(d.get("pm_t"), 0.4)  # the photo eases up over its grey slot
            if kp < 1:
                p.fillPath(clip, QColor(TH.T["back"]))
                c = th.center()
                th = QRectF(c.x() - th.width() * (0.86 + 0.14 * kp) / 2, c.y() - th.height() * (0.86 + 0.14 * kp) / 2,
                            th.width() * (0.86 + 0.14 * kp), th.height() * (0.86 + 0.14 * kp))
                clip = QPainterPath()
                clip.addRoundedRect(th, 6, 6)
                p.setOpacity(p.opacity() * kp)
            p.setClipPath(clip)
            sc = max(th.width() / pm.width(), th.height() / pm.height())
            w, h = pm.width() * sc, pm.height() * sc
            p.drawPixmap(QRectF(th.center().x() - w / 2, th.center().y() - h / 2, w, h), pm, QRectF(pm.rect()))
            p.setClipping(False)
            p.setOpacity(k if k < 1 else 1.0)
            th = QRectF(r.x() + 10, r.y() + 8, 42, r.height() - 16)
        else:
            p.fillPath(clip, QColor(TH.T["back"]))
        tx = th.right() + 10
        f = QFont(SANS, TH.BASE_PT - 1)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(TH.T["text"]))
        fm = p.fontMetrics()
        p.drawText(QPointF(tx, r.y() + 26), fm.elidedText(d.get("name", ""), Qt.ElideRight, int(r.right() - tx - 8)))
        f = QFont(SANS, TH.BASE_PT - 2)
        p.setFont(f)
        p.setPen(QColor(TH.T["muted"]))
        fm = p.fontMetrics()
        p.drawText(QPointF(tx, r.y() + 44), fm.elidedText(d.get("side", ""), Qt.ElideRight, int(r.right() - tx - 8)))
        from ui_marks import paint_status_mark
        paint_status_mark(p, QPointF(tx + 5, r.y() + 58), 12, d.get("mstate", "pending"),
                          QColor(d.get("color", STATUS["idle"])), d.get("m_t", 0.0))
        p.setPen(QColor(TH.T["text"] if d.get("strong") else TH.T["muted"]))
        p.drawText(QPointF(tx + 14, r.y() + 62), fm.elidedText(d.get("state", ""), Qt.ElideRight,
                                                                int(r.right() - tx - 22)))
        p.restore()


class CommandPalette(QDialog):
    """Cmd+K: every action the screens leave out, found by typing."""

    def __init__(self, main, actions):
        super().__init__(main, Qt.FramelessWindowHint | Qt.Popup)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.actions_ = actions
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        box = QFrame(objectName="island")
        box.setStyleSheet(f"QFrame#island {{ background:{TH.T['island']}; border:1px solid {TH.T['line']}; }}")
        outer.addWidget(box)
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Type a command")
        self.q.textChanged.connect(self._filter)
        self.q.returnPressed.connect(self._run)
        v.addWidget(self.q)
        self.lst = QListWidget()
        self.lst.itemActivated.connect(lambda _it: self._run())
        v.addWidget(self.lst, 1)
        self.resize(560, 460)
        self._filter("")
        self.q.installEventFilter(self)

    def eventFilter(self, o, e):
        from PySide6.QtCore import QEvent
        if o is self.q and e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Down, Qt.Key_Up):
            r = self.lst.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            n = self.lst.count()
            if n:
                self.lst.setCurrentRow(max(0, min(n - 1, r)))
            return True
        return super().eventFilter(o, e)

    def _filter(self, text):
        words = text.lower().split()
        self.lst.clear()
        for name, keys, fn in self.actions_:
            if all(w in name.lower() for w in words):
                it = QListWidgetItem(f"{name}" + (f"      {keys}" if keys else ""))
                it.setData(Qt.UserRole, fn)
                self.lst.addItem(it)
        if self.lst.count():
            self.lst.setCurrentRow(0)

    def _run(self):
        it = self.lst.currentItem()
        if it is None:
            return
        fn = it.data(Qt.UserRole)
        self.accept()
        QTimer.singleShot(0, fn)


class AutoLabel(QLabel):
    """A label that takes no room while it has nothing to say."""

    def setText(self, t):
        super().setText(t)
        self.setVisible(bool(t))


class PriceBox(QDoubleSpinBox):
    """A price field that only takes the scroll wheel once you have clicked into it,
    so scrolling a list never changes a price by accident."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSingleStep(1.0)          # the arrows and Up and Down move a whole dollar
        self._fresh = False
        self._replace = False

    # the first key typed after coming in writes over the whole price, whatever the click left selected
    # (on a Mac the click could land the cursor inside it, so typing went in among the old digits)
    def keyPressEvent(self, e):
        if self._replace and e.text() and (e.text()[0].isdigit() or e.text()[0] in ".,"):
            self.lineEdit().setText(self.prefix())
            self.lineEdit().setCursorPosition(len(self.prefix()))
        if e.text() or e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End, Qt.Key_Backspace):
            self._replace = False
        super().keyPressEvent(e)

    # the price already there is selected when you click or tab in, so typing writes over it
    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._fresh = True
        self._replace = True
        QTimer.singleShot(0, self.selectAll)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if self._fresh:
            self.selectAll()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self._fresh:
            self._fresh = False
            self.selectAll()

    def focusOutEvent(self, e):
        self._fresh = False
        self._replace = False
        super().focusOutEvent(e)

    def wheelEvent(self, e):
        e.ignore()                       # scrolling scrolls the page; the arrows and the keys step it


class NoWheelSpin(QSpinBox):
    """A whole-number field the scroll wheel never changes: the arrows and the Up and Down keys do."""

    def wheelEvent(self, e):
        e.ignore()


def fade_in(w, ms=220):
    """Fades a widget up from clear, then takes the effect off again so it costs nothing after."""
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    from PySide6.QtCore import QPropertyAnimation
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)
    an = QPropertyAnimation(eff, b"opacity", w)
    an.setDuration(ms)
    an.setStartValue(0.0)
    an.setEndValue(1.0)

    def done():
        try:
            w.setGraphicsEffect(None)
        except RuntimeError:
            pass
    an.finished.connect(done)
    an.start()


def soft_scroll(w, min_h=140, min_w=None):
    """w in a frameless scroll area that only scrolls when the window is too short for it, so a tall
    panel scrolls on its own instead of pushing the whole page into a scroll."""
    from PySide6.QtWidgets import QScrollArea
    sa = QScrollArea()
    sa.setWidget(w)
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if min_w is None else Qt.ScrollBarAsNeeded)
    sa.setObjectName("soft")
    sa.setStyleSheet("QScrollArea#soft { background: transparent; } "
                     "QScrollArea#soft > QWidget#qt_scrollarea_viewport { background: transparent; }")
    sa.viewport().setAutoFillBackground(False)
    sa.setMinimumWidth(w.minimumSizeHint().width() if min_w is None else min_w)
    sa.setMinimumHeight(min_h)
    return sa


class StepButton(QAbstractButton):
    """A small up or down arrow, drawn in the current theme's colours whenever it paints, so it reads in
    light and dark alike."""

    def __init__(self, up):
        super().__init__()
        self.up = up
        self.setAutoRepeat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = TH.T["hover"] if (self.underMouse() or self.isDown()) else TH.T["pill"]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(r, 5, 5)
        c = r.center()
        w, h = 4.5, 3.0
        pts = [QPointF(c.x() - w, c.y() + h), QPointF(c.x() + w, c.y() + h), QPointF(c.x(), c.y() - h)] if self.up \
            else [QPointF(c.x() - w, c.y() - h), QPointF(c.x() + w, c.y() - h), QPointF(c.x(), c.y() + h)]
        p.setBrush(QColor(TH.T["text"]))
        p.drawPolygon(pts)
        p.end()


def with_arrows(field, width):
    """A field with small up and down arrows beside it (the Up and Down keys step it too)."""
    w = QWidget()
    w.setFixedWidth(width)
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(2)
    field.setMinimumWidth(10)
    field.setMaximumWidth(16777215)
    fh = max(28, field.sizeHint().height())
    field.setFixedHeight(fh)
    h.addWidget(field, 1, Qt.AlignVCenter)
    cw = QWidget()
    cw.setFixedSize(22, fh)
    col = QVBoxLayout(cw)
    col.setSpacing(2)
    col.setContentsMargins(0, 0, 0, 0)
    for up, fn, tip in ((True, field.stepUp, "Up one step (or press the Up key)"),
                        (False, field.stepDown, "Down one step (or press the Down key)")):
        b = StepButton(up)
        b.setFixedSize(22, (fh - 2) // 2)          # the pair is exactly as tall as the field
        b.setToolTip(tip)
        b.clicked.connect(fn)
        col.addWidget(b)
    h.addWidget(cw, 0, Qt.AlignVCenter)
    return w


def _price_line(r):
    """One compact line under the price: where the suggestion comes from."""
    bits = []
    e, t, c = r.get("ebay"), r.get("tcgplayer"), r.get("cardmarket")
    o, pc = r.get("own"), r.get("pricecharting")
    if o:
        bits.append(f"You sold {o['count']}× · {o['median']:.2f}")
    if pc:
        bits.append(f"PC {pc['loose']:.2f}")
    if e:
        bits.append(f"eBay {e['count']} listed, low {e['low']:.2f}, median {e['median']:.2f}")
    if t:
        bits.append(f"TCG {t['market']:.2f}")
    if c:
        bits.append(f"CM €{c['trend']:.2f}")
    if r.get("error") and not bits:
        bits.append(str(r["error"])[:80])
    return " · ".join(bits) or "No price data for this card"


def _short_needs(need):
    words = {"identify it (I)": "ID", "a condition (set on the back)": "grade", "a price": "price",
             "an English name": "English name"}
    return ", ".join(words.get(n, n) for n in need)


# ------------------------------------------------------------------ tracking charts
CHART = {"NM": "#2BB673", "LP": "#3B82F6", "MP": "#8B5CF6", "HP": "#F08C1B", "DMG": "#E5484D",
         "Not set": "#8A8A90", "English": "#3B82F6", "Japanese": "#E5484D", "Pokémon": "#F2C230",
         "Yu-Gi-Oh!": "#8B5CF6", "One Piece": "#E5484D",
         "Search": "#3B82F6", "Other eBay": "#8B5CF6", "Store": "#2BB673", "Direct": "#F2C230",
         "External": "#2CC4C4"}


def _blend(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


class Heatmap(QWidget):
    """Cards per day as a grid of rounded squares, oldest week on the left, today bottom right."""

    def __init__(self, weeks=26):
        super().__init__()
        self.weeks, self.data = weeks, {}
        self.setMouseTracking(True)
        self.setMinimumHeight(7 * 14 + 6 * 4)

    def set_data(self, d):
        self.data = d or {}
        self.update()

    def _geom(self):
        """Cells sized by the height, and as many weeks as fill the width (up to a year)."""
        import datetime as dt
        today = dt.date.today()
        gap = 4
        cell = max(8, min(26, (self.height() - gap * 6) // 7))
        self.weeks = max(4, min(53, (self.width() + gap) // (cell + gap)))
        start = today - dt.timedelta(days=today.weekday() + 7 * (self.weeks - 1))
        return start, today, cell, gap

    def paintEvent(self, e):
        import datetime as dt
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        start, today, cell, gap = self._geom()
        top = max(self.data.values()) if self.data else 0
        for w in range(self.weeks):
            for d in range(7):
                day = start + dt.timedelta(days=w * 7 + d)
                if day > today:
                    continue
                n = self.data.get(day.isoformat(), 0)
                if n:
                    t = 0.35 + 0.65 * (n / top if top else 1)
                    p.setBrush(_blend(TH.T["island"], LIME if TH.THEME == "dark" else "#9BC20F", t))
                else:
                    p.setBrush(QColor(TH.T["pill"]))
                p.drawRoundedRect(QRectF(w * (cell + gap), d * (cell + gap), cell, cell), cell * .28, cell * .28)
        p.end()

    def mouseMoveEvent(self, e):
        import datetime as dt
        start, today, cell, gap = self._geom()
        w, d = int(e.position().x() // (cell + gap)), int(e.position().y() // (cell + gap))
        day = start + dt.timedelta(days=w * 7 + d)
        if 0 <= w < self.weeks and 0 <= d < 7 and day <= today:
            n = self.data.get(day.isoformat(), 0)
            self.setToolTip(f"{day.strftime('%a %d %b')}: {n} card{'s' if n != 1 else ''}")


class SegBar(QWidget):
    """One rounded bar split by share, colours from CHART."""

    def __init__(self, h=14):
        super().__init__()
        self.items = []
        self.setFixedHeight(h)

    def set_items(self, items):
        self.items = [(k, n) for k, n in items if n]
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(clip, QColor(TH.T["pill"]))
        total = sum(n for _, n in self.items)
        if total:
            p.setClipPath(clip)
            x = 0.0
            for k, n in self.items:
                w = r.width() * n / total
                p.fillRect(QRectF(x, 0, w - (2 if x + w < r.width() - 1 else 0), r.height()),
                           QColor(CHART.get(k, LIME)))
                x += w
        p.end()


class Bars(QWidget):
    """Vertical bars with the count on top and the label underneath."""

    def __init__(self, color=None):
        super().__init__()
        self.items, self.color = [], color
        self.setMinimumHeight(140)

    def set_items(self, items):
        self.items = list(items)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.items)
        if not n:
            return
        W, H = self.width(), self.height()
        gap = 10
        bw = (W - gap * (n - 1)) / n
        top = max([v for _, v in self.items] + [1])
        fs = QFont(SANS, TH.BASE_PT - 2)
        fm = QFont(MONO, TH.BASE_PT - 1)
        lab_h, num_h = 22, 20
        area = H - lab_h - num_h
        for i, (k, v) in enumerate(self.items):
            x = i * (bw + gap)
            h = max(6, area * v / top) if v else 6
            y = num_h + area - h
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.color or LIME) if v else QColor(TH.T["pill"]))
            p.drawRoundedRect(QRectF(x, y, bw, h), min(10, bw / 2), min(10, bw / 2))
            p.setPen(QColor(TH.T["text"]))
            p.setFont(fm)
            p.drawText(QRectF(x, y - num_h, bw, num_h), Qt.AlignHCenter | Qt.AlignBottom, str(v) if v else "")
            p.setPen(QColor(TH.T["muted"]))
            p.setFont(fs)
            p.drawText(QRectF(x - 4, H - lab_h, bw + 8, lab_h), Qt.AlignHCenter | Qt.AlignBottom, k)
        p.end()


class HBars(QWidget):
    """Label, bar and count per row, for eras and the like."""

    ROW = 26

    def __init__(self):
        super().__init__()
        self.items = []

    def set_items(self, items):
        self.items = list(items)[:9]
        self.setMinimumHeight(max(1, len(self.items)) * self.ROW)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        top = max([v for _, v in self.items] + [1])
        lw, nw = 118, 34
        bar_w = max(10, self.width() - lw - nw - 12)
        for i, (k, v) in enumerate(self.items):
            y = i * self.ROW
            p.setPen(QColor(TH.T["text"]))
            p.setFont(QFont(SANS, TH.BASE_PT - 1))
            p.drawText(QRectF(0, y, lw, self.ROW), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(k, Qt.ElideRight, lw - 6))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(TH.T["pill"]))
            p.drawRoundedRect(QRectF(lw, y + 8, bar_w, self.ROW - 16), 5, 5)
            p.setBrush(QColor(LIME if i == 0 else _blend(TH.T["pill"], LIME, .55)))
            p.drawRoundedRect(QRectF(lw, y + 8, max(10, bar_w * v / top), self.ROW - 16), 5, 5)
            p.setPen(QColor(TH.T["muted"]))
            p.setFont(QFont(MONO, TH.BASE_PT - 1))
            p.drawText(QRectF(lw + bar_w + 8, y, nw, self.ROW), Qt.AlignVCenter | Qt.AlignRight, str(v))
        p.end()


# ------------------------------------------------------------------ store
def _ago(iso):
    import datetime as dt
    try:
        t = dt.datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError):
        return ""
    sec = (dt.datetime.now(dt.timezone.utc) - t).total_seconds()
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if sec >= n:
            return f"{int(sec // n)}{unit} ago"
    return "just now"


def _local_day(iso):
    import datetime as dt
    try:
        t = dt.datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
        return t.astimezone().date()
    except (ValueError, TypeError):
        return None


class SparkBars(QWidget):
    """Sales per day: one slim bar per day, today on the right, hover for the day."""

    def __init__(self):
        super().__init__()
        self.vals, self.days = [], []
        self.setMinimumHeight(90)
        self.setMouseTracking(True)

    def set_data(self, days, vals):
        self.days, self.vals = days, vals
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.vals)
        if not n:
            return
        gap = 3
        bw = (self.width() - gap * (n - 1)) / n
        top = max(self.vals + [1])
        p.setPen(Qt.NoPen)
        for i, v in enumerate(self.vals):
            h = max(4, (self.height() - 2) * v / top) if v else 4
            p.setBrush(QColor(LIME if v and i == n - 1 else (_blend(TH.T["pill"], LIME if TH.THEME == "dark" else "#9BC20F",
                                                                     .75) if v else TH.T["pill"])))
            p.drawRoundedRect(QRectF(i * (bw + gap), self.height() - h, bw, h), min(4, bw / 2), min(4, bw / 2))
        p.end()

    def mouseMoveEvent(self, e):
        n = len(self.vals)
        if not n:
            return
        i = int(e.position().x() // (self.width() / n))
        if 0 <= i < n:
            self.setToolTip(f"{self.days[i].strftime('%a %d %b')}: ${self.vals[i]:,.2f}")


def rounded_pixmap(pm, w, h, radius=6):
    """A rounded thumbnail. A photo of a whole card is shown whole (fitted, not cropped) with the
    card's own small corner, about 3 mm on 63 mm; anything else is cover-fitted with the given radius."""
    out = QPixmap(w * 2, h * 2)
    out.fill(Qt.transparent)
    if pm is None or pm.isNull():
        return out
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    ar = pm.width() / max(1, pm.height())
    card = 0.66 <= ar <= 0.78 or 1 / 0.78 <= ar <= 1 / 0.66
    if card:
        sc = min(w * 2 / pm.width(), h * 2 / pm.height())
        pw, ph = pm.width() * sc, pm.height() * sc
        rect = QRectF((w * 2 - pw) / 2, (h * 2 - ph) / 2, pw, ph)
        r2 = 0.048 * min(pw, ph)
    else:
        sc = max(w * 2 / pm.width(), h * 2 / pm.height())
        pw, ph = pm.width() * sc, pm.height() * sc
        rect = QRectF((w * 2 - pw) / 2, (h * 2 - ph) / 2, pw, ph)
        r2 = radius * 2
    path = QPainterPath()
    clip = rect.intersected(QRectF(0, 0, w * 2, h * 2))
    path.addRoundedRect(clip, r2, r2)
    p.setClipPath(path)
    p.drawPixmap(rect, pm, QRectF(pm.rect()))
    p.end()
    out.setDevicePixelRatio(2.0)
    return out
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w * 2, h * 2), radius * 2, radius * 2)
    p.setClipPath(path)
    sc = max(w * 2 / pm.width(), h * 2 / pm.height())
    pw, ph = pm.width() * sc, pm.height() * sc
    p.drawPixmap(QRectF((w * 2 - pw) / 2, (h * 2 - ph) / 2, pw, ph), pm, QRectF(pm.rect()))
    p.end()
    out.setDevicePixelRatio(2.0)
    return out


def _logo_pixmap(size):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    # light: an ink tile; night: a graphite tile with a faint edge, so the lime mark stays the light
    if TH.THEME == "dark":
        p.setBrush(QColor("#232327"))
        p.setPen(QPen(QColor("#34343A"), size * .04))
    else:
        p.setBrush(QColor(TH.T["ink"]))
    p.drawRoundedRect(QRectF(size * .02, size * .02, size * 1.96, size * 1.96), size * .6, size * .6)
    p.setPen(QPen(QColor(LIME), size * .12))
    p.setBrush(Qt.NoBrush)
    w, h = size * .70, size * 1.0
    p.drawRoundedRect(QRectF(size - w / 2, size - h / 2, w, h), size * .16, size * .16)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return pm


class PageStack(QStackedWidget):
    """Only the page on screen sets how small the window can go, so a wide Store page never
    pushes the Edit page's right column off a small screen."""

    def __init__(self):
        super().__init__()
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()



def scrolled(page):
    """A wide page in a scroll area: on a screen narrower than the page it scrolls sideways
    instead of running off the edge."""
    from PySide6.QtWidgets import QScrollArea
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
    sa.setWidget(page)
    return sa


# names from the other parts, bound once every part has loaded
from ui_base import LIME, MONO, SANS, STATUS, icon_button  # noqa: E402
