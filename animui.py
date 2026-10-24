"""The animation editor: a timeline and a node graph, two views of one anim.Sequence, with a library of
blocks and a properties panel. Every edit goes through AnimEditor.changed, so the view, the other tab
and the saved copy all follow."""

from __future__ import annotations

import json
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QMenu, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

import anim
import card3d as C

INK = QColor("#E8E8EA")
MUTED = QColor("#85858D")
PANEL = QColor("#141416")
LINE = QColor(255, 255, 255, 26)


def _col(fam, a=255):
    c = QColor(anim.COLOURS.get(fam, "#E6E6E8"))
    c.setAlpha(a)
    return c


def _fam(b):
    return anim.KINDS[b["kind"]][1]


def _label(b):
    return anim.KINDS[b["kind"]][0]


def _summary(b):
    """A block's numbers in a few words, for its bar and its node."""
    bits = [f"{b['dur']:.1f} s"]
    for k, v in b["params"].items():
        spec = anim.KINDS[b["kind"]][3].get(k)
        if spec is None:
            continue
        if isinstance(v, str):
            names = dict((k_, l_) for k_, (l_, _f) in C.ENTRANCES.items()) if b["kind"] == "enter" else \
                dict((k_, l_) for k_, (l_, _f) in C.OUTROS.items()) if b["kind"] == "exit" else \
                {k_: anim.KINDS[k_][0] for k_ in anim.STAGGER_OF}
            bits.append(names.get(v, v))
        else:
            bits.append(f"{spec[3]} {v:g}")
    return " · ".join(bits)


# ======================================================================= icons
def draw_kind(p, kind, r, col):
    """A small line drawing for a kind of block, in rect r: what it does at a glance."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(col, max(1.2, r.width() / 11), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    cx, cy = x + w / 2, y + h / 2

    def card(px, py, cw=w * 0.34, chh=h * 0.48, rot=0.0, fill=False):
        p.save()
        p.translate(px, py)
        p.rotate(rot)
        if fill:
            p.setBrush(col)
        p.drawRoundedRect(QRectF(-cw / 2, -chh / 2, cw, chh), cw * 0.16, cw * 0.16)
        p.restore()

    def arc(rect, start, span, head=True):
        path = QPainterPath()
        path.arcMoveTo(rect, start)
        path.arcTo(rect, start, span)
        p.drawPath(path)
        if head:
            a = math.radians(start + span)
            ex = rect.center().x() + rect.width() / 2 * math.cos(a)
            ey = rect.center().y() - rect.height() / 2 * math.sin(a)
            d = 1 if span > 0 else -1
            t = a + d * math.pi / 2
            hl = w * 0.16
            for k in (0.5, -0.5):
                p.drawLine(QPointF(ex, ey), QPointF(ex - hl * math.cos(t + k), ey + hl * math.sin(t + k)))

    def arrow(x0, y0, x1, y1):
        p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        a = math.atan2(y1 - y0, x1 - x0)
        hl = w * 0.16
        for k in (2.6, -2.6):
            p.drawLine(QPointF(x1, y1), QPointF(x1 + hl * math.cos(a + k), y1 + hl * math.sin(a + k)))
    if kind == "flip":
        card(cx, cy)
        arc(QRectF(x + w * 0.1, cy - h * 0.12, w * 0.8, h * 0.24), 200, -220)
    elif kind == "flip_v":
        card(cx, cy)
        arc(QRectF(cx - w * 0.12, y + h * 0.1, w * 0.24, h * 0.8), 290, -220)
    elif kind == "spin":
        arc(QRectF(x + w * 0.15, y + h * 0.15, w * 0.7, h * 0.7), 120, -300)
    elif kind == "sway":
        path = QPainterPath(QPointF(x + w * 0.1, cy))
        path.cubicTo(QPointF(x + w * 0.35, y + h * 0.1), QPointF(x + w * 0.65, y + h * 0.9), QPointF(x + w * 0.9, cy))
        p.drawPath(path)
    elif kind == "hop":
        card(cx, cy + h * 0.12, rot=0)
        arrow(cx, cy - h * 0.18, cx, y + h * 0.05)
    elif kind == "move":
        arrow(cx, cy, x + w * 0.9, cy)
        arrow(cx, cy, x + w * 0.1, cy)
        arrow(cx, cy, cx, y + h * 0.1)
        arrow(cx, cy, cx, y + h * 0.9)
    elif kind == "tilt":
        card(cx, cy, rot=-22)
    elif kind == "enter":
        card(cx, cy + h * 0.16)
        arrow(cx, y + h * 0.02, cx, cy - h * 0.12)
    elif kind == "exit":
        card(cx, cy + h * 0.16)
        arrow(cx + w * 0.2, cy - h * 0.05, x + w * 0.92, y + h * 0.05)
    elif kind == "stagger":
        for k in range(3):
            p.drawLine(QPointF(x + w * (0.12 + 0.26 * k), y + h * (0.75 - 0.22 * k)),
                       QPointF(x + w * (0.34 + 0.26 * k), y + h * (0.75 - 0.22 * k)))
    elif kind in ("stack", "flip_through", "lift_off"):
        for k in range(3):
            card(cx - w * 0.1 + k * w * 0.1, cy + h * 0.1 - k * h * 0.08, w * 0.4, h * 0.46)
        if kind == "flip_through":
            arc(QRectF(x + w * 0.05, y + h * 0.0, w * 0.6, h * 0.5), 180, -200)
        if kind == "lift_off":
            arrow(x + w * 0.85, cy, x + w * 0.85, y + h * 0.0)
    elif kind == "row":
        for k in range(3):
            card(x + w * (0.2 + 0.3 * k), cy, w * 0.24, h * 0.42)
    elif kind in ("fan",):
        for k in (-1, 0, 1):
            card(cx + k * w * 0.16, cy + abs(k) * h * 0.06, w * 0.3, h * 0.5, rot=k * 22)
    elif kind in ("circle", "carousel"):
        for k in range(6):
            a = 2 * math.pi * k / 6
            p.drawEllipse(QPointF(cx + w * 0.32 * math.cos(a), cy + h * 0.32 * math.sin(a)), w * 0.06, w * 0.06)
        if kind == "carousel":
            arc(QRectF(x + w * 0.3, y + h * 0.3, w * 0.4, h * 0.4), 90, -270)
    elif kind == "wave":
        for k in range(3):
            card(x + w * (0.2 + 0.3 * k), cy, w * 0.22 * (1 - 0.35 * (k == 1)), h * 0.42)
    elif kind == "spread":
        arrow(cx - w * 0.06, cy, x + w * 0.05, cy)
        arrow(cx + w * 0.06, cy, x + w * 0.95, cy)
        card(cx, cy, w * 0.2, h * 0.36)
    elif kind in ("push", "pull"):
        p.drawRect(QRectF(x + w * 0.12, y + h * 0.28, w * 0.5, h * 0.44))
        p.drawPolygon([QPointF(x + w * 0.62, cy - h * 0.1), QPointF(x + w * 0.88, cy - h * 0.22),
                       QPointF(x + w * 0.88, cy + h * 0.22), QPointF(x + w * 0.62, cy + h * 0.1)])
        if kind == "push":
            arrow(x + w * 0.37, y + h * 0.95, x + w * 0.37, y + h * 0.78)
        else:
            arrow(x + w * 0.37, y + h * 0.78, x + w * 0.37, y + h * 0.98)
    elif kind == "orbit":
        p.drawEllipse(QRectF(x + w * 0.08, y + h * 0.3, w * 0.84, h * 0.4))
        p.setBrush(col)
        p.drawEllipse(QPointF(x + w * 0.85, cy), w * 0.08, w * 0.08)
    elif kind == "cam_tilt":
        p.translate(cx, cy)
        p.rotate(-20)
        p.drawRect(QRectF(-w * 0.36, -h * 0.2, w * 0.5, h * 0.4))
        p.drawPolygon([QPointF(w * 0.14, -h * 0.08), QPointF(w * 0.38, -h * 0.2), QPointF(w * 0.38, h * 0.2),
                       QPointF(w * 0.14, h * 0.08)])
    elif kind == "focus":
        for k in (0.4, 0.26, 0.1):
            p.drawEllipse(QPointF(cx, cy), w * k, h * k)
    elif kind in ("sleeve_in", "sleeve_load", "unload", "unsleeve"):
        card(cx, cy + h * 0.06, w * 0.3, h * 0.44, fill=True)
        p.drawRoundedRect(QRectF(cx - w * 0.22, cy - h * 0.28, w * 0.44, h * 0.6), 2, 2)
        if kind in ("sleeve_load", "unload"):
            p.drawRect(QRectF(cx - w * 0.3, cy - h * 0.38, w * 0.6, h * 0.76))
        if kind in ("unload", "unsleeve"):
            arrow(x + w * 0.88, cy + h * 0.2, x + w * 0.88, y + h * 0.95)
    else:                                   # a card
        card(cx, cy, w * 0.42, h * 0.62)
    p.restore()


_ICONS = {}


def kind_icon(kind, fam=None):
    """The kind's drawing as an icon, for menus."""
    key = (kind, fam)
    if key not in _ICONS:
        pm = QPixmap(36, 36)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        draw_kind(p, kind, QRectF(3, 3, 30, 30), _col(fam or anim.KINDS.get(kind, ("", "card"))[1]))
        p.end()
        _ICONS[key] = QIcon(pm)
    return _ICONS[key]


