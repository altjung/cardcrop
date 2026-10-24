"""CardCrop Market stage: what your cards sell for and what moved."""
from __future__ import annotations

import ebay
import identify
import time
from PySide6.QtCore import QThreadPool, QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget
import ui_base as TH
import ui_motion as motion

MK_COLS = (44, 0, 84, 76, 96, 84, 56, 88)       # photo, card, yours, market, position, change, trend, action
POS_COLORS = {"over": "#F08C1B", "under": "#2BB673", "in": "#8E8E95"}


def position(r, threshold):
    """Where your price sits against the market: over, under or in market (within the alert threshold)."""
    mine, mk = r.get("mine") or 0.0, r.get("sugg") or 0.0
    if not mine or not mk:
        return None, None
    gap = (mk - mine) / mine
    if gap >= threshold:
        return "under", gap
    if gap <= -threshold:
        return "over", gap
    return "in", gap


def pos_pill(r, threshold):
    """A small coloured pill: Over 47%, Under 22%, In market."""
    kind, gap = position(r, threshold)
    l = QLabel("")
    l.setFixedWidth(MK_COLS[4])
    l.setAlignment(Qt.AlignCenter)
    if kind is None:
        l.setText("–")
        l.setStyleSheet(f"color:{TH.T['muted']};")
        return l
    mine, mk = r.get("mine") or 0.0, r.get("sugg") or 0.0
    pct = abs(mine - mk) / mk * 100 if mk else 0
    l.setText({"over": f"Over {pct:.0f}%", "under": f"Under {pct:.0f}%", "in": "In market"}[kind])
    c = POS_COLORS[kind]
    rgb = ",".join(str(int(c[i:i + 2], 16)) for i in (1, 3, 5))
    l.setFixedHeight(24)
    l.setStyleSheet(f"color:{c}; background: rgba({rgb},38); border-radius:12px; padding:0; font-weight:600;")
    l.setToolTip(f"You ask ${mine:,.2f}, the market says ${mk:,.2f}")
    return l


def price_field(value, width, commit, tip=""):
    """A price you type: committed on Return or when you click away, never while typing or scrolling."""
    f = PriceBox(objectName="rowprice")
    f.setRange(0, 100000)
    f.setDecimals(2)
    f.setPrefix("$")
    f.setKeyboardTracking(False)
    f.setValue(float(value or 0))
    f.setFixedWidth(width)
    f.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    f.setToolTip(tip)
    f._last = f.value()

    def fire():
        v = round(f.value(), 2)
        if v > 0 and abs(v - f._last) >= 0.005:
            f._last = v
            commit(v)
    f.editingFinished.connect(fire)
    # a run of arrow clicks or key presses is sent once, when it pauses
    f._t = QTimer(f, singleShot=True, interval=900)
    f._t.timeout.connect(fire)
    f.valueChanged.connect(lambda _v: f._t.start())
    return f


def _pct(v):
    return "–" if v is None else f"{'▲' if v > 0 else '▼' if v < 0 else ''} {abs(v) * 100:.1f}%"


