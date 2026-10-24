"""CardCrop Reports stage, Centering: guides on each side's photo, the splits they measure, the grade those
allow, and a one-page report of it all.

The guides are found for you (the card's edge and its printed frame) and then yours to set: drag a line,
type its position, nudge it with the arrow keys, or turn either set to follow a crooked cut or print.
Zoom with the wheel or a pinch, pan by dragging the photo, double-click to fit."""
from __future__ import annotations

import math
import os
import time

import centering as C
import engine
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout,
                               QWidget)
import ui_base as TH

OUTER, INNER = "#3DDC84", "#4C8DFF"          # the cut edge in green, the printed frame in blue
LONG = 2400                                   # the photo is shown at most this long; guides stay in full pixels


class GuideCanvas(QWidget):
    """The photo with its two sets of guides. Lines are dragged, the photo panned and zoomed."""
    changed = Signal()
    picked = Signal(str, str)                  # which set and side is selected

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.pm, self.k = None, 1.0            # shown picture, and full-res pixels to shown pixels
        self.g = None
        self.zoom, self.off = 1.0, QPointF(0, 0)
        self.sel = None                         # ("outer"|"inner", side)
        self._drag = None
        self._hover = None

    # ---------- what is shown
    def set_photo(self, qimg, full_w):
        self.pm = QPixmap.fromImage(qimg) if qimg is not None else None
        self.k = (qimg.width() / full_w) if (qimg is not None and full_w) else 1.0
        self.fit()

    def set_guides(self, g):
        self.g = g
        self.update()

    def fit(self):
        if self.pm is None:
            return
        s = min(self.width() / self.pm.width(), self.height() / self.pm.height()) * 0.96
        self.zoom = max(1e-3, s)
        self.off = QPointF((self.width() - self.pm.width() * s) / 2, (self.height() - self.pm.height() * s) / 2)
        self.update()

    def zoom_by(self, f, at=None):
        if self.pm is None:
            return
        at = at or QPointF(self.width() / 2, self.height() / 2)
        old = self.zoom
        self.zoom = max(0.05, min(40.0, self.zoom * f))
        self.off = at - (at - self.off) * (self.zoom / old)
        self.update()

    def resizeEvent(self, e):
        self.fit()

    # full-res photo pixels <-> widget
    def to_w(self, x, y):
        return QPointF(self.off.x() + x * self.k * self.zoom, self.off.y() + y * self.k * self.zoom)

    def to_img(self, p):
        return ((p.x() - self.off.x()) / (self.k * self.zoom), (p.y() - self.off.y()) / (self.k * self.zoom))

    # ---------- drawing
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(TH.T["well"] if "well" in TH.T else TH.T["pill"]))
        if self.pm is None:
            p.setPen(QColor(TH.T["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, "Pick a card on the left")
            return
        p.drawPixmap(QRectF(self.off.x(), self.off.y(), self.pm.width() * self.zoom, self.pm.height() * self.zoom),
                     self.pm, QRectF(0, 0, self.pm.width(), self.pm.height()))
        if not self.g:
            return
        p.setRenderHint(QPainter.Antialiasing)
        for which, col in (("outer", OUTER), ("inner", INNER)):
            for side in C.SIDES:
                a, b = C.line(self.g[which], side)
                on = self.sel == (which, side)
                hov = self._hover == (which, side)
                pen = QPen(QColor(col), 2.2 if (on or hov) else 1.2)
                pen.setStyle(Qt.SolidLine if on else Qt.DashLine)
                pen.setDashPattern([6, 4]) if not on else None
                p.setPen(pen)
                A, B = self.to_w(*a), self.to_w(*b)
                # run past the corners, as a ruler would, so the line is easy to find and grab
                dx, dy = B.x() - A.x(), B.y() - A.y()
                L = math.hypot(dx, dy) or 1
                ext = 40
                p.drawLine(QPointF(A.x() - dx / L * ext, A.y() - dy / L * ext),
                           QPointF(B.x() + dx / L * ext, B.y() + dy / L * ext))
        p.end()

    # ---------- pointer
    def _hit(self, pos):
        if not self.g:
            return None
        best, bd = None, 9.0
        for which in ("inner", "outer"):
            for side in C.SIDES:
                a, b = C.line(self.g[which], side)
                A, B = self.to_w(*a), self.to_w(*b)
                d = C._dist((pos.x(), pos.y()), (A.x(), A.y()), (B.x(), B.y()))
                # within the line's length (plus its overrun)
                t = ((pos.x() - A.x()) * (B.x() - A.x()) + (pos.y() - A.y()) * (B.y() - A.y())) / \
                    max(1e-6, (B.x() - A.x()) ** 2 + (B.y() - A.y()) ** 2)
                if -0.2 <= t <= 1.2 and d < bd:
                    best, bd = (which, side), d
        return best

    def mousePressEvent(self, e):
        self.setFocus()
        h = self._hit(e.position())
        if h is not None:
            self.sel = h
            self.picked.emit(*h)
            self._drag = ("line", e.position())
        else:
            self._drag = ("pan", e.position())
            self.setCursor(Qt.ClosedHandCursor)
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is None:
            h = self._hit(pos)
            if h != self._hover:
                self._hover = h
                self.setCursor(Qt.SizeVerCursor if h and h[1] in ("top", "bottom") else
                               Qt.SizeHorCursor if h else Qt.OpenHandCursor)
                self.update()
            return
        kind, last = self._drag
        d = pos - last
        self._drag = (kind, pos)
        if kind == "pan":
            self.off += d
            self.update()
            return
        which, side = self.sel
        R = self.g[which]
        a = math.radians(R["rot"])
        # the pointer's move along the side's own normal, in full-res pixels
        s = 1.0 / (self.k * self.zoom)
        if side in ("top", "bottom"):
            mv = (-d.x() * math.sin(a) + d.y() * math.cos(a)) * s
            R["t" if side == "top" else "b"] += mv
        else:
            mv = (d.x() * math.cos(a) + d.y() * math.sin(a)) * s
            R["l" if side == "left" else "r"] += mv
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if dy:
            self.zoom_by(1.0015 ** dy, e.position())

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.NativeGesture and e.gestureType() == Qt.ZoomNativeGesture:
            self.zoom_by(1 + e.value(), e.position())
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        """Arrow keys nudge the selected line a pixel (Shift: ten, Alt: a tenth)."""
        if not self.sel or not self.g:
            return super().keyPressEvent(e)
        step = 10.0 if e.modifiers() & Qt.ShiftModifier else 0.1 if e.modifiers() & Qt.AltModifier else 1.0
        which, side = self.sel
        key = {"top": "t", "bottom": "b", "left": "l", "right": "r"}[side]
        d = {Qt.Key_Up: -1, Qt.Key_Left: -1, Qt.Key_Down: 1, Qt.Key_Right: 1}.get(e.key())
        if d is None:
            return super().keyPressEvent(e)
        if side in ("top", "bottom") and e.key() in (Qt.Key_Left, Qt.Key_Right):
            return
        if side in ("left", "right") and e.key() in (Qt.Key_Up, Qt.Key_Down):
            return
        self.g[which][key] += d * step
        self.update()
        self.changed.emit()


def _spin(lo, hi, dec=0, step=1.0, suffix=""):
    s = QDoubleSpinBox() if dec else QSpinBox()
    s.setRange(lo, hi)
    if dec:
        s.setDecimals(dec)
    s.setSingleStep(step)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    s.setButtonSymbols(QSpinBox.UpDownArrows)
    s.setFixedHeight(30)
    return s


class CenteringView(QWidget):
    """Pick a card, set the guides on its front and back, read the splits and the grade, save, export."""

    def __init__(self, main):
        super().__init__()
        self.m = main
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.card = None                       # {"name", "folder", "slug", "photos": {side: path}}
        self.side = "front"
        self.data = {}                         # what is saved: {"front": guides, "back": guides, ...}
        self.imgs = {}                         # side -> (QImage shown, full width)
        self._sync = False
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        # cards
        left = Island()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.setSpacing(8)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Name or number")
        self.q.textChanged.connect(lambda _t: self.refresh())
        lv.addWidget(self.q)
        self.lst = QListWidget()
        self.lst.setIconSize(QSize(30, 42))
        self.lst.currentRowChanged.connect(self._pick)
        lv.addWidget(self.lst, 1)
        left.setFixedWidth(250)
        h.addWidget(left)

        # the photo
        mid = Island()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(12, 12, 12, 12)
        mv.setSpacing(8)
        top = QHBoxLayout()
        self.title = QLabel("", objectName="small")
        self.title.setStyleSheet("font-weight:600;")
        top.addWidget(self.title, 1)
        for label, tip, fn in (("−", "Zoom out", lambda: self.canvas.zoom_by(1 / 1.4)),
                               ("+", "Zoom in", lambda: self.canvas.zoom_by(1.4)),
                               ("Fit", "The whole card  (double-click)", lambda: self.canvas.fit())):
            b = QPushButton(label, objectName="chip")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            top.addWidget(b)
        for corner in ("TL", "TR", "BL", "BR"):
            b = QPushButton(corner, objectName="chip")
            b.setToolTip("Zoom to this corner")
            b.clicked.connect(lambda _=False, c=corner: self.zoom_corner(c))
            top.addWidget(b)
        mv.addLayout(top)
        self.canvas = GuideCanvas()
        self.canvas.changed.connect(self._guides_moved)
        self.canvas.picked.connect(lambda w, s: self._note(f"{'Outer' if w == 'outer' else 'Inner'} {s} selected: "
                                                         "drag it, or nudge with the arrow keys (Shift ×10, Alt ×0.1)"))
        mv.addWidget(self.canvas, 1)
        self.hint = QLabel("Green: the card's cut edge. Blue: the printed frame. Drag a line, scroll to zoom, "
                           "drag the photo to pan.", objectName="small")
        self.hint.setWordWrap(True)
        mv.addWidget(self.hint)
        h.addWidget(mid, 1)

        # the numbers
        right = Island()
        rv_out = QVBoxLayout(right)
        rv_out.setContentsMargins(16, 14, 16, 14)
        rv_out.setSpacing(10)
        inner = QWidget()
        rv = QVBoxLayout(inner)              # the controls scroll on a short screen; the buttons stay put
        rv.setContentsMargins(0, 0, 4, 0)
        rv.setSpacing(10)
        seg = QFrame(objectName="segbox")
        sg = QHBoxLayout(seg)
        sg.setContentsMargins(4, 4, 4, 4)
        sg.setSpacing(4)
        self.side_btns = {}
        for sd in ("front", "back"):
            b = QPushButton(sd.title(), objectName="seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, s=sd: self.set_side(s))
            sg.addWidget(b, 1)
            self.side_btns[sd] = b
        rv.addWidget(seg)
        gb = QFrame(objectName="gradebox")
        gb.setStyleSheet(f"QFrame#gradebox {{ background:{TH.T['ink']}; border-radius:14px; }}"
                         f"QFrame#gradebox QLabel {{ color:{TH.T['ink_text']}; }}")
        gl = QHBoxLayout(gb)
        gl.setContentsMargins(16, 10, 16, 10)
        gcol = QVBoxLayout()
        gcol.setSpacing(0)
        self.g_side = QLabel("FRONT", objectName="mono")
        gcol.addWidget(self.g_side)
        gcol.addWidget(QLabel("Expected grade", objectName="small"))
        gl.addLayout(gcol, 1)
        self.g_num = QLabel("–")
        self.g_num.setStyleSheet(f"font-size:{TH.BASE_PT + 14}pt; font-weight:700;")
        gl.addWidget(self.g_num)
        rv.addWidget(gb)
        ax = QGridLayout()
        ax.setHorizontalSpacing(8)
        ax.setVerticalSpacing(4)
        self.ax = {}
        for col, (k, cap) in enumerate((("tb", "Top / Bottom"), ("lr", "Left / Right"))):
            c = QLabel(cap, objectName="small")
            c.setAlignment(Qt.AlignCenter)
            chip = QLabel("–")
            chip.setAlignment(Qt.AlignCenter)
            chip.setFixedHeight(28)
            val = QLabel("", objectName="mono")
            val.setAlignment(Qt.AlignCenter)
            ax.addWidget(c, 0, col)
            ax.addWidget(chip, 1, col)
            ax.addWidget(val, 2, col)
            self.ax[k] = (chip, val)
        rv.addLayout(ax)
        self.both = QLabel("", objectName="small")
        self.both.setAlignment(Qt.AlignCenter)
        rv.addWidget(self.both)

        def section(t):
            l_ = QLabel(t.upper(), objectName="mono")
            l_.setContentsMargins(0, 6, 0, 0)
            rv.addWidget(l_)

        def cell(cap, w):
            box = QVBoxLayout()
            box.setSpacing(1)
            box.addWidget(QLabel(cap, objectName="small"))
            box.addWidget(with_arrows(w, 140) if isinstance(w, (QSpinBox, QDoubleSpinBox)) else w)
            return box
        section("Turn lines")
        g0 = QGridLayout()
        g0.setSpacing(8)
        self.rot = {}
        for col, which in enumerate(("outer", "inner")):
            s = _spin(-15, 15, 2, 0.05, "°")
            s.valueChanged.connect(lambda v, w=which: self._typed(w, "rot", v))
            g0.addLayout(cell(which.title(), s), 0, col)
            self.rot[which] = s
        rv.addLayout(g0)
        self.pos = {}
        for which in ("outer", "inner"):
            section(f"{which} lines, pixels")
            gg = QGridLayout()
            gg.setSpacing(8)
            for i, (side, key) in enumerate((("Top", "t"), ("Bottom", "b"), ("Left", "l"), ("Right", "r"))):
                s = _spin(-100000, 100000)
                s.valueChanged.connect(lambda v, w=which, k=key: self._typed(w, k, v))
                gg.addLayout(cell(side, s), i // 2, i % 2)
                self.pos[(which, key)] = s
            rv.addLayout(gg)
        section("Grade")
        g2 = QGridLayout()
        g2.setSpacing(8)
        self.cert = QLineEdit()
        self.cert.setPlaceholderText("Cert #")
        self.predict = _spin(0, 10, 1, 0.5)
        self.predict.setSpecialValueText("–")
        self.actual = _spin(0, 10, 1, 0.5)
        self.actual.setSpecialValueText("–")
        g2.addLayout(cell("Cert #", self.cert), 0, 0, 1, 2)
        g2.addLayout(cell("Predict", self.predict), 1, 0)
        g2.addLayout(cell("Actual", self.actual), 1, 1)
        rv.addLayout(g2)
        rv.addStretch(1)
        rv_out.addWidget(soft_scroll(inner, min_h=200), 1)
        rv = rv_out
        self.b_auto = QPushButton("Find again")
        self.b_auto.setToolTip("Place this side's guides from the photo again, losing your changes to them")
        self.b_auto.clicked.connect(lambda: self.find(self.side, force=True))
        self.b_save = QPushButton("Save")
        self.b_save.clicked.connect(self.save)
        self.b_exp = QPushButton("Export")
        self.b_exp.setToolTip("Save the report as an image: both sides with their guides, the splits and the "
                              "grade, in the card's folder under reports (not a listing photo)")
        self.b_exp.clicked.connect(self.export)
        self.b_pub = QPushButton("Publish", objectName="primary")
        self.b_pub.setToolTip("Add the report to the card's listing photos, and to its live eBay listing "
                              "when it is up")
        self.b_pub.clicked.connect(self.publish)
        # two even rows, every button the same height: the quiet ones above, the report's two below
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for i, b in enumerate((self.b_auto, self.b_save, self.b_exp, self.b_pub)):
            b.setFixedHeight(36)
            b.setMinimumWidth(0)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setStyleSheet("padding: 0 10px;")
            grid.addWidget(b, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        rv.addLayout(grid)
        self.note = QLabel("", objectName="small")
        self.note.setWordWrap(True)
        rv.addWidget(self.note)
        right.setFixedWidth(330)
        h.addWidget(right)
        self._dirty = False
        self._autosave = QTimer(self, singleShot=True, interval=1200)
        self._autosave.timeout.connect(lambda: self.save(quiet=True))
        self.set_side("front", load=False)

    # ---------- the cards
    def refresh(self):
        import stats
        cur = self.card["folder"] if self.card else None
        q = self.q.text().strip().lower()
        self.lst.blockSignals(True)
        self.lst.clear()
        out, seen = [], set()
        names = list(self.m._card_names())
        for n in names:
            out.append((n, os.path.join(self.m.out_dir, engine.safe_name(n))))
        try:
            dirs = sorted((e for e in os.scandir(self.m.out_dir) if e.is_dir()), key=lambda e: -e.stat().st_mtime)
        except OSError:
            dirs = []
        for e in dirs[:600]:
            out.append((e.name, e.path))
        for name, folder in out:
            nf = os.path.normpath(folder)
            if nf in seen or (q and q not in name.lower()):
                continue
            try:
                files = sorted(os.listdir(folder))
            except OSError:
                continue
            photos = {}
            for f in files:
                mm = stats.MAIN_PHOTO_RE.search(f)
                if mm and mm.group(2) not in photos:
                    photos[mm.group(2)] = os.path.join(folder, f)
            if not photos:
                continue
            seen.add(nf)
            slug = os.path.basename(folder.rstrip(os.sep))
            done = os.path.exists(C.path_for(folder, slug))
            it = QListWidgetItem(f"{name}\n{'Measured' if done else 'Not measured yet'}")
            it.setData(Qt.UserRole, {"name": name, "folder": folder, "slug": slug, "photos": photos})
            self.lst.addItem(it)
        self.lst.blockSignals(False)
        row = next((i for i in range(self.lst.count()) if self.lst.item(i).data(Qt.UserRole)["folder"] == cur), 0)
        if self.lst.count():
            self.lst.setCurrentRow(row)
            self._pick(row)

    def _pick(self, row):
        if self._dirty:
            self.save(quiet=True)
        it = self.lst.item(row) if row >= 0 else None
        if it is None:
            self.card = None
            self.canvas.set_photo(None, 0)
            return
        d = it.data(Qt.UserRole)
        if self.card and self.card["folder"] == d["folder"]:
            return
        self.card = d
        self.data = C.load(d["folder"], d["slug"])
        self.imgs = {}
        self.title.setText(d["name"])
        self.cert.setText(self.data.get("cert", ""))
        self.predict.setValue(float(self.data.get("predict") or 0))
        self.actual.setValue(float(self.data.get("actual") or 0))
        self.set_side("front" if "front" in d["photos"] else "back")

    def set_side(self, sd, load=True):
        self.side = sd
        for k, b in self.side_btns.items():
            b.setChecked(k == sd)
        self.g_side.setText(sd.upper())
        if not load or not self.card:
            self._show_numbers()
            return
        if sd not in self.card["photos"]:
            self.canvas.set_photo(None, 0)
            self._note(f"No {sd} photo in this card's folder.")
            self._show_numbers()
            return
        self._load_side(sd)

    def _load_side(self, sd):
        """The photo, and its guides: saved ones, else found (in the background, a moment for a big photo)."""
        if sd in self.imgs:
            self.canvas.set_photo(*self.imgs[sd])
            self.canvas.set_guides(self.data.get(sd))
            self._show_numbers()
            if not self.data.get(sd):
                self.find(sd)
            return
        path = self.card["photos"][sd]
        folder = self.card["folder"]
        self._note("Opening the photo…")

        def work():
            img = engine.to8(engine.imread(path))
            g = None if self.data.get(sd) else C.auto(img)
            Hh, Ww = img.shape[:2]
            s = min(1.0, LONG / max(Hh, Ww))
            import cv2
            small = cv2.resize(img, (int(Ww * s), int(Hh * s)), interpolation=cv2.INTER_AREA) if s < 1 else img
            return to_qimage(small), Ww, g
        t = CallTask(work)

        def done(r, err):
            if err or not self.card or self.card["folder"] != folder:
                if err:
                    self._note(f"Could not open the photo: {err}")
                return
            qimg, w, g = r
            self.imgs[sd] = (qimg, w)
            if g is not None and not self.data.get(sd):
                self.data[sd] = {"outer": g["outer"], "inner": g["inner"]}
                if not g["found"]:
                    self._note("No printed border found (full art?): the blue lines sit a typical border in; "
                               "place them on the frame you are measuring.")
            if self.side == sd:
                self.canvas.set_photo(qimg, w)
                self.canvas.set_guides(self.data.get(sd))
                self._show_numbers()
                if g is None or g["found"]:
                    self._note("")
        t.then(done)
        self.pool.start(t)

    def find(self, sd, force=False):
        if not self.card or sd not in self.card["photos"]:
            return
        if force:
            self.data.pop(sd, None)
            self.imgs.pop(sd, None)
            self._dirty = True
        self._load_side(sd)

    def open_live(self, item):
        """A live listing to measure: its card folder when there is one, else its photos from eBay, the front
        and back found among them and given a margin so the cut edge shows."""
        import stats
        iid = str(item.get("id", ""))
        if not iid:
            return
        folder = ""
        try:
            folder = self.m.card_folder_for(item, ask=False)
        except Exception:  # noqa: BLE001
            folder = ""
        photos = {}
        if folder and os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                mm = stats.MAIN_PHOTO_RE.search(f)
                if mm and mm.group(2) not in photos:
                    photos[mm.group(2)] = os.path.join(folder, f)
        if photos:
            self._add_live(item, folder, os.path.basename(folder.rstrip(os.sep)), photos)
            return
        c = self.m.ebay_client()
        if c is None or not c.signed_in():
            self.m.notice("Connect eBay to read this listing's photos.", "warn")
            return
        import identify
        cache = os.path.join(identify._cache_dir(), "centering", iid)
        slug = engine.safe_name(item.get("sku") or iid)
        self._note("Reading the listing's photos from eBay…")

        def work():
            import cv2
            from ui_tasks import live_sides
            f_, b_ = live_sides(c, self.m.db, dict(item))
            os.makedirs(cache, exist_ok=True)
            out = {}
            for sd, im in (("front", f_), ("back", b_)):
                if im is None:
                    continue
                im = engine.to8(im)
                pad = int(0.05 * max(im.shape[:2]))
                im = cv2.copyMakeBorder(im, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(24, 24, 26))
                p = os.path.join(cache, f"{slug}_0{2 if sd == 'front' else 3}_{sd}.jpg")
                cv2.imwrite(p, im, [cv2.IMWRITE_JPEG_QUALITY, 94])
                out[sd] = p
            if not out:
                raise RuntimeError("no whole-card photo of the front or back in this listing")
            return out
        t = CallTask(work)
        t.then(lambda photos_, err: self._note(f"Could not read the listing's photos: {err}") if err
               else self._add_live(item, cache, slug, photos_))
        self.pool.start(t)

    def _add_live(self, item, folder, slug, photos):
        title = item.get("title") or slug
        d = {"name": title, "folder": folder, "slug": slug, "photos": photos,
             "live": {"id": str(item.get("id", "")), "sku": item.get("sku", ""), "title": title}}
        it = QListWidgetItem(f"{title[:60]}\nLive on eBay")
        it.setData(Qt.UserRole, d)
        self.lst.insertItem(0, it)
        self.card = None
        self.lst.setCurrentRow(0)
        self._note("Set the guides, then Publish adds the report to this listing.")

    # ---------- numbers
    def _guides_moved(self):
        self._dirty = True
        self._autosave.start()
        self._show_numbers()

    def _typed(self, which, key, v):
        if self._sync:
            return
        g = self.data.get(self.side)
        if not g:
            return
        g[which][key] = float(v)
        self.canvas.update()
        self._guides_moved()

    def _show_numbers(self):
        g = self.data.get(self.side)
        self._sync = True
        for (which, key), s in self.pos.items():
            s.setEnabled(bool(g))
            if g:
                s.setValue(int(round(g[which][key])))
        for which, s in self.rot.items():
            s.setEnabled(bool(g))
            if g:
                s.setValue(g[which]["rot"])
        self._sync = False
        if not g:
            self.g_num.setText("–")
            for chip, val in self.ax.values():
                chip.setText("–")
                chip.setStyleSheet("")
                val.setText("")
            self.both.setText("")
            return
        sp = C.splits(g)
        self.g_num.setText(str(C.expected(g, self.side)))
        for k, (chip, val) in self.ax.items():
            a = C.axis(sp[k], self.side)
            col = "#2BB673" if a["word"] in ("Pristine", "Pass") else "#F08C1B"
            rgb = ",".join(str(int(col[i:i + 2], 16)) for i in (1, 3, 5))
            chip.setText(a["word"].upper())
            chip.setStyleSheet(f"color:{col}; background: rgba({rgb},36); border-radius:8px; font-weight:700;"
                               "letter-spacing:1px;")
            x, y = sp[k]
            val.setText(f"{x:.2f}{'T' if k == 'tb' else 'L'} / {y:.2f}{'B' if k == 'tb' else 'R'}")
        sides = {sd: self.data.get(sd) for sd in ("front", "back")}
        o = C.overall({k: v for k, v in sides.items() if v})
        have = [sd for sd, v in sides.items() if v]
        self.both.setText(f"Both sides: centering allows {o}" if len(have) == 2 else
                          f"Measure the {'back' if self.side == 'front' else 'front'} too for the card's grade")

    def _note(self, t):
        self.note.setText(t)

    def zoom_corner(self, c):
        g = self.data.get(self.side)
        if not g or self.canvas.pm is None:
            return
        k = C.corners(g["outer"])[c.lower()]
        cv = self.canvas
        cv.zoom = min(cv.width(), cv.height()) / (0.16 * max(cv.pm.width(), cv.pm.height()))
        w = QPointF(k[0] * cv.k * cv.zoom, k[1] * cv.k * cv.zoom)
        cv.off = QPointF(cv.width() / 2, cv.height() / 2) - w
        cv.update()

    # ---------- keep and share
    def _record(self):
        d = dict(self.data)
        d["cert"] = self.cert.text().strip()
        d["predict"] = self.predict.value() or None
        d["actual"] = self.actual.value() or None
        d["measured"] = time.strftime("%Y-%m-%d %H:%M")
        for sd in ("front", "back"):
            if d.get(sd):
                sp = C.splits(d[sd])
                d.setdefault("results", {})[sd] = {"tb": [round(x, 2) for x in sp["tb"]],
                                                  "lr": [round(x, 2) for x in sp["lr"]],
                                                  "grade": C.expected(d[sd], sd)}
        d["grade"] = C.overall({sd: d.get(sd) for sd in ("front", "back") if d.get(sd)})
        return d

    def save(self, quiet=False):
        if not self.card:
            return
        try:
            C.save(self.card["folder"], self.card["slug"], self._record())
            self._dirty = False
            it = self.lst.currentItem()
            if it is not None:
                it.setText(f"{self.card['name']}\nMeasured")
            if not quiet:
                self._note("Saved with the card.")
        except OSError as e:
            self._note(f"Could not save: {e}")

    def _page(self, then, tries=0):
        """The report page, once both sides are open (the other side opens first when it is not yet)."""
        if not self.card:
            return
        missing = [sd for sd in ("front", "back") if sd in self.card["photos"] and sd not in self.imgs]
        if missing and tries < 60:
            if tries == 0:
                self._note("Opening the other side first…")
                for sd in missing:
                    self._load_side(sd)
            QTimer.singleShot(250, lambda: self._page(then, tries + 1))
            return
        self.save(quiet=True)
        then(render_report(self.card["name"], self._record(), self.imgs))

    def export(self):
        """The report as an image, kept in the card's folder under reports, where it is never taken for a
        listing photo."""
        def done(img):
            d = os.path.join(self.card["folder"], "reports")
            os.makedirs(d, exist_ok=True)
            out = os.path.join(d, f"{self.card['slug']}_centering.png")
            if not img.save(out):
                self._note("Could not write the report.")
                return
            self._note(f"Report saved: reports/{os.path.basename(out)}")
            self.m.notice("Centering report saved as an image.", "ok", action=("Show", lambda p=out: subprocess_reveal(p)))
        self._page(done)

    def publish(self):
        """The report as the card's last listing photo: saved beside its other photos (so every upload takes
        it), and added to the live listing on eBay when the card is up."""
        import ebay
        card = self.card
        if not card:
            return
        rec = ebay.load_records(self.m.out_dir).get(ebay.sku_for(card["slug"])) or {}
        if card.get("live"):                       # opened from Store: that listing, whatever CardCrop recorded
            rec = {"status": "published", "listing_id": card["live"]["id"], "sku": card["live"].get("sku", "")}
        live = rec.get("status") == "published" and rec.get("listing_id")

        def done(img):
            folder, slug = card["folder"], card["slug"]
            for old in os.listdir(folder):
                if "_13_centering" in old:
                    try:
                        os.remove(os.path.join(folder, old))
                    except OSError:
                        pass
            out = os.path.join(folder, f"{slug}_13_centering.jpg")
            if not img.save(out, "JPG", 92):
                self._note("Could not write the report.")
                return
            self.data["published"] = time.strftime("%Y-%m-%d %H:%M")
            self.save(quiet=True)
            if not card.get("live"):
                try:
                    self.m._mark_changed(card["name"])  # an upload or re-upload takes the new photo
                except Exception:  # noqa: BLE001
                    pass
            if not live:
                self._note("Added to the card's listing photos: it goes up with the listing.")
                self.m.notice(f"Centering report added to {card['name']}'s listing photos.", "ok", secs=4)
                return
            c = self.m.ebay_client()
            if c is None or not c.signed_in():
                self._note("Added to the listing photos here; connect eBay to add it to the live listing.")
                return
            from ui_tasks import AddLivePhotoTask
            self._note("Adding the report to the live listing…")
            iid = str(rec["listing_id"])
            had = live_reports(self.m.cfg).get(iid, "")     # one report a listing: a new one takes its place
            t = AddLivePhotoTask(c, {"id": iid, "sku": rec.get("sku") or ebay.live_sku(self.m.out_dir, slug)},
                                 out, replace=had)

            def landed(_iid, err, t=t):
                if err:
                    self._note(f"eBay did not take the photo: {err}")
                    return
                set_live_report(self.m.cfg, iid, t.url)
                self._note("The report is on the live listing now" + (", in place of the earlier one." if had else "."))
                self.m.notice(f"Centering report {'replaced' if had else 'added'} on {card['name']}.", "ok", secs=4)
                sp = getattr(self.m, "store_page", None)
                if sp is not None and hasattr(sp, "listings"):
                    try:
                        sp.listings.fill()
                    except Exception:  # noqa: BLE001
                        pass
            relay = _Relay(landed)
            relay._sig = t.sig
            t.sig.done.connect(relay.fire)
            self._relays = getattr(self, "_relays", []) + [relay]
            QThreadPool.globalInstance().start(t)
        self._page(done)


def live_reports(cfg) -> dict:
    """Listings with a centering report on eBay: listing id -> the report photo's address."""
    import json
    try:
        return json.loads(str(cfg.value("live_centering", "") or "{}"))
    except ValueError:
        return {}


def set_live_report(cfg, iid, url):
    import json
    d = live_reports(cfg)
    d[str(iid)] = url or d.get(str(iid), "") or "yes"
    cfg.setValue("live_centering", json.dumps(d))


def render_report(name, rec, imgs, width=1800) -> QImage:
    """The report page: quiet, white, small type."""
    sides = [sd for sd in ("front", "back") if rec.get(sd) and sd in imgs]
    pad, gap = 70, 50
    colw = (width - 2 * pad - gap * (max(1, len(sides)) - 1)) // max(1, len(sides))
    img_h = int(colw * 88 / 63) + 40
    H = pad + 150 + img_h + 230 + pad
    page = QImage(width, H, QImage.Format_RGB32)
    page.fill(QColor("#FFFFFF"))
    p = QPainter(page)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    ink, mute, line = QColor("#111111"), QColor("#8A8A8F"), QColor("#E6E6E3")

    def text(x, y, s, size, col=ink, bold=False, w=None, align=Qt.AlignLeft, spacing=0.0):
        f = QFont(TH.SANS)
        f.setPixelSize(size)
        f.setBold(bold)
        if spacing:
            f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(x, y, w or (width - x - pad), size * 1.6), align | Qt.AlignTop, s)
    text(pad, pad, "CENTERING REPORT", 20, mute, spacing=3)
    text(pad, pad + 34, name, 38, ink, True)
    meta = " · ".join(x for x in (time.strftime("%d %b %Y"), f"Cert {rec['cert']}" if rec.get("cert") else "",
                                  f"Predicted {rec['predict']:g}" if rec.get("predict") else "",
                                  f"Actual {rec['actual']:g}" if rec.get("actual") else "") if x)
    text(pad, pad + 90, meta, 20, mute)
    if rec.get("grade") is not None:
        text(width - pad - 360, pad, "CENTERING ALLOWS", 20, mute, w=360, align=Qt.AlignRight, spacing=3)
        text(width - pad - 360, pad + 26, str(rec["grade"]), 84, ink, True, w=360, align=Qt.AlignRight)
    y0 = pad + 150
    p.setPen(QPen(line, 2))
    p.drawLine(pad, y0 - 20, width - pad, y0 - 20)
    for i, sd in enumerate(sides):
        x0 = pad + i * (colw + gap)
        qimg, full_w = imgs[sd]
        g = rec[sd]
        k = qimg.width() / full_w
        cs = C.corners(g["outer"])
        xs, ys = [c[0] * k for c in cs.values()], [c[1] * k for c in cs.values()]
        m = 0.04 * (max(xs) - min(xs))
        src = QRectF(min(xs) - m, min(ys) - m, (max(xs) - min(xs)) + 2 * m, (max(ys) - min(ys)) + 2 * m)
        s = min(colw / src.width(), img_h / src.height())
        dst = QRectF(x0 + (colw - src.width() * s) / 2, y0, src.width() * s, src.height() * s)
        path = QPainterPath()
        path.addRoundedRect(dst, 14, 14)
        p.save()
        p.setClipPath(path)
        p.drawImage(dst, qimg, src)
        p.restore()

        def W(x, y):
            return QPointF(dst.x() + (x * k - src.x()) * s, dst.y() + (y * k - src.y()) * s)
        for which, col in (("outer", OUTER), ("inner", INNER)):
            pen = QPen(QColor(col), 2.4)
            pen.setDashPattern([5, 4])
            p.setPen(pen)
            for side in C.SIDES:
                a, b = C.line(g[which], side)
                p.drawLine(W(*a), W(*b))
        sp = C.splits(g)
        ty = dst.bottom() + 28
        text(x0, ty, sd.upper(), 18, mute, w=colw, spacing=3)
        text(x0, ty + 26, f"Grade {C.expected(g, sd)}", 30, ink, True, w=colw)
        bw = C.borders(g)
        for j, (kk, cap, a_, b_) in enumerate((("tb", "Top / Bottom", "T", "B"), ("lr", "Left / Right", "L", "R"))):
            cx = x0 + j * colw / 2
            ax_ = C.axis(sp[kk], sd)
            x_, y_ = sp[kk]
            text(cx, ty + 80, cap, 18, mute, w=colw / 2)
            text(cx, ty + 104, f"{x_:.2f}{a_} / {y_:.2f}{b_}", 24, ink, True, w=colw / 2)
            col = QColor("#2BB673" if ax_["word"] in ("Pristine", "Pass") else "#E07A10")
            text(cx, ty + 138, ax_["word"], 18, col, True, w=colw / 2)
        text(x0, ty + 170, f"Borders, px  T {bw['top']:.0f}  B {bw['bottom']:.0f}  L {bw['left']:.0f}  R {bw['right']:.0f}"
             f"   ·   turned {g['outer']['rot']:+.2f}° / {g['inner']['rot']:+.2f}°", 16, mute, w=colw)
    text(pad, H - pad + 10, "Measured in CardCrop against PSA's published centering limits (front 55/45 and back "
         "75/25 for a 10). Green: the cut edge. Blue: the printed frame.", 16, mute)
    p.end()
    return page


# names from the other parts, bound once every part has loaded
from ui_base import subprocess_reveal, to_qimage  # noqa: E402
from ui_tasks import CallTask, _Relay  # noqa: E402
from ui_widgets import Island, soft_scroll, with_arrows  # noqa: E402