# ======================================================================= timeline
class TimelineView(QWidget):
    """Tracks for the cards and the camera; each block a bar from its start to its end. Drag a bar to slide
    it (its delay), its right end to change its length, the ruler to move the playhead. Double-click a track
    to add a block there at that moment."""

    HEAD, RULER, ROW = 160, 30, 36

    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self.pps = 90.0                       # pixels a second
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._drag = None
        self.setMinimumHeight(self.RULER + self.ROW * 3)

    def rows(self):
        seq = self.ed.seq
        return [("card", i, c["name"]) for i, c in enumerate(seq.cards)] + [("camera", None, "Camera")] + \
            ([("loose", None, "Not linked")] if any(not seq.targets(b["id"]) and _fam(b) != "camera"
                                                    for b in seq.blocks) else [])

    def _x(self, t):
        return self.HEAD + 8 + t * self.pps

    def _t(self, x):
        return max(0.0, (x - self.HEAD - 8) / self.pps)

    def _layout(self):
        """Each track's top and height, and each bar's lane: blocks that overlap in time on one card sit
        in lanes one under another, so none hides another. Returns (tops, heights, [(row, lane, bid, s, e)])."""
        seq = self.ed.seq
        times = seq.times()
        rows = self.rows()
        index = {(k, i): r for r, (k, i, _n) in enumerate(rows)}
        memo = {}
        per = {r: [] for r in range(len(rows))}
        for b in seq.blocks:
            s, e = times[b["id"]]
            if _fam(b) == "camera":
                rr = [index[("camera", None)]]
            else:
                tg = seq.targets(b["id"], memo)
                rr = [index[("card", i)] for i in tg] if tg else [index.get(("loose", None), 0)]
            for r in rr:
                per[r].append((s, e, b["id"]))
        placed, lanes_n = [], {}
        for r, items in per.items():
            ends = []
            for s, e, bid in sorted(items):
                ln = next((k for k, end in enumerate(ends) if end <= s + 1e-6), len(ends))
                if ln == len(ends):
                    ends.append(e)
                else:
                    ends[ln] = e
                placed.append((r, ln, bid, s, e))
            lanes_n[r] = max(1, len(ends))
        tops, hs, y = [], [], self.RULER
        for r in range(len(rows)):
            tops.append(y)
            hs.append(self.ROW + (lanes_n[r] - 1) * (self.ROW - 6))
            y += hs[-1]
        return tops, hs, placed

    def _row_at(self, py):
        tops, hs, _p = self._layout()
        for r, (t, h) in enumerate(zip(tops, hs)):
            if t <= py < t + h:
                return r
        return -1

    def bars(self):
        """Every bar on screen: (QRectF, block id)."""
        tops, _hs, placed = self._layout()
        return [(QRectF(self._x(s), tops[r] + 4 + ln * (self.ROW - 6), max(6.0, (e - s) * self.pps), self.ROW - 8), bid)
                for r, ln, bid, s, e in placed]

    def sizeHint(self):
        from PySide6.QtCore import QSize
        tops, hs, _p = self._layout()
        return QSize(900, (tops[-1] + hs[-1] if tops else self.RULER) + self.ROW)

    def paintEvent(self, _e):
        seq = self.ed.seq
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), PANEL)
        f = QFont(self.font())
        f.setPointSize(f.pointSize() + 1)
        p.setFont(f)
        rows = self.rows()
        # ruler
        ln = seq.length()
        p.setPen(MUTED)
        step = 1.0 if self.pps >= 45 else 2.0
        t = 0.0
        while self._x(t) < self.width():
            x = self._x(t)
            p.drawLine(QPointF(x, self.RULER - 8), QPointF(x, self.RULER))
            p.drawText(QRectF(x + 3, 4, 50, 20), Qt.AlignLeft | Qt.AlignVCenter, f"{t:.0f}s")
            t += step
        # the end of the animation
        p.setPen(QPen(QColor(255, 255, 255, 50), 1, Qt.DashLine))
        p.drawLine(QPointF(self._x(ln), self.RULER), QPointF(self._x(ln), self.height()))
        # tracks
        tops, hs, _pl = self._layout()
        for r, (kind, i, name) in enumerate(rows):
            y, rh = tops[r], hs[r]
            p.fillRect(QRectF(0, y, self.width(), rh), QColor(255, 255, 255, 6 if r % 2 else 0))
            p.setPen(LINE)
            p.drawLine(QPointF(0, y + rh), QPointF(self.width(), y + rh))
            sel = self.ed.sel == (f"card:{i}" if kind == "card" else None)
            p.setPen(INK if sel or kind == "card" else MUTED)
            p.drawText(QRectF(12, y, self.HEAD - 16, self.ROW), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(name, Qt.ElideRight, self.HEAD - 20))
        p.setPen(LINE)
        p.drawLine(QPointF(self.HEAD, 0), QPointF(self.HEAD, self.height()))
        # bars
        for rect, bid in self.bars():
            b = seq.block(bid)
            fam = _fam(b)
            selected = self.ed.sel == bid
            p.setPen(QPen(QColor("#FFFFFF") if selected else _col(fam, 200), 2 if selected else 1))
            p.setBrush(_col(fam, 120 if selected else 70))
            p.drawRoundedRect(rect, 7, 7)
            ic = QRectF(rect.left() + 6, rect.center().y() - 9, 18, 18)
            if rect.width() > 30:
                draw_kind(p, b["kind"], ic, INK)
            p.setPen(INK)
            txt = f"{_label(b)}   {_summary(b)}"
            if b.get("only") is not None and len(seq.targets(bid)) == 1 and len(seq.set_of(bid)) > 1:
                txt = "◆ " + txt                  # a separated card's own copy
            p.drawText(rect.adjusted(30, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(txt, Qt.ElideRight, int(rect.width()) - 36))
            p.fillRect(QRectF(rect.right() - 4, rect.top() + 6, 2, rect.height() - 12), QColor(255, 255, 255, 120))
        # playhead
        x = self._x(self.ed.view.seq_t)
        p.setPen(QPen(QColor(anim.COLOURS["action"]), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        p.setBrush(QColor(anim.COLOURS["action"]))
        p.drawPolygon([QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 9)])
        p.end()

    def _hit(self, pos):
        for rect, bid in reversed(self.bars()):
            if rect.adjusted(-2, 0, 2, 0).contains(pos):
                return bid, rect
        return None, None

    def _row_card(self, pos):
        r = self._row_at(pos.y())
        rows = self.rows()
        return rows[r][1] if 0 <= r < len(rows) and rows[r][0] == "card" else None

    def mousePressEvent(self, e):
        pos = e.position()
        self.setFocus()
        if e.button() == Qt.RightButton:
            bid, _rect = self._hit(pos)
            if bid is not None:
                self.ed.select(bid)
                self.ed.block_menu(self.mapToGlobal(pos.toPoint()), bid, card=self._row_card(pos))
            return
        if pos.y() < self.RULER and pos.x() > self.HEAD:
            self._drag = ("scrub",)
            self.ed.seek(self._t(pos.x()))
            return
        if pos.x() < self.HEAD:
            r = self._row_at(pos.y())
            rows = self.rows()
            if 0 <= r < len(rows) and rows[r][0] == "card":
                self.ed.select(f"card:{rows[r][1]}")
            return
        bid, rect = self._hit(pos)
        if bid is None:
            self.ed.select(None)
            self._drag = ("scrub",)
            self.ed.seek(self._t(pos.x()))
            return
        self.ed.begin_edit()
        if e.modifiers() & Qt.ControlModifier:      # Cmd-drag: drag a copy, the original stays
            bid = self.ed.seq.clone(bid)["id"]
            self.ed.edited(live=True)
        self.ed.select(bid)
        b = self.ed.seq.block(bid)
        if pos.x() > rect.right() - 8:
            self._drag = ("len", bid, pos.x(), b["dur"])
        else:
            self._drag = ("move", bid, pos.x(), b["delay"])

    def mouseMoveEvent(self, e):
        pos = e.position()
        d = self._drag
        if d is None:
            bid, rect = self._hit(pos)
            self.setCursor(Qt.SizeHorCursor if bid and pos.x() > rect.right() - 8 else
                           Qt.OpenHandCursor if bid else Qt.ArrowCursor)
            return
        if d[0] == "scrub":
            self.ed.seek(self._t(pos.x()))
            return
        b = self.ed.seq.block(d[1])
        dt = (pos.x() - d[2]) / self.pps
        snap = 0.1 if not (e.modifiers() & Qt.ShiftModifier) else 0.01
        if d[0] == "move":
            b["delay"] = max(0.0, round((d[3] + dt) / snap) * snap)
        else:
            b["dur"] = max(0.1, round((d[3] + dt) / snap) * snap)
        self.ed.edited(live=True)

    def mouseReleaseEvent(self, _e):
        if self._drag and self._drag[0] in ("move", "len"):
            self.ed.edited()
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        pos = e.position()
        r = self._row_at(pos.y())
        rows = self.rows()
        if pos.x() <= self.HEAD or not (0 <= r < len(rows)):
            return
        kind, i, _n = rows[r]
        t = self._t(pos.x())
        self.ed.add_menu(self.mapToGlobal(pos.toPoint()),
                         inputs=[f"card:{i}"] if kind == "card" else [], delay=t, camera_only=kind == "camera")

    def wheelEvent(self, e):
        if e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            self.pps = max(20.0, min(400.0, self.pps * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15)))
            self.update()
        else:
            super().wheelEvent(e)

    def keyPressEvent(self, e):
        if not self.ed.key(e, where="timeline"):
            super().keyPressEvent(e)


# ======================================================================= nodes
class NodeView(QWidget):
    """The same animation as a graph: card nodes on the left, a node per block. Drag from a node's right
    dot to another's left dot to make the second follow the first (and act on its cards); click a link to
    pick it (Delete removes it), drag it onto another node to redraw it, or drop it on the canvas to remove it. Right-click the canvas to add a node there. Drag the canvas to pan,
    scroll to zoom."""

    W, H = 200, 64

    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self.off = QPointF(0, 0)
        self.zoom = 1.0
        self._drag = None
        self.sel_link = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(180)

    # node geometry, in canvas units
    def nodes(self):
        seq = self.ed.seq
        out = []
        for i, c in enumerate(seq.cards):
            x, y = seq.card_pos.get(f"card:{i}", (40.0, 40.0 + 90.0 * i))
            out.append((f"card:{i}", QRectF(x, y, self.W - 40, self.H - 10)))
        for b in seq.blocks:
            out.append((b["id"], QRectF(b["x"], b["y"], self.W, self.H)))
        return out

    def _to_screen(self, p):
        return QPointF(p.x() * self.zoom + self.off.x(), p.y() * self.zoom + self.off.y())

    def _to_canvas(self, p):
        return QPointF((p.x() - self.off.x()) / self.zoom, (p.y() - self.off.y()) / self.zoom)

    def _in_dot(self, r):
        return QPointF(r.left(), r.center().y())

    def _out_dot(self, r):
        return QPointF(r.right(), r.center().y())

    def paintEvent(self, _e):
        seq = self.ed.seq
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), PANEL)
        # a quiet grid, like a node editor's
        p.setPen(QColor(255, 255, 255, 10))
        g = 40 * self.zoom
        x0 = self.off.x() % g
        y0 = self.off.y() % g
        x = x0
        while x < self.width():
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            x += g
        y = y0
        while y < self.height():
            p.drawLine(QPointF(0, y), QPointF(self.width(), y))
            y += g
        p.save()
        p.translate(self.off)
        p.scale(self.zoom, self.zoom)
        rects = dict(self.nodes())
        # links
        for b in seq.blocks:
            dst = rects[b["id"]]
            for src in b["inputs"]:
                if src not in rects:
                    continue
                on = self.sel_link == (src, b["id"])
                self._wire(p, self._out_dot(rects[src]), self._in_dot(dst),
                           QColor("#FFFFFF") if on else
                           _col("card" if src.startswith("card:") else _fam(seq.block(src)), 200), 4.0 if on else 2.5)
        if self._drag and self._drag[0] == "wire":
            self._wire(p, self._drag[2], self._to_canvas(self._drag[3]), QColor(255, 255, 255, 180))
        f = QFont(self.font())
        f.setPointSize(f.pointSize() + 1)
        times = seq.times()
        for nid, r in self.nodes():
            card = nid.startswith("card:")
            fam = "card" if card else _fam(seq.block(nid))
            sel = self.ed.sel == nid
            p.setPen(QPen(QColor("#FFFFFF") if sel else QColor(255, 255, 255, 40), 2 if sel else 1))
            p.setBrush(QColor("#1E1E22"))
            p.drawRoundedRect(r, 8, 8)
            head = QRectF(r.left(), r.top(), r.width(), 24)
            path = QPainterPath()
            path.addRoundedRect(head, 8, 8)
            p.fillPath(path, _col(fam, 200))
            p.fillRect(QRectF(head.left(), head.bottom() - 8, head.width(), 8), _col(fam, 200))
            f.setBold(True)
            p.setFont(f)
            title = "Card" if card else _label(seq.block(nid))
            draw_kind(p, "card" if card else seq.block(nid)["kind"], QRectF(head.left() + 6, head.top() + 3, 18, 18),
                      QColor("#111114"))
            p.setPen(QColor("#111114"))
            p.drawText(head.adjusted(28, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, title)
            f.setBold(False)
            p.setFont(f)
            p.setPen(INK)
            if card:
                body = seq.cards[int(nid[5:])]["name"]
            else:
                b = seq.block(nid)
                s, e = times[nid]
                rest = _summary(b).split(" · ", 1)
                body = f"{s:.1f}–{e:.1f} s" + (" · " + rest[1] if len(rest) > 1 else "")
            p.drawText(QRectF(r.left() + 10, head.bottom() + 2, r.width() - 20, r.height() - 28),
                       Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(body, Qt.ElideRight,
                                                                                  int(r.width()) - 20))
            for dot, show in ((self._in_dot(r), not card), (self._out_dot(r), True)):
                if show:
                    p.setPen(QPen(QColor("#111114"), 2))
                    p.setBrush(_col(fam))
                    p.drawEllipse(dot, 6, 6)
        p.restore()
        if not seq.cards:
            p.setPen(MUTED)
            p.drawText(self.rect(), Qt.AlignCenter, "Add cards to begin")
        p.end()

    @staticmethod
    def _wire_path(a, b):
        path = QPainterPath(a)
        dx = max(40.0, abs(b.x() - a.x()) * 0.5)
        path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
        return path

    def _wire(self, p, a, b, col, width=2.5):
        path = self._wire_path(a, b)
        p.setPen(QPen(col, width))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _link_at(self, pos):
        """The link under the pointer, as (source, block), or None."""
        c = self._to_canvas(pos)
        rects = dict(self.nodes())
        best, bd = None, 9.0 / self.zoom
        for b in self.ed.seq.blocks:
            for src in b["inputs"]:
                if src not in rects:
                    continue
                path = self._wire_path(self._out_dot(rects[src]), self._in_dot(rects[b["id"]]))
                for k in range(41):
                    q = path.pointAtPercent(k / 40.0)
                    d = math.hypot(q.x() - c.x(), q.y() - c.y())
                    if d < bd:
                        best, bd = (src, b["id"]), d
        return best

    def delete_link(self, link=None):
        link = link or self.sel_link
        if link and link[0] in self.ed.seq.block(link[1])["inputs"]:
            self.ed.begin_edit()
            self.ed.seq.unlink(*link)
            self.sel_link = None
            self.ed.edited()
            self.ed.say("Link removed")

    def _at(self, pos):
        c = self._to_canvas(pos)
        for nid, r in reversed(self.nodes()):
            if (self._out_dot(r) - c).manhattanLength() < 12:
                return nid, "out", r
            if not nid.startswith("card:") and (self._in_dot(r) - c).manhattanLength() < 12:
                return nid, "in", r
            if r.contains(c):
                return nid, "body", r
        return None, None, None

    def mousePressEvent(self, e):
        pos = e.position()
        self.setFocus()
        if e.button() == Qt.RightButton:
            nid, part, _r = self._at(pos)
            c = self._to_canvas(pos)
            link = self._link_at(pos) if nid is None else None
            if link is not None:
                self.sel_link = link
                self.update()
                m = QMenu(self)
                m.addAction("Delete link  ⌫", lambda: self.delete_link(link))
                m.exec(self.mapToGlobal(pos.toPoint()))
            elif nid is None:
                self.ed.paste_pos = (c.x(), c.y())
                self.ed.add_menu(self.mapToGlobal(pos.toPoint()), inputs=[], pos=(c.x(), c.y()))
            elif not nid.startswith("card:"):
                self.ed.select(nid)
                self.ed.block_menu(self.mapToGlobal(pos.toPoint()), nid)
            return
        nid, part, r = self._at(pos)
        self.sel_link = None
        if nid is None:
            link = self._link_at(pos)
            if link is not None:
                # a link: click to pick it (Delete removes it), drag it to another node to redraw it,
                # or drop it on empty canvas to remove it
                self.sel_link = link
                self._drag = ("link", link, pos)
                self.update()
                return
            self.ed.select(None)
            self._drag = ("pan", pos, QPointF(self.off))
            return
        if part == "out":
            self._drag = ("wire", nid, self._out_dot(r), pos)
            return
        if part == "in":
            # pick up the newest link into this node, to move or drop it
            b = self.ed.seq.block(nid)
            if b["inputs"]:
                src = b["inputs"][-1]
                self.ed.begin_edit()
                self.ed.seq.unlink(src, nid)
                rects = dict(self.nodes())
                self._drag = ("wire", src, self._out_dot(rects[src]), pos, True)
                self.ed.edited(live=True)
            return
        self.ed.begin_edit()
        if e.modifiers() & Qt.ControlModifier and not nid.startswith("card:"):    # Cmd-drag: a copy
            nid = self.ed.seq.clone(nid, dx=0.0, dy=0.0)["id"]
            b = self.ed.seq.block(nid)
            r = QRectF(b["x"], b["y"], self.W, self.H)
            self.ed.edited(live=True)
        self.ed.select(nid)
        self._drag = ("node", nid, self._to_canvas(pos), QPointF(r.topLeft()))

    def mouseMoveEvent(self, e):
        pos = e.position()
        d = self._drag
        if d is None:
            nid, part, _r = self._at(pos)
            self.setCursor(Qt.CrossCursor if part in ("in", "out") else Qt.OpenHandCursor if nid else
                           Qt.PointingHandCursor if self._link_at(pos) else Qt.ArrowCursor)
            return
        if d[0] == "pan":
            self.off = d[2] + (pos - d[1])
        elif d[0] == "link":
            if (pos - d[2]).manhattanLength() > 6:           # dragged: lift the link off to redraw it
                src, dst = d[1]
                self.ed.begin_edit()
                self.ed.seq.unlink(src, dst)
                self.sel_link = None
                rects = dict(self.nodes())
                self._drag = ("wire", src, self._out_dot(rects[src]), pos, True)
                self.ed.edited(live=True)
        elif d[0] == "wire":
            self._drag = (d[0], d[1], d[2], pos) + tuple(d[4:])
        elif d[0] == "node":
            c = self._to_canvas(pos)
            np_ = d[3] + (c - d[2])
            if not (e.modifiers() & Qt.ShiftModifier):    # snap to the grid; Shift places freely
                np_ = QPointF(round(np_.x() / 20.0) * 20.0, round(np_.y() / 20.0) * 20.0)
            nid = d[1]
            if nid.startswith("card:"):
                self.ed.seq.card_pos[nid] = (np_.x(), np_.y())
            else:
                b = self.ed.seq.block(nid)
                b["x"], b["y"] = np_.x(), np_.y()
        self.update()

    def mouseReleaseEvent(self, e):
        d = self._drag
        self._drag = None
        if d is None:
            return
        if d[0] == "link":
            self.update()
            return
        if d[0] == "wire":
            nid, part, _r = self._at(e.position())
            if nid is not None and not nid.startswith("card:") and nid != d[1]:
                if not len(d) > 4:
                    self.ed.begin_edit()
                if not self.ed.seq.link(d[1], nid):
                    self.ed.say("That link would make a loop, so it was not made.")
            self.ed.edited()
        elif d[0] == "node":
            self.ed.edited()
        self.update()

    def wheelEvent(self, e):
        k = 1.12 if e.angleDelta().y() > 0 else 1 / 1.12
        pos = e.position()
        c = self._to_canvas(pos)
        self.zoom = max(0.4, min(2.2, self.zoom * k))
        self.off = pos - QPointF(c.x() * self.zoom, c.y() * self.zoom)
        self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F and not e.modifiers():
            self.frame_all()
        elif self.sel_link and e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_link()
        elif not self.ed.key(e, where="nodes"):
            super().keyPressEvent(e)

    def frame_all(self):
        rs = [r for _n, r in self.nodes()]
        if not rs:
            return
        x0, y0 = min(r.left() for r in rs), min(r.top() for r in rs)
        x1, y1 = max(r.right() for r in rs), max(r.bottom() for r in rs)
        z = min(1.4, max(0.4, min((self.width() - 60) / max(1, x1 - x0), (self.height() - 60) / max(1, y1 - y0))))
        self.zoom = z
        self.off = QPointF(30 - x0 * z + (self.width() - 60 - (x1 - x0) * z) / 2,
                           30 - y0 * z + (self.height() - 60 - (y1 - y0) * z) / 2)
        self.update()


# ======================================================================= the editor
class AnimEditor(QFrame):
    """Toolbar, library, the two views and the properties of what is picked."""

    changed = Signal()
    closed = Signal()
    export = Signal()
    blender = Signal()
    cards_wanted = Signal()

    def __init__(self, view, say=None):
        super().__init__()
        self.setObjectName("animdock")
        self.view = view
        self.seq = anim.Sequence()
        self.sel = None
        self._say = say
        self._undo, self._redo = [], []
        self.clip = None                     # a copied block, as JSON
        self.paste_pos = None
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)
        # toolbar
        tb = QHBoxLayout()
        tb.setSpacing(6)
        self.b_play = QPushButton("Play")
        self.b_play.setToolTip("Play or pause  (Space)")
        self.b_play.clicked.connect(self.toggle_play)
        b_start = QPushButton("|◀")
        b_start.setToolTip("Back to the start")
        b_start.clicked.connect(lambda: self.seek(0.0))
        self.time_lbl = QLabel("", objectName="animtime")
        self.b_loop = QCheckBox("Loop")
        self.b_loop.setChecked(True)
        self.b_loop.toggled.connect(self._loop)
        self.tabs = {}
        for key, label in (("timeline", "Timeline"), ("nodes", "Nodes")):
            b = QPushButton(label, objectName="animtab")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.show_tab(k))
            self.tabs[key] = b
        tb.addWidget(self.b_play)
        tb.addWidget(b_start)
        tb.addWidget(self.time_lbl)
        tb.addWidget(self.b_loop)
        tb.addSpacing(16)
        for b in self.tabs.values():
            tb.addWidget(b)
        tb.addStretch(1)
        # the blocks to add sit on a row of their own, so the editor fits a laptop screen
        fb = QHBoxLayout()
        fb.setSpacing(6)
        short = {"action": "Moves", "holder": "Sleeves", "layout": "Arrange", "group": "Set", "camera": "Camera"}
        for fam, label in anim.FAMILIES:
            b = QPushButton(short.get(fam, label) + " ▾")
            b.setToolTip(label)
            m = QMenu(b)
            for k, (lab, f_, _d, _p) in anim.KINDS.items():
                if f_ == fam:
                    m.addAction(kind_icon(k), lab, lambda k_=k: self.add(k_))
            b.setMenu(m)
            b.setIcon(kind_icon({"action": "flip", "holder": "sleeve_in", "layout": "stack", "group": "flip_through",
                                 "camera": "push"}[fam], fam))
            fb.addWidget(b)
        fb.addStretch(1)
        b_cards = QPushButton("Cards…")
        b_cards.setToolTip("Choose the cards: one track and one card node each")
        b_cards.clicked.connect(self.cards_wanted.emit)
        b_undo = QPushButton("↶")
        b_undo.clicked.connect(self.undo)
        b_redo = QPushButton("↷")
        b_redo.clicked.connect(self.redo)
        b_exp = QPushButton("Video…", objectName="animprimary")
        b_exp.setToolTip("Export the animation as a video")
        b_exp.clicked.connect(self.export.emit)
        b_bl = QPushButton("Blender…")
        b_bl.setToolTip("Save the cards, their holders, the camera and every keyframe as a glTF file for "
                        "Blender (File > Import > glTF 2.0), at real size")
        b_bl.clicked.connect(self.blender.emit)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.closed.emit)
        b_undo.setToolTip("Undo  (⌘Z)")
        b_redo.setToolTip("Redo  (⇧⌘Z)")
        for b in (b_undo, b_redo):
            tb.addWidget(b)
        for b in (b_cards, b_bl, b_exp, b_close):
            fb.addWidget(b)
        v.addLayout(tb)
        v.addLayout(fb)
        # the views and the properties
        mid = QHBoxLayout()
        mid.setSpacing(10)
        self.stack = QStackedWidget()
        self.timeline = TimelineView(self)
        self.nodes = NodeView(self)
        self.stack.addWidget(self.timeline)
        self.stack.addWidget(self.nodes)
        mid.addWidget(self.stack, 1)
        self.props = QWidget(objectName="animprops")
        self.props.setMinimumWidth(200)
        self.props.setMaximumWidth(300)
        self.pform = QFormLayout(self.props)
        self.pform.setContentsMargins(12, 10, 12, 10)
        self.pform.setSpacing(8)
        mid.addWidget(self.props)
        v.addLayout(mid, 1)
        self.setStyleSheet(STYLE)
        self.show_tab("timeline")
        self._fill_props()

    # ---------- the sequence
    def set_sequence(self, seq):
        self.seq = seq
        self.view.seq = seq
        self.b_loop.blockSignals(True)
        self.b_loop.setChecked(seq.loop)
        self.b_loop.blockSignals(False)
        self.sel = None
        self._undo, self._redo = [], []
        self._fill_props()
        self.refresh()
        self.nodes.frame_all()

    def begin_edit(self):
        """Remember the sequence as it is, for Undo."""
        self._undo.append(self.seq.to_json())
        self._undo = self._undo[-80:]
        self._redo = []

    def edited(self, live=False):
        self.view.seq = self.seq
        self.refresh()
        if not live:
            self._fill_props()
            self.changed.emit()

    def undo(self):
        if not self._undo:
            return
        self._redo.append(self.seq.to_json())
        self._restore(self._undo.pop())

    def redo(self):
        if not self._redo:
            return
        self._undo.append(self.seq.to_json())
        self._restore(self._redo.pop())

    def _restore(self, text):
        s = anim.Sequence.from_json(text)
        self.seq = s
        self.view.seq = s
        if self.sel and not (self.sel.startswith("card:") or s.block(self.sel)):
            self.sel = None
        self.edited()

    def refresh(self):
        self.timeline.update()
        self.timeline.updateGeometry()
        self.nodes.update()
        self._time()
        self.view.update()

    def say(self, msg):
        if self._say:
            self._say(msg, "info")

    # ---------- picking, adding, deleting
    def select(self, sid):
        self.sel = sid
        self._fill_props()
        self.refresh()

    def add(self, kind, inputs=None, delay=None, pos=None):
        """Add a block: after what is picked (a block, so it follows it; a card, so it acts on it) or, with
        nothing picked, on every card, at the playhead."""
        self.begin_edit()
        seq = self.seq
        fam = anim.KINDS[kind][1]
        if inputs is None:
            if self.sel and (self.sel.startswith("card:") or seq.block(self.sel)):
                inputs, delay = [self.sel], (0.0 if not self.sel.startswith("card:") else self.view.seq_t)
            elif fam == "camera":
                inputs, delay = [], self.view.seq_t
            else:
                inputs, delay = [f"card:{i}" for i in range(len(seq.cards))], self.view.seq_t
        if pos is None:
            src = [seq.block(x) for x in inputs if not x.startswith("card:")]
            if src:
                pos = (max(b["x"] for b in src) + NodeView.W + 60, src[0]["y"])
            else:
                pos = (260.0, 40.0 + 80.0 * (len(seq.blocks) % 6))
        b = seq.add_block(kind, inputs, delay or 0.0, pos)
        self.sel = b["id"]
        self.edited()
        return b

    def add_menu(self, gpos, inputs=None, delay=None, pos=None, camera_only=False):
        m = QMenu(self)
        for fam, label in anim.FAMILIES:
            if camera_only and fam != "camera":
                continue
            sub = m.addMenu(label)
            for k, (lab, f_, _d, _p) in anim.KINDS.items():
                if f_ == fam:
                    sub.addAction(kind_icon(k), lab, lambda k_=k: self.add(k_, list(inputs or []) or None
                                                                          if inputs else
                                                                          ([] if anim.KINDS[k_][1] == "camera"
                                                                           else None), delay, pos))
        if self.clip:
            m.addSeparator()
            m.addAction("Paste  ⌘V", self.paste)
        m.exec(gpos)

    def block_menu(self, gpos, bid, card=None):
        """Right-click on a block: copy, cut, duplicate, delete, and give cards their own copy of it."""
        m = QMenu(self)
        seq = self.seq
        tg = seq.targets(bid)
        if card is not None and len(tg) > 1 and card in tg:
            m.addAction(f"Separate {seq.cards[card]['name']}", lambda: self.separate(bid, card))
        if len(tg) > 1:
            m.addAction("Separate every card", lambda: self.separate(bid))
            m.addSeparator()
        m.addAction("Copy  ⌘C", self.copy)
        m.addAction("Cut  ⌘X", self.cut)
        m.addAction("Duplicate  ⌘D", self.duplicate)
        if self.clip:
            m.addAction("Paste  ⌘V", self.paste)
        m.addSeparator()
        m.addAction("Delete  ⌫", self.delete_selected)
        m.exec(gpos)

    # ---------- keys and the clipboard
    def key(self, e, where):
        """The editor's keys, from either view: ⌘C ⌘X ⌘V ⌘D, ⌘Z and ⇧⌘Z, Delete, Space."""
        cmd = bool(e.modifiers() & Qt.ControlModifier)
        k = e.key()
        if k in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected()
        elif k == Qt.Key_Space:
            self.toggle_play()
        elif cmd and k == Qt.Key_C:
            self.copy()
        elif cmd and k == Qt.Key_X:
            self.cut()
        elif cmd and k == Qt.Key_V:
            self.paste(where=where)
        elif cmd and k == Qt.Key_D:
            self.duplicate()
        elif cmd and k == Qt.Key_Z:
            self.redo() if e.modifiers() & Qt.ShiftModifier else self.undo()
        else:
            return False
        return True

    def copy(self):
        b = self.seq.block(self.sel) if self.sel else None
        if b is not None:
            self.clip = json.dumps(b)
            self.say(f"Copied {_label(b)}")

    def cut(self):
        self.copy()
        if self.clip:
            self.delete_selected()

    def paste(self, where=None):
        """The copied block back: on the picked card or after the picked block, at the playhead on the
        timeline, or where you right-clicked in Nodes."""
        if not self.clip:
            return
        self.begin_edit()
        inputs, delay = None, None
        if self.sel and (self.sel.startswith("card:") or self.seq.block(self.sel)):
            inputs = [self.sel]
            delay = self.view.seq_t if self.sel.startswith("card:") else 0.0
        elif where != "nodes":
            delay = self.view.seq_t
        nb = self.seq.paste(self.clip, inputs=inputs, delay=delay, pos=self.paste_pos)
        self.paste_pos = None
        if nb is not None:
            if delay is not None and inputs is None:
                nb["delay"] = max(0.0, self.view.seq_t - self.seq.follows_from(nb["id"]))
            self.sel = nb["id"]
        self.edited()

    def duplicate(self):
        if self.sel and self.seq.block(self.sel):
            self.begin_edit()
            self.sel = self.seq.clone(self.sel)["id"]
            self.edited()

    def separate(self, bid, card=None):
        self.begin_edit()
        new = self.seq.separate(bid, card)
        if new:
            self.sel = new[0]
            self.say("Separated: each copy now slides, stretches and sets on its own")
        self.edited()

    def delete_selected(self):
        if not self.sel:
            return
        if self.sel.startswith("card:"):
            self.say("Take a card out with Cards….")
            return
        self.begin_edit()
        self.seq.remove_block(self.sel)
        self.sel = None
        self.edited()

    # ---------- playing
    def toggle_play(self):
        self.view.play_seq(not self.view.seq_playing)
        self.b_play.setText("Pause" if self.view.seq_playing else "Play")

    def seek(self, t):
        if self.view.seq_playing:
            self.toggle_play()
        self.view.seek_seq(min(t, self.seq.length()))
        self.refresh()

    def on_time(self, _t):
        self.timeline.update()
        self._time()
        if not self.view.seq_playing:
            self.b_play.setText("Play")

    def _time(self):
        self.time_lbl.setText(f"{self.view.seq_t:4.1f} / {self.seq.length():.1f} s")

    def _loop(self, on):
        self.begin_edit()
        self.seq.loop = on
        self.edited()

    def show_tab(self, key):
        for k, b in self.tabs.items():
            b.setChecked(k == key)
        self.stack.setCurrentWidget(self.timeline if key == "timeline" else self.nodes)
        if key == "nodes":
            self.nodes.frame_all()

    # ---------- properties
    def _fill_props(self):
        while self.pform.rowCount():
            self.pform.removeRow(0)
        seq = self.seq
        if not self.sel:
            t = QLabel("Pick a block or a card", objectName="animhead")
            self.pform.addRow(t)
            hint = QLabel("Add blocks from the menus above. On the timeline, drag a block to slide it and its "
                          "right end to change its length (⇧ for fine steps); double-click a track to add one "
                          "there; right-click a block to separate a card from it. In Nodes, drag from a node's "
                          "right dot to another's left dot to make it follow; right-click to add a node. "
                          "⌘-drag copies, ⌘C ⌘X ⌘V ⌘D, ⌫ deletes, ⌘Z undoes, Space plays.", objectName="animhint")
            hint.setWordWrap(True)
            self.pform.addRow(hint)
            return
        if self.sel.startswith("card:"):
            i = int(self.sel[5:])
            self.pform.addRow(QLabel("Card", objectName="animhead"))
            nm = QLabel(seq.cards[i]["name"] if i < len(seq.cards) else "")
            nm.setWordWrap(True)
            self.pform.addRow(nm)
            hint = QLabel("A block added now acts on this card, at the playhead.", objectName="animhint")
            hint.setWordWrap(True)
            self.pform.addRow(hint)
            return
        b = seq.block(self.sel)
        if b is None:
            self.sel = None
            return self._fill_props()
        self.pform.addRow(QLabel(_label(b), objectName="animhead"))
        s, e = seq.times()[b["id"]]
        after = [x for x in b["inputs"] if not x.startswith("card:")]
        tg = seq.targets(b["id"])
        who = "the camera" if _fam(b) == "camera" else (", ".join(seq.cards[i]["name"] for i in tg) or "no card yet")
        info = QLabel(f"{s:.2f} to {e:.2f} s, on {who}" + (", after " + ", ".join(_label(seq.block(x)) for x in after)
                                                           if after else ""), objectName="animhint")
        info.setWordWrap(True)
        self.pform.addRow(info)

        def spin(val, lo, hi, step, cb, suffix=""):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(2)
            sp.setSingleStep(step)
            sp.setSuffix(suffix)
            sp.setValue(val)
            sp.setKeyboardTracking(False)
            sp.valueChanged.connect(cb)
            return sp

        def setter(key, sub=None):
            def f(v):
                self.begin_edit()
                if sub:
                    b["params"][sub] = v
                else:
                    b[key] = v
                self.edited(live=True)
                self.changed.emit()
            return f
        self.pform.addRow("Delay", spin(b["delay"], 0.0, 60.0, 0.1, setter("delay"), " s"))
        self.pform.addRow("Length", spin(b["dur"], 0.1, 60.0, 0.1, setter("dur"), " s"))
        for k, (dflt, lo, hi, lab) in anim.KINDS[b["kind"]][3].items():
            if isinstance(dflt, str):
                cb = QComboBox()
                items = list(C.ENTRANCES.items()) if b["kind"] == "enter" else \
                    list(C.OUTROS.items()) if b["kind"] == "exit" else \
                    [(k_, (anim.KINDS[k_][0], None)) for k_ in anim.STAGGER_OF]
                for key_, (lb_, _f) in items:
                    cb.addItem(lb_, key_)
                cb.setCurrentIndex(max(0, cb.findData(b["params"].get(k, dflt))))
                cb.activated.connect(lambda _i, k_=k, c_=cb: setter(None, k_)(c_.currentData()))
                self.pform.addRow(lab, cb)
            else:
                self.pform.addRow(lab, spin(float(b["params"].get(k, dflt)), lo, hi,
                                            1.0 if hi > 20 else 0.05, setter(None, k)))
        if len(tg) > 1:
            sp = QPushButton("Separate every card")
            sp.setToolTip("Give each card its own copy of this block, to slide, stretch or set on its own")
            sp.clicked.connect(lambda: self.separate(b["id"]))
            self.pform.addRow(sp)
        rm = QPushButton("Delete block")
        rm.clicked.connect(self.delete_selected)
        self.pform.addRow(rm)