class MoverRow(QFrame):
    def __init__(self, page, r, mode):
        super().__init__()
        self.setObjectName("row")
        self.page, self.r = page, r
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(12)
        ph = QLabel()
        ph.setFixedSize(MK_COLS[0], 60)
        ph.setAlignment(Qt.AlignCenter)
        pm = page.thumb(r.get("photo", ""))
        if pm is not None:
            ph.setPixmap(pm)
        else:
            ph.setStyleSheet(f"background:{TH.T['pill']}; border-radius:6px;")
            if r.get("image") or r.get("item_id"):
                page.thumb_url(r.get("image") or f"item:{r['item_id']}", ph)
        h.addWidget(ph)
        info = r.get("info") or {}
        name = QLabel(info.get("name") or r.get("title") or r["key"])
        if r.get("outside"):
            name.setToolTip(r.get("title", ""))
        name.setStyleSheet("font-weight:600;")
        meta = QLabel(" · ".join(x for x in (info.get("set_name", "") or ("from the eBay title" if r.get("outside") else ""),
                                             f"#{info.get('number')}" if info.get("number")
                                             else "", {"live": "Live", "unpublished": "On eBay, unpublished",
                                                        "exported": "Not listed"}.get(r["status"], "")) if x),
                      objectName="small")
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(name)
        col.addWidget(meta)
        h.addLayout(col, 1)
        self.yours = price_field(r.get("mine") or 0, MK_COLS[2],
                                 lambda v, rr=r: page.use_price(rr, v),
                                 "Your price. Type any amount and press Return"
                                 + (" to change the eBay listing too" if r["status"] in ("live", "unpublished") else ""))
        h.addWidget(self.yours)
        mk = r.get("sugg") or r.get("market")
        mkt = QPushButton(f"${mk:,.2f}" if mk else "–", objectName="ghost")
        mkt.setStyleSheet(f"font-family:'{MONO}'; padding:0 4px; text-align:right;")
        mkt.setFixedWidth(MK_COLS[3])
        mkt.setEnabled(bool(mk))
        mkt.setToolTip((f"Suggested from {r.get('basis') or 'market data'}. " if r.get("sugg") else "")
                       + "Click to put it in your price box; nothing changes until you press Return there.")
        mkt.clicked.connect(lambda _=False, v=mk: (self.yours.setValue(v), self.yours.setFocus(),
                                                   self.yours.selectAll()))
        h.addWidget(mkt)
        h.addWidget(pos_pill(r, page.threshold()))
        ch = r.get("day") if mode == "day" else r.get("week")
        chl = QLabel(_pct(ch), objectName="mono")
        chl.setFixedWidth(MK_COLS[5])
        chl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if ch:
            chl.setStyleSheet(f"color:{'#2BB673' if ch > 0 else '#E5484D'}; font-weight:600;")
        chl.setToolTip(r.get("day_basis") if mode == "day" else r.get("week_basis"))
        h.addWidget(chl)
        mb = MiniBars()
        mb.setFixedSize(MK_COLS[6], 30)
        mb.set_vals(r.get("series") or [])
        mb.setToolTip("Market price at each scan, oldest on the left")
        h.addWidget(mb)
        act = QWidget()
        act.setFixedWidth(MK_COLS[7])
        al = QHBoxLayout(act)
        al.setContentsMargins(0, 0, 0, 0)
        if r.get("item_id") and r["status"] == "live":
            b = icon_button("film", "Add a 360° video to this listing: rendered from its photos with your "
                                    "video settings (Settings, Videos), uploaded and attached", 30, text="Video")
            b.clicked.connect(lambda _=False, rr=r: page.add_video(rr))
            mark_video(b, page.m, r.get("item_id"))
            al.addWidget(b)
        al.addStretch(1)
        h.addWidget(act)


