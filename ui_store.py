"""CardCrop Store stage: active listings, store categories, sales and orders."""
from __future__ import annotations

import ebay
import engine
import identify
import json
import listing
import os
import time
from PySide6.QtCore import QRectF, QThreadPool, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget
import ui_base as TH
import ui_motion as motion

def mark_video(b, main, iid):
    """A video button for a listing that already has one: ringed, and says so."""
    rp = getattr(main, "reports_page", None)
    if rp is not None and iid and rp.has_video(iid):
        b.setStyleSheet(f"QPushButton {{ border: 2px solid {LIME}; }}")
        b.setToolTip("This listing has a video. Click to make a new one (you will be asked before it is replaced)")


def mark_report(b, main, iid):
    """A centering report button for a listing that has one: ringed, and says so."""
    from ui_centering import live_reports
    if iid and str(iid) in live_reports(main.cfg):
        b.setStyleSheet(f"QPushButton {{ border: 2px solid {LIME}; }}")
        b.setToolTip("This listing has a centering report. Click to measure again; Publish replaces it")


class ListingRow(QFrame):
    """One active listing: quantity and price change right here, everything else in the editor."""

    def __init__(self, view, item):
        super().__init__()
        self.view, self.item = view, item
        self.setObjectName("row")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(64)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 4, 10, 4)
        h.setSpacing(12)
        self.tick = QCheckBox()
        self.tick.setFixedWidth(LST_COLS[0])
        self.tick.setToolTip("Tick listings to change their store categories together")
        self.tick.setChecked(item.get("id") in view.ticked)
        self.tick.toggled.connect(lambda on: view.set_ticked(item.get("id"), on))
        h.addWidget(self.tick)
        self.th = QLabel()
        self.th.setFixedSize(40, 52)
        self.th.setStyleSheet(f"background:{TH.T['pill']}; border-radius:6px;")
        h.addWidget(self.th)
        view.page.thumb_for(self, item)
        v = QVBoxLayout()
        v.setSpacing(2)
        t = QLabel(item.get("title", ""))
        t.setTextFormat(Qt.PlainText)
        t.setMinimumWidth(10)
        t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        t.setStyleSheet("font-weight:500;")
        v.addWidget(t)
        bits = [f"listed {_ago(item.get('start', ''))}"]
        if item.get("watchers"):
            bits.append(f"{item['watchers']} watching")
        if item.get("sku"):
            bits.append(item["sku"])
        cats = view.cat_names(item)
        if cats:
            bits.append(" + ".join(cats))
        sub = QLabel(" · ".join(bits), objectName="mono")
        sub.setMinimumWidth(10)
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(sub)
        h.addLayout(v, 1)
        self.qty = NoWheelSpin()
        self.qty.setRange(0, 9999)
        self.qty.setKeyboardTracking(False)
        self.qty.setValue(int(item.get("qty") or 0))
        self.qty.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.qty.setToolTip("Quantity available. Type a number and press Return, or use the arrows or the Up and "
                            "Down keys, to change it on eBay")
        self._qty = self.qty.value()
        self.qty.editingFinished.connect(self._qty_done)
        self._qt = QTimer(self, singleShot=True, interval=900)
        self._qt.timeout.connect(self._qty_done)
        self.qty.valueChanged.connect(lambda _v: self._qt.start())
        h.addWidget(with_arrows(self.qty, LST_COLS[3]))
        h.addWidget(with_arrows(price_field(item.get("price") or 0, LST_COLS[4],
                                            lambda pr: view.quick(self.item, {"price": pr}),
                                            "Price on eBay. Type any amount and press Return, or use the "
                                            "arrows or the Up and Down keys (10¢ a step)"), LST_COLS[4]))
        b = icon_button("film", "Add a 360° video to this listing", LST_COLS[5])
        b.clicked.connect(lambda: view.add_video(self.item))
        mark_video(b, view.m, item.get("id"))
        h.addWidget(b)
        r = icon_button("report", "Add a centering report: measure this listing's photos in Reports, then "
                                  "Publish adds the report to the listing", LST_COLS[6])
        r.clicked.connect(lambda: view.m.open_centering(self.item))
        mark_report(r, view.m, item.get("id"))
        h.addWidget(r)

    def _qty_done(self):
        q = self.qty.value()
        if q != self._qty:
            self._qty = q
            self.view.quick(self.item, {"available": q})

    def set_pixmap(self, pm):
        self.th.setStyleSheet("")
        self.th.setPixmap(rounded_pixmap(pm, 40, 52, 6))
        fade_in(self.th, 260)                       # the photo fades up over its grey placeholder

    def set_selected(self, on):
        self.setProperty("sel", on)
        self.setStyleSheet(f"QFrame#row {{ background:{TH.T['island2']}; border-radius:10px; }}" if on else "")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.view.select(self.item.get("id"))

    def mouseDoubleClickEvent(self, e):
        if self.item.get("url"):
            self.view.page._open(self.item["url"])


LST_COLS = (22, 40, 0, 96, 120, 30, 30)      # tick, photo, listing, quantity, price, video, report


def _when(iso):
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


# the filters the Store's listings offer, on the Mac and on the phone alike
ENDS = (("Any time left", None), ("Ends within a day", 1), ("Within 3 days", 3), ("Within a week", 7))
AGES = (("Listed any time", ""), ("Listed this week", "new7"), ("Older than 30 days", "old30"),
        ("Older than 90 days", "old90"))
WATCH = (("Watched or not", ""), ("Watched", "yes"), ("No watchers", "no"))


def listing_filter(a: dict, f: dict) -> bool:
    """True when listing a passes every filter in f: pmin, pmax (dollars), ends (days left at most),
    age (new7, old30, old90) and watch (yes, no). An empty or missing filter lets everything through."""
    import datetime as dt
    price = float(a.get("price") or 0)
    if f.get("pmin") and price < float(f["pmin"]):
        return False
    if f.get("pmax") and price > float(f["pmax"]):
        return False
    now = dt.datetime.now(dt.timezone.utc)
    if f.get("ends"):
        end = _when(a.get("end"))
        if end is None or (end - now).total_seconds() > float(f["ends"]) * 86400:
            return False
    age = f.get("age") or ""
    if age:
        start = _when(a.get("start"))
        if start is None:
            return False
        days = (now - start).total_seconds() / 86400
        if (age == "new7" and days > 7) or (age == "old30" and days < 30) or (age == "old90" and days < 90):
            return False
    w = int(a.get("watchers") or 0)
    if (f.get("watch") == "yes" and not w) or (f.get("watch") == "no" and w):
        return False
    return True