STYLE = """
QFrame#animdock { background: #141416; border-radius: 22px; }
QFrame#animdock QLabel { color: #E8E8EA; }
QLabel#animhead { font-weight: 600; font-size: 15pt; color: #F4F4F2; }
QLabel#animhint { color: #A8A8B0; }
QLabel#animtime { font-family: 'Geist Mono'; color: #E8E8EA; padding: 0 8px; }
QFrame#animdock QPushButton { background: rgba(255,255,255,9); color: #E8E8EA; border: 1px solid rgba(255,255,255,20);
                              border-radius: 10px; padding: 7px 12px; }
QFrame#animdock QPushButton:hover { background: rgba(255,255,255,20); }
QFrame#animdock QPushButton#animtab { border: none; background: transparent; color: #85858D; border-radius: 0;
                                      border-bottom: 2px solid transparent; padding: 7px 4px; }
QFrame#animdock QPushButton#animtab:checked { color: #F4F4F2; border-bottom: 2px solid #D6F24B; }
QFrame#animdock QPushButton#animprimary { background: #D6F24B; color: #111; border: none; font-weight: 600; }
QFrame#animdock QCheckBox { color: #E8E8EA; }
QWidget#animprops { background: rgba(255,255,255,5); border-radius: 14px; }
QWidget#animprops QDoubleSpinBox, QWidget#animprops QComboBox { background: rgba(255,255,255,9); color: #E8E8EA;
    border: 1px solid rgba(255,255,255,20); border-radius: 8px; padding: 4px 8px; }
"""
