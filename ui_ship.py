"""The Shipments page: your eBay sales' tracking numbers and ones you add by hand, each with a nickname,
its USPS scan history as a timeline, and a link to the carrier's page. The data and the USPS calls are in
shiptrack.py; this is only the page."""
from __future__ import annotations

import datetime as dt
import html

from PySide6.QtCore import QRectF, QThreadPool, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

import shiptrack as st
from ui_base import LIME
from ui_tasks import CallTask
from ui_widgets import Island

RED, AMBER, TEXT, MUTED = "#FF6B5A", "#F2C14B", "#F2F2F0", "#A4A4AC"
FILTERS = (("active", "Moving"), ("delivered", "Delivered"), ("archived", "Archived"), ("all", "All"))
AUTO_EVERY = 30 * 60 * 1000
BTN_H = 44                    # every button on the page, the same height
DIM = "#3A3A40"
BLUE = "#7CC4FF"                  # inbound: coming to you
CARD = "rgba(255,255,255,0.045)"


def dir_tag(it, size=11):
    """A small OUT or IN pill: what you send, or what comes to you."""
    out = st.direction_of(it) == "out"
    col = LIME if out else BLUE
    t = QLabel("↗ OUT" if out else "↙ IN")
    t.setStyleSheet(f"font-size: {size}px; font-weight: 700; color: {col}; background: rgba(255,255,255,0.07);"
                    f"border-radius: 6px; padding: 0px 8px;")
    t.setAlignment(Qt.AlignCenter)
    t.setFixedHeight(size + 10)
    t.setToolTip("Outbound: going out to a buyer" if out else "Inbound: coming to you")
    return t


def when(t: float, with_time: bool = True) -> str:
    if not t:
        return ""
    d = dt.datetime.fromtimestamp(t)
    s = f"{d:%a %b} {d.day}"
    if d.year != dt.date.today().year:
        s += f", {d.year}"
    return s + (f", {d:%I:%M %p}".replace(" 0", " ") if with_time else "")


class _Form(QDialog):
    """A small form: a few labelled fields, OK and Cancel."""

    def __init__(self, parent, title, fields, note=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        v.setSpacing(14)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            n.setOpenExternalLinks(True)
            n.setStyleSheet("font-size: 15px;")
            v.addWidget(n)
        f = QFormLayout()
        f.setSpacing(10)
        self.edits = {}
        for key, label, value, secret in fields:
            if isinstance(value, list):                  # [(data, text), ...]: a choice
                from PySide6.QtWidgets import QComboBox
                e = QComboBox()
                for d_, t_ in value:
                    e.addItem(t_, d_)
            else:
                e = QLineEdit(value)
                if secret:
                    e.setEchoMode(QLineEdit.PasswordEchoOnEdit)
            e.setMinimumHeight(36)
            e.setStyleSheet("font-size: 16px;")
            lab = QLabel(label)
            lab.setStyleSheet("font-size: 15px;")
            f.addRow(lab, e)
            self.edits[key] = e
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self):
        return {k: (e.currentData() if hasattr(e, "currentData") else e.text().strip()) for k, e in self.edits.items()}


class Elided(QLabel):
    """One line, cut with … to whatever width it is given."""

    def __init__(self, text="", style=""):
        super().__init__()
        self.full = text
        self.setStyleSheet(style)
        self.setMinimumWidth(40)
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(text)

    def set_full(self, text):
        self.full = text
        self.setToolTip(text)
        self._fit()

    def _fit(self):
        super().setText(self.fontMetrics().elidedText(self.full, Qt.ElideRight, max(10, self.width())))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