def time_left(a: dict) -> str:
    import datetime as dt
    end = _when(a.get("end"))
    if end is None:
        return ""
    s = (end - dt.datetime.now(dt.timezone.utc)).total_seconds()
    if s <= 0:
        return "ending"
    d, h = int(s // 86400), int(s % 86400 // 3600)
    return f"{d}d {h}h left" if d else f"{h}h {int(s % 3600 // 60)}m left"


class ListingsView(QWidget):
    """Every active listing, edited the way Seller Hub's editor would: title, price, quantity,
    condition and best offer, plus video, report, open and end."""

    SORTS = (("Newest first", lambda a: a.get("start", ""), True), ("Price, high to low", lambda a: a.get("price", 0), True),
             ("Price, low to high", lambda a: a.get("price", 0), False),
             ("Most watched", lambda a: a.get("watchers", 0), True), ("Title A to Z", lambda a: a.get("title", "").lower(), False),
             ("Quantity, most first", lambda a: a.get("qty", 0), True))
    # the column headers sort too: each click turns its column's order round
    HEAD_SORTS = {"Listing": (4, 0), "Qty": (5, 5), "Price": (1, 2)}

    def __init__(self, page):
        super().__init__()
        self.page, self.m = page, page.m
        self.items, self.rows, self.cur, self.loaded = [], {}, None, None
        self.page_i, self._filtered = 0, []
        self.ticked = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        left = Island()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 10)
        lv.setSpacing(8)
        bar = QHBoxLayout()
        cap = QLabel("ACTIVE LISTINGS", objectName="mono")
        cap.setContentsMargins(6, 0, 0, 0)
        bar.addWidget(cap)
        self.count = QLabel("", objectName="small")
        self.count.setMinimumWidth(10)
        self.count.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        bar.addWidget(self.count, 1)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Search title or SKU")
        self.q.setMinimumWidth(110)
        self.q.setMaximumWidth(220)
        self.q.textChanged.connect(lambda _t: self.fill(page=0))
        bar.addWidget(self.q)
        self.sort = QComboBox()
        self.sort.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.sort.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        for name, _k, _r in self.SORTS:
            self.sort.addItem(name)
        self.sort.setCurrentIndex(int(self.m.cfg.value("listings_sort", 0) or 0))
        self.sort.currentIndexChanged.connect(lambda i: (self.m.cfg.setValue("listings_sort", i), self.fill(page=0)))
        self.catf = QComboBox()
        self.catf.setToolTip("Show only the listings in one of your store categories (a parent includes its "
                             "subcategories)")
        # full width when there is room, narrower only when the window is
        self.catf.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.catf.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)     # never clipped; the search gives way
        self.catf.setMaximumWidth(260)
        self.catf.activated.connect(lambda _i: self.fill(page=0))
        bar.addWidget(self.catf)
        bar.addWidget(self.sort)
        lv.addLayout(bar)
        # ticked listings change together
        bb = QHBoxLayout()
        bb.setContentsMargins(6, 0, 0, 0)
        bb.setSpacing(6)
        self.tick_lbl = QLabel("", objectName="small")
        self.tick_lbl.setMinimumWidth(10)
        self.tick_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        bb.addWidget(self.tick_lbl, 1)
        for label, on in (("Select all", True), ("Select none", False)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, o=on: self.tick_all(o))
            bb.addWidget(b)
        self.b_bcat = QPushButton("Categories ▾")
        self.b_bcat.setToolTip("Put every ticked listing in a store category, or a second one, at once")
        bm = QMenu(self.b_bcat)
        bm.aboutToShow.connect(lambda: self._batch_cat_menu(bm))
        self.b_bcat.setMenu(bm)
        bb.addWidget(self.b_bcat)
        self.b_bprice = QPushButton("Prices…")
        self.b_bprice.setToolTip("Raise or lower every ticked listing's price at once, by a percentage or an amount")
        self.b_bprice.clicked.connect(self.batch_price)
        bb.addWidget(self.b_bprice)
        lv.addLayout(bb)
        # filters: price range, time left, how long it has been listed, watchers
        fr = QHBoxLayout()
        fr.setContentsMargins(6, 0, 0, 0)
        fr.setSpacing(6)
        self.f_min, self.f_max = PriceBox(), PriceBox()
        for b_, tip in ((self.f_min, "Lowest price shown"), (self.f_max, "Highest price shown")):
            b_.setRange(0, 100000)
            b_.setPrefix("$")
            b_.setSpecialValueText("Any")
            b_.setToolTip(tip)
            b_.setMaximumWidth(96)
            b_.valueChanged.connect(lambda _v: self.fill(page=0))
        fr.addWidget(QLabel("Price", objectName="small"))
        fr.addWidget(self.f_min)
        fr.addWidget(QLabel("to", objectName="small"))
        fr.addWidget(self.f_max)
        self.f_ends, self.f_age, self.f_watch = QComboBox(), QComboBox(), QComboBox()
        for combo, opts in ((self.f_ends, ENDS), (self.f_age, AGES), (self.f_watch, WATCH)):
            for label, val in opts:
                combo.addItem(label, val)
            # sized to a short label, not the longest choice, so the filter row fits a laptop window
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(9)
            combo.currentIndexChanged.connect(lambda _i: self.fill(page=0))
            fr.addWidget(combo)
        self.f_clear = QPushButton("Clear")
        self.f_clear.clicked.connect(self.clear_filters)
        fr.addWidget(self.f_clear)
        fr.addStretch(1)
        lv.addLayout(fr)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(10, 0, 10, 0)
        hdr.setSpacing(12)
        self.head_btns = {}
        for w_, text in zip(LST_COLS, ("", "", "Listing", "Qty", "Price", "", "")):
            if text in self.HEAD_SORTS:
                l = QPushButton(text, objectName="head")
                l.setFlat(True)
                l.setCursor(Qt.PointingHandCursor)
                l.setToolTip(f"Sort by {text.lower()}; click again to turn the order round")
                l.setStyleSheet(f"QPushButton#head {{ background: transparent; border: none; padding: 0; "
                                f"color: {TH.T['muted']}; font-size: {TH.BASE_PT - 1}pt; text-align: "
                                f"{'right' if text != 'Listing' else 'left'}; }} "
                                f"QPushButton#head:hover {{ color: {TH.T['text']}; }}")
                l.clicked.connect(lambda _=False, t=text: self._head_sort(t))
                self.head_btns[text] = l
            else:
                l = QLabel(text, objectName="small")
            if text in ("Qty", "Price") and isinstance(l, QLabel):
                l.setAlignment(Qt.AlignRight)
            if w_:
                l.setFixedWidth(w_)
                hdr.addWidget(l)
            else:
                hdr.addWidget(l, 1)
        lv.addLayout(hdr)
        from PySide6.QtWidgets import QScrollArea
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.lst = QVBoxLayout(body)
        self.lst.setContentsMargins(0, 0, 0, 0)
        self.lst.setSpacing(2)
        self.lst.addStretch(1)
        sa.setWidget(body)
        self._sa = sa
        lv.addWidget(sa, 1)
        # a page at a time: a store of thousands opens as fast as one of fifty
        pg = QHBoxLayout()
        pg.setContentsMargins(6, 6, 6, 2)
        pg.setSpacing(10)
        self.pg_prev = QPushButton("‹  Previous")
        self.pg_prev.clicked.connect(lambda: self.fill(page=self.page_i - 1))
        self.pg_next = QPushButton("Next  ›")
        self.pg_next.clicked.connect(lambda: self.fill(page=self.page_i + 1))
        self.pg_lbl = QLabel("", objectName="small")
        self.pg_lbl.setAlignment(Qt.AlignCenter)
        pg.addWidget(self.pg_prev)
        pg.addWidget(self.pg_lbl, 1)
        pg.addWidget(self.pg_next)
        self.pager = QWidget()
        self.pager.setLayout(pg)
        lv.addWidget(self.pager)
        h.addWidget(left, 5)
        h.addWidget(soft_scroll(self._editor(), min_w=300), 4)
        self.show_editor(None)

    # ------------------------------------------------------------ the editor
    def _editor(self):
        ed = Island()
        ev = QVBoxLayout(ed)
        ev.setContentsMargins(20, 18, 20, 18)
        ev.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(16)
        self.e_photo = QLabel()
        self.e_photo.setFixedSize(120, 166)
        self.e_photo.setStyleSheet(f"background:{TH.T['pill']}; border-radius:10px;")
        top.addWidget(self.e_photo, 0, Qt.AlignTop)
        tv = QVBoxLayout()
        tv.setSpacing(6)
        self.e_head = QLabel("")
        self.e_head.setWordWrap(True)
        self.e_head.setStyleSheet(f"font-size:{TH.BASE_PT + 4}pt; font-weight:600;")
        tv.addWidget(self.e_head)
        self.e_stats = QLabel("", objectName="small")
        self.e_stats.setWordWrap(True)
        tv.addWidget(self.e_stats)
        tv.addStretch(1)
        top.addLayout(tv, 1)
        ev.addLayout(top)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        self.e_title = QLineEdit()
        self.e_title.setMaxLength(80)
        self.e_title.textChanged.connect(self._dirty)
        tl.addWidget(self.e_title)
        self.e_tcount = QLabel("", objectName="small")
        tl.addWidget(self.e_tcount, 0, Qt.AlignRight)
        form.addRow("Title", tl)
        self.e_price = PriceBox()
        self.e_price.setRange(0, 100000)
        self.e_price.setDecimals(2)
        self.e_price.setPrefix("$")
        self.e_price.valueChanged.connect(self._dirty)
        form.addRow("Price", self.e_price)
        self.e_qty = QSpinBox()
        self.e_qty.setRange(0, 9999)
        self.e_qty.valueChanged.connect(self._dirty)
        form.addRow("Available", self.e_qty)
        self.e_cond = QComboBox()
        self.e_cond.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.e_cond.setMinimumContentsLength(6)
        for code, (name, _ebay, _id) in listing.CONDITIONS.items():
            self.e_cond.addItem(f"{code} · {name}", code)
        self.e_cond.currentIndexChanged.connect(self._dirty)
        form.addRow("Condition", self.e_cond)
        self.e_bo = QCheckBox("Accept offers")
        self.e_bo.toggled.connect(self._dirty)
        form.addRow("Best offer", self.e_bo)
        self.e_acc = PriceBox()
        self.e_acc.setRange(0, 100000)
        self.e_acc.setPrefix("$")
        self.e_acc.setSpecialValueText("Off")
        self.e_acc.setToolTip("Offers at or above this are accepted for you. Off: you decide each one")
        self.e_acc.valueChanged.connect(self._dirty)
        form.addRow("Auto-accept at", self.e_acc)
        self.e_dec = PriceBox()
        self.e_dec.setRange(0, 100000)
        self.e_dec.setPrefix("$")
        self.e_dec.setSpecialValueText("Off")
        self.e_dec.setToolTip("Offers below this are declined for you")
        self.e_dec.valueChanged.connect(self._dirty)
        form.addRow("Auto-decline below", self.e_dec)
        # shipping is a business policy you set up in Seller Hub: pick which one the listing uses, and see
        # what it offers (services, costs, local pickup) as eBay has it
        self.e_ship = QComboBox()
        self.e_ship.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.e_ship.setMinimumContentsLength(6)
        self.e_ship.setToolTip("Which of your shipping policies this listing uses. Policies, local pickup "
                               "included, are made and changed in Seller Hub > Business policies")
        self.e_ship.currentIndexChanged.connect(self._ship_picked)
        b_shipr = icon_button("reset", "Read your shipping policies from eBay again", 34)
        b_shipr.clicked.connect(lambda: self._load_policies(force=True))
        sr_ = QHBoxLayout()
        sr_.setSpacing(6)
        sr_.addWidget(self.e_ship, 1)
        sr_.addWidget(b_shipr)
        form.addRow("Shipping policy", sr_)
        self.e_pick = QLabel("", objectName="small")
        self.e_pick.setWordWrap(True)
        form.addRow("Local pickup", self.e_pick)
        self.e_cat = QComboBox()
        self.e_cat.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.e_cat.setMinimumContentsLength(6)
        self.e_cat.setToolTip("Which of your eBay Store categories this listing is in")
        self.e_cat.currentIndexChanged.connect(self._dirty)
        b_catr = icon_button("reset", "Read your store categories from eBay again", 34)
        b_catr.clicked.connect(lambda: self.m.refresh_store_cats(
            then=lambda: self._fill_cats(self.e_cat.currentData(), self.e_cat2.currentData())))
        cr = QHBoxLayout()
        cr.setSpacing(6)
        cr.addWidget(self.e_cat, 1)
        cr.addWidget(b_catr)
        form.addRow("Store category", cr)
        self.e_cat2 = QComboBox()
        self.e_cat2.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.e_cat2.setMinimumContentsLength(6)
        self.e_cat2.setToolTip("A second eBay Store category this listing also shows in")
        self.e_cat2.currentIndexChanged.connect(self._dirty)
        form.addRow("Second category", self.e_cat2)
        self._fill_cats("")
        ev.addLayout(form)
        sv = QHBoxLayout()
        self.e_revert = QPushButton("Revert")
        self.e_revert.clicked.connect(lambda: self.fill_editor(self.loaded))
        self.e_save = QPushButton("Save to eBay", objectName="primary")
        self.e_save.setMinimumHeight(40)
        self.e_save.clicked.connect(self.save)
        sv.addWidget(self.e_revert)
        sv.addWidget(self.e_save, 1)
        ev.addLayout(sv)
        self.e_note = QLabel("", objectName="small")
        self.e_note.setWordWrap(True)
        ev.addWidget(self.e_note)
        ev.addStretch(1)
        act = QHBoxLayout()
        act.setSpacing(6)
        self.e_vid = icon_button("film", "Render a 360° video from the listing's photos and attach it", 34, text="Video")
        self.e_vid.clicked.connect(lambda: self.add_video(self.cur))
        self.e_vup = icon_button("film", "Attach a video you already have: one rendered earlier for this card, "
                                 "or any MP4 or MOV", 34, text="File…")
        self.e_vup.clicked.connect(lambda: self.upload_video(self.cur))
        self.e_ctr = icon_button("report", "A centering report: measure this listing's photos in Reports, then "
                                 "Publish adds it to the listing", 34, text="Centering")
        self.e_ctr.clicked.connect(lambda: self.cur and self.m.open_centering(self.cur))
        self.e_open = QPushButton("eBay ↗")
        self.e_open.setToolTip("Open this listing on eBay")
        self.e_open.clicked.connect(lambda: self.cur and self.page._open(self.cur.get("url", "")))
        self.e_end = QPushButton("End")
        self.e_end.setToolTip("End this listing on eBay (you are asked first)")
        self.e_end.setStyleSheet("color:#E5484D;")
        self.e_end.clicked.connect(self.end)
        # one row; on a narrow window the row wraps instead of pushing the editor wider
        from ui_widgets import FlowLayout
        box = QWidget()
        g = FlowLayout(box, spacing=6)
        for b_ in (self.e_vid, self.e_vup, self.e_ctr, self.e_open, self.e_end):
            g.addWidget(b_)
        ev.addWidget(box)
        self._ed = ed
        return ed

    def _fields(self):
        return (self.e_title, self.e_price, self.e_qty, self.e_cond, self.e_bo, self.e_acc, self.e_dec,
                self.e_ship, self.e_cat, self.e_cat2, self.e_vup, self.e_save, self.e_revert, self.e_vid, self.e_ctr, self.e_open, self.e_end)

    def show_editor(self, item):
        on = item is not None
        for w in self._fields():
            w.setEnabled(on)
        if not on:
            self.e_head.setText("Pick a listing")
            self.e_stats.setText("Its title, price, quantity, condition and offers can all be changed here, "
                                 "and saved straight to the live listing.")
            self.e_photo.clear()
            self.e_note.setText("")

    def _fill_cats(self, select_id, select2=None):
        """The store category lists, with the listing's own selected (kept even when unknown here)."""
        was = getattr(self, "_filling", False)
        self._filling = True
        if select2 is None:
            select2 = self.e_cat2.currentData() if hasattr(self, "e_cat2") else ""
        for c, sel in ((self.e_cat, select_id), (getattr(self, "e_cat2", None), select2)):
            if c is None:
                continue
            c.blockSignals(True)
            c.clear()
            c.addItem("None", "")
            for cid, path in self.m.store_cats():
                c.addItem(path.strip("/").replace("/", " › "), cid)
            if sel and c.findData(sel) < 0:
                c.addItem(f"Category {sel} (read your categories to name it)", sel)
            c.setCurrentIndex(max(0, c.findData(sel or "")))
            c.blockSignals(False)
        self._filling = was

    # ---------- shipping policies
    def _load_policies(self, force=False):
        """Your shipping policies, read from eBay once (Refresh reads them again)."""
        if getattr(self, "_pol_loading", False) or (getattr(self, "_policies", None) is not None and not force):
            return
        c = self.m.ebay_client()
        if c is None or not c.signed_in():
            return
        self._pol_loading = True

        def done(pols, err):
            self._pol_loading = False
            if err:
                self.m.notice(f"Shipping policies could not be read: {err}", "warn")
                return
            self._policies = pols or []
            if self.loaded:
                self._fill_ship(self.loaded.get("ship_policy", ""), self.loaded.get("ship_policy_name", ""),
                                keep=True)
        t = CallTask(c.fulfillment_policies)
        t.then(done)
        self.pool.start(t)

    def _fill_ship(self, pid, name="", keep=False):
        was = getattr(self, "_filling", False)
        self._filling = True
        cur = self.e_ship.currentData() if keep else pid
        self.e_ship.blockSignals(True)
        self.e_ship.clear()
        pols = getattr(self, "_policies", None)
        if pols is None:
            self._load_policies()
            pols = []
        for p in pols:
            self.e_ship.addItem(p["name"] + ("  ·  local pickup" if p["pickup"] else ""), p["id"])
            self.e_ship.setItemData(self.e_ship.count() - 1, p["summary"], Qt.ToolTipRole)
        if pid and self.e_ship.findData(pid) < 0:
            self.e_ship.addItem(name or f"Policy {pid}", pid)
        if not pid:
            self.e_ship.insertItem(0, "No shipping policy (set in Seller Hub)", "")
        self.e_ship.setCurrentIndex(max(0, self.e_ship.findData(cur or "")))
        self.e_ship.blockSignals(False)
        self._filling = was

    def _show_pickup(self, pid, d=None):
        """What the chosen policy offers, local pickup first."""
        p = next((x for x in (getattr(self, "_policies", None) or []) if x["id"] == pid), None)
        if p is not None:
            pick, summary = p["pickup"], p["summary"]
        else:
            pick, summary = (d or {}).get("pickup"), (d or {}).get("ship_summary", "")
        head = ("Yes, buyers can pick it up" if pick else "No" if pick is not None else "Not known")
        self.e_pick.setText(head + (f"\n{summary}" if summary else ""))

    def _ship_picked(self, _i):
        self._show_pickup(self.e_ship.currentData() or "", self.loaded if self.e_ship.currentData() ==
                          (self.loaded or {}).get("ship_policy") else None)
        self._dirty()

    def _cat_path(self, cid):
        return next((p for i, p in self.m.store_cats() if i == cid), "")

    def fill_editor(self, d):
        if not d:
            return
        self._filling = True
        if not self.m.store_cats() and d.get("store_cat") is not None and not getattr(self, "_cats_asked", False):
            self._cats_asked = True             # first use: read them once, quietly
            self.m.refresh_store_cats(then=lambda: self._fill_cats(self.e_cat.currentData()))
        self._fill_cats(d.get("store_cat", ""), d.get("store_cat2", ""))
        self.e_title.setText(d["title"])
        self.e_price.setValue(d["price"])
        self.e_qty.setValue(d["available"])
        i = self.e_cond.findData(d["condition"])
        self.e_cond.setCurrentIndex(max(0, i))
        self.e_cond.setEnabled(not d["graded"])
        self.e_cond.setToolTip("A professionally graded card keeps its grade" if d["graded"] else "")
        self.e_bo.setChecked(d["best_offer"])
        self.e_acc.setValue(d["auto_accept"])
        self.e_dec.setValue(d["auto_decline"])
        self._fill_ship(d.get("ship_policy", ""), d.get("ship_policy_name", ""))
        self._show_pickup(d.get("ship_policy", ""), d)
        self.e_stats.setText(" · ".join(x for x in (
            f"{d['sold']} sold" if d["sold"] else "", f"{d['watchers']} watching" if d["watchers"] else "",
            f"{d['views']} views" if d.get("views") else "",
            "graded: " + d["condition_name"] if d["graded"] else "",
            f"item {d['id']}", f"SKU {d['sku']}" if d["sku"] else "listed outside CardCrop") if x))
        self._filling = False
        self._dirty()

    def changes(self):
        d = self.loaded
        if not d:
            return {}
        ch = {}
        if self.e_title.text().strip() != d["title"]:
            ch["title"] = self.e_title.text().strip()
        if abs(self.e_price.value() - d["price"]) >= 0.005:
            ch["price"] = round(self.e_price.value(), 2)
        if self.e_qty.value() != d["available"]:
            ch["available"] = self.e_qty.value()
        if not d["graded"] and self.e_cond.currentData() != d["condition"] and self.e_cond.currentData():
            ch["condition"] = self.e_cond.currentData()
        bo = (self.e_bo.isChecked(), round(self.e_acc.value(), 2), round(self.e_dec.value(), 2))
        if bo != (d["best_offer"], round(d["auto_accept"], 2), round(d["auto_decline"], 2)):
            ch.update(best_offer=bo[0], auto_accept=bo[1], auto_decline=bo[2])
        pid = self.e_ship.currentData() or ""
        if pid and pid != (d.get("ship_policy") or ""):
            ch["ship_policy_set"] = pid
        cid = self.e_cat.currentData() or ""
        cid2 = self.e_cat2.currentData() or ""
        if cid != (d.get("store_cat") or "") or cid2 != (d.get("store_cat2") or ""):
            # both go together: eBay sets a listing's store categories as a pair
            ch["store_cat"] = (cid, self._cat_path(cid))
            ch["store_cat2"] = (cid2, self._cat_path(cid2))
        return ch

    def _dirty(self, *_a):
        if getattr(self, "_filling", False):
            return
        self.e_tcount.setText(f"{len(self.e_title.text())}/80")
        self.e_acc.setEnabled(self.e_bo.isChecked() and self.loaded is not None)
        self.e_dec.setEnabled(self.e_bo.isChecked() and self.loaded is not None)
        ch = self.changes()
        self.e_save.setEnabled(bool(ch))
        self.e_revert.setEnabled(bool(ch))
        if ch.get("best_offer") and ch.get("auto_accept") and ch.get("auto_decline") \
                and ch["auto_decline"] >= ch["auto_accept"]:
            self.e_note.setText("Auto-decline has to be below auto-accept.")
            self.e_save.setEnabled(False)
        elif ch:
            self.e_note.setText("Unsaved: " + ", ".join({"title": "title", "price": "price", "available": "quantity",
                                                          "condition": "condition", "best_offer": "offers",
                                                          "ship_policy_set": "shipping policy",
                                                          "store_cat": "store categories"}.get(k, "")
                                                         for k in ch if k not in ("auto_accept", "auto_decline",
                                                                                  "ship_policy", "store_cat2")) + ".")
        else:
            self.e_note.setText("")

    # ------------------------------------------------------------ data
    def set_data(self, active):
        self.items = list(active or [])
        self.fill()

    def _head_sort(self, col):
        a, b = self.HEAD_SORTS[col]
        cur = self.sort.currentIndex()
        self.sort.setCurrentIndex(b if cur == a else a)

    def _head_marks(self):
        cur = self.sort.currentIndex()
        for col, b in getattr(self, "head_btns", {}).items():
            a, z = self.HEAD_SORTS[col]
            mark = " ↓" if cur == a else (" ↑" if cur == z and a != z else (" ↓" if cur == z else ""))
            b.setText(col + mark)

    PAGE = 50

    def filters(self) -> dict:
        return {"pmin": self.f_min.value(), "pmax": self.f_max.value(), "ends": self.f_ends.currentData(),
                "age": self.f_age.currentData(), "watch": self.f_watch.currentData()}

    def clear_filters(self):
        for w_ in (self.f_min, self.f_max, self.f_ends, self.f_age, self.f_watch):
            w_.blockSignals(True)
        self.f_min.setValue(0)
        self.f_max.setValue(0)
        for c_ in (self.f_ends, self.f_age, self.f_watch):
            c_.setCurrentIndex(0)
        for w_ in (self.f_min, self.f_max, self.f_ends, self.f_age, self.f_watch):
            w_.blockSignals(False)
        self.fill(page=0)

    def fill(self, page=None):
        self._head_marks()
        while self.lst.count() > 1:
            w = self.lst.takeAt(0).widget()
            if w:
                w.deleteLater()
        q = self.q.text().strip().lower()
        _n, key, rev = self.SORTS[self.sort.currentIndex()]
        self._fill_catf()
        want = self.catf.currentData()
        flt = self.filters()
        self.f_clear.setVisible(any(flt.values()))
        rows = [a for a in self.items if (not q or q in a.get("title", "").lower() or q in (a.get("sku") or "").lower())
                and self._in_cat(a, want) and listing_filter(a, flt)]
        rows.sort(key=key, reverse=rev)
        self._filtered = [a.get("id") for a in rows]
        pages = max(1, -(-len(rows) // self.PAGE))
        if page is not None:
            self.page_i = page
            self._sa.verticalScrollBar().setValue(0)
        self.page_i = max(0, min(pages - 1, self.page_i))
        first = self.page_i * self.PAGE
        shown_n = len(rows)
        rows = rows[first:first + self.PAGE]
        self.pager.setVisible(pages > 1)
        self.pg_prev.setEnabled(self.page_i > 0)
        self.pg_next.setEnabled(self.page_i < pages - 1)
        self.pg_lbl.setText(f"Page {self.page_i + 1} of {pages}  ·  {first + 1}–{first + len(rows)} of {shown_n}")
        self.rows = {}
        # the first screenful at once, the rest a batch at a time, so the list shows straight away
        # and scrolls while the others come in, each fading up as it arrives
        self._fill_gen = getattr(self, "_fill_gen", 0) + 1
        gen = self._fill_gen

        def add(start, n):
            if gen != self._fill_gen:
                return                              # a newer search or sort took over
            for i, a in enumerate(rows[start:start + n], start):
                r = ListingRow(self, a)
                self.rows[a.get("id")] = r
                self.lst.insertWidget(i, r)
                if start:
                    fade_in(r, 220)
                if self.cur and self.cur.get("id") == a.get("id"):
                    r.set_selected(True)
            if start + n < len(rows):
                QTimer.singleShot(0, lambda: add(start + n, 40))
        add(0, 24)
        total = sum(float(a.get("price") or 0) * max(1, int(a.get("qty") or 1)) for a in self.items)
        self.count.setText(f"{shown_n} of {len(self.items)} · ${total:,.2f} listed")
        if self.cur and self.cur.get("id") in self.rows:
            self.rows[self.cur["id"]].set_selected(True)
        self._sync_ticks()

    # ------------------------------------------------------------ store categories, together
    def _cat_paths(self):
        return {cid: path for cid, path in self.m.store_cats()}

    def cat_names(self, item):
        """The listing's store categories as you named them (the last part of each path)."""
        paths = self._cat_paths()
        out = []
        for k in ("store_cat", "store_cat2"):
            cid = item.get(k) or ""
            if cid:
                p = paths.get(cid, "")
                out.append(p.strip("/").replace("/", " › ") if p else f"category {cid}")
        return out

    def _fill_catf(self):
        cur = self.catf.currentData()
        self.catf.blockSignals(True)
        self.catf.clear()
        self.catf.addItem("All categories", None)
        self.catf.addItem(f"No store category  ({sum(1 for a in self.items if self._in_cat(a, ''))})", "")
        for cid, path in self.m.store_cats():
            n = sum(1 for a in self.items if self._in_cat(a, cid))
            self.catf.addItem("   " * (path.count("/") - 1) + path.rsplit("/", 1)[-1] + f"  ({n})", cid)
        i = self.catf.findData(cur) if cur is not None else 0
        self.catf.setCurrentIndex(max(0, i))
        self.catf.blockSignals(False)

    def _in_cat(self, a, want):
        if want is None:
            return True
        mine = [a.get("store_cat") or "", a.get("store_cat2") or ""]
        if want == "":
            return not any(mine)
        paths = self._cat_paths()
        root = paths.get(want, "")
        return any(c == want or (root and paths.get(c, "").startswith(root + "/")) for c in mine if c)

    def set_ticked(self, iid, on):
        (self.ticked.add if on else self.ticked.discard)(iid)
        self._sync_ticks()

    def tick_all(self, on):
        """Ticks every listing shown (after search and the category filter), or none."""
        if on:
            self.ticked |= set(self._filtered or self.rows)       # every page of what is shown, not just this one
        else:
            self.ticked.clear()
        for iid, r in self.rows.items():
            r.tick.blockSignals(True)
            r.tick.setChecked(iid in self.ticked)
            r.tick.blockSignals(False)
        self._sync_ticks()

    def _sync_ticks(self):
        live = {a.get("id") for a in self.items}
        self.ticked &= live
        n = len(self.ticked)
        self.tick_lbl.setText(f"{n} ticked" if n else "Tick listings to change them together")
        self.b_bcat.setEnabled(bool(n))
        if hasattr(self, "b_bprice"):
            self.b_bprice.setEnabled(bool(n))

    def _batch_cat_menu(self, menu):
        menu.clear()
        cats = self.m.store_cats()
        if not cats:
            menu.addAction("Read my store categories from eBay first",
                           lambda: self.m.refresh_store_cats(then=self.fill))
            return
        for slot, label in ((1, "First category"), (2, "Second category")):
            sub = menu.addMenu(label)
            sub.addAction("None", lambda s_=slot: self.batch_category(s_, ("", "")))
            sub.addSeparator()
            for cid, path in cats:
                sub.addAction("      " * (path.count("/") - 1) + path.rsplit("/", 1)[-1],
                              lambda s_=slot, c_=(cid, path): self.batch_category(s_, c_))
        menu.addSeparator()
        menu.addAction("Read my store categories from eBay again", lambda: self.m.refresh_store_cats(then=self.fill))

    def batch_category(self, slot, cat):
        """Every ticked listing into cat (first or second store category), keeping the other one."""
        c = self.client()
        items = [a for a in self.items if a.get("id") in self.ticked]
        if c is None or not items:
            return
        where = cat[1].strip("/").replace("/", " › ") if cat[1] else "no category"
        if QMessageBox.question(self, "Store categories", f"Put {len(items)} listing{'s' if len(items) != 1 else ''} "
                                f"in {where} as their {'first' if slot == 1 else 'second'} store category, live "
                                "on eBay?") != QMessageBox.Yes:
            return
        paths = self._cat_paths()
        self._batch_left = len(items)
        self._batch_err = []
        self.m.notice(f"Changing the store category of {len(items)} listings…", "info", secs=3)
        for a in items:
            keep = "store_cat2" if slot == 1 else "store_cat"
            kid = a.get(keep) or ""
            other = (kid, paths.get(kid, ""))
            ch = {"store_cat": cat if slot == 1 else other, "store_cat2": other if slot == 1 else cat}
            t = CallTask(c.revise_listing, a.get("id", ""), a.get("sku", ""), ch)

            def done(_r, err, iid=a.get("id"), ch=ch, title=a.get("title", "")):
                self._batch_left -= 1
                if err:
                    self._batch_err.append(f"{title[:30]}: {err}")
                else:
                    self._apply_local(iid, ch)
                if self._batch_left <= 0:
                    bad = self._batch_err
                    self.m.notice(f"{len(items) - len(bad)} listings moved to {where}" +
                                  (f"; {len(bad)} did not: {bad[0]}" if bad else ""), "warn" if bad else "ok", secs=6)
                    self.fill()
            t.then(done)
            self.pool.start(t)

    @staticmethod
    def parse_change(text):
        """'-10%' -> ('pct', -10), '+1.50' or '1.5' -> ('amt', 1.5); None when it is not a change."""
        t = text.strip().replace("$", "").replace(" ", "")
        try:
            if t.endswith("%"):
                return "pct", float(t[:-1])
            return "amt", float(t)
        except ValueError:
            return None

    def batch_price(self):
        from PySide6.QtWidgets import QInputDialog
        c = self.client()
        items = [a for a in self.items if a.get("id") in self.ticked]
        if c is None or not items:
            return
        text, ok = QInputDialog.getText(self, "Change prices", f"Change the price of {len(items)} ticked listing"
                                        f"{'s' if len(items) != 1 else ''} by, for example, -10% or +1.50:")
        ch = self.parse_change(text) if ok else None
        if not ch or not ch[1]:
            return
        mode, v = ch
        plan = [(a, max(0.99, round(float(a.get("price") or 0) * (1 + v / 100) if mode == "pct"
                                     else float(a.get("price") or 0) + v, 2))) for a in items]
        ex = plan[0]
        if QMessageBox.question(self, "Change prices", f"Change {len(plan)} prices live on eBay? For example "
                                f"“{ex[0].get('title', '')[:40]}” goes from ${float(ex[0].get('price') or 0):,.2f} "
                                f"to ${ex[1]:,.2f}.") != QMessageBox.Yes:
            return
        self._bp_left, self._bp_bad = len(plan), []
        self.m.notice(f"Changing {len(plan)} prices on eBay…", "info", secs=3)
        for a, p in plan:
            t = CallTask(c.revise_listing, a.get("id", ""), a.get("sku", ""), {"price": p})

            def done(_r, err, iid=a.get("id"), p=p, title=a.get("title", "")):
                self._bp_left -= 1
                if err:
                    self._bp_bad.append(f"{title[:30]}: {err}")
                else:
                    self._apply_local(iid, {"price": p})
                if self._bp_left <= 0:
                    bad = self._bp_bad
                    self.m.notice(f"{len(plan) - len(bad)} prices changed" + (f"; {len(bad)} did not: {bad[0]}" if bad else ""),
                                  "warn" if bad else "ok", secs=6)
                    self.fill()
            t.then(done)
            self.pool.start(t)

    def client(self):
        c = self.m.ebay_client()
        if c is None or not c.signed_in():
            self.m.notice("Connect eBay in Settings > eBay to edit your listings.", "warn")
            return None
        return c

    def select(self, iid):
        if self.loaded and self.changes() and (self.cur or {}).get("id") != iid:
            if QMessageBox.question(self, "Unsaved changes", "Leave this listing without saving your changes?") \
                    != QMessageBox.Yes:
                return
        item = next((a for a in self.items if a.get("id") == iid), None)
        for k, r in self.rows.items():
            r.set_selected(k == iid)
        self.cur, self.loaded = item, None
        self.show_editor(item)
        if item is None:
            return
        self.e_head.setText(item.get("title", ""))
        self.e_stats.setText("Reading the listing from eBay…")
        for w in self._fields():
            w.setEnabled(False)
        pm = self.page._pix.get(next((k for k in self.page._pix if k.endswith(iid)), ""), None) \
            or (self.rows[iid].th.pixmap() if iid in self.rows else None)
        if pm is not None and not pm.isNull():
            self.e_photo.setPixmap(rounded_pixmap(pm, 120, 166, 10))
        c = self.client()
        if c is None:
            return
        t = CallTask(c.listing_details, iid)
        t.then(lambda d, err, i=iid: self._details(i, d, err))
        self.pool.start(t)

    def _details(self, iid, d, err):
        if (self.cur or {}).get("id") != iid:
            return
        if err:
            self.e_stats.setText(f"Could not read this listing: {err}")
            return
        self.loaded = d
        for w in self._fields():
            w.setEnabled(True)
        self.fill_editor(d)

    def _apply_local(self, iid, ch):
        for a in self.items:
            if a.get("id") == iid:
                if "price" in ch:
                    a["price"] = ch["price"]
                if "available" in ch:
                    a["qty"] = ch["available"]
                if "title" in ch:
                    a["title"] = ch["title"]
                for k in ("store_cat", "store_cat2"):
                    if k in ch:
                        a[k] = (ch[k] or ("", ""))[0]

    def quick(self, item, ch):
        c = self.client()
        if c is None:
            return
        label = item.get("title", "")[:40]
        self.m.notice(f"Updating {label} on eBay…", "info", secs=2)
        t = CallTask(c.revise_listing, item.get("id", ""), item.get("sku", ""), ch)

        def done(_r, err, iid=item.get("id"), ch=ch):
            if err:
                self.m.notice(f"{label}: {err}", "error")
                return
            self._apply_local(iid, ch)
            what = f"${ch['price']:,.2f}" if "price" in ch else f"{ch['available']} available"
            self.m.notice(f"{label} is now {what} on eBay", "ok", secs=3)
            if (self.cur or {}).get("id") == iid and self.loaded:
                self.loaded.update({k: v for k, v in ch.items() if k in ("price", "available")})
                self.fill_editor(self.loaded)
        t.then(done)
        self.pool.start(t)

    def save(self):
        ch = self.changes()
        c = self.client()
        if not ch or c is None or not self.cur:
            return
        self.e_save.setEnabled(False)
        self.e_save.setText("Saving…")
        iid = self.cur["id"]
        t = CallTask(c.revise_listing, iid, self.loaded.get("sku") or self.cur.get("sku", ""), ch)

        def done(_r, err):
            self.e_save.setText("Save to eBay")
            if err:
                self.e_note.setText(f"eBay did not take it: {err}")
                self.e_save.setEnabled(True)
                return
            self._apply_local(iid, ch)
            self.m.notice("Saved to eBay", "ok", secs=3)
            self.fill()
            if (self.cur or {}).get("id") == iid:
                self.loaded = None
                self.select(iid)                   # read back what eBay now shows
        t.then(done)
        self.pool.start(t)

    def add_video(self, item):
        if item and item.get("id"):
            self.m.reports_page.add_videos([{"key": f"live:{item['id']}", "live": dict(item)}], ask=True)

    def _known_videos(self, item):
        """Videos already made for this listing's card: in its export folder, or in Videos, newest first."""
        out_dir = self.m.out_dir
        sku = item.get("sku") or ""
        dirs = [item.get("folder") or "", os.path.join(out_dir, sku) if sku else "", os.path.join(out_dir, "Videos")]
        stem = engine.safe_name(sku or item.get("title", ""))[:60]
        seen, found = set(), []
        saved = getattr(self.m.reports_page, "_vpaths", {}).get(item.get("id"), "")
        for p in [saved] + [os.path.join(d, f) for d in dirs if d and os.path.isdir(d) for f in os.listdir(d)]:
            if not p or p in seen or not os.path.isfile(p) or not p.lower().endswith((".mp4", ".mov")):
                continue
            seen.add(p)
            in_videos = os.path.basename(os.path.dirname(p)) == "Videos"
            if in_videos and stem and not os.path.basename(p).startswith(stem):
                continue                                # another card's video
            found.append(p)
        return sorted(found, key=lambda p: -os.path.getmtime(p))

    def upload_video(self, item):
        if not item or not item.get("id") or self.client() is None:
            return
        known = self._known_videos(item)
        start = os.path.dirname(known[0]) if known else (item.get("folder") or self.m.out_dir)
        path, _ = QFileDialog.getOpenFileName(self, "Video to attach to the listing",
                                              known[0] if known else start, "Videos (*.mp4 *.mov)")
        if path:
            self.m.reports_page.upload_existing_video(dict(item), path)

    def add_report(self):
        it = self.cur
        c = self.client()
        if not it or c is None or not self.m.calibrated_or_ask():
            return
        if QMessageBox.question(self, "Add condition report", "Make a condition report from this listing's photos "
                                "and add it as its last photo, live?") != QMessageBox.Yes:
            return
        rp = self.m.reports_page
        d = {"key": f"live:{it['id']}", "live": dict(it)}
        t = LiveReportTask(c, self.m.db, self.m.prepare_live(it), add=True,
                           out_path=rp._live_path(d))
        r = _Relay(lambda iid, im, path, err: self.m.notice(
            f"Report not added: {err}" if err else "Condition report added as the listing's last photo",
            "error" if err else "ok"))
        r._sig = t.sig
        t.sig.done.connect(r.fire)
        self.pool.start(t)
        self.m.notice("Making the condition report…", "info", secs=3)

    def end(self):
        it = self.cur
        c = self.client()
        if not it or c is None:
            return
        if QMessageBox.question(self, "End listing", f"End “{it.get('title', '')[:70]}” on eBay now? It comes off "
                                "sale straight away.") != QMessageBox.Yes:
            return
        t = CallTask(c.end_listing, it["id"], it.get("sku", ""))

        def done(_r, err, iid=it["id"]):
            if err:
                self.m.notice(f"Not ended: {err}", "error")
                return
            self.items = [a for a in self.items if a.get("id") != iid]
            if self.page.data:
                self.page.data["active"] = [a for a in self.page.data.get("active", []) if a.get("id") != iid]
            self.cur, self.loaded = None, None
            self.show_editor(None)
            self.fill()
            self.m.notice("Listing ended", "ok")
        t.then(done)
        self.pool.start(t)


class StoreRow(QFrame):
    def __init__(self, page, item, sub, chip="", chip_color=""):
        super().__init__()
        self.setObjectName("row")
        self.setCursor(Qt.PointingHandCursor)
        self.url = item.get("url", "")
        self.setFixedHeight(58)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 10, 4)
        h.setSpacing(12)
        self.th = QLabel()
        self.th.setFixedSize(40, 48)
        self.th.setStyleSheet(f"background:{TH.T['pill']}; border-radius:6px;")
        h.addWidget(self.th)
        page.thumb_for(self, item)
        v = QVBoxLayout()
        v.setSpacing(2)
        t = QLabel()
        t.setTextFormat(Qt.PlainText)
        t.setText(item.get("title", ""))
        t.setMinimumWidth(10)
        t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        t.setToolTip(item.get("title", ""))
        v.addWidget(t)
        sl = QLabel(sub + (f" · {chip}" if chip else ""), objectName="mono")
        sl.setMinimumWidth(10)
        sl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(sl)
        h.addLayout(v, 1)
        if item.get("id"):                     # a live listing: price and video right here
            m = page.m
            h.addWidget(price_field(item.get("price") or 0, 84,
                                    lambda pr, it=item: m.push_price(it.get("title", "")[:40], it["id"],
                                                                     it.get("sku", ""), pr),
                                    "This listing's price on eBay. Type any amount and press Return"))
            b = icon_button("film", "Add a 360° video to this listing: rendered from its photos with your "
                                    "video settings (Settings, Videos), uploaded and attached", 30)
            b.clicked.connect(lambda _=False, it=item: m.reports_page.add_videos(
                [{"key": f"live:{it['id']}", "live": dict(it)}], ask=True))
            mark_video(b, m, item.get("id"))
            h.addWidget(b)

    def set_pixmap(self, pm):
        self.th.setStyleSheet("")
        self.th.setPixmap(rounded_pixmap(pm, 40, 48, 6))

    def mouseDoubleClickEvent(self, e):
        if self.url:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(self.url))