class AlertRow(QFrame):
    """One price alert. Drag it right to open the listing in Store, left to put it away."""
    COLORS = {"raise": "#2BB673", "lower": "#F08C1B", "up": "#2BB673", "down": "#E5484D"}
    PULL = 110                                  # points of drag that count as a decision

    def __init__(self, page, r):
        super().__init__()
        self.setObjectName("row")
        self.page, self.r = page, r
        self._x0, self._dx = None, 0
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag right to open the listing, left to dismiss")
        v = QVBoxLayout(self)
        self._v = v
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(3)
        info = r.get("info") or {}
        t = QLabel(f"{info.get('name') or r.get('title') or r['key']}  "
                   f"<span style='color:{TH.T['muted']}'>#{info.get('number', '')}</span>")
        t.setTextFormat(Qt.RichText)
        t.setStyleSheet("font-weight:600;")
        v.addWidget(t)
        for kind, text in r["alerts"]:
            l = QLabel(f"<span style='color:{self.COLORS.get(kind, TH.T['text'])}'>●</span> {text}", objectName="small")
            l.setTextFormat(Qt.RichText)
            l.setWordWrap(True)
            v.addWidget(l)
        bl = QHBoxLayout()
        bl.setSpacing(6)
        bl.addWidget(price_field(r.get("mine") or 0, 96, lambda v, rr=r: page.use_price(rr, v),
                                 "Your price. Type any amount and press Return"))
        b = QPushButton("Sold on eBay")
        b.setToolTip("Open eBay's sold listings for this card, to check what it actually goes for")
        b.clicked.connect(lambda _=False, rr=r: page.research(rr))
        bl.addWidget(b)
        if r.get("item_id"):
            b = QPushButton("Listing")
            b.setToolTip("Open this listing in Store")
            b.clicked.connect(lambda _=False, rr=r: page.open_listing(rr))
            bl.addWidget(b)
        elif r.get("url"):
            b = QPushButton("Listing")
            b.clicked.connect(lambda _=False, u=r["url"]: page.m.store_page._open(u))
            bl.addWidget(b)
        bl.addStretch(1)
        v.addLayout(bl)

    # the row slides with the pointer; the strip it uncovers says what letting go will do
    def _shift(self, dx):
        self._dx = dx
        self._v.setContentsMargins(10 + max(0, dx), 8, 10 + max(0, -dx), 8)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._x0 = e.position().x()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._x0 is not None:
            dx = int(e.position().x() - self._x0)
            if self.r.get("item_id") is None and dx > 0:
                dx = 0                               # nothing to open for a card that is not listed
            self._shift(max(-220, min(220, dx)))
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        dx, self._x0 = self._dx, None
        self.setCursor(Qt.OpenHandCursor)
        self._shift(0)
        if dx >= self.PULL:
            self.page.open_listing(self.r)
        elif dx <= -self.PULL:
            self.page.dismiss([self.r])
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self._dx:
            return
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self)
        right = self._dx > 0
        far = abs(self._dx) >= self.PULL
        c = QColor(LIME if right else "#E5484D")
        c.setAlpha(255 if far else 120)
        p.setPen(c)
        w = abs(self._dx)
        rect = self.rect().adjusted(0, 0, -(self.width() - w), 0) if right else \
            self.rect().adjusted(self.width() - w, 0, 0, 0)
        p.drawText(rect, Qt.AlignCenter, "Open" if right else "Dismiss")
        p.end()


