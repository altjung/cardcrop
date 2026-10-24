"""CardCrop Reports stage and Settings tracking page: condition reports and videos."""
from __future__ import annotations

import cv2
import ebay
import engine
import identify
import json
import numpy as np
import os
from PySide6.QtCore import QSize, QThreadPool, QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QPushButton, QSizePolicy, QVBoxLayout, QWidget
import ui_base as TH
import ui_motion as motion

class TrackingPage(QWidget):
    """Settings > Tracking: what has gone through CardCrop, by day, grade, language, era and price."""

    RANGES = (("7 days", 7), ("30 days", 30), ("All time", None))

    def __init__(self, main):
        super().__init__()
        from PySide6.QtWidgets import QScrollArea
        self.m = main
        self.days = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(sa)
        body = QWidget()
        sa.setWidget(body)
        g = QGridLayout(body)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(12)
        for c in range(3):
            g.setColumnStretch(c, 1)

        def tile(title):
            f = Island()
            v = QVBoxLayout(f)
            v.setContentsMargins(20, 16, 20, 18)
            v.setSpacing(10)
            v.addWidget(QLabel(title, objectName="small"))
            return f, v

        def big(obj="dot"):
            l = QLabel("0", objectName=obj)
            return l

        # today
        t0, v0 = tile("Today")
        self.n_today = big("dotbig")
        v0.addWidget(self.n_today)
        v0.addWidget(QLabel("cards exported", objectName="small"))
        sub = QGridLayout()
        sub.setHorizontalSpacing(16)
        self.subs = {}
        for i, (k, cap) in enumerate((("photos", "photos today"), ("week", "this week"), ("streak", "day streak"),
                                      ("best", "best day"))):
            n = big()
            n.setStyleSheet(f"font-size:{TH.BASE_PT + 10}pt;")
            sub.addWidget(n, (i // 2) * 2, i % 2)
            sub.addWidget(QLabel(cap, objectName="small"), (i // 2) * 2 + 1, i % 2)
            self.subs[k] = n
        v0.addLayout(sub)
        v0.addStretch(1)
        g.addWidget(t0, 0, 0)

        # every day
        t1, v1 = tile("Cards exported, every day")
        self.heat = Heatmap(26)
        v1.addWidget(self.heat, 1)
        leg = QHBoxLayout()
        self.all_lbl = QLabel("", objectName="small")
        leg.addWidget(self.all_lbl)
        leg.addStretch(1)
        leg.addWidget(QLabel("less", objectName="small"))
        for t in (0, .35, .6, .8, 1):
            sw = QLabel()
            sw.setFixedSize(12, 12)
            sw.setStyleSheet(f"background:{(_blend(TH.T['island'], LIME, t).name() if t else TH.T['pill'])};"
                             "border-radius:3px;")
            leg.addWidget(sw)
        leg.addWidget(QLabel("more", objectName="small"))
        v1.addLayout(leg)
        g.addWidget(t1, 0, 1, 1, 2)

        # conditions
        t2, v2 = tile("Condition")
        self.cond_bar = SegBar()
        v2.addWidget(self.cond_bar)
        self.cond_leg = QGridLayout()
        self.cond_leg.setHorizontalSpacing(14)
        v2.addLayout(self.cond_leg)
        v2.addStretch(1)
        g.addWidget(t2, 1, 0)

        # language and game
        t3, v3 = tile("Language and game")
        self.lang_bar = SegBar()
        v3.addWidget(self.lang_bar)
        self.lang_leg = QHBoxLayout()
        v3.addLayout(self.lang_leg)
        v3.addSpacing(6)
        self.game_bar = SegBar()
        v3.addWidget(self.game_bar)
        self.game_leg = QHBoxLayout()
        v3.addLayout(self.game_leg)
        v3.addStretch(1)
        g.addWidget(t3, 1, 1)

        # eBay
        t4, v4 = tile("On eBay")
        r4 = QHBoxLayout()
        self.ebay_n = {}
        for k, cap in (("live", "live"), ("unpublished", "unpublished"), ("draft", "drafts")):
            box = QVBoxLayout()
            n = big()
            box.addWidget(n)
            box.addWidget(QLabel(cap, objectName="small"))
            r4.addLayout(box, 1)
            self.ebay_n[k] = n
        v4.addLayout(r4)
        self.live_value = QLabel("", objectName="mono")
        v4.addWidget(self.live_value)
        v4.addStretch(1)
        g.addWidget(t4, 1, 2)

        # price ranges
        t5, v5 = tile("Price range")
        self.price_head = QLabel("", objectName="mono")
        v5.addWidget(self.price_head)
        self.bars = Bars()
        v5.addWidget(self.bars, 1)
        g.addWidget(t5, 2, 0, 1, 2)

        # eras
        t6, v6 = tile("Era")
        self.eras = HBars()
        v6.addWidget(self.eras)
        v6.addStretch(1)
        g.addWidget(t6, 2, 2)
        g.setRowStretch(3, 1)
        self._cache = None

    def _legend(self, lay, items, cols=None):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                sub = it.layout()
                while sub.count():
                    w = sub.takeAt(0).widget()
                    if w:
                        w.deleteLater()
        for i, (k, n) in enumerate(items):
            box = QHBoxLayout()
            box.setSpacing(6)
            box.addWidget(dot_label(CHART.get(k, LIME)))
            box.addWidget(QLabel(k, objectName="small"))
            num = QLabel(str(n), objectName="monotext")
            box.addWidget(num)
            box.addStretch(1)
            if isinstance(lay, QGridLayout):
                lay.addLayout(box, i // (cols or 2), i % (cols or 2))
            else:
                lay.addLayout(box)

    def set_days(self, days):
        self.days = days
        self.refresh(reuse=True)

    def refresh(self, reuse=False):
        import stats
        if not reuse or self._cache is None:
            m = self.m
            self._cache = stats.collect(m.out_dir, m._prices(), ebay.load_records(m.out_dir))
        S = stats.summarize(self._cache, self.days)
        motion.count_to(self.n_today, S['today_cards'])
        self.subs["photos"].setText(str(S["today_photos"]))
        self.subs["week"].setText(str(S["week_cards"]))
        self.subs["streak"].setText(str(S["streak"]))
        self.subs["best"].setText(str(S["best_day"]))
        self.heat.set_data(S["per_day_cards"])
        self.all_lbl.setText(f"{S['all_cards']} cards in all")
        conds = [(k, n) for k, n in S["conditions"] if n or k in stats.CONDITIONS]
        self.cond_bar.set_items(conds)
        self._legend(self.cond_leg, [(k, n) for k, n in conds if n or k != "Not set"], cols=2)
        langs = list(S["langs"].items())
        self.lang_bar.set_items(langs)
        self._legend(self.lang_leg, langs)
        games = list(S["games"].items())
        self.game_bar.set_items(games)
        self._legend(self.game_leg, [(k, n) for k, n in games if n] or games[:1])
        for k, lbl in self.ebay_n.items():
            motion.count_to(lbl, S['status'][k])
        self.live_value.setText(f"${S['live_value']:,.2f} live")
        self.price_head.setText(f"{S['cards']} cards · ${S['value']:,.2f} in all · average ${S['avg']:,.2f} · "
                                f"median ${S['median']:,.2f}")
        self.bars.set_items(S["buckets"])
        self.eras.set_items(S["eras"])


class ReportsPage(QWidget):
    """Condition reports, one card at a time or for a ticked set: this batch, every card in the save
    folder, and any card folders you add. A report is only made when you ask for it."""

    def __init__(self, main):
        super().__init__()
        self.m, self.cfg = main, main.cfg
        self.pending = None                   # (key, PIL image) made but not yet added
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        head = QHBoxLayout()
        head.setContentsMargins(8, 4, 4, 0)
        head.addWidget(QLabel("Reports", objectName="title2"))
        head.addSpacing(16)
        # Centering for grading first; the listing condition reports beside it
        mseg = QFrame(objectName="segbox")
        ml = QHBoxLayout(mseg)
        ml.setContentsMargins(4, 4, 4, 4)
        ml.setSpacing(4)
        self.mode_btns = {}
        for k, label in (("centering", "Centering"), ("condition", "Condition reports")):
            b = QPushButton(label, objectName="seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k_=k: self.set_mode(k_))
            ml.addWidget(b)
            self.mode_btns[k] = b
        head.addWidget(mseg)
        head.addSpacing(12)
        self.cond_bits = []
        seg = QFrame(objectName="segbox")
        sg = QHBoxLayout(seg)
        sg.setContentsMargins(4, 4, 4, 4)
        sg.setSpacing(4)
        self.src_btns = {}
        for k, label in (("cards", "My cards"), ("live", "Live on eBay")):
            b = QPushButton(label, objectName="seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k_=k: self.set_source(k_))
            sg.addWidget(b)
            self.src_btns[k] = b
        head.addWidget(seg)
        self.cond_bits.append(seg)
        head.addSpacing(12)
        self.source = "cards"
        self.src_btns["cards"].setChecked(True)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.busy = set()
        self.count = QLabel("", objectName="small")
        head.addWidget(self.count)
        head.addStretch(1)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Name or number")
        self.q.setMinimumWidth(110)
        self.q.setMaximumWidth(240)
        self.q.textChanged.connect(lambda _t: self.refresh(keep=True))
        head.addWidget(self.q)
        self.b_addf = QPushButton("Add folders…")
        self.b_addf.setToolTip("Card folders from anywhere: one folder per card, or a folder of card folders")
        self.b_addf.clicked.connect(self.add_folders)
        head.addWidget(self.b_addf)
        self.b_cal = QPushButton("Calibrate…")
        self.b_cal.clicked.connect(lambda: self.m.calibrate_reports())
        head.addWidget(self.b_cal)
        self.cond_bits += [self.count, self.q, self.b_addf, self.b_cal]
        v.addLayout(head)
        from PySide6.QtWidgets import QStackedWidget
        from ui_centering import CenteringView
        self.modes = QStackedWidget()
        self.centering = CenteringView(main)
        self.modes.addWidget(self.centering)
        cond = QWidget()
        cv_ = QVBoxLayout(cond)
        cv_.setContentsMargins(0, 0, 0, 0)
        cv_.setSpacing(12)
        self.modes.addWidget(cond)
        v.addWidget(self.modes, 1)
        v = cv_
        self.cal_note = QLabel("", objectName="small")
        self.cal_note.setWordWrap(True)
        self.cal_note.setContentsMargins(10, 0, 10, 0)
        v.addWidget(self.cal_note)
        self.show_calibration()

        body = QHBoxLayout()
        body.setSpacing(12)
        left = Island()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 14)
        lv.setSpacing(8)
        sel = QHBoxLayout()
        cap = QLabel("CARDS", objectName="mono")
        cap.setContentsMargins(6, 0, 0, 0)
        sel.addWidget(cap)
        sel.addStretch(1)
        for label, on in (("All", True), ("None", False)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, o=on: self._tick_all(o))
            sel.addWidget(b)
        lv.addLayout(sel)
        self.lst = QListWidget()
        self.lst.setIconSize(QSize(40, 56))
        self.lst.setSpacing(2)
        self.lst.currentRowChanged.connect(self._show)
        self.lst.itemChanged.connect(lambda _i: self._sync_bar())
        lv.addWidget(self.lst, 1)
        # two steps: make the reports and look them over, then add them to the listings
        self.b_make = QPushButton("1  Make reports")
        self.b_make.setMinimumHeight(44)
        self.b_make.setToolTip("A report for each ticked card, to look over first; nothing is added yet")
        self.b_make.clicked.connect(self.make_ticked)
        self.b_addr = QPushButton("2  Add to listings", objectName="primary")
        self.b_addr.setMinimumHeight(44)
        self.b_addr.setToolTip("Each ticked card's report added as its last listing photo (live listings change "
                               "on eBay straight away)")
        self.b_addr.clicked.connect(self.add_ticked)
        self.b_vids = QPushButton("Add videos")
        self.b_vids.setToolTip("A 360° video for each ticked live listing, added to the listing")
        self.b_vids.setMinimumHeight(44)
        self.b_vids.clicked.connect(lambda: self.add_videos(self._ticked(), ask=True))
        mk = QHBoxLayout()
        mk.addWidget(self.b_make, 1)
        mk.addWidget(self.b_addr, 1)
        lv.addLayout(mk)
        lv.addWidget(self.b_vids)
        body.addWidget(left, 2)

        right = Island()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(18, 18, 18, 18)
        rv.setSpacing(12)
        self.title = QLabel("")
        self.title.setStyleSheet(f"font-size:{TH.BASE_PT + 8}pt; font-weight:600;")
        rv.addWidget(self.title)
        self.state = QLabel("", objectName="small")
        rv.addWidget(self.state)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(200, 200)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        rv.addWidget(self.preview, 1)
        br = QHBoxLayout()
        self.b_one = QPushButton("Make report")
        self.b_one.clicked.connect(self.make_current)
        self.b_save = QPushButton("Add to listing photos", objectName="primary")
        self.b_save.setToolTip("Saved as the card's last photo (12), so it uploads with the listing")
        self.b_save.clicked.connect(self.save_current)
        self.b_del = QPushButton("Remove from listing")
        self.b_del.clicked.connect(self.remove_current)
        self.b_show = QPushButton("Show in Finder")
        self.b_show.clicked.connect(self.reveal_current)
        self.b_video = QPushButton("Add video")
        self.b_video.setToolTip("Render a 360° turn of this card (your video settings in Settings, Videos) and add it to "
                                "the live listing")
        self.b_video.clicked.connect(lambda: self.add_videos([self._current()]) if self._current() else None)
        self.b_open = QPushButton("Open listing")
        self.b_open.clicked.connect(lambda: self._current() and self.m.store_page._open(self._current()["live"]["url"]))
        for b in (self.b_one, self.b_video, self.b_open):
            br.addWidget(b)
        br.addStretch(1)
        br.addWidget(self.b_save)
        rv.addLayout(br)
        br2 = QHBoxLayout()                       # two rows, so the panel fits a laptop window
        for b in (self.b_del, self.b_show):
            br2.addWidget(b)
        br2.addStretch(1)
        rv.addLayout(br2)
        body.addWidget(right, 3)
        v.addLayout(body, 1)
        self._pm = None
        self.mode = None
        self.set_mode(str(self.cfg.value("reports_mode", "centering")))

    def set_mode(self, k):
        self.mode = k if k in self.mode_btns else "centering"
        self.cfg.setValue("reports_mode", self.mode)
        for key, b in self.mode_btns.items():
            b.setChecked(key == self.mode)
        for w in self.cond_bits:
            w.setVisible(self.mode == "condition")
        self.modes.setCurrentIndex(0 if self.mode == "centering" else 1)
        if self.mode == "centering":
            self.centering.refresh()

    # ---------- the list
    def _extra(self):
        try:
            return [f for f in json.loads(str(self.cfg.value("report_folders", "[]"))) if os.path.isdir(f)]
        except ValueError:
            return []

    def add_folders(self):
        d = QFileDialog.getExistingDirectory(self, "A card folder, or a folder of card folders", self.m.out_dir)
        if not d:
            return
        found = FolderListDialog.expand([d])
        extra = self._extra()
        for f in found:
            if f not in extra:
                extra.append(f)
        self.cfg.setValue("report_folders", json.dumps(extra[-500:]))
        self.refresh()

    def set_source(self, k):
        self.source = k
        for k_, b in self.src_btns.items():
            b.setChecked(k_ == k)
        self.b_addf.setVisible(k == "cards")
        self.pending = None
        self.refresh()

    def _live_done(self):
        try:
            return set(json.loads(str(self.cfg.value("live_reports", "[]"))))
        except ValueError:
            return set()

    def _entries(self):
        """(key, name, folder or None, report path) for every card that can have a report."""
        import stats
        if self.source == "live":
            done = self._live_done()
            return [(f"live:{a['id']}", a["title"], None, "added" if a["id"] in done else "")
                    for a in (self.m.store_page.data or {}).get("active", [])]
        out, seen = [], set()
        for n in self.m._card_names():
            folder = os.path.join(self.m.out_dir, engine.safe_name(n))
            out.append((n, n, None, self._report_path(folder)))
            seen.add(os.path.normpath(folder))
        try:
            dirs = sorted((e for e in os.scandir(self.m.out_dir) if e.is_dir()), key=lambda e: -e.stat().st_mtime)
        except OSError:
            dirs = []
        for e in dirs[:600]:
            if os.path.normpath(e.path) in seen:
                continue
            try:
                if any(stats.MAIN_PHOTO_RE.search(f) for f in os.listdir(e.path)):
                    out.append((e.path, e.name, e.path, self._report_path(e.path)))
                    seen.add(os.path.normpath(e.path))
            except OSError:
                pass
        for f in self._extra():
            if os.path.normpath(f) not in seen:
                out.append((f, os.path.basename(f), f, self._report_path(f)))
        return out

    @staticmethod
    def _report_path(folder):
        try:
            return next((os.path.join(folder, f) for f in os.listdir(folder) if "_12_grade" in f), "")
        except OSError:
            return ""

    def refresh(self, keep=False):
        if getattr(self, "mode", None) == "centering" and not keep:
            self.centering.refresh()
        cur = self.lst.currentItem().data(Qt.UserRole)["key"] if self.lst.currentItem() else None
        ticked = {self.lst.item(i).data(Qt.UserRole)["key"] for i in range(self.lst.count())
                  if self.lst.item(i).checkState() == Qt.Checked}
        q = self.q.text().strip().lower()
        self.lst.blockSignals(True)
        self.lst.clear()
        entries = [e for e in self._entries() if not q or q in e[1].lower()]
        live = {f"live:{a['id']}": a for a in (self.m.store_page.data or {}).get("active", [])}
        for key, name, folder, rep in entries:
            draft = os.path.exists(self._draft_path({"key": key, "name": name, "live": live.get(key)}))
            state = ("Working…" if key in self.busy else "Report added" if rep else
                     "Report made · not added yet" if draft else "No report yet")
            if key.startswith("live:"):
                try:
                    if key[5:] in set(json.loads(str(self.cfg.value("live_videos", "[]")) or "[]")):
                        state += " · video added"
                except ValueError:
                    pass
            it = QListWidgetItem(f"{name}\n{state}")
            it.setData(Qt.UserRole, {"key": key, "name": name, "folder": folder, "report": rep,
                                     "live": live.get(key)})
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if key in ticked else Qt.Unchecked)
            pm = self._thumb(name, folder) if self.source == "cards" else self.m.store_page._pix.get(
                (live.get(key) or {}).get("image", ""))
            if pm is not None:
                from PySide6.QtGui import QIcon
                it.setIcon(QIcon(pm))
            self.lst.addItem(it)
        self.lst.blockSignals(False)
        n_rep = sum(1 for e in entries if e[3])
        if self.source == "live" and not entries:
            self.count.setText("No live listings loaded: open Store and Refresh first")
        else:
            self.count.setText(f"{len(entries)} {'listings' if self.source == 'live' else 'cards'} · "
                               f"{n_rep} with a report")
        row = next((i for i in range(self.lst.count()) if self.lst.item(i).data(Qt.UserRole)["key"] == cur), 0)
        if self.lst.count():
            self.lst.setCurrentRow(row)
            self._show(row)
        else:
            self._show(-1)
        self._sync_bar()

    def _thumb(self, name, folder):
        j = next((x for x in self.m.jobs if x.card_name.strip() == name and x.side == "front"), None)
        if j is not None and folder is None:
            return self.m._thumb_pm(j)
        import stats
        f = folder or os.path.join(self.m.out_dir, engine.safe_name(name))
        try:
            p = next((os.path.join(f, x) for x in sorted(os.listdir(f)) if stats.MAIN_PHOTO_RE.search(x)
                      and "_front" in x), None)
        except OSError:
            p = None
        if not p:
            return None
        from PySide6.QtGui import QImageReader
        rd = QImageReader(p)
        rd.setAutoTransform(True)
        sz = rd.size()
        if sz.isValid() and sz.height():
            rd.setScaledSize(QSize(int(sz.width() * 112 / sz.height()), 112))
        img = rd.read()
        return QPixmap.fromImage(img) if not img.isNull() else None

    def _tick_all(self, on):
        for i in range(self.lst.count()):
            self.lst.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self._sync_bar()

    def _ticked(self):
        return [self.lst.item(i).data(Qt.UserRole) for i in range(self.lst.count())
                if self.lst.item(i).checkState() == Qt.Checked]

    def _draft_path(self, d):
        """Where a made report waits until it is added: for a live listing, its cached report."""
        if d.get("live"):
            return self._live_path(d)
        return os.path.join(identify._cache_dir(), "report_drafts", engine.safe_name(d["name"]) + ".jpg")

    def _sync_bar(self):
        t = self._ticked()
        n = len(t)
        ready = sum(1 for d in t if os.path.exists(self._draft_path(d)) and not (d.get("live") and d.get("report")))
        self.b_make.setText(f"1  Make {n} report{'s' if n != 1 else ''}" if n else "1  Make reports")
        self.b_addr.setText(f"2  Add {ready} to listing{'s' if ready != 1 else ''}" if ready else "2  Add to listings")
        self.b_addr.setEnabled(ready > 0)
        self.b_vids.setVisible(self.source == "live")
        self.b_vids.setEnabled(n > 0)
        self.b_vids.setText(f"Add {n} video{'s' if n != 1 else ''}" if n else "Add videos")
        self.b_make.setEnabled(n > 0)

    # ---------- the preview
    def _current(self):
        it = self.lst.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _show(self, row):
        d = self._current() if row >= 0 else None
        self.pending = None if not d or (self.pending and self.pending[0] != d["key"]) else self.pending
        if not d:
            self.title.setText("No cards yet")
            self.state.setText("Export cards, or add card folders, to make reports for them.")
            self._set_pm(None)
            for b in (self.b_one, self.b_save, self.b_del, self.b_show):
                b.setEnabled(False)
            return
        self.title.setText(d["name"])
        self.b_open.setVisible(bool(d.get("live")))
        self.b_video.setVisible(bool(d.get("live")))
        self.b_video.setEnabled(d["key"] not in self.busy)
        self.b_show.setVisible(not d.get("live"))
        self.b_del.setVisible(not d.get("live"))
        self.b_save.setText("Add to live listing" if d.get("live") else "Add to listing photos")
        if d.get("live"):
            lp = self._live_path(d)
            self.state.setText("Making the report from the listing's photos…" if d["key"] in self.busy else
                               ("Added to the live listing as its last photo" if d["report"] else
                                "Make report reads the front and back from this listing's photos"))
            self._set_pm(QPixmap(lp) if os.path.exists(lp) else None)
            self.b_one.setEnabled(d["key"] not in self.busy)
            self.b_one.setText("Make again" if os.path.exists(lp) else "Make report")
            self.b_save.setEnabled(bool(self.pending and self.pending[0] == d["key"]))
            self.b_open.setEnabled(True)
            return
        dp = self._draft_path(d)
        if os.path.exists(dp) and not (self.pending and self.pending[0] == d["key"]):
            import PIL.Image
            try:
                self.pending = (d["key"], PIL.Image.open(dp).convert("RGB"))
            except Exception:  # noqa: BLE001
                self.pending = None
        if self.pending and self.pending[0] == d["key"]:
            self.state.setText("Made, not added yet: Add to listing photos when it looks right")
            self._set_pm(QPixmap(dp) if os.path.exists(dp) else self._pm)
        elif d["report"]:
            self.state.setText("Added to the listing photos (photo 12)")
            self._set_pm(QPixmap(d["report"]))
        else:
            self.state.setText("No report yet: Make report to preview one")
            self._set_pm(None)
        self.b_one.setEnabled(True)
        self.b_one.setText("Make again" if (d["report"] or os.path.exists(dp)) else "Make report")
        self.b_save.setEnabled(bool(self.pending and self.pending[0] == d["key"]))
        self.b_del.setEnabled(bool(d["report"]))
        self.b_show.setEnabled(bool(d["report"]))

    def _set_pm(self, pm):
        self._pm = pm
        if pm is None or pm.isNull():
            self.preview.clear()
            self.preview.setText("")
            return
        side = max(200, min(self.preview.width(), self.preview.height()) - 8)
        self.preview.setPixmap(pm.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._pm is not None:
            self._set_pm(self._pm)

    def show_calibration(self):
        import calibrate
        m = calibrate.load_model()
        self.cal_note.setText(calibrate.summary(m) if m else
                              "Reports are calibrated on cards you have already graded before the first one is "
                              "made. Click Calibrate… to start.")
        self.b_cal.setText("Recalibrate…" if m else "Calibrate…")
        self.b_cal.setObjectName("" if m else "primary")
        self.b_cal.style().unpolish(self.b_cal)
        self.b_cal.style().polish(self.b_cal)

    def _live_path(self, d):
        return os.path.join(identify._cache_dir(), "live_reports", f"{d['live']['id']}.jpg")

    def make_current(self):
        d = self._current()
        if not d or not self.m.calibrated_or_ask():
            return
        if d.get("live"):
            c = self.m.ebay_client()
            if c is None or not c.signed_in():
                self.m.notice("Connect eBay in Settings > eBay to read your listings.", "warn")
                return
            self.busy.add(d["key"])
            t = LiveReportTask(c, self.m.db, self.m.prepare_live(d["live"]),
                               out_path=self._live_path(d))
            t.sig.done.connect(self._live_made)
            self.pool.start(t)
            self._show(self.lst.currentRow())
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            got = self.m._report_for(d["name"], d["folder"])
        except Exception as e:  # noqa: BLE001
            got = None
            self.m.notice(f"The report could not be made: {e}", "error")
        finally:
            QApplication.restoreOverrideCursor()
        if got is None:
            self.state.setText("No straightened photo of this card to measure: set its corners in Edit first.")
            return
        im = got[0]
        self.pending = (d["key"], im)
        dp = self._draft_path(d)
        os.makedirs(os.path.dirname(dp), exist_ok=True)
        cv2.imwrite(dp, cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 94])
        q = QImage(im.tobytes(), im.width, im.height, 3 * im.width, QImage.Format_RGB888).copy()
        self._set_pm(QPixmap.fromImage(q))
        self.state.setText("Preview: Add to listing photos to keep it")
        self.b_save.setEnabled(True)

    def _live_made(self, iid, im, path, err):
        key = f"live:{iid}"
        self.busy.discard(key)
        if err:
            self.m.notice(f"No report for that listing: {err}", "warn")
        elif im is not None:
            self.pending = (key, im)
        self.refresh(keep=True)
        cur = self._current()
        if cur and cur["key"] == key and self.pending and self.pending[0] == key:
            self.state.setText("Preview: Add to live listing to put it up as its last photo")
            self.b_save.setEnabled(True)

    def _live_added(self, iid, err):
        key = f"live:{iid}"
        self.busy.discard(key)
        if err:
            self.m.notice(f"The report was not added to the listing: {err}", "error")
        else:
            done = self._live_done() | {iid}
            self.cfg.setValue("live_reports", json.dumps(sorted(done)))
            self.m.notice("Report added to the live listing as its last photo", "ok", secs=5)
        self.refresh(keep=True)

    def save_current(self):
        d = self._current()
        if not d or not self.pending or self.pending[0] != d["key"]:
            return
        if d.get("live"):
            c = self.m.ebay_client()
            if c is None or not c.signed_in():
                return
            self.busy.add(d["key"])
            t = AddLivePhotoTask(c, dict(d["live"]), self._live_path(d))
            t.sig.done.connect(self._live_added)
            self.pool.start(t)
            self.pending = None
            self.refresh(keep=True)
            return
        path = self.m._save_report(d["name"], self.pending[1], d["folder"])
        self.pending = None
        try:
            os.remove(self._draft_path(d))
        except OSError:
            pass
        self.m.notice(f"Report added to {d['name']}'s listing photos", "ok", secs=4)
        self.refresh(keep=True)
        return path

    def remove_current(self):
        d = self._current()
        if d and d["report"]:
            try:
                os.remove(d["report"])
            except OSError:
                pass
            self.refresh(keep=True)

    def reveal_current(self):
        d = self._current()
        if d and d["report"]:
            subprocess_reveal(d["report"])

    def make_ticked(self):
        t = self._ticked()
        if not t or not self.m.calibrated_or_ask():
            return
        if self.source == "live":
            c = self.m.ebay_client()
            if c is None or not c.signed_in():
                self.m.notice("Connect eBay in Settings > eBay to read your listings.", "warn")
                return
            for d in t:
                self.busy.add(d["key"])
                tk = LiveReportTask(c, self.m.db, self.m.prepare_live(d["live"]), out_path=self._live_path(d))
                tk.sig.done.connect(self._live_made_batch)
                self.pool.start(tk)
            self.refresh(keep=True)
            return
        self.m.batch_reports([d["name"] for d in t], [d["folder"] for d in t],
                             save_to=[self._draft_path(d) for d in t])
        self.refresh(keep=True)

    def _live_made_batch(self, iid, im, path, err):
        self.busy.discard(f"live:{iid}")
        if err:
            self.m.notice(f"A listing was skipped: {err}", "warn")
        if not any(k.startswith("live:") for k in self.busy):
            self.m.notice("Reports made: look them over, then Add to listings puts them up", "ok", secs=5)
        self.refresh(keep=True)

    def add_ticked(self):
        """Step two: each ticked card's made report added as its last listing photo."""
        t = [d for d in self._ticked() if os.path.exists(self._draft_path(d)) and not (d.get("live") and d.get("report"))]
        if not t:
            return
        if self.source == "live":
            c = self.m.ebay_client()
            if c is None or not c.signed_in():
                self.m.notice("Connect eBay in Settings > eBay to change your listings.", "warn")
                return
            if QMessageBox.question(self, "Add condition reports", f"Add the report to each of the {len(t)} "
                                    "listings as its last photo, live on eBay?") != QMessageBox.Yes:
                return
            for d in t:
                self.busy.add(d["key"])
                tk = AddLivePhotoTask(c, dict(d["live"]), self._live_path(d))
                tk.sig.done.connect(self._live_added)
                self.pool.start(tk)
            self.refresh(keep=True)
            return
        import PIL.Image
        n = 0
        for d in t:
            dp = self._draft_path(d)
            try:
                self.m._save_report(d["name"], PIL.Image.open(dp).convert("RGB"), d["folder"])
                os.remove(dp)
                n += 1
            except Exception as e:  # noqa: BLE001
                self.m.notice(f"{d['name']}: the report was not added: {e}", "error")
        self.pending = None
        self.m.notice(f"{n} report{'s' if n != 1 else ''} added to the listing photos (photo 12); cards on eBay "
                      "pick them up when they upload again", "ok", secs=5)
        self.refresh(keep=True)

    # ---------- videos for live listings
    def has_video(self, iid):
        return iid in set(json.loads(str(self.cfg.value("live_videos", "[]")) or "[]"))

    def add_videos(self, items, ask=False, checked=False):
        items = [d for d in items if d and d.get("live")]
        if not items:
            return
        c = self.m.ebay_client()
        if c is None or not c.signed_in():
            self.m.notice("Connect eBay in Settings > eBay to add videos.", "warn")
            return
        if not checked:
            # first ask eBay which of these already carry a video, so none is replaced unawares
            def look(lst=items, cl=c):
                out = set()
                for d in lst:
                    it = d["live"]
                    try:
                        if cl.listing_videos(it["id"], it.get("sku", "")):
                            out.add(it["id"])
                    except Exception:  # noqa: BLE001
                        if self.has_video(it["id"]):
                            out.add(it["id"])
                return out
            self.m.notice("Checking for videos already on eBay…", "info", secs=2)
            t = CallTask(look)
            t.then(lambda have, err, lst=items, a=ask: self._videos_checked(lst, have or set(), a))
            self.pool.start(t)
            return
        msg = (f"Render a 360° video of “{items[0]['live'].get('title', '')[:60]}” from its photos and add it "
               "to the listing, live?" if len(items) == 1 else
               f"Render a 360° video for each of the {len(items)} ticked listings and add it to the listing, live?")
        if ask and QMessageBox.question(self, "Add video" if len(items) == 1 else "Add videos", msg) != QMessageBox.Yes:
            return
        if not getattr(self, "_vrunning", False):
            self._vreturn = self.m.stage          # come back here once the videos are made
        for d in items:
            d["live"] = self.m.prepare_live(d["live"])
        self.vqueue = getattr(self, "vqueue", []) + [dict(d["live"]) for d in items]
        for d in items:
            self.busy.add(d["key"])
        self.refresh(keep=True)
        if not getattr(self, "_vrunning", False):
            self._next_video()

    def _videos_checked(self, items, have, ask):
        dup = [d for d in items if d["live"]["id"] in have]
        if dup:
            names = "\n".join(f"• {d['live'].get('title', '')[:70]}" for d in dup[:8])
            more = f"\n…and {len(dup) - 8} more" if len(dup) > 8 else ""
            box = QMessageBox(self)
            box.setWindowTitle("Already has a video")
            box.setText(("This listing already has a video:" if len(dup) == 1 else
                         f"{len(dup)} of these listings already have a video:") + f"\n\n{names}{more}\n\n"
                        "A new video replaces the one there now.")
            b_rep = box.addButton("Replace", QMessageBox.AcceptRole)
            b_skip = box.addButton(("Skip it" if len(dup) == 1 else "Skip those") if len(dup) < len(items) else
                                   ("Keep it" if len(dup) == 1 else "Keep them"), QMessageBox.RejectRole)
            box.setDefaultButton(b_skip)
            box.exec()
            if box.clickedButton() is not b_rep:
                items = [d for d in items if d["live"]["id"] not in have]
                if not items:
                    return
            ask = False                            # that was the question
        self.add_videos(items, ask=ask, checked=True)

    def _next_video(self):
        if not self.vqueue:
            self._vrunning = False
            if self.m.stage == "view3d":
                self.m.go(getattr(self, "_vreturn", "") or "reports")
            return
        self._vrunning = True
        item = self.vqueue.pop(0)
        t = LiveSidesTask(self.m.ebay_client(), self.m.db, item)
        t.sig.done.connect(self._video_sides)
        self.pool.start(t)

    def _video_sides(self, item, front, back, err):
        if err:
            self._video_fail(item, err)
            return
        v3 = self.m.viewer3d
        self.m.go("view3d")
        v3.show_images(item.get("title", "")[:40], front, back)
        QTimer.singleShot(700, lambda: self._render_video(item))   # let the 3D view start before rendering

    def _render_video(self, item):
        v3 = self.m.viewer3d
        # kept with the card's exported photos when CardCrop has them, else in a Videos folder
        sku = item.get("sku") or ""
        folder = item.get("folder") if item.get("folder") and os.path.isdir(item["folder"]) else \
            os.path.join(self.m.out_dir, sku) if sku and os.path.isdir(os.path.join(self.m.out_dir, sku)) \
            else os.path.join(self.m.out_dir, "Videos")
        base = engine.safe_name(sku or item.get("title", "") or item["id"])[:60] or item["id"]
        path = os.path.join(folder, f"{base}_360.mp4")
        item["video_path"] = path
        self._vpaths = getattr(self, "_vpaths", {})
        self._vpaths[item["id"]] = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        prog = QProgressDialog(f"Rendering the 360° video for {item.get('title', '')[:40]}…", "Cancel", 0, 100, self.m)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)

        def step(i, n):
            prog.setMaximum(n)
            prog.setValue(i)
            QApplication.processEvents()
            return not prog.wasCanceled()

        try:
            ok = v3.render_saved(path, step)
        except Exception as e:  # noqa: BLE001
            prog.close()
            self._video_fail(item, f"the video could not be rendered: {e}")
            return
        prog.close()
        if not ok:
            self._video_fail(item, "cancelled")
            return
        up = path
        try:
            if os.path.getsize(path) > 145 * 1024 * 1024:
                import card3d
                self.m.notice("That video is over eBay's 150 MB limit; making a smaller copy to upload…", "info",
                              secs=4)
                QApplication.processEvents()
                up = card3d.shrink_for_ebay(path)
        except Exception as e:  # noqa: BLE001
            self._video_fail(item, f"the video is too big for eBay and could not be made smaller: {e}")
            return
        self.m.notice(f"Uploading the video to {item.get('title', '')[:40]}…", "info", secs=4)
        t = VideoUploadTask(self.m.ebay_client(), item, up)
        t.sig.done.connect(self._video_done)
        self.pool.start(t)
        self._next_video()                         # render the next while this one uploads

    def upload_existing_video(self, item, path):
        """A video you already have (made earlier, or anywhere else) attached to a live listing."""
        up = path
        try:
            if os.path.getsize(path) > 145 * 1024 * 1024:
                import card3d
                self.m.notice("That video is over eBay's 150 MB limit; making a smaller copy to upload…", "info",
                              secs=4)
                QApplication.processEvents()
                up = card3d.shrink_for_ebay(path)
        except Exception as e:  # noqa: BLE001
            self.m.notice(f"The video could not be prepared for eBay: {e}", "error")
            return
        self.busy.add(f"live:{item['id']}")
        self._vpaths = getattr(self, "_vpaths", {})
        self._vpaths[item["id"]] = path
        self.m.notice(f"Uploading {os.path.basename(path)} to {item.get('title', '')[:40]}…", "info", secs=4)
        t = VideoUploadTask(self.m.ebay_client(), item, up)
        t.sig.done.connect(self._video_done)
        self.pool.start(t)

    def _video_fail(self, item, err):
        self.busy.discard(f"live:{item['id']}")
        self.m.notice(f"No video for {item.get('title', '')[:40]}: {err}", "warn")
        self.refresh(keep=True)
        self._next_video()

    def _video_done(self, iid, status, err):
        self.busy.discard(f"live:{iid}")
        saved = getattr(self, "_vpaths", {}).get(iid, "")
        where = f" The MP4 is saved in {os.path.basename(os.path.dirname(saved))}." if saved else ""
        if err:
            self.m.notice(f"The video was not added: {err}.{where}", "error")
        else:
            vids = set(json.loads(str(self.cfg.value("live_videos", "[]")) or "[]")) | {iid}
            self.cfg.setValue("live_videos", json.dumps(sorted(vids)))
            word = {"LIVE": "is live on the listing", "PROCESSING": "is added; eBay is still processing it",
                    "PENDING_UPLOAD": "is added; eBay is still processing it"}.get(status, f"is added ({status})")
            self.m.notice(f"Video {word}. eBay shows listing videos in its iPhone and Android apps.{where}", "ok", secs=8)
        self.refresh(keep=True)

    def _live_batch_done(self, iid, im, path, err):
        key = f"live:{iid}"
        self.busy.discard(key)
        if err:
            self.m.notice(f"A listing was skipped: {err}", "warn")
        else:
            self.cfg.setValue("live_reports", json.dumps(sorted(self._live_done() | {iid})))
        if not self.busy:
            self.m.notice("Condition reports added to the ticked live listings", "ok", secs=5)
        self.refresh(keep=True)


# names from the other parts, bound once every part has loaded
from ui_base import LIME, subprocess_reveal  # noqa: E402
from ui_dialogs import FolderListDialog  # noqa: E402
from ui_tasks import AddLivePhotoTask, CallTask, LiveReportTask, LiveSidesTask, VideoUploadTask  # noqa: E402
from ui_widgets import Bars, CHART, HBars, Heatmap, Island, SegBar, _blend, dot_label  # noqa: E402