class MiniBars(QWidget):
    """A tiny bar strip for a KPI tile: the last few days, today brightest."""

    def __init__(self):
        super().__init__()
        self.vals = []
        self.setFixedSize(64, 34)

    def set_vals(self, vals):
        self.vals = list(vals)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.vals)
        if not n:
            return
        top = max(self.vals) if max(self.vals) > 0 else 1
        bw = 2.0
        gap = min(4.0, (self.width() - bw * n) / max(1, n - 1))     # short histories sit at the right
        x0 = self.width() - (bw * n + gap * (n - 1))
        p.setPen(Qt.NoPen)
        for i, v in enumerate(self.vals):
            h = max(3, (self.height() - 1) * v / top)
            p.setBrush(QColor(TH.T["text"] if i == n - 1 else TH.T["faint"]))
            p.drawRoundedRect(QRectF(x0 + i * (bw + gap), self.height() - h, bw, h), 1, 1)
        p.end()


class SquareColumns(QWidget):
    """Sales as columns of small squares, one column per day or week; a filled square
    is a step of dollars, so the height reads at a glance and the grid stays calm."""

    def __init__(self):
        super().__init__()
        self.labels, self.vals, self.marks = [], [], []
        self.setMinimumHeight(170)
        self.setMouseTracking(True)

    def set_data(self, labels, vals, marks=None):
        self.labels, self.vals = labels, vals
        self.marks = marks or [""] * len(vals)
        self.update()

    def _geom(self):
        n = max(1, len(self.vals))
        axis = 20
        gap = 3
        cell = max(4, min(16, (self.width() - gap * (n - 1)) / n))
        rows = max(4, int((self.height() - axis + gap) // (cell + gap)))
        return n, cell, gap, rows, axis

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n, cell, gap, rows, axis = self._geom()
        top = max(self.vals + [1])
        step = top / rows
        fill = QColor(TH.T["text"]) if TH.THEME == "light" else QColor(LIME)
        p.setPen(Qt.NoPen)
        x0 = (self.width() - (n * cell + (n - 1) * gap)) / 2
        for i, v in enumerate(self.vals):
            k = int(round(v / step)) if v else 0
            if v and k == 0:
                k = 1
            for r in range(rows):
                y = self.height() - axis - (r + 1) * (cell + gap) + gap
                p.setBrush(fill if r < k else QColor(TH.T["pill"]))
                p.drawRoundedRect(QRectF(x0 + i * (cell + gap), y, cell, cell), cell * .22, cell * .22)
        p.setPen(QColor(TH.T["muted"]))
        p.setFont(QFont(MONO, TH.BASE_PT - 3))
        for i, m in enumerate(self.marks):
            if m:
                p.drawText(QRectF(x0 + i * (cell + gap) - 20, self.height() - axis + 4, cell + 40, axis - 4),
                           Qt.AlignHCenter | Qt.AlignTop, m)
        p.end()

    def mouseMoveEvent(self, e):
        n, cell, gap, rows, axis = self._geom()
        x0 = (self.width() - (n * cell + (n - 1) * gap)) / 2
        i = int((e.position().x() - x0) // (cell + gap))
        if 0 <= i < len(self.vals):
            self.setToolTip(f"{self.labels[i]}: ${self.vals[i]:,.2f}")


TX_COLS = (40, 0, 84, 84, 56, 70)        # photo, item, buyer, status, when, price


class TxRow(QFrame):
    def __init__(self, page, item):
        super().__init__()
        self.setObjectName("row")
        self.setCursor(Qt.PointingHandCursor)
        self.url = item.get("url", "")
        self.setFixedHeight(52)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 12, 4)
        h.setSpacing(12)
        self.th = QLabel()
        self.th.setFixedSize(32, 42)
        self.th.setStyleSheet(f"background:{TH.T['pill']}; border-radius:5px;")
        h.addWidget(self.th)
        page.thumb_for(self, item)
        t = QLabel()
        t.setTextFormat(Qt.PlainText)
        t.setText(item.get("title", ""))
        t.setToolTip(item.get("title", ""))
        t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # the buyer under the title, so the table fits a laptop window
        tv = QVBoxLayout()
        tv.setSpacing(0)
        tv.addWidget(t)
        if item.get("buyer"):
            b_ = QLabel(item.get("buyer", ""), objectName="mono")
            b_.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            tv.addWidget(b_)
        h.addLayout(tv, 1)
        paid, shipped = item.get("paid"), item.get("shipped")
        label, col = (("Shipped", STATUS["ready"]) if shipped else ("To ship", STATUS["need"]) if paid
                      else ("Unpaid", STATUS["idle"]))
        st = QHBoxLayout()
        st.setSpacing(6)
        st.addWidget(dot_label(col))
        st.addWidget(QLabel(label))
        st.addStretch(1)
        sw = QWidget()
        sw.setFixedWidth(TX_COLS[3])
        sw.setLayout(st)
        st.setContentsMargins(0, 0, 0, 0)
        h.addWidget(sw)
        when = QLabel(_ago(item.get("date", "")), objectName="mono")
        when.setFixedWidth(TX_COLS[4])
        h.addWidget(when)
        pr = QLabel(f"${item.get('price', 0):,.2f}", objectName="monotext")
        pr.setFixedWidth(TX_COLS[5])
        pr.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(pr)

    def set_pixmap(self, pm):
        self.th.setStyleSheet("")
        self.th.setPixmap(rounded_pixmap(pm, 32, 42, 5))

    def mouseDoubleClickEvent(self, e):
        if self.url:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(self.url))


class CurrentStack(QStackedWidget):
    """A stack sized by the page on show, not by the widest page, so a narrow window never cuts one off."""

    def __init__(self, *a):
        super().__init__(*a)
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()


class StorePage(QWidget):
    """Your eBay store at a glance: sales, what to ship, what just went up, what people watch."""

    def __init__(self, main):
        super().__init__()
        self.m = main
        self.data = None
        self.after_fetch = []                 # run once after the next refresh, success or not
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self._pix = {}
        self._waiting = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        head = QHBoxLayout()
        head.setContentsMargins(8, 4, 4, 0)
        head.addWidget(QLabel("Store", objectName="title2"))
        head.addSpacing(16)
        vseg = QFrame(objectName="segbox")
        vsl = QHBoxLayout(vseg)
        vsl.setContentsMargins(4, 4, 4, 4)
        vsl.setSpacing(4)
        self.view_btns = {}
        for k, label in (("overview", "Overview"), ("listings", "Listings")):
            b = QPushButton(label, objectName="seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k_=k: self.set_view(k_))
            vsl.addWidget(b)
            self.view_btns[k] = b
        head.addWidget(vseg)
        head.addSpacing(12)
        self.upd = QLabel("", objectName="small")
        head.addWidget(self.upd)
        head.addStretch(1)
        self.b_ref = QPushButton("Refresh")
        self.b_ref.clicked.connect(self.refresh)
        head.addWidget(self.b_ref)
        b_sh = QPushButton("Seller Hub")
        b_sh.clicked.connect(lambda: self._open("https://www.ebay.com/sh/ovw"))
        head.addWidget(b_sh)
        b_ord = QPushButton("Orders to ship")
        b_ord.clicked.connect(lambda: self._open("https://www.ebay.com/sh/ord/?filter=status:AWAITING_SHIPMENT"))
        head.addWidget(b_ord)
        v.addLayout(head)

        from PySide6.QtWidgets import QScrollArea as _SA
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.nums = {}

        def tile(key, cap, need=False):
            f = Island()
            fv = QVBoxLayout(f)
            fv.setContentsMargins(20, 14, 16, 12)
            fv.setSpacing(2)
            top = QHBoxLayout()
            capl = QLabel(cap.upper(), objectName="mono")
            top.addWidget(capl)
            top.addStretch(1)
            fv.addLayout(top)
            mid = QHBoxLayout()
            n = QLabel("–", objectName="dotneed" if need else "dot")
            mid.addWidget(n)
            mid.addStretch(1)
            mb = MiniBars()
            mid.addWidget(mb, 0, Qt.AlignBottom)
            fv.addLayout(mid)
            sub = QLabel("", objectName="small")
            sub.setTextFormat(Qt.RichText)
            fv.addWidget(sub)
            tiles.addWidget(f, 1)
            self.nums[key] = (n, sub, mb)

        tile("sold", "Sales, 60 days")
        tile("week", "Last 7 days")
        tile("ship", "To ship", need=True)
        tile("active", "Active listings")
        tile("watch", "Watchers")
        outer_v = v
        self.views = CurrentStack()
        ov = QWidget()
        v = QVBoxLayout(ov)                    # the overview is built into its own page
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        v.addLayout(tiles)

        sp = Island()
        spv = QVBoxLayout(sp)
        spv.setContentsMargins(20, 14, 20, 14)
        spv.setSpacing(10)
        sh = QHBoxLayout()
        sh.addWidget(QLabel("SALES TREND", objectName="mono"))
        sh.addSpacing(12)
        self.trend_total = QLabel("", objectName="dot")
        self.trend_total.setStyleSheet(f"font-size:{TH.BASE_PT + 8}pt;")
        sh.addWidget(self.trend_total)
        sh.addStretch(1)
        seg = QFrame(objectName="segbox")
        sg = QHBoxLayout(seg)
        sg.setContentsMargins(4, 4, 4, 4)
        sg.setSpacing(4)
        self.trend_btns = {}
        for key, label in (("daily", "Daily"), ("weekly", "Weekly")):
            b = QPushButton(label, objectName="seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_trend(k))
            sg.addWidget(b)
            self.trend_btns[key] = b
        sh.addWidget(seg)
        spv.addLayout(sh)
        self.trend = SquareColumns()
        self.trend.setMinimumHeight(96)
        spv.addWidget(self.trend, 1)
        sp.setMaximumHeight(236)              # a glance, so the lists below get the room
        self.trend_mode = str(self.m.cfg.value("store_trend", "daily"))
        traffic = self._traffic_island()

        def side_list(key, title):
            f = Island()
            fv = QVBoxLayout(f)
            fv.setContentsMargins(14, 14, 14, 10)
            fv.setSpacing(6)
            lab = QLabel(title.upper(), objectName="mono")
            lab.setContentsMargins(6, 0, 0, 0)
            fv.addWidget(lab)
            sa = _SA()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            body = QWidget()
            bl = QVBoxLayout(body)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(2)
            bl.addStretch(1)
            sa.setWidget(body)
            fv.addWidget(sa, 1)
            self.lists[key] = bl
            return f

        self.lists = {}
        tx = Island()
        txv = QVBoxLayout(tx)
        txv.setContentsMargins(14, 14, 14, 10)
        txv.setSpacing(6)
        th_ = QHBoxLayout()
        lab = QLabel("RECENTLY SOLD", objectName="mono")
        lab.setContentsMargins(6, 0, 0, 0)
        th_.addWidget(lab)
        th_.addStretch(1)
        self.tx_q = QLineEdit()
        self.tx_q.setPlaceholderText("Search sales")
        self.tx_q.setMinimumWidth(90)
        self.tx_q.setMaximumWidth(200)
        self.tx_q.textChanged.connect(lambda _t: self._fill_tx())
        th_.addWidget(self.tx_q)
        b_csv = QPushButton("Export CSV")
        b_csv.clicked.connect(self.export_csv)
        th_.addWidget(b_csv)
        txv.addLayout(th_)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 0, 12, 0)
        hdr.setSpacing(12)
        for w_, text in zip(TX_COLS, ("", "Item · buyer", None, "Status", "Sold", "Price")):
            if text is None:
                continue
            l = QLabel(text, objectName="small")
            if text == "Price":
                l.setAlignment(Qt.AlignRight)
            if w_:
                l.setFixedWidth(w_)
                hdr.addWidget(l)
            else:
                hdr.addWidget(l, 1)
        txv.addLayout(hdr)
        sa = _SA()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.tx_list = QVBoxLayout(body)
        self.tx_list.setContentsMargins(0, 0, 0, 0)
        self.tx_list.setSpacing(2)
        self.tx_list.addStretch(1)
        sa.setWidget(body)
        txv.addWidget(sa, 1)
        # three columns: sales (trend over recent sales), traffic, and the two listing lists
        cols = QHBoxLayout()
        cols.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(sp, 0)
        left.addWidget(tx, 1)
        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(side_list("watched", "Most watched"), 1)
        right.addWidget(side_list("new", "Just listed"), 1)
        cols.addLayout(left, 6)
        cols.addWidget(soft_scroll(traffic), 3)
        cols.addLayout(right, 4)
        v.addLayout(cols, 1)
        self.views.addWidget(ov)
        self.listings = ListingsView(self)
        self.views.addWidget(self.listings)
        v = outer_v
        v.addWidget(self.views, 1)
        self.err = QLabel("", objectName="small")
        self.err.setWordWrap(True)
        self.err.hide()
        v.addWidget(self.err)
        self.set_view(str(self.m.cfg.value("store_view", "overview")))
        self._load_cache()

    def _traffic_island(self):
        """Seller Hub's Traffic card: impressions, click-through, page views, conversion,
        each with its change on the 30 days before and a bar per day."""
        f = Island()
        fv = QVBoxLayout(f)
        fv.setContentsMargins(20, 14, 20, 12)
        fv.setSpacing(4)
        th = QHBoxLayout()
        th.addWidget(QLabel("TRAFFIC, 30 DAYS", objectName="mono"))
        th.addStretch(1)
        b = icon_button("next", "Traffic in Seller Hub", 26)
        b.clicked.connect(lambda: self._open("https://www.ebay.com/sh/performance/traffic"))
        th.addWidget(b)
        fv.addLayout(th)
        self.traf = {}
        for i, (key, cap, tip) in enumerate((
                ("impr", "Listing impressions", "How often your listings were shown, anywhere on eBay"),
                ("ctr", "Click-through rate", "Clicks from search results ÷ times shown in search results"),
                ("views", "Listing page views", "Visits to your listing pages, from any source"),
                ("conv", "Sales conversion rate", "Items sold ÷ listing page views"))):
            if i:
                line = QFrame(objectName="hline")
                line.setFixedHeight(1)
                fv.addStretch(1)
                fv.addWidget(line)
                fv.addStretch(1)
            capl = QLabel(cap, objectName="small")
            capl.setToolTip(tip)
            fv.addWidget(capl)
            r = QHBoxLayout()
            n = QLabel("–")
            n.setStyleSheet(f"font-size:{TH.BASE_PT + 10}pt; font-weight:500;")
            # one fixed width for every figure, so the four bar strips start at the same x
            # and each day sits in the same column all the way down
            f_ = QFont(n.font())
            f_.setPointSize(TH.BASE_PT + 10)
            f_.setWeight(QFont.Medium)
            from PySide6.QtGui import QFontMetrics
            n.setFixedWidth(QFontMetrics(f_).horizontalAdvance("8,888,888") + 6)
            r.addWidget(n, 0, Qt.AlignBottom)
            r.addSpacing(8)
            mb = MiniBars()
            r.addWidget(mb, 0, Qt.AlignBottom)
            r.addStretch(1)
            dl = QLabel("", objectName="mono")
            dl.setTextFormat(Qt.RichText)
            r.addWidget(dl, 0, Qt.AlignBottom)
            fv.addLayout(r)
            self.traf[key] = (n, dl, mb)
        line = QFrame(objectName="hline")
        line.setFixedHeight(1)
        fv.addStretch(1)
        fv.addWidget(line)
        fv.addStretch(1)
        src_cap = QLabel("Where views came from", objectName="small")
        src_cap.setToolTip("Listing page views by source. eBay's traffic report does not split out "
                           "Promoted Listings; those views are counted inside the eBay sources.")
        fv.addWidget(src_cap)
        self.src_bar = SegBar(10)
        fv.addWidget(self.src_bar)
        self.src_rows = {}
        for key in ("On eBay", "External"):
            r = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(f"background:{CHART['Search'] if key == 'On eBay' else CHART['External']};"
                              "border-radius:4px;")
            r.addWidget(dot)
            lab = QLabel(key)
            r.addWidget(lab)
            r.addStretch(1)
            val = QLabel("–", objectName="mono")
            val.setTextFormat(Qt.RichText)
            r.addWidget(val)
            fv.addLayout(r)
            self.src_rows[key] = val
        fv.addStretch(1)
        self.traf_note = QLabel("", objectName="small")
        self.traf_note.setWordWrap(True)
        fv.addWidget(self.traf_note)
        self.traf_btn = QPushButton("Reconnect eBay")
        self.traf_btn.setToolTip("Traffic needs one more read-only permission; sign in to eBay again once")
        self.traf_btn.clicked.connect(lambda: self.m.ebay_account())
        self.traf_btn.hide()
        fv.addWidget(self.traf_btn, 0, Qt.AlignLeft)
        return f

    def show_traffic(self):
        import datetime as dt
        d = self.data or {}
        tr, terr = d.get("traffic"), d.get("traffic_err")
        self.traf_btn.setVisible(terr == "reconnect")
        if not tr:
            for n, dl, mb in self.traf.values():
                n.setText("–")
                dl.setText("")
                mb.set_vals([])
            self.src_bar.set_items([])
            for v_ in self.src_rows.values():
                v_.setText("–")
            self.traf_note.setText(
                "Traffic needs one more read-only eBay permission. Reconnect once and it fills in."
                if terr == "reconnect" else (f"Traffic could not be read: {terr}" if terr else ""))
            return
        days, split = tr.get("days", []), tr.get("split", "")
        cur = [v for k, v in days if k > split]
        prev = [v for k, v in days if k <= split]

        def tot(rows, key, alt=None):
            if alt and rows and not any(key in r for r in rows):
                key = alt
            return sum(r.get(key, 0.0) for r in rows)

        def figures(rows):
            impr = tot(rows, "TOTAL_IMPRESSION_TOTAL", "LISTING_IMPRESSION_TOTAL")
            srp_i, srp_v = tot(rows, "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE"), tot(
                rows, "LISTING_VIEWS_SOURCE_SEARCH_RESULTS_PAGE")
            views, tx = tot(rows, "LISTING_VIEWS_TOTAL"), tot(rows, "TRANSACTION")
            return {"impr": impr, "ctr": (srp_v / srp_i * 100) if srp_i else 0.0, "views": views,
                    "conv": (tx / views * 100) if views else 0.0}

        a, b = figures(cur), figures(prev) if prev else None
        up, down = "#2BB673", "#E5484D"

        def change(key):
            if b is None:
                return ""
            if key in ("ctr", "conv"):
                dd = a[key] - b[key]
                txt = f"{dd:+.1f} pts"
            else:
                if not b[key]:
                    return "" if not a[key] else f"<span style='color:{up}'>new</span>"
                dd = (a[key] - b[key]) / b[key] * 100
                txt = f"{dd:+.1f}%"
            if abs(dd) < 0.05:
                return txt.replace("+", "").replace("-", "")
            arrow = "▲" if dd > 0 else "▼"
            return f"<span style='color:{up if dd > 0 else down}'>{arrow} {txt.lstrip('+-')}</span>"

        def series(key):
            out = []
            for r in cur[-14:]:
                if key == "impr":
                    out.append(r.get("TOTAL_IMPRESSION_TOTAL", r.get("LISTING_IMPRESSION_TOTAL", 0.0)))
                elif key == "views":
                    out.append(r.get("LISTING_VIEWS_TOTAL", 0.0))
                elif key == "ctr":
                    i_ = r.get("LISTING_IMPRESSION_SEARCH_RESULTS_PAGE", 0.0)
                    out.append(r.get("LISTING_VIEWS_SOURCE_SEARCH_RESULTS_PAGE", 0.0) / i_ if i_ else 0.0)
                else:
                    v_ = r.get("LISTING_VIEWS_TOTAL", 0.0)
                    out.append(r.get("TRANSACTION", 0.0) / v_ if v_ else 0.0)
            return out

        # where the page views came from
        parts = (("Search", "LISTING_VIEWS_SOURCE_SEARCH_RESULTS_PAGE"), ("Other eBay", "LISTING_VIEWS_SOURCE_OTHER_EBAY"),
                 ("Store", "LISTING_VIEWS_SOURCE_STORE"), ("Direct", "LISTING_VIEWS_SOURCE_DIRECT"),
                 ("External", "LISTING_VIEWS_SOURCE_OFF_EBAY"))
        have = any("LISTING_VIEWS_SOURCE_OFF_EBAY" in r for r in cur)
        if have:
            now = {k: tot(cur, m) for k, m in parts}
            before = {k: tot(prev, m) for k, m in parts} if prev else None
            self.src_bar.set_items(list(now.items()))
            views_all = sum(now.values()) or 1
            groups = {"On eBay": [k for k, _ in parts if k != "External"], "External": ["External"]}
            for g, keys in groups.items():
                v_now = sum(now[k] for k in keys)
                txt = f"{v_now:,.0f}  ·  {v_now / views_all * 100:.0f}%"
                if before is not None:
                    v_b = sum(before[k] for k in keys)
                    if v_b:
                        dd = (v_now - v_b) / v_b * 100
                        col = up if dd >= 0 else down
                        txt += f"  <span style='color:{col}'>{'▲' if dd > 0 else '▼' if dd < 0 else ''}" \
                               f"{abs(dd):.1f}%</span>"
                self.src_rows[g].setText(txt)
            tip = "On eBay: " + ", ".join(f"{k} {now[k]:,.0f}" for k, _ in parts if k != "External")
            self.src_bar.setToolTip(tip)
            self.src_rows["On eBay"].setToolTip(tip)
        else:
            self.src_bar.set_items([])
            for v_ in self.src_rows.values():
                v_.setText("–")
        for key, (n, dl, mb) in self.traf.items():
            v = a[key]
            n.setText(f"{v:.1f}%" if key in ("ctr", "conv") else f"{v:,.0f}")
            dl.setText(change(key))
            mb.set_vals(series(key))
        try:
            s0 = dt.date.fromisoformat(split) + dt.timedelta(days=1)
            e0 = dt.date.fromisoformat(tr.get("end", ""))
            span = f"{s0.strftime('%b %d')} to {e0.strftime('%b %d')}"
        except ValueError:
            span = "the last 30 days"
        self.traf_note.setText(f"{span}, Pacific time; changes against the 30 days before."
                               + ("" if b is not None else " No earlier period to compare."))

    # ---------- data
    def _cache_path(self):
        return os.path.join(identify._cache_dir(), "store.json")

    def _load_cache(self):
        try:
            with open(self._cache_path(), encoding="utf-8") as f:
                self.data = json.load(f)
            self.show_data()
        except (OSError, ValueError):
            self.data = None

    def stale(self):
        return not self.data or time.time() - float(self.data.get("fetched", 0)) > 600

    def refresh(self):
        c = self.m.ebay_client()
        if not c or not c.signed_in():
            self.err.setText("Connect eBay in Settings > eBay to see your store.")
            self.err.show()
            return
        self.b_ref.setEnabled(False)
        self.b_ref.setText("Refreshing…")
        if getattr(self, "_bar", None) is None:
            self._bar, self._skel = motion.LoadingBar(self), motion.Skeleton(self, top=120)
        self._bar.start()
        if not (self.data or {}).get("active"):
            self._skel.begin()                  # nothing to show yet: placeholder rows until it lands
        t = StoreTask(c)
        t.sig.done.connect(self._fetched)
        self.pool.start(t)

    def _fetched(self, data, err):
        self.b_ref.setEnabled(True)
        self.b_ref.setText("Refresh")
        if getattr(self, "_bar", None) is not None:
            self._bar.stop()
            self._skel.finish()
        hooks, self.after_fetch = self.after_fetch, []
        for fn in hooks:
            QTimer.singleShot(0, fn)
        if err:
            self.err.setText(f"Could not read your store: {err}")
            self.err.show()
            return
        self.err.hide()
        self.data = data
        try:
            import sales
            sales.merge(data.get("sold") or [])     # kept beyond eBay's 60 days, for pricing and reports
            self.m._sold_cache = None
        except Exception:  # noqa: BLE001
            pass
        try:
            import shiptrack                        # every sale with a tracking number joins Shipments
            if shiptrack.import_ebay(data.get("sold") or []) and getattr(self.m, "ship_page", None) is not None:
                self.m.ship_page.reload()
        except Exception:  # noqa: BLE001
            pass
        try:
            with open(self._cache_path(), "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass
        self.show_data()

    def _open(self, url):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    # ---------- thumbnails: your own photo when CardCrop made the listing, else eBay's
    def set_view(self, k):
        k = k if k in self.view_btns else "overview"
        for key, b in self.view_btns.items():
            b.setChecked(key == k)
        self.views.setCurrentIndex(0 if k == "overview" else 1)
        self.m.cfg.setValue("store_view", k)

    def thumb_for(self, row, item):
        sku = item.get("sku") or ""
        local = None
        if sku:
            folder = os.path.join(self.m.out_dir, sku)
            if os.path.isdir(folder):
                ph = ebay.listing_photos(folder)
                fr = next((p for p in ph if "_02_front" in p or "_01_hero" in p), ph[0] if ph else None)
                if fr:
                    local = fr
        key = local or item.get("image") or (f"item:{item['id']}" if item.get("id") else "")
        if not key:
            return
        if key in self._pix:
            row.set_pixmap(self._pix[key])
            return
        if local:
            img = QImage(local)
            if not img.isNull():
                pm = QPixmap.fromImage(img.scaled(160, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self._pix[key] = pm
                row.set_pixmap(pm)
            return
        self._waiting.setdefault(key, []).append(row)
        if len(self._waiting[key]) == 1:
            c = self.m.ebay_client() if key.startswith("item:") else None
            t = ImgTask(self.m.db, key, c, item.get("id") or "")
            t.sig.done.connect(self._img)
            self.pool.start(t)

    def _img(self, url, data):
        rows = self._waiting.pop(url, [])
        if not data:
            return
        pm = QPixmap()
        if not pm.loadFromData(data):
            try:                     # WebP and anything else Qt cannot read on its own
                import io
                from PIL import Image
                im = Image.open(io.BytesIO(data)).convert("RGB")
                q = QImage(im.tobytes(), im.width, im.height, 3 * im.width, QImage.Format_RGB888).copy()
                pm = QPixmap.fromImage(q)
            except Exception:  # noqa: BLE001
                return
        self._pix[url] = pm
        for r in rows:
            try:
                r.set_pixmap(pm)
            except RuntimeError:
                pass

    def show_data(self):
        import datetime as dt
        d = self.data or {}
        active, sold = d.get("active", []), d.get("sold", [])
        fetched = float(d.get("fetched", 0) or 0)
        self.upd.setText(f"Updated {time.strftime('%a %H:%M', time.localtime(fetched))}" if fetched else "")
        self.listings.set_data(active)
        today = dt.date.today()
        per = {}
        for x in sold:
            day = _local_day(x["date"])
            if day:
                per[day] = per.get(day, 0.0) + x["price"]

        def span(a, b):          # sales from a days ago up to b days ago
            return sum(v for k, v in per.items() if today - dt.timedelta(days=a) <= k <= today - dt.timedelta(days=b))

        def delta(now, before):
            if not before:
                return "" if not now else "<span style='color:#2BB673'>new</span> vs the week before"
            pct = (now - before) / before * 100
            col = "#2BB673" if pct >= 0 else "#E5484D"
            return f"<span style='color:{col}'>{pct:+.0f}%</span> vs the week before"

        sold_total = sum(x["price"] for x in sold)
        week_total, prev_week = span(6, 0), span(13, 7)
        n_week = sum(1 for x in sold if (_local_day(x["date"]) or today) >= today - dt.timedelta(days=6))
        to_ship = [x for x in sold if x.get("paid") and not x.get("shipped")]
        last14 = [per.get(today - dt.timedelta(days=13 - i), 0.0) for i in range(14)]
        n, sub, mb = self.nums["sold"]
        n.setText(f"${sold_total:,.0f}")
        sub.setText(f"{len(sold)} sales · average ${(sold_total / len(sold)) if sold else 0:,.2f}")
        mb.set_vals(last14)
        n, sub, mb = self.nums["week"]
        n.setText(f"${week_total:,.0f}")
        sub.setText(delta(week_total, prev_week) or f"{n_week} sales")
        mb.set_vals(last14[-7:])
        n, sub, mb = self.nums["ship"]
        n.setText(f"{len(to_ship):02d}")
        sub.setText("paid, waiting to ship" if to_ship else "all shipped")
        mb.set_vals([])
        n, sub, mb = self.nums["active"]
        n.setText(f"{len(active):02d}")
        sub.setText(f"${sum(x['price'] * max(1, x.get('qty', 1)) for x in active):,.2f} listed")
        new_per = {}
        for x in active:
            day = _local_day(x["start"])
            if day:
                new_per[day] = new_per.get(day, 0) + 1
        mb.set_vals([new_per.get(today - dt.timedelta(days=13 - i), 0) for i in range(14)])
        n, sub, mb = self.nums["watch"]
        n.setText(f"{sum(x.get('watchers', 0) for x in active):02d}")
        sub.setText(f"on {sum(1 for x in active if x.get('watchers'))} listings")
        mb.set_vals(sorted([x.get("watchers", 0) for x in active if x.get("watchers")])[-14:])
        self._per = per
        self.set_trend(self.trend_mode)
        watched = sorted([x for x in active if x.get("watchers")], key=lambda x: -x["watchers"])
        self._fill("watched", [(x, f"listed {_ago(x['start'])}", f"{x['watchers']} watching", LIME)
                               for x in watched[:40]])
        self._fill("new", [(x, f"listed {_ago(x['start'])}"
                            + (f" · {x['watchers']} watching" if x.get("watchers") else ""), "", "")
                           for x in active[:60]])
        self._fill_tx()
        self.show_traffic()

    def set_trend(self, mode):
        import datetime as dt
        self.trend_mode = mode
        self.m.cfg.setValue("store_trend", mode)
        for k, b in self.trend_btns.items():
            b.setChecked(k == mode)
        per = getattr(self, "_per", {})
        today = dt.date.today()
        if mode == "weekly":
            weeks = 12
            start = today - dt.timedelta(days=today.weekday() + 7 * (weeks - 1))
            labels, vals, marks = [], [], []
            for w in range(weeks):
                a = start + dt.timedelta(days=7 * w)
                vals.append(sum(v for k, v in per.items() if a <= k < a + dt.timedelta(days=7)))
                labels.append(f"Week of {a.strftime('%d %b')}")
                marks.append(a.strftime("%d %b") if w % 3 == 1 else "")
            total = sum(vals)
        else:
            days = [today - dt.timedelta(days=59 - i) for i in range(60)]
            vals = [per.get(d, 0.0) for d in days]
            labels = [d.strftime("%a %d %b") for d in days]
            marks = [d.strftime("%d %b") if i % 10 == 4 else "" for i, d in enumerate(days)]
            total = sum(vals)
        self.trend.set_data(labels, vals, marks)
        self.trend_total.setText(f"${total:,.0f}")

    def _all_sales(self):
        """Every sale CardCrop has seen, not just eBay's last 60 days, with the fresh ones on top."""
        import sales
        fresh = (self.data or {}).get("sold", [])
        seen = {(x.get("id"), x.get("date"), x.get("buyer")) for x in fresh}
        older = [x for x in sales.entries() if (x.get("id"), x.get("date"), x.get("buyer")) not in seen]
        return fresh + older

    def _fill_tx(self):
        sold = self._all_sales()
        q = self.tx_q.text().strip().lower()
        rows = [x for x in sold if not q or q in (x.get("title", "") + " " + x.get("buyer", "")).lower()]
        bl = self.tx_list
        while bl.count() > 1:
            w = bl.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not rows:
            e = QLabel("No sales yet" if not q else "No sales match", objectName="muted")
            e.setContentsMargins(8, 8, 0, 0)
            bl.insertWidget(0, e)
            return
        import datetime as dt
        from ui_marks import Marker
        today, k, last = dt.date.today(), 0, None
        for x in rows[:200]:
            day = _local_day(x.get("date", ""))
            if day != last:                     # a day heading between days, the way a chat dates its messages
                last = day
                label = ("Today" if day == today else "Yesterday" if day == today - dt.timedelta(days=1)
                         else day.strftime("%a %d %b" if day.year == today.year else "%d %b %Y") if day else "Earlier")
                bl.insertWidget(k, Marker(label))
                k += 1
            bl.insertWidget(k, TxRow(self, x))
            k += 1

    def export_csv(self):
        import csv
        sold = self._all_sales()
        if not sold:
            self.m.notice("No sales to export yet.", "warn")
            return
        out = os.path.join(self.m.out_dir, f"ebay_sales_{time.strftime('%Y%m%d-%H%M')}.csv")
        os.makedirs(self.m.out_dir, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Sold", "Item", "Item ID", "SKU", "Buyer", "Quantity", "Price", "Paid", "Shipped", "Link"])
            for x in sold:
                w.writerow([x.get("date", ""), x.get("title", ""), x.get("id", ""), x.get("sku", ""),
                            x.get("buyer", ""), x.get("qty", 1), f"{x.get('price', 0):.2f}",
                            "yes" if x.get("paid") else "no", "yes" if x.get("shipped") else "no", x.get("url", "")])
        subprocess_reveal(out)
        self.m.notice(f"{len(sold)} sales saved to {os.path.basename(out)}; Finder is showing it.", "ok")

    def _fill(self, key, rows):
        bl = self.lists[key]
        while bl.count() > 1:
            w = bl.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not rows:
            e = QLabel({"new": "Nothing listed yet", "sold": "No sales in the last 60 days",
                        "watched": "No watchers yet"}[key], objectName="muted")
            e.setContentsMargins(8, 8, 0, 0)
            bl.insertWidget(0, e)
            return
        for i, (item, sub, chip, col) in enumerate(rows):
            bl.insertWidget(i, StoreRow(self, item, sub, chip, col))


class _StageShim:
    """Older code asks whether live view is showing through self.stack; this answers from the stage."""

    def __init__(self, m):
        self.m = m

    def currentWidget(self):
        return self.m.live if self.m.stage == "shoot" else self.m.editor

    def setCurrentWidget(self, w):
        self.m.go("shoot" if w is self.m.live else "edit")


# names from the other parts, bound once every part has loaded
from ui_base import LIME, MONO, STATUS, icon_button, subprocess_reveal  # noqa: E402
from ui_market import price_field  # noqa: E402
from ui_tasks import CallTask, ImgTask, LiveReportTask, StoreTask, _Relay  # noqa: E402
from ui_widgets import CHART, Island, NoWheelSpin, PriceBox, SegBar, _ago, _local_day, dot_label, fade_in, rounded_pixmap, soft_scroll, with_arrows  # noqa: E402