class MarketPage(QWidget):
    """What your cards are worth today: the biggest movers first, and the cards whose price
    no longer matches the market. Fed by the nightly scan (or Scan now)."""

    def __init__(self, main):
        super().__init__()
        self.m, self.cfg = main, main.cfg
        self.rows, self.task, self._thumbs = [], None, {}
        self._mine = {}                          # prices you just set, until the store's data catches up
        self.page_i = 0
        self.pos = str(self.cfg.value("market_pos", "all"))
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.mode = str(self.cfg.value("market_mode", "day"))
        self.scope = str(self.cfg.value("market_scope", "listed"))
        if self.scope not in ("listed", "live"):
            self.scope = "listed"
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        head = QHBoxLayout()
        head.setContentsMargins(8, 4, 4, 0)
        head.addWidget(QLabel("Market", objectName="title2"))
        head.addSpacing(16)
        self.upd = QLabel("", objectName="small")
        head.addWidget(self.upd)
        head.addStretch(1)
        self.prog = ProgressCell()
        self.prog.setFixedWidth(200)
        self.prog.hide()
        head.addWidget(self.prog)
        self.b_scan = QPushButton("Scan now")
        self.b_scan.setToolTip("Price every card you have on eBay now; this also runs by itself each night")
        self.b_scan.clicked.connect(lambda: self.scan())
        head.addWidget(self.b_scan)
        v.addLayout(head)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.nums = {}
        for key, cap, need in (("tracked", "Cards tracked", False), ("up", "Up", False), ("down", "Down", False),
                               ("alerts", "Need a price check", True), ("value", "Market value", False)):
            f = Island()
            fv = QVBoxLayout(f)
            fv.setContentsMargins(20, 14, 16, 12)
            fv.setSpacing(2)
            capl = QLabel(cap.upper(), objectName="mono")
            fv.addWidget(capl)
            n = QLabel("–", objectName="dotneed" if need else "dot")
            fv.addWidget(n)
            sub = QLabel("", objectName="small")
            sub.setTextFormat(Qt.RichText)
            fv.addWidget(sub)
            tiles.addWidget(f, 1)
            self.nums[key] = (n, sub, capl)
        v.addLayout(tiles)

        body = QHBoxLayout()
        body.setSpacing(12)
        mv = Island()
        mvl = QVBoxLayout(mv)
        mvl.setContentsMargins(14, 14, 14, 10)
        mvl.setSpacing(6)
        mh = QHBoxLayout()
        self.mode_btns, self.scope_btns = {}, {}
        self.pos_btns = {}
        for opts, store, fn in (((("all", "All"), ("over", "Over"), ("under", "Under"), ("in", "In market")),
                                 self.pos_btns, self.set_pos),
                                ((("day", "Today"), ("week", "7 days")), self.mode_btns, self.set_mode),
                                ((("listed", "On eBay"), ("live", "Live")), self.scope_btns,
                                 self.set_scope)):
            seg = QFrame(objectName="segbox")
            sg = QHBoxLayout(seg)
            sg.setContentsMargins(4, 4, 4, 4)
            sg.setSpacing(4)
            for k, label in opts:
                b = QPushButton(label, objectName="seg")
                b.setCheckable(True)
                b.clicked.connect(lambda _=False, k_=k, f_=fn: f_(k_))
                sg.addWidget(b)
                store[k] = b
            mh.addWidget(seg)
            if store is self.pos_btns:
                mh.addStretch(1)              # where your price sits on the left, the change and scope on the right
        mvl.addLayout(mh)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 0, 8, 0)
        hdr.setSpacing(12)
        for w_, text in zip(MK_COLS, ("", "Card", "Yours", "Market", "Position", "Change", "Trend", "")):
            l = QLabel(text, objectName="small")
            if text in ("Yours", "Market", "Change"):
                l.setAlignment(Qt.AlignRight)
            elif text == "Position":
                l.setAlignment(Qt.AlignCenter)
            if w_:
                l.setFixedWidth(w_)
                hdr.addWidget(l)
            else:
                hdr.addWidget(l, 1)
        mvl.addLayout(hdr)
        self.mv_list = self._scroll(mvl)
        pg = QHBoxLayout()
        pg.setContentsMargins(6, 4, 6, 0)
        pg.setSpacing(10)
        self.pg_prev = QPushButton("‹  Previous")
        self.pg_prev.clicked.connect(lambda: self.show_rows(page=self.page_i - 1))
        self.pg_next = QPushButton("Next  ›")
        self.pg_next.clicked.connect(lambda: self.show_rows(page=self.page_i + 1))
        self.pg_lbl = QLabel("", objectName="small")
        self.pg_lbl.setAlignment(Qt.AlignCenter)
        pg.addWidget(self.pg_prev)
        pg.addWidget(self.pg_lbl, 1)
        pg.addWidget(self.pg_next)
        self.pager = QWidget()
        self.pager.setLayout(pg)
        mvl.addWidget(self.pager)
        body.addWidget(mv, 2)

        al = Island()
        all_ = QVBoxLayout(al)
        all_.setContentsMargins(14, 14, 14, 10)
        all_.setSpacing(6)
        lab = QLabel("PRICE ALERTS", objectName="mono")
        lab.setContentsMargins(6, 0, 0, 0)
        ah = QHBoxLayout()
        ah.addWidget(lab)
        ah.addStretch(1)
        self.b_clear = QPushButton("Clear all", objectName="ghost")
        self.b_clear.setToolTip("Put every alert away; each comes back only if its market price changes")
        self.b_clear.clicked.connect(lambda: self.dismiss([r for r in self.rows if r.get("alerts")]))
        ah.addWidget(self.b_clear)
        all_.addLayout(ah)
        sr = QHBoxLayout()
        sr.setContentsMargins(6, 0, 0, 0)
        sr.addWidget(QLabel("Scan nightly at", objectName="small"))
        self.hour = QComboBox()
        self.hour.addItem("Off", -1)
        for hh in range(24):
            self.hour.addItem(f"{(hh % 12) or 12}:00 {'AM' if hh < 12 else 'PM'}", hh)
        self.hour.setCurrentIndex(max(0, self.hour.findData(int(self.cfg.value("market_hour", 0)))))
        self.hour.currentIndexChanged.connect(lambda _i: self.cfg.setValue("market_hour", self.hour.currentData()))
        self.hour.setToolTip("CardCrop must be open (it can sit in the background) and the Mac awake. "
                             "A missed night runs as soon as CardCrop opens.")
        sr.addWidget(self.hour)
        sr.addStretch(1)
        all_.addLayout(sr)
        sr = QHBoxLayout()                        # two rows, so the panel stays narrow
        sr.setContentsMargins(6, 0, 0, 0)
        sr.addWidget(QLabel("Alert at", objectName="small"))
        self.pct = QSpinBox()
        self.pct.setRange(3, 60)
        self.pct.setSuffix(" %")
        self.pct.setFixedWidth(80)
        self.pct.setValue(int(self.cfg.value("market_pct", 10)))
        self.pct.setToolTip("Flag a card when its market price is this far from yours, or moves this much in a day")
        self.pct.valueChanged.connect(self._pct_changed)
        sr.addWidget(self.pct)
        sr.addStretch(1)
        all_.addLayout(sr)
        self.al_list = self._scroll(all_)
        body.addWidget(al, 1)
        v.addLayout(body, 1)
        self.note = QLabel("Changes come from CardCrop's nightly scans: TCGplayer's market price (built from its "
                           "recent sales) where there is one, else eBay's live asking prices. Until two scans exist, "
                           "Cardmarket's 1-day against 7-day sold average stands in.", objectName="small")
        self.note.setWordWrap(True)
        self.note.setContentsMargins(8, 0, 8, 0)
        v.addWidget(self.note)
        self._sync_btns()
        self.show_rows()

    def _scroll(self, parent_layout):
        from PySide6.QtWidgets import QScrollArea
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(2)
        bl.addStretch(1)
        sa.setWidget(body)
        parent_layout.addWidget(sa, 1)
        return bl

    def _sync_btns(self):
        for k, b in self.pos_btns.items():
            b.setChecked(k == self.pos)
        for k, b in self.mode_btns.items():
            b.setChecked(k == self.mode)
        for k, b in self.scope_btns.items():
            b.setChecked(k == self.scope)

    def threshold(self):
        return self.pct.value() / 100 if hasattr(self, "pct") else 0.10

    def set_pos(self, k):
        self.pos = k
        self.cfg.setValue("market_pos", k)
        self._sync_btns()
        self.show_rows(page=0)

    def dismissed(self) -> dict:
        """Alerts put away (here or on the phone), each with the market price it had: one stays away until
        that price changes."""
        import json
        try:
            return json.loads(str(self.cfg.value("phone_market_dismissed", "") or "{}"))
        except ValueError:
            return {}

    def is_dismissed(self, r):
        gone = self.dismissed().get(r.get("key"))
        return gone is not None and r.get("sugg") is not None and abs(float(gone) - float(r["sugg"])) < 0.01

    def dismiss(self, rows):
        import json
        d = self.dismissed()
        for r in rows:
            if r.get("sugg") is not None:
                d[r["key"]] = r["sugg"]
        self.cfg.setValue("phone_market_dismissed", json.dumps(d))
        self._phone_stale()
        self.show_rows()

    def _phone_stale(self):
        ph = getattr(self.m, "phone", None)
        if ph is not None:
            ph._ins = None
            try:
                ph.dirty("store")
            except Exception:  # noqa: BLE001
                pass

    def open_listing(self, r):
        """The listing in CardCrop's own Store editor."""
        iid = r.get("item_id")
        if not iid:
            return
        sp = self.m.store_page
        self.m.go("store")
        sp.set_view("listings")
        sp.listings.select(iid)

    def set_mode(self, k):
        self.mode = k
        self.cfg.setValue("market_mode", k)
        self._sync_btns()
        self.show_rows()

    def set_scope(self, k):
        self.scope = k
        self.cfg.setValue("market_scope", k)
        self._sync_btns()
        self.show_rows()

    def _pct_changed(self, v):
        self.cfg.setValue("market_pct", v)
        self.analyze()

    def thumb_url(self, url, label):
        """eBay's own picture for a listing made outside CardCrop, fetched off the UI thread."""
        if url in self._thumbs and self._thumbs[url] is not None:
            label.setPixmap(self._thumbs[url])
            label.setStyleSheet("")
            return
        self._img_wait = getattr(self, "_img_wait", {})
        first = url not in self._img_wait
        self._img_wait.setdefault(url, []).append(label)
        if first:
            iid = url[5:] if url.startswith("item:") else ""
            t = ImgTask(self.m.db, url, self.m.ebay_client() if iid else None, iid)
            t.sig.done.connect(self._got_img)
            self.pool.start(t)

    def _got_img(self, url, data):
        labels = self._img_wait.pop(url, [])
        if not data:
            return
        q = QImage.fromData(data)
        if q.isNull():
            try:
                import io
                from PIL import Image
                im = Image.open(io.BytesIO(data)).convert("RGB")
                q = QImage(im.tobytes(), im.width, im.height, 3 * im.width, QImage.Format_RGB888).copy()
            except Exception:  # noqa: BLE001
                return
        pm = rounded_pixmap(QPixmap.fromImage(q.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)),
                            MK_COLS[0], 60)
        self._thumbs[url] = pm
        for l in labels:
            try:
                l.setPixmap(pm)
                l.setStyleSheet("")
            except RuntimeError:
                pass

    def thumb(self, path):
        if not path:
            return None
        if path not in self._thumbs:
            from PySide6.QtGui import QImageReader
            rd = QImageReader(path)
            rd.setAutoTransform(True)
            sz = rd.size()
            if sz.isValid() and sz.height() > 0:
                from PySide6.QtCore import QSize
                rd.setScaledSize(QSize(int(sz.width() * 120 / sz.height()), 120))
            img = rd.read()
            pm = QPixmap.fromImage(img) if not img.isNull() else None
            if pm is not None:
                pm = rounded_pixmap(pm, MK_COLS[0], 60)
            self._thumbs[path] = pm
        return self._thumbs[path]

    # ---------- data
    def inventory(self):
        import market
        store = self.m.store_page.data if hasattr(self.m, "store_page") else None
        items = market.inventory(self.m.out_dir, store, self.m._prices(), ebay.load_records(self.m.out_dir))
        # only cards up on eBay, live or waiting to publish: those are the prices that matter
        return [x for x in items if x["status"] in ("live", "unpublished")]

    def analyze(self):
        import market
        hist = market.load_history()
        th = self.pct.value() / 100
        items = self.inventory()
        for it in items:
            want = self._mine.get(it["key"])
            if want is None:
                continue
            if abs(float(it.get("mine") or 0) - want) < 0.005:
                self._mine.pop(it["key"], None)          # the store has caught up
            else:
                it["mine"] = want
        self.rows = [market.analyze(it, hist.get(it["key"], []), th) for it in items]
        self.show_rows()
        return self.rows

    def scanning(self):
        return self.task is not None

    def scan(self, quiet=False):
        if self.task is not None:
            self.task.stop = True
            self.b_scan.setText("Stopping…")
            return
        sp = self.m.store_page
        if not getattr(self, "_store_fresh", False):
            c = self.m.ebay_client()
            if c is not None and c.signed_in() and sp.stale():
                # the whole store, fresh, before pricing it: listings made anywhere are included
                self._store_fresh = True
                self.b_scan.setText("Reading store…")
                sp.after_fetch.append(lambda: self.scan(quiet))
                sp.refresh()
                return
        self._store_fresh = False
        items = self.inventory()
        if not items:
            if not quiet:
                self.m.notice("No listed cards to scan: Market watches cards that are on eBay (live or "
                              "unpublished). Refresh Store first if you listed some outside CardCrop.", "info")
            return
        self._quiet = quiet
        self.task = MarketScanTask(self.m.ebay_client(), self.m.db, items)
        self.task.sig.progress.connect(self._progress)
        self.task.sig.done.connect(self._scanned)
        self.prog.show()
        self.prog.set(f"Pricing 0 of {len(items)}")
        self.b_scan.setText("Stop")
        self.pool.start(self.task)
        n_out = sum(1 for x in items if x.get("outside"))
        self.prog.setToolTip(f"{len(items)} listings, {n_out} of them made outside CardCrop")

    def _progress(self, i, n, msg):
        self.prog.set(f"Pricing {i} of {n}")
        self.prog.setToolTip(msg)

    def _scanned(self, hist):
        self.task = None
        self.prog.hide()
        self.b_scan.setText("Scan now")
        self.cfg.setValue("market_last_scan", time.time())
        rows = self.analyze()
        n_alert = sum(1 for r in rows if r["alerts"])
        self.m._market_done(n_alert, len(rows), getattr(self, "_quiet", False))

    PAGE = 40

    def show_rows(self, page=None):
        rows = self.rows
        if self.scope == "listed":
            rows = [r for r in rows if r["status"] in ("live", "unpublished")]
        elif self.scope == "live":
            rows = [r for r in rows if r["status"] == "live"]
        key = "day" if self.mode == "day" else "week"
        ranked = sorted(rows, key=lambda r: (r.get(key) is None, -(r.get(key) or 0)))
        for lay in (self.mv_list, self.al_list):
            while lay.count() > 1:
                w = lay.takeAt(0).widget()
                if w is not None:
                    w.hide()
                    w.deleteLater()
        th = self.threshold()
        if self.pos != "all":
            ranked = [r for r in ranked if position(r, th)[0] == self.pos]
        pages = max(1, -(-len(ranked) // self.PAGE))
        if page is not None:
            self.page_i = page
        self.page_i = max(0, min(pages - 1, self.page_i))
        first = self.page_i * self.PAGE
        self.pager.setVisible(pages > 1)
        self.pg_prev.setEnabled(self.page_i > 0)
        self.pg_next.setEnabled(self.page_i < pages - 1)
        self.pg_lbl.setText(f"Page {self.page_i + 1} of {pages}  ·  {first + 1}–{min(len(ranked), first + self.PAGE)}"
                            f" of {len(ranked)}")
        made = []
        for r in ranked[first:first + self.PAGE]:
            made.append(MoverRow(self, r, key))
            self.mv_list.insertWidget(self.mv_list.count() - 1, made[-1])
        alerts = [r for r in rows if r["alerts"] and not self.is_dismissed(r)]
        self.b_clear.setVisible(bool(alerts))
        alerts.sort(key=lambda r: -abs((r.get("gap") or 0)))
        al = []
        for r in alerts[:150]:
            al.append(AlertRow(self, r))
            self.al_list.insertWidget(self.al_list.count() - 1, al[-1])
        motion.cascade(made)
        motion.cascade(al)
        if self.rows and not alerts:
            msg = QLabel("No alerts: every price sits within the market, or you put the alerts away.",
                         objectName="small")
            msg.setWordWrap(True)
            msg.setContentsMargins(8, 8, 8, 8)
            self.al_list.insertWidget(0, msg)
        if not self.rows:
            msg = QLabel("Scan to see your listed cards' prices: every card on eBay, live or unpublished.",
                         objectName="small")
            msg.setWordWrap(True)
            msg.setContentsMargins(8, 8, 8, 8)
            self.mv_list.insertWidget(0, msg)
        moved = [r for r in rows if r.get(key) is not None]
        up = [r for r in moved if r[key] > 0.005]
        down = [r for r in moved if r[key] < -0.005]

        def dollars(rs):
            return sum((r["market"] or 0) * r[key] / (1 + r[key]) for r in rs if r.get("market"))

        word = "today" if key == "day" else "this week"
        n, sub, cap = self.nums["tracked"]
        n.setText(f"{len(rows):02d}")
        last = float(self.cfg.value("market_last_scan", 0) or 0)
        sub.setText(f"{sum(1 for r in rows if r['status'] == 'live')} live on eBay")
        self.upd.setText(f"Last scan {time.strftime('%a %d %b, %H:%M', time.localtime(last))}" if last
                         else "Not scanned yet")
        n, sub, cap = self.nums["up"]
        cap.setText(f"UP {word.upper()}")
        n.setText(f"{len(up):02d}")
        sub.setText(f"<span style='color:#2BB673'>+${dollars(up):,.2f}</span> in market value" if up else "")
        n, sub, cap = self.nums["down"]
        cap.setText(f"DOWN {word.upper()}")
        n.setText(f"{len(down):02d}")
        sub.setText(f"<span style='color:#E5484D'>−${abs(dollars(down)):,.2f}</span> in market value" if down else "")
        n, sub, cap = self.nums["alerts"]
        n.setText(f"{len(alerts):02d}")
        raise_ = sum(1 for r in alerts if any(k == "raise" for k, _ in r["alerts"]))
        lower = sum(1 for r in alerts if any(k == "lower" for k, _ in r["alerts"]))
        sub.setText(f"{raise_} under market · {lower} over" if alerts else "prices match the market")
        n, sub, cap = self.nums["value"]
        mv_ = sum((r.get("sugg") or 0) for r in rows)
        mine = sum((r.get("mine") or 0) for r in rows if r.get("sugg"))
        n.setText(f"${mv_:,.0f}")
        sub.setText(f"you ask ${mine:,.0f} for the same cards" if mine else "")

    # ---------- actions
    def use_price(self, r, price=None):
        """Your price for a card, whatever you type; on eBay too when it is listed."""
        price = round(float(r["sugg"] if price is None else price), 2)
        if price <= 0 or abs(price - float(r.get("mine") or 0)) < 0.005:
            return
        if not r.get("outside"):
            self.m._set_price(r["key"], price)
        r["mine"] = price
        self._mine[r["key"]] = price          # the alert goes now, not when eBay's data next arrives
        self._phone_stale()
        label = (r.get("info") or {}).get("name") or r.get("title") or r["key"]
        if r["status"] in ("live", "unpublished"):
            if not self.m.push_price(label, r.get("item_id", ""), r.get("sku", ""), price):
                self.m.notice("Price saved in CardCrop; connect eBay to change the listing too.", "warn")
        else:
            self.m.notice(f"{label} set to ${price:,.2f}", "ok", secs=3)
        QTimer.singleShot(0, self.analyze)

    def add_video(self, r):
        if r.get("item_id"):
            self.m.reports_page.add_videos([{"key": f"live:{r['item_id']}",
                                             "live": {"id": r["item_id"], "title": r.get("title", ""),
                                                      "sku": r.get("sku", ""), "url": r.get("url", "")}}],
                                           ask=True)

    def research(self, r):
        import urllib.parse
        info = r.get("info") or {}
        q = " ".join(x for x in (info.get("name_en") or info.get("name", ""),
                                 f"{info.get('number', '')}/{info.get('set_total')}" if info.get("set_total")
                                 else str(info.get("number", ""))) if x)
        if identify.LANG_WORD.get(info.get("language", "en")):
            q += " " + identify.LANG_WORD[info["language"]]
        self.m.store_page._open("https://www.ebay.com/sch/i.html?" + urllib.parse.urlencode(
            {"_nkw": q, "LH_Sold": 1, "LH_Complete": 1, "_sacat": ebay.CATEGORY_ID}))


# names from the other parts, bound once every part has loaded
from ui_base import LIME, MONO, icon_button  # noqa: E402
from ui_store import MiniBars, mark_video  # noqa: E402
from ui_tasks import ImgTask, MarketScanTask  # noqa: E402
from ui_widgets import Island, PriceBox, ProgressCell, rounded_pixmap  # noqa: E402