class StageBar(QWidget):
    """The package's progress as segments, lit up to where it is. With labels it is clickable: a click on a
    stage marks the package there by hand."""
    picked = Signal(int)

    def __init__(self, labels=False, parent=None):
        super().__init__(parent)
        self.stage, self.labels, self.bad, self.names = 0, labels, False, st.STAGES
        self.setFixedHeight(44 if labels else 6)

    def set(self, stage, bad=False, names=None):
        self.stage, self.bad, self.names = stage, bad, names or st.STAGES
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n, gap = len(self.names), 6
        w = (self.width() - gap * (n - 1)) / n
        h = 6
        lit = QColor(RED if self.bad else LIME)
        for i in range(n):
            x = i * (w + gap)
            p.setPen(Qt.NoPen)
            p.setBrush(lit if i <= self.stage else QColor(DIM))
            p.drawRoundedRect(QRectF(x, 0, w, h), h / 2, h / 2)
            if self.labels:
                f = QFont(self.font())
                f.setPixelSize(13)
                f.setBold(i == self.stage)
                p.setFont(f)
                p.setPen(QColor(TEXT if i <= self.stage else MUTED))
                p.drawText(QRectF(x, 18, w, 24), Qt.AlignHCenter | Qt.AlignTop, self.names[i])
        p.end()


class Row(QWidget):
    """One package in the list, as a tile: nickname, a smaller line under it, and its stage bar."""
    HEIGHT = 112                   # fixed, so the tile always holds its three lines whatever the fonts load as

    def __init__(self, it):
        super().__init__()
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(6)
        k = st.stage_of(it)
        names = st.stages_of(it)
        title = Elided(it["nickname"], f"font-size: 15px; font-weight: 700; color: {TEXT}; background: transparent;")
        title.setFixedHeight(24)
        v.addWidget(title)
        scan = next((r for r in st.timeline(it) if r["kind"] == "scan"), None)
        bits = ["Local pickup" if it.get("pickup") else f"{it['carrier']} · {it['number'][-10:]}", names[k]]
        if scan and scan["t"]:
            bits.append(when(scan["t"]))
        elif it.get("status") == st.NOT_YET and not it.get("pickup"):
            bits.append("not scanned yet")
        bad = bool(it.get("error")) and not scan and not it.get("pickup")
        if bad:
            bits.append("could not check")
        line = QHBoxLayout()
        line.setSpacing(8)
        line.addWidget(dir_tag(it, 10))
        sub = Elided(" · ".join(bits), f"font-size: 12px; color: {MUTED}; background: transparent;")
        sub.setFixedHeight(22)
        line.addWidget(sub, 1)
        v.addLayout(line)
        v.addStretch(1)
        bar = StageBar()
        bar.set(k, bad, names)
        v.addWidget(bar)


class ShipPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.m = main
        self.filter = "active"
        self.items: list[dict] = []
        self.cur_id = None
        self.busy = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        # header
        top = Island()
        tv = QHBoxLayout(top)
        tv.setContentsMargins(22, 16, 22, 16)
        tv.setSpacing(10)
        title = QLabel("Shipments", objectName="display")
        tv.addWidget(title)
        self.summary = QLabel("")
        self.summary.setStyleSheet(f"font-size: 15px; color: {MUTED};")
        from PySide6.QtWidgets import QSizePolicy as _SP
        self.summary.setSizePolicy(_SP.Ignored, _SP.Preferred)
        tv.addWidget(self.summary)
        tv.addStretch(1)
        self.b_add = QPushButton("Add tracking", objectName="primary")
        self.b_add.setToolTip("Track a number by hand, with a nickname")
        self.b_add.clicked.connect(self.add_manual)
        self.b_sync = QPushButton("Sync eBay")
        self.b_sync.setToolTip("Read your eBay sales now: every sale with a tracking number joins the list")
        self.b_sync.clicked.connect(self.sync_ebay)
        self.b_check = QPushButton("Check all")
        self.b_check.setToolTip("Ask USPS about every package still moving (it also does this every 30 minutes)")
        self.b_check.clicked.connect(lambda: self.check(force=True))
        self.b_api = QPushButton("USPS API…")
        self.b_api.setToolTip("Your USPS developer app's Consumer Key and Secret, for the scan history")
        self.b_api.clicked.connect(self.edit_api)
        for b in (self.b_add, self.b_sync, self.b_check, self.b_api):
            b.setMinimumHeight(38)
            tv.addWidget(b)
        outer.addWidget(top)

        body = QHBoxLayout()
        body.setSpacing(12)
        # the list
        left = Island()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 14)
        lv.setSpacing(10)
        seg = QFrame(objectName="segbox")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(4, 4, 4, 4)
        sl.setSpacing(4)
        self.seg = {}
        for key, label in FILTERS:
            b = QPushButton(label, objectName="seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            sl.addWidget(b, 1)
            self.seg[key] = b
        lv.addWidget(seg)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find by nickname, number or buyer")
        self.search.setMinimumHeight(36)
        self.search.setStyleSheet("font-size: 15px;")
        self.search.textChanged.connect(lambda _t: self.fill())
        lv.addWidget(self.search)
        self.listw = QListWidget()
        self.listw.setStyleSheet("QListWidget { border: none; background: transparent; outline: none; }"
                                 f"QListWidget::item {{ background: {CARD}; border-radius: 14px; margin-bottom: 10px; }}"
                                 "QListWidget::item:selected { background: rgba(255,255,255,0.10);"
                                 " border: 1px solid rgba(214,242,75,0.55); }")
        self.listw.setSpacing(0)
        self.listw.setWordWrap(True)
        self.listw.currentItemChanged.connect(lambda cur, _p: self.show_item(cur.data(Qt.UserRole) if cur else None))
        lv.addWidget(self.listw, 1)
        left.setFixedWidth(440)             # fixed: what a package says never moves the split
        body.addWidget(left, 2)

        # the package
        right = Island()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(26, 22, 26, 22)
        rv.setSpacing(10)
        self.empty = QLabel("Nothing selected. Add a tracking number, or Sync eBay to bring in your sales.")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"font-size: 17px; color: {MUTED};")
        rv.addWidget(self.empty)
        self.detail = QWidget()
        dv = QVBoxLayout(self.detail)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(18)
        # where it is, first: a card in the spirit of eBay's tracking
        head = QFrame()
        head.setStyleSheet(f"QFrame#shiphead {{ background: {CARD}; border-radius: 16px; }}")
        head.setObjectName("shiphead")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(24, 22, 24, 22)
        hv.setSpacing(10)
        kr = QHBoxLayout()
        kr.setSpacing(8)
        self.kicker = QLabel("")
        self.kicker.setStyleSheet("font-size: 12px; font-weight: 700; letter-spacing: 1px; background: transparent;")
        from PySide6.QtWidgets import QSizePolicy as _SP2
        self.kicker.setSizePolicy(_SP2.Ignored, _SP2.Preferred)
        kr.addWidget(self.kicker)
        kr.addStretch(1)
        hv.addLayout(kr)
        self.headline = Elided("", f"font-size: 24px; font-weight: 700; color: {TEXT}; background: transparent;")
        hv.addWidget(self.headline)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setMaximumWidth(620)
        self.status.setStyleSheet(f"font-size: 13px; color: {MUTED}; background: transparent;")
        hv.addWidget(self.status)
        hv.addSpacing(10)
        self.bar = StageBar(labels=True)
        self.bar.setMaximumWidth(680)
        hv.addWidget(self.bar)
        dv.addWidget(head)
        # what and whose
        self.nick = Elided("", f"font-size: 22px; font-weight: 700; color: {TEXT};")
        b_ren = QPushButton("Rename")
        b_ren.clicked.connect(self.rename)
        nr = QHBoxLayout()
        nr.setSpacing(10)
        nr.addWidget(self.nick, 1)
        nr.addWidget(b_ren)
        dv.addLayout(nr)
        self.num = QLabel("")
        self.num.setStyleSheet(f"font-size: 17px; font-family: Menlo, monospace; color: {TEXT};")
        self.num.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.b_copy = QPushButton("Copy")
        self.b_copy.clicked.connect(self.copy_number)
        self.b_num = QPushButton("Edit number")
        self.b_num.clicked.connect(self.edit_number)
        self.b_carrier = QPushButton("Carrier")
        self.b_carrier.setToolTip("Change the carrier, when the number's shape or eBay got it wrong")
        self.b_carrier.clicked.connect(self.edit_carrier)
        self.b_open = QPushButton("Open on USPS", objectName="primary")
        self.b_open.clicked.connect(self.open_link)
        from PySide6.QtWidgets import QSizePolicy
        self.num.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # never what holds the page wide
        self.b_num.hide()
        self.b_carrier.hide()
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(self.num, 1)
        for b in (self.b_copy, self.b_open):
            r2.addWidget(b)
        dv.addLayout(r2)
        self.meta = QLabel("")
        self.meta.setWordWrap(True)
        self.meta.setOpenExternalLinks(True)
        self.meta.setStyleSheet(f"font-size: 13px; color: {MUTED};")
        dv.addWidget(self.meta)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,0.12);")
        dv.addWidget(line)
        tl_head = QLabel("Shipment history")
        tl_head.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {MUTED};")
        dv.addWidget(tl_head)
        self.tl = QLabel("")
        self.tl.setWordWrap(True)
        self.tl.setTextFormat(Qt.RichText)
        self.tl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.tl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(self.tl)
        sa.setStyleSheet("background: transparent;")
        dv.addWidget(sa, 1)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.b_one = QPushButton("Check now")
        self.b_one.clicked.connect(lambda: self.check(ids=[self.cur_id]))
        self.b_dir = QPushButton("Mark inbound")
        self.b_dir.clicked.connect(self.toggle_direction)
        self.b_pick = QPushButton("Mark local pickup")
        self.b_pick.clicked.connect(self.toggle_pickup)
        self.b_arch = QPushButton("Archive")
        self.b_arch.clicked.connect(self.toggle_archive)
        b_del = QPushButton("Delete")
        b_del.clicked.connect(self.delete)
        # the less used actions in one menu, so the page fits a narrower window
        from PySide6.QtWidgets import QMenu
        self.more = QMenu(self)
        self.more.setStyleSheet("QMenu { font-size: 15px; padding: 6px; } QMenu::item { padding: 9px 22px; border-radius: 6px; }")
        self.a_dir = self.more.addAction("Mark inbound", self.toggle_direction)
        self.a_pick = self.more.addAction("Mark local pickup", self.toggle_pickup)
        self.more.addSeparator()
        self.a_carrier = self.more.addAction("Change carrier…", self.edit_carrier)
        self.a_num = self.more.addAction("Edit number…", self.edit_number)
        self.more.addSeparator()
        self.a_del = self.more.addAction("Delete…", self.delete)
        self.status_menu = QMenu(self)
        self.status_menu.setStyleSheet(self.more.styleSheet())
        self.b_status = QPushButton("Set status")
        self.b_status.setToolTip("Set where the package is by hand; a newer carrier scan takes over again")
        self.b_status.setMenu(self.status_menu)
        b_more = QPushButton("More")
        b_more.setMenu(self.more)
        for b in (self.b_one, self.b_status, self.b_arch, b_more):
            foot.addWidget(b)
        foot.addStretch(1)
        self.b_dir.hide()
        self.b_pick.hide()
        b_del.hide()
        dv.addLayout(foot)
        rv.addWidget(self.detail, 1)
        self.detail.hide()
        right.setMaximumWidth(1100)         # capped: a wide window gives it room, never stretches it thin
        body.addWidget(right, 3)
        body.addStretch(0)
        outer.addLayout(body, 1)

        for b in self.findChildren(QPushButton):          # one height for every button, text never clipped
            if b.objectName() != "seg":
                b.setFixedHeight(BTN_H)
                b.setMinimumHeight(BTN_H)
                b.setStyleSheet("padding-top: 0px; padding-bottom: 0px; padding-left: 18px; padding-right: 18px;")
        self.web = None
        self.timer = QTimer(self, interval=AUTO_EVERY)       # packages still moving, every half hour
        self.timer.timeout.connect(lambda: (self.check(quiet=True), self.sync_ebay(quiet=True)))
        self.timer.start()
        self.set_filter("active")
        QTimer.singleShot(4000, lambda: (self.sync_ebay(quiet=True), self.check(quiet=True)))

    # ------------------------------------------------------------------ data
    def creds(self):
        return str(self.m.cfg.value("usps_key", "") or ""), str(self.m.cfg.value("usps_secret", "") or "")

    def reload(self):
        self.items = st.load()
        self.fill()

    def _shown(self, it):
        f = self.filter
        if f == "all":
            ok = True
        elif f == "archived":
            ok = it.get("archived")
        elif f == "delivered":
            ok = it.get("delivered") and not it.get("archived")
        else:
            ok = not it.get("delivered") and not it.get("archived")
        q = self.search.text().strip().lower()
        if ok and q:
            hay = " ".join([it["nickname"], it["number"], (it.get("ebay") or {}).get("buyer", ""),
                            (it.get("ebay") or {}).get("title", "")]).lower()
            ok = q in hay or st.clean(q).lower() in it["number"].lower()
        return ok

    def fill(self):
        keep = self.cur_id
        self.listw.blockSignals(True)
        self.listw.clear()
        pick = None
        for it in self.items:
            if not self._shown(it):
                continue
            li = QListWidgetItem()
            li.setData(Qt.UserRole, it["id"])
            li.setToolTip(it["number"])
            row = Row(it)
            from PySide6.QtCore import QSize
            li.setSizeHint(QSize(100, Row.HEIGHT + 10))     # the tile and the gap under it
            self.listw.addItem(li)
            self.listw.setItemWidget(li, row)
            if it["id"] == keep:
                pick = li
        self.listw.blockSignals(False)
        moving = sum(1 for x in self.items if not x.get("delivered") and not x.get("archived"))
        self.summary.setText(f"{moving} moving · {len(self.items)} in all")
        if pick is not None:
            self.listw.setCurrentItem(pick)
            self.show_item(pick.data(Qt.UserRole))
        elif keep and st.find(self.items, keep):
            self.listw.setCurrentItem(None)            # it left this filter (delivered, archived): keep showing it
            self.show_item(keep)
        elif self.listw.count():
            pick = self.listw.item(0)
            self.listw.setCurrentItem(pick)
            self.show_item(pick.data(Qt.UserRole))
        else:
            self.show_item(None)

    def set_filter(self, key):
        if key != self.filter:
            self.cur_id = None                       # a new tab starts at its first package
        self.filter = key
        for k, b in self.seg.items():
            b.setChecked(k == key)
        self.reload()

    def current(self):
        return st.find(self.items, self.cur_id) if self.cur_id else None

    def show_item(self, pid):
        self.cur_id = pid
        it = self.current()
        self.empty.setVisible(it is None)
        self.detail.setVisible(it is not None)
        if it is None:
            return
        out = st.direction_of(it) == "out"
        pickup = bool(it.get("pickup"))
        names, k = st.stages_of(it), st.stage_of(it)
        last = len(names) - 1
        scan = next((r for r in st.timeline(it) if r["kind"] == "scan"), None)
        # the card at the top
        who = "BUYER" if out else "YOU"
        if pickup:
            kick = "LOCAL PICKUP · " + ("PICKED UP" if k == last else "WAITING FOR THE BUYER")
        elif k == last:
            kick = f"DELIVERED TO {who}"
        elif k == 0:
            kick = "LABEL CREATED" + (" · NOT SCANNED YET" if it.get("status") == st.NOT_YET else "")
        else:
            kick = f"SHIPPED TO {who}" if out else "ON ITS WAY TO YOU"
        col = LIME if out else BLUE
        self.kicker.setText(f"<span style='color:{col}'>{'↗ OUTBOUND' if out else '↙ INBOUND'}</span>"
                            f"<span style='color:{MUTED}'>  ·  {html.escape(kick)}</span>")
        if k == last:
            t = scan["t"] if scan and k == last and not pickup else it.get("stage_t") or (scan or {}).get("t", 0)
            self.headline.set_full(f"{names[k]} {when(t, False)}".strip())
        elif it.get("expected") and not pickup:
            self.headline.set_full(f"Arrives by {st.nice_date(it['expected'])}")
        else:
            self.headline.set_full(names[k])
        sub = []
        if scan and scan.get("place"):
            sub.append(f"Last location: {scan['place']}")
        if it.get("stage_manual") is not None:
            sub.append("status set by hand")
        if it.get("error") and not pickup:
            sub.append(st.tidy(it["error"], 140))
        if it.get("checked") and not pickup:
            sub.append(f"checked {when(it['checked'])}")
        self.status.setText(html.escape(" · ".join(sub)))
        self.status.setVisible(bool(sub))
        self.bar.set(k, bool(it.get("error")) and not scan and not pickup, names)
        # what and whose
        self.nick.set_full(it["nickname"])
        n = it["number"]
        self.num.setText("Local pickup" if pickup and n.startswith("PICKUP") else " ".join(n[i:i + 4] for i in range(0, len(n), 4)))
        self.b_open.setText(f"Open on {it['carrier']}")
        self.b_open.setVisible(not pickup)
        self.b_copy.setVisible(not (pickup and n.startswith("PICKUP")))
        self._fill_status_menu(it, names, k, pickup)
        self.a_carrier.setVisible(not pickup)
        self.a_num.setVisible(it["source"] == "manual" and not pickup)
        self.b_one.setVisible(it["carrier"] == "USPS" and not pickup)
        self.a_dir.setText("Mark outbound (going out)" if not out else "Mark inbound (coming to you)")
        self.a_pick.setText("Not a local pickup" if pickup else "Mark local pickup")
        self.b_arch.setText("Restore" if it.get("archived") else "Archive")
        e = it.get("ebay") or {}
        if it["source"] == "ebay":
            title = e.get("title", "")
            title = title if len(title) <= 34 else title[:34].rstrip() + "…"
            bits = [f"eBay sale: {html.escape(title)}"]
            if e.get("buyer"):
                bits.append(f"buyer {html.escape(e['buyer'])}")
            if e.get("price"):
                bits.append(f"${float(e['price']):,.2f}")
            if e.get("url"):
                bits.append(f"<a href='{html.escape(e['url'])}' style='color:{LIME}'>listing</a>")
            self.meta.setText(" · ".join(bits))
        else:
            self.meta.setText(f"Added by hand {when(it.get('added', 0), False)}")
        # the history: date and time on the left, what happened and where on the right
        rows = []
        for r in st.timeline(it):
            d = dt.datetime.fromtimestamp(r["t"]) if r["t"] else None
            day = f"{d:%a, %b} {d.day}" if d else ""
            tm = f"{d:%I:%M %p}".lstrip("0").lower() if d else ""
            if r["kind"] == "scan":
                what = f"<span style='color:{TEXT}'>{html.escape(r['text'])}</span>"
            else:
                what = f"<i style='color:{MUTED}'>{html.escape(r['text'])}</i>"
            place = f"<br><span style='font-size:12px; color:{MUTED}'>{html.escape(r['place'])}</span>" if r.get("place") else ""
            rows.append(f"<tr><td width='130' style='padding:0 18px 22px 0; font-size:14px; color:{TEXT}; line-height:150%'>{day}"
                        f"<br><span style='font-size:12px; color:{MUTED}'>{tm}</span></td>"
                        f"<td style='padding-bottom:22px; font-size:14px; line-height:150%'>{what}{place}</td></tr>")
        self.tl.setText(f"<table cellspacing='0'>{''.join(rows)}</table>" if rows
                        else f"<span style='font-size:14px; color:{MUTED}'>No activity yet.</span>")

    # ------------------------------------------------------------------ actions
    def add_manual(self):
        d = _Form(self, "Add tracking", [("number", "Tracking number", "", False), ("nick", "Nickname", "", False),
                                         ("dir", "Direction", [("in", "↙ Inbound, coming to you"),
                                                               ("out", "↗ Outbound, going out")], False)],
                  "Paste or type the number. The nickname is how it shows in the list; you can change it later.")
        if d.exec() != QDialog.Accepted:
            return
        v = d.values()
        it, err = st.add_manual(v["number"], v["nick"], v.get("dir") or "in")
        if err and it is None:
            return QMessageBox.warning(self, "Add tracking", err)
        self.cur_id = it["id"]
        if self.filter not in ("active", "all"):
            self.filter = "active"
        self.set_filter(self.filter)
        if err:
            self.m.notice(err)
        else:
            self.check(ids=[it["id"]], quiet=True)

    def rename(self):
        it = self.current()
        if not it:
            return
        d = _Form(self, "Rename", [("nick", "Nickname", it["nickname"], False)])
        if d.exec() == QDialog.Accepted:
            st.update(it["id"], nickname=d.values()["nick"])
            self.reload()

    def edit_number(self):
        it = self.current()
        if not it:
            return
        d = _Form(self, "Edit number", [("number", "Tracking number", it["number"], False)],
                  "Correcting the number starts its scan history over.")
        if d.exec() != QDialog.Accepted:
            return
        _it, err = st.update(it["id"], number=d.values()["number"])
        if err:
            return QMessageBox.warning(self, "Edit number", err)
        self.reload()
        self.check(ids=[it["id"]], quiet=True)

    def toggle_direction(self):
        it = self.current()
        if it:
            st.update(it["id"], direction="in" if st.direction_of(it) == "out" else "out")
            self.reload()

    def toggle_pickup(self):
        it = self.current()
        if it:
            st.update(it["id"], pickup=not it.get("pickup"))
            self.reload()

    def edit_carrier(self):
        it = self.current()
        if not it:
            return
        opts = [(c, c) for c in st.LINKS]
        opts.sort(key=lambda o: o[0] != it["carrier"])
        d = _Form(self, "Carrier", [("carrier", "Carrier", opts, False)])
        if d.exec() == QDialog.Accepted:
            st.update(it["id"], carrier=d.values()["carrier"])
            self.reload()

    def toggle_archive(self):
        it = self.current()
        if it:
            st.update(it["id"], archived=not it.get("archived"))
            self.cur_id = None
            self.reload()

    def delete(self):
        it = self.current()
        if not it:
            return
        if QMessageBox.question(self, "Delete", f"Stop tracking “{it['nickname']}” and drop its timeline?") \
                != QMessageBox.Yes:
            return
        st.remove(it["id"])
        self.cur_id = None
        self.reload()

    def copy_number(self):
        it = self.current()
        if it:
            QGuiApplication.clipboard().setText(it["number"])
            self.m.notice("Tracking number copied")

    def open_link(self):
        it = self.current()
        if it:
            QDesktopServices.openUrl(QUrl(st.link(it["number"], it["carrier"])))

    def edit_api(self):
        k, s = self.creds()
        d = _Form(self, "USPS API", [("key", "Consumer Key", k, False), ("secret", "Consumer Secret", s, True)],
                  "Optional. Without a key, CardCrop reads USPS's own tracking page in a hidden built-in browser. "
                  "With one, it asks USPS's tracking API instead (an app at "
                  "<a href='https://developers.usps.com'>developers.usps.com</a>: its Consumer Key and Secret). "
                  "They stay on this Mac. Leave both empty to use the browser.")
        if d.exec() == QDialog.Accepted:
            v = d.values()
            self.m.cfg.setValue("usps_key", v["key"])
            self.m.cfg.setValue("usps_secret", v["secret"])
            self.check(force=True)

    def _fill_status_menu(self, it, names, k, pickup):
        m = self.status_menu
        m.clear()
        last = len(names) - 1
        top = m.addAction("Mark as picked up" if pickup else "Mark as delivered", lambda: self.set_stage(last))
        top.setEnabled(k != last or it.get("stage_manual") is None)
        m.addSeparator()
        for i, name in enumerate(names):
            a = m.addAction(name, lambda i=i: self.set_stage(i))
            a.setCheckable(True)
            a.setChecked(i == k)
        if it.get("stage_manual") is not None:
            m.addSeparator()
            m.addAction("Follow the carrier's scans again", lambda: self.set_stage(None))

    def set_stage(self, k):
        it = self.current()
        if it:
            st.update(it["id"], stage=k)
            self.reload()

    def sync_ebay(self, quiet=False):
        """Your orders' tracking numbers from eBay (GetOrders, the last 90 days), off the UI thread."""
        c = self.m.ebay_client()
        if not c or not c.signed_in():
            if not quiet:
                QMessageBox.information(self, "Sync eBay", "Connect eBay in Settings > eBay first.")
            return
        if getattr(self, "_syncing", False):
            return
        self._syncing = True
        self.b_sync.setEnabled(False)
        self.b_sync.setText("Syncing…")
        t = CallTask(lambda: st.import_ebay(c.shipments()))
        t.then(lambda res, err: self._synced(res, err, quiet))
        QThreadPool.globalInstance().start(t)

    def _synced(self, new, err, quiet):
        self._syncing = False
        self.b_sync.setEnabled(True)
        self.b_sync.setText("Sync eBay")
        if err:
            if not quiet:
                self.m.notice(f"Could not read your eBay orders: {err}", "error")
            return
        self.reload()
        if not quiet:
            self.m.notice(f"{new} new from eBay" if new else "eBay is in sync: no new tracking numbers")
        if new:
            self.check(quiet=True)

    def check(self, ids=None, force=False, quiet=False):
        """USPS scans: through the API when you gave it a key, else USPS's page in the hidden browser."""
        if self.busy:
            return
        k, s_ = self.creds()
        if k and s_:
            self.busy = True
            self._checking()
            t = CallTask(st.refresh, k, s_, ids, force)
            t.then(lambda res, err: self._checked(res, err, quiet))
            QThreadPool.globalInstance().start(t)
            return
        import usps_web
        if not usps_web.available():
            if not quiet:
                self.m.notice("This build has no built-in browser: set the status by hand, or add a USPS API key", "error")
            return
        todo = st.due(ids, force)
        if not todo:
            if not quiet:
                self.m.notice("Nothing needed checking")
            return
        if self.web is None:
            self.web = usps_web.UspsWeb(self)
            self.web.finished.connect(self._read_web)
        self.busy = True
        self._web_quiet = quiet
        self._checking(len(todo))
        self.web.start(todo)

    def _checking(self, n=0):
        self.b_check.setEnabled(False)
        self.b_check.setText(f"Checking {n}…" if n else "Checking…")

    def _read_web(self, results):
        st.apply(results)
        errs = [r["error"] for r in results.values() if "error" in r]
        self._checked({"checked": len(results), "errors": errs}, "", getattr(self, "_web_quiet", True))

    def _checked(self, res, err, quiet):
        self.busy = False
        self.b_check.setEnabled(True)
        self.b_check.setText("Check all")
        self.reload()
        if quiet:
            return
        errs = [st.tidy(x, 120) for x in ((res or {}).get("errors") or ([err] if err else []))]
        waiting = sum(1 for x in self.items if x.get("status") == st.NOT_YET and not x.get("delivered"))
        n = (res or {}).get("checked", 0)
        bits = [f"Checked {n}" if n else "Nothing needed checking"]
        if waiting:
            bits.append(f"{waiting} not scanned by USPS yet")
        if errs:
            bits.append(f"{len(errs)} could not be read")
        self.m.notice(" · ".join(bits), "error" if errs and len(errs) == n else "info",
                      details=errs[0] if errs else "")

    def showEvent(self, e):
        super().showEvent(e)
        sp = getattr(self.m, "store_page", None)          # sales already read by the Store page join the list
        try:
            st.import_ebay(((sp.data if sp is not None else None) or {}).get("sold") or [])
        except Exception:  # noqa: BLE001
            pass
        self.reload()
