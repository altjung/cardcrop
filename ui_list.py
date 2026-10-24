"""CardCrop List stage: the batch as cards, ready to list on eBay."""
from __future__ import annotations

import ebay
import engine
import re
import time
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget
import ui_base as TH
import ui_motion as motion
from ui_marks import StatusMark

LIST_COLS = (24, 48, 0, 64, 112, 96, 52, 170)     # check, thumb, card (stretch), grade, price, outputs, photos, status


class ListRow(QFrame):
    """One card in the List stage."""

    def __init__(self, page, c):
        super().__init__()
        self.page, self.c = page, c
        self.setObjectName("row")
        self.setFixedHeight(72)
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(14)
        self.chk = QCheckBox()
        self.chk.setFixedWidth(LIST_COLS[0])
        self.chk.setChecked(c["name"] in page.selected)
        self.chk.toggled.connect(self._toggled)
        h.addWidget(self.chk)
        th = QLabel()
        th.setFixedSize(LIST_COLS[1], 60)
        th.setPixmap(rounded_pixmap(c.get("pm"), 44, 60, 5))
        h.addWidget(th)
        who = QVBoxLayout()
        who.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(8)
        nm = QLabel(c["title"])
        nm.setStyleSheet(f"font-size:{TH.BASE_PT + 2}pt; font-weight:500;")
        top.addWidget(nm)
        num = QLabel(c["num"], objectName="mono")
        top.addWidget(num)
        top.addStretch(1)
        who.addLayout(top)
        sub = c["set"] or c["name"]
        if c.get("store"):
            sub += "   ·   Store: " + c["store"].strip("/").replace("/", " › ")
        who.addWidget(QLabel(sub, objectName="small"))
        h.addLayout(who, 1)
        g = QLabel(c["cond"] or "None")
        g.setAlignment(Qt.AlignCenter)
        g.setFixedHeight(26)
        g.setStyleSheet(f"background:{TH.T['pill']}; border-radius:13px; padding:0 12px; font-weight:600;" if c["cond"]
                        else f"border:1.5px solid {TH.T['need']}; color:{TH.T['need']}; border-radius:13px; "
                             "padding:0 10px; font-weight:600;")
        gw = QWidget()
        gw.setFixedWidth(LIST_COLS[3])
        gl = QHBoxLayout(gw)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.addWidget(g)
        gl.addStretch(1)
        h.addWidget(gw)
        pr = QVBoxLayout()
        pr.setSpacing(2)
        self.price = PriceBox(objectName="rowprice")
        self.price.setRange(0, 100000)
        self.price.setDecimals(2)
        self.price.setPrefix("$")
        self.price.setValue(c["price"])
        self.price.setFixedWidth(LIST_COLS[4] - 16)
        self.price.valueChanged.connect(self._price)
        self.price.setKeyboardTracking(False)
        self.price.editingFinished.connect(self._price_live)
        self._sent = float(c["price"] or 0)
        pr.addWidget(self.price)
        sg = QPushButton(c["sugg_text"], objectName="ghost")
        sg.setStyleSheet(f"font-family:'{MONO}'; font-size:{TH.BASE_PT - 1}pt; padding:0 4px; text-align:left;")
        sg.setToolTip("Suggested from live eBay listings; click to use it")
        sg.setEnabled(bool(c.get("sugg")))
        sg.clicked.connect(lambda: (self.price.setValue(c["sugg"]), self._price_live()))
        pr.addWidget(sg, 0, Qt.AlignLeft)
        pw = QWidget()
        pw.setFixedWidth(LIST_COLS[4])
        pw.setLayout(pr)
        pr.setContentsMargins(0, 8, 0, 8)
        h.addWidget(pw)
        ow = QWidget()
        ow.setFixedWidth(LIST_COLS[5])
        ol = QHBoxLayout(ow)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(6)
        e = QLabel("eBay")
        e.setFixedHeight(22)
        e.setStyleSheet(f"background:{TH.T['pill']}; border-radius:11px; padding:0 10px; font-size:{TH.BASE_PT - 1}pt;")
        ol.addWidget(e, 0, Qt.AlignVCenter)
        if c["ig"]:
            ig = QLabel("IG", objectName="tag")
            ig.setFixedHeight(22)
            ol.addWidget(ig, 0, Qt.AlignVCenter)
        ol.addStretch(1)
        h.addWidget(ow)
        ph = QLabel(str(c["photos"]) if c["photos"] else "–", objectName="mono")
        ph.setFixedWidth(LIST_COLS[6])
        h.addWidget(ph)
        st = QHBoxLayout()
        st.setSpacing(8)
        self.dot = StatusMark(14)
        st.addWidget(self.dot)
        self.sl = QLabel()
        self.sl.setTextFormat(Qt.PlainText)          # eBay error pages are HTML; show them as words
        st.addWidget(self.sl, 1)
        self.prog = ProgressCell()
        self.prog.hide()
        st.addWidget(self.prog, 1)
        self.set_status(c["status"], c["status_key"], c.get("status_tip", ""))
        more = QToolButton()
        more.setText("•••")
        more.setFixedSize(30, 26)
        more.setToolTip("Upload again, or remove this card from CardCrop")
        more.setStyleSheet("QToolButton{border:none; font-weight:700;} QToolButton::menu-indicator{image:none;}")
        more.setPopupMode(QToolButton.InstantPopup)
        mm = QMenu(more)
        mm.addAction("Upload to eBay again…", lambda: page.m.list_reupload(c["name"]))
        mm.addAction("Remove from CardCrop…", lambda: page.m.list_remove([c["name"]]))
        sm = mm.addMenu("Store category")
        sm.aboutToShow.connect(lambda: page.m.store_cat_menu(sm, [c["name"]]))
        mm.addSeparator()
        mm.addAction("Open the card in Edit", lambda: page.m.open_card(c["name"]))
        more.setMenu(mm)
        st.addWidget(more)
        sw = QWidget()
        sw.setFixedWidth(LIST_COLS[7])
        sw.setLayout(st)
        st.setContentsMargins(0, 0, 0, 0)
        h.addWidget(sw)
        self._mark()

    def set_status(self, text, key, tip=""):
        one = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(text))).strip()
        busy = is_progress(one)
        self.prog.setVisible(busy)
        self.sl.setVisible(not busy)
        self.dot.setVisible(not busy)
        if busy:
            self.prog.set(one)
            self._was_busy = True
            return
        failed = one.startswith("Failed")
        state = ("failed" if failed else "done" if key in ("live", "unpub", "draft", "sold", "ready")
                 else "need" if key == "need" else "running" if key == "idle" and one.endswith("…") else "pending")
        self.dot.set_state(state, STATUS["error"] if failed else STATUS.get(key, STATUS["idle"]))
        if failed and getattr(self, "_was_busy", False):
            motion.shake(self)
        self._was_busy = False
        fm = self.sl.fontMetrics()
        self.sl.setText(fm.elidedText(one, Qt.ElideRight, LIST_COLS[7] - 24))
        self.sl.setToolTip(tip or one)
        col = STATUS["error"] if one.startswith("Failed") else STATUS.get(key, STATUS["idle"])
        self.dot.setStyleSheet(f"background:{col}; border-radius:4px;")

    def _mark(self):
        self.setProperty("sel", "true" if self.chk.isChecked() else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def _toggled(self, on):
        (self.page.selected.add if on else self.page.selected.discard)(self.c["name"])
        self._mark()
        self.page._update_bar()

    def _price(self, v):
        self.page.m._set_price(self.c["name"], v)
        self.c["price"] = v
        self.page._update_bar()

    def _price_live(self):
        """A live card's price goes to eBay as well, once you finish typing."""
        v = round(self.price.value(), 2)
        name = self.c["name"]
        if v <= 0 or abs(v - self._sent) < 0.005 or self.page.m._ebay_tag(name) != "eBay: live":
            return
        self._sent = v
        self.page.m.push_price(name, "", ebay.live_sku(self.page.m.out_dir, engine.safe_name(name)), v)

    def mouseDoubleClickEvent(self, e):
        self.page.m.open_card(self.c["name"])

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.chk.toggle()


class ListPage(QWidget):
    """The List stage: the batch as cards, priced and graded, sent in one go."""

    # live listings sit in a tab of their own; everything else is still being worked on
    FILTERS = (("all", "All"), ("ready", "Ready"), ("need", "Needs you"), ("ebay", "On eBay"),
               ("uploaded", "Uploaded"), ("live", "Live"), ("sold", "Sold"))
    MATCH = {"all": lambda k: k not in ("live", "sold"), "sold": lambda k: k == "sold", "ready": lambda k: k == "ready", "need": lambda k: k == "need",
             "ebay": lambda k: k in ("unpub", "draft"), "uploaded": lambda k: k == "unpub",
             "live": lambda k: k == "live"}
    PAGE = 25                    # cards a page: a session of hundreds opens as fast as one of twenty

    def __init__(self, main):
        super().__init__()
        self.m = main
        self.selected = set()
        self.filter = "all"
        self.rows = []
        self.page_i = 0
        self._show = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.isl = Island()
        outer.addWidget(self.isl)
        v = QVBoxLayout(self.isl)
        v.setContentsMargins(28, 26, 28, 0)
        v.setSpacing(16)
        head = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(6)
        self.date_lbl = QLabel(time.strftime("Batch · %A %d %B"), objectName="small")
        left.addWidget(self.date_lbl)
        left.addWidget(QLabel("Ready to list", objectName="title2"))
        head.addLayout(left, 1)
        self.stats = {}
        for key, label in (("cards", "cards"), ("total", "total, USD"), ("need", "need you")):
            box = QVBoxLayout()
            box.setSpacing(0)
            n = QLabel("0", objectName="dotneedbig" if key == "need" else "dotbig")
            box.addWidget(n)
            box.addWidget(QLabel(label, objectName="small"))
            head.addSpacing(30)
            head.addLayout(box)
            self.stats[key] = n
        v.addLayout(head)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.fbtns = {}
        for key, label in self.FILTERS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(key == "all")
            b.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            bar.addWidget(b)
            self.fbtns[key] = b
        bar.addStretch(1)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Name or number")
        self.q.setMinimumWidth(110)
        self.q.setMaximumWidth(220)
        self.q.textChanged.connect(lambda _t: self.refresh(page=0))
        bar.addWidget(self.q)
        self.b_route = QPushButton("")
        self.route_menu = QMenu(self.b_route)
        self.b_route.setMenu(self.route_menu)
        bar.addWidget(self.b_route)
        b_sel = QPushButton("Ready")
        b_sel.setToolTip("Tick every card that is ready to list")
        b_sel.clicked.connect(self.select_ready)
        b_all = QPushButton("All")
        b_all.setToolTip("Tick every card shown")
        b_all.clicked.connect(self.select_all)
        b_none = QPushButton("None")
        b_none.setToolTip("Untick everything")
        b_none.clicked.connect(self.select_none)
        sel_lbl = QLabel("Select", objectName="small")
        v.addLayout(bar)
        # ticking sits on a row of its own, so the List fits a laptop window
        bar2 = QHBoxLayout()
        bar2.addStretch(1)
        for w in (sel_lbl, b_sel, b_all, b_none):
            bar2.addWidget(w)
        v.addLayout(bar2)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(12, 0, 12, 0)
        hdr.setSpacing(14)
        for w_, text in zip(LIST_COLS, ("", "", "Card", "Grade", "Price", "Outputs", "Photos", "Status")):
            l = QLabel(text, objectName="small")
            if w_:
                l.setFixedWidth(w_)
                hdr.addWidget(l)
            else:
                hdr.addWidget(l, 1)
        v.addLayout(hdr)
        from PySide6.QtWidgets import QScrollArea
        self.sa = QScrollArea()
        self.sa.setWidgetResizable(True)
        self.sa.setFrameShape(QFrame.NoFrame)
        self.sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.bv = QVBoxLayout(self.body)
        self.bv.setContentsMargins(0, 0, 0, 110)
        self.bv.setSpacing(4)
        self.sa.setWidget(self.body)
        v.addWidget(self.sa, 1)
        self.empty = QLabel("Cards appear here once photos are named or identified in Edit.\n"
                            "Folders exported earlier: Cmd+K, Add exported folders.", objectName="muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.bv.addWidget(self.empty)
        pg = QHBoxLayout()
        pg.setContentsMargins(6, 10, 6, 0)
        pg.setSpacing(10)
        self.pg_prev = QPushButton("‹  Previous")
        self.pg_prev.clicked.connect(lambda: self.refresh(page=self.page_i - 1))
        self.pg_next = QPushButton("Next  ›")
        self.pg_next.clicked.connect(lambda: self.refresh(page=self.page_i + 1))
        self.pg_lbl = QLabel("", objectName="small")
        self.pg_lbl.setAlignment(Qt.AlignCenter)
        pg.addWidget(self.pg_prev)
        pg.addWidget(self.pg_lbl, 1)
        pg.addWidget(self.pg_next)
        self.pager = QWidget()
        self.pager.setLayout(pg)
        self.pager.hide()
        self.bv.addWidget(self.pager)
        self.bv.addStretch(1)
        # floating action bar
        self.abar = QFrame(objectName="actionbar")
        ab = QHBoxLayout(self.abar)
        ab.setContentsMargins(24, 8, 8, 8)
        ab.setSpacing(14)
        self.n_sel = QLabel("00", objectName="dot")
        self.n_sel.setStyleSheet(f"font-size:{TH.BASE_PT + 8}pt;")
        ab.addWidget(self.n_sel)
        ab.addWidget(QLabel("selected"))
        line = QFrame()
        line.setFixedSize(1, 24)
        line.setStyleSheet("background:#333338;")
        ab.addWidget(line)
        self.sum_lbl = QLabel("$0.00", objectName="mono")
        ab.addWidget(self.sum_lbl)
        self.b_ig = QPushButton("Instagram carousels")
        self.b_ig.setToolTip("Write the three Instagram slides for every selected card")
        self.b_ig.clicked.connect(lambda: self.m.batch_ig(sorted(self.selected)))
        ab.addWidget(self.b_ig)
        self.b_rep = QPushButton("Condition reports")
        self.b_rep.setToolTip("A condition report for each selected card, added as its last listing photo")
        self.b_rep.clicked.connect(lambda: self.m.batch_reports(sorted(self.selected)))
        ab.addWidget(self.b_rep)
        self.b_cat = QPushButton("Store category")
        self.b_cat.setToolTip("Which of your eBay Store categories the selected cards list into. Cards already "
                              "on eBay from CardCrop move straight away")
        cm = QMenu(self.b_cat)
        cm.aboutToShow.connect(lambda: self.m.store_cat_menu(cm, sorted(self.selected)))
        self.b_cat.setMenu(cm)
        ab.addWidget(self.b_cat)
        self.b_rm = QPushButton("Remove")
        self.b_rm.setToolTip("Take the selected cards out of CardCrop, for cards you listed by hand. Their photos "
                             "stay in their folders, and Cmd+Z brings them back")
        self.b_rm.clicked.connect(lambda: self.m.list_remove(sorted(self.selected)))
        ab.addWidget(self.b_rm)
        self.b_pub = QPushButton("", objectName="accent")
        self.b_pub.setToolTip("Put the selected unpublished listings live on eBay")
        self.b_pub.clicked.connect(lambda: self.m.batch_publish(
            [c["name"] for c in self.cards if c["name"] in self.selected and c["status_key"] == "unpub"]))
        ab.addWidget(self.b_pub)
        self.b_go = QPushButton("", objectName="accent")
        self.b_go.clicked.connect(self._go)
        ab.addWidget(self.b_go)
        for b in (self.b_ig, self.b_rep, self.b_cat, self.b_rm, self.b_pub, self.b_go):
            b.setFixedHeight(44)
        self.isl.float_widget(self.abar, "b", 20, 20)
        self.cards = []

    def _route_menu(self):
        m = self.route_menu
        m.clear()
        r = self.m.ebay_route()
        for key, label in (("direct", "Upload unpublished (API)"), ("drafts", "Seller Hub drafts")):
            a = m.addAction(label, lambda key=key: (self.m.set_ebay_route(key), self.refresh()))
            a.setCheckable(True)
            a.setChecked(key == r)
        m.addSeparator()
        a = m.addAction("Auto-upload finished cards", lambda: self.m.c_auto.toggle())
        a.setCheckable(True)
        a.setChecked(self.m.c_auto.isChecked())
        m.addSeparator()
        m.addAction("Review and publish…", self.m.ebay_review)
        m.addAction("Add exported folders…", lambda: self.m.list_folders([]))
        m.addAction("Drafts file for every exported card…", self.m.fill_drafts)
        m.addSeparator()
        m.addAction("eBay account…", self.m.ebay_account)
        self.b_route.setText("Route  ·  " + ("Unpublished" if r == "direct" else "Drafts"))

    def set_filter(self, k):
        self.filter = k
        for key, b in self.fbtns.items():
            b.setChecked(key == k)
        self.refresh(page=0)

    def select_all(self):
        self.selected |= {c["name"] for c in self._show}          # every page of what the filter shows
        self.refresh()

    def select_none(self):
        self.selected = set()
        self.refresh()

    def select_ready(self):
        self.selected = {c["name"] for c in self.cards if c["status_key"] == "ready"}
        self.refresh()

    def refresh(self, page=None):
        self._route_menu()
        self.cards = self.m._cards()
        names = {c["name"] for c in self.cards}
        self.selected &= names
        q = self.q.text().strip().lower()
        show = []
        for c in self.cards:
            if not self.MATCH.get(self.filter, self.MATCH["all"])(c["status_key"]):
                continue
            if q and q not in (c["title"] + " " + c["num"] + " " + c["name"]).lower():
                continue
            show.append(c)
        for r in self.rows:
            r.setParent(None)
            r.deleteLater()
        self.rows = []
        self._show = show
        pages = max(1, -(-len(show) // self.PAGE))
        if page is not None:
            self.page_i = page
            self.sa.verticalScrollBar().setValue(0)
        self.page_i = max(0, min(pages - 1, self.page_i))
        first = self.page_i * self.PAGE
        at = self.bv.indexOf(self.pager)
        for c in show[first:first + self.PAGE]:
            r = ListRow(self, c)
            self.bv.insertWidget(at, r)
            at += 1
            self.rows.append(r)
        self.pager.setVisible(pages > 1)
        self.pg_prev.setEnabled(self.page_i > 0)
        self.pg_next.setEnabled(self.page_i < pages - 1)
        self.pg_lbl.setText(f"Page {self.page_i + 1} of {pages}  ·  {first + 1}–{min(len(show), first + self.PAGE)} "
                            f"of {len(show)}")
        motion.cascade(self.rows)
        self.empty.setVisible(not show)
        counts = {k: sum(1 for c in self.cards if self.MATCH[k](c["status_key"])) for k, _ in self.FILTERS}
        for key, label in self.FILTERS:
            self.fbtns[key].setText(f"{label}  {counts[key]}")
        self.stats["cards"].setText(f"{len(self.cards):02d}")
        self.stats["total"].setText(f"{sum(c['price'] for c in self.cards):.0f}")
        self.stats["need"].setText(f"{sum(1 for c in self.cards if c['status_key'] == 'need'):02d}")
        self._update_bar()

    def _update_bar(self):
        sel = [c for c in self.cards if c["name"] in self.selected]
        n = len(sel)
        # what is on eBay comes from CardCrop's eBay record, not the last status shown: a card
        # whose publish failed still has its unpublished listing, and needs Publish, not Upload
        tags = {c["name"]: self.m._ebay_tag(c["name"]) for c in sel}
        new = [c for c in sel if not tags[c["name"]] and c["status_key"] not in ("unpub", "live", "draft")]
        copies = [c for c in sel if tags[c["name"]] in ("eBay: live", "eBay: sold")] \
            if self.m.ebay_route() == "direct" else []
        unpub = [c for c in sel if tags[c["name"]] == "eBay: unpublished"
                 or (not tags[c["name"]] and c["status_key"] == "unpub")]
        self.n_sel.setText(f"{n:02d}")
        self.sum_lbl.setText(f"${sum(c['price'] for c in sel):,.2f}")
        verb = "Upload" if self.m.ebay_route() == "direct" else "Draft"
        self.b_go.setText(f"{verb} {len(new) + len(copies)} to eBay" if new or copies else f"{verb} to eBay")
        self.b_go.setVisible(bool(new or copies) or not unpub)
        self.b_go.setEnabled(bool(new or copies))
        self.b_pub.setText(f"Publish {len(unpub)}")
        self.b_pub.setVisible(bool(unpub))
        self.b_ig.setEnabled(n > 0)
        self.b_rep.setEnabled(n > 0)
        self.b_rm.setEnabled(n > 0)
        self.b_cat.setEnabled(n > 0)
        self.abar.setVisible(bool(self.cards))
        self.isl._place()

    def refresh_status(self, name):
        """Progress for one card, without rebuilding the list."""
        for r in self.rows:
            if r.c["name"] == name:
                r.set_status(self.m._batch_state.get(name, r.c["status"]), "idle")

    def _go(self):
        names = [c["name"] for c in self.cards if c["name"] in self.selected
                 and not self.m._ebay_tag(c["name"]) and c["status_key"] not in ("unpub", "live", "draft", "sold")]
        tags = {c["name"]: self.m._ebay_tag(c["name"]) for c in self.cards if c["name"] in self.selected}
        again = [n for n, t in tags.items() if t in ("eBay: sold", "eBay: live")]
        relist = False
        if again and self.m.ebay_route() == "direct":
            from PySide6.QtWidgets import QMessageBox
            n_live = sum(1 for n in again if tags[n] == "eBay: live")
            why = (f"{n_live} of these {'is' if n_live == 1 else 'are'} already live on eBay"
                   if n_live else f"{len(again)} of these sold before")
            relist = QMessageBox.question(
                self, "Another copy?", f"{why}. List these photos as another copy, a listing of its own? "
                "The listing already there is left exactly as it is.") == QMessageBox.Yes
            if relist:
                names += again
        if self.m.ebay_route() == "direct":
            self.m.batch_upload(names, relist=relist)
        else:
            self.m.batch_drafts(names)


# names from the other parts, bound once every part has loaded
from ui_base import MONO, STATUS  # noqa: E402
from ui_widgets import Island, PriceBox, ProgressCell, is_progress, rounded_pixmap  # noqa: E402
