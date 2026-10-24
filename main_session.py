"""CardCrop window, part: The open batch kept on disk, so a crash or a quit loses nothing.

A mixin of app.Main; every method runs with self as the main window."""
from __future__ import annotations

import engine
import identify
import json
import numpy as np
import os
import ui_base as TH
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFileDialog, QLabel, QListWidgetItem
from engine import Job
from ui_base import LIME, _icon_color, make_icon, set_theme
from ui_tasks import DetectTask, ThumbOnlyTask
from ui_widgets import CommandPalette, _logo_pixmap

SESSION_FIELDS = ("rotate", "edited", "done", "card_name", "side", "condition", "card_info", "ig_only",
                  "confidence")

SESSION_EXTRA = ("det", "auto_name", "from_camera", "id_reading", "id_edition", "id_tried", "ig_state", "id_unsure")

def session_path() -> str:
    return os.path.join(identify._cache_dir(), "session.json")


class SessionMixin:
    # ---------- the batch, kept on disk so a crash or a quit loses nothing
    def _session_state(self) -> str:
        jobs = []
        for j in self.jobs:
            d = {"path": j.path, "quad": j.quad.tolist() if j.quad is not None else None,
                 "ig_crop": list(j.ig_crop) if j.ig_crop else None}
            for k in SESSION_FIELDS:
                d[k] = getattr(j, k)
            d["confidence"] = float(j.confidence or 0)
            d["rotate"] = int(j.rotate or 0)
            for k in SESSION_EXTRA:
                v = getattr(j, k, None)
                if v not in (None, "", False):
                    d[k] = v
            if getattr(j, "id_bg", False):
                d.pop("id_tried", None)          # read again after a restart: the reading was cut short
            # pair and batch shooting: which front a back belongs to, and which shots start a card
            pf = getattr(j, "_pair_of", None)
            if pf in self.jobs:
                d["pair_of"] = self.jobs.index(pf)
            if getattr(j, "_new_card", False):
                d["new_card"] = True
            jobs.append(d)
        cur = self.jobs.index(self.cur) if self.cur in self.jobs else -1
        pend = getattr(self, "_pair_front", None)
        return json.dumps({"version": 2, "jobs": jobs, "current": cur, "titles": self.title_overrides,
                           "pair_front": self.jobs.index(pend) if pend in self.jobs else -1,
                           "level": getattr(self, "_level_rep", None) or None},
                          default=str)

    def save_session(self):
        try:
            state = self._session_state()
        except Exception:  # noqa: BLE001
            return
        if state == getattr(self, "_session_last", None):
            return
        p = session_path()
        tmp = p + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(state)
            os.replace(tmp, p)                  # all or nothing: a crash mid-write keeps the last copy
            self._session_last = state
        except OSError:
            pass

    def restore_session(self):
        """Puts back the batch you had open: every photo with its edges, rotation, name, side,
        condition and identification, and the edited titles. Photos moved or deleted since are skipped."""
        try:
            with open(session_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        every = data.get("jobs", [])
        rows = [d for d in every if os.path.exists(d.get("path", ""))]
        missing = len(every) - len(rows)
        if not rows:
            return
        made = {}                               # saved position -> restored photo, for the pair links
        for i, d in enumerate(every):
            if d not in rows:
                continue
            j = Job(d["path"], settings=self.settings)
            # corners an older detector found, never touched by hand and not exported yet, are found again
            stale = not d.get("edited") and not d.get("done") and d.get("det") != engine.DETECT_VERSION
            if d.get("quad") is not None and not stale:
                j.quad = np.array(d["quad"], np.float32)
            j.ig_crop = tuple(d["ig_crop"]) if d.get("ig_crop") else None
            for k in SESSION_FIELDS + SESSION_EXTRA:
                if k in d:
                    setattr(j, k, d[k])
            if not self.c_carousel_mode.isChecked():
                j.ig_only = False           # carousel only belongs to the mode, which is off now
            if d.get("new_card"):
                j._new_card = True
            made[i] = j
            self.jobs.append(j)
            self.listw.addItem(QListWidgetItem())
            self._label(j)
            t = ThumbOnlyTask(j) if j.quad is not None else DetectTask(j, keep=False)
            t.sig.done.connect(self.on_detected)
            self.pool.start(t)
        for i, d in enumerate(every):
            if i in made and d.get("pair_of") in made:
                made[i]._pair_of = made[d["pair_of"]]
        pend = made.get(data.get("pair_front", -1))
        if pend is not None and not any(getattr(x, "_pair_of", None) is pend for x in self.jobs):
            self._pair_front = pend               # a front was shot and its back is still to come
        self.title_overrides.update(data.get("titles") or {})
        cur = data.get("current", 0)
        self.listw.setCurrentRow(min(max(0, cur), len(self.jobs) - 1))
        self._session_last = self._session_state()
        self.notice(f"Picked up where you left off: {len(rows)} photo{'s' if len(rows) != 1 else ''}"
                    + (f" ({missing} no longer on disk)" if missing else "") + ".", "ok", secs=6)
        self._update_summary()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "rail_pill", None) is not None:
            QTimer.singleShot(0, self.rail_pill.follow)
        if hasattr(self, "banner"):
            self._place_floats()
        if getattr(self, "rail_sa", None) is not None:      # a short window: icons only in the rail
            compact = self.rail_sa.height() < self._rail_full
            if compact != self._rail_compact:
                self._rail_compact = compact
                for b in self._rail_btns:
                    b.setToolButtonStyle(Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextUnderIcon)
                    b.setFixedSize(64, 44 if compact else 58)
                QTimer.singleShot(0, self.rail_pill.follow)

    def _status(self, msg):
        if not msg:
            return
        self.status_lbl.setText(msg)
        self.hud_status.show()
        self.canvas_isl._place()
        self.status_timer.start()

    def settings_tab(self, i):
        self.set_stack.setCurrentIndex(i)
        for k, b in self.set_tabs.items():
            b.setChecked(k == i)
        for b in self.range_btns.values():
            b.setVisible(i == 0)
        if i == 0 and self.stage == "settings":
            self.tracking.refresh()
        self._sync_settings()

    def open_settings(self, title):
        self.go("settings")
        for i in range(self.set_stack.count()):
            if self.set_tabs[i].text() == title:
                self.settings_tab(i)

    def _set_range(self, days):
        for d, b in self.range_btns.items():
            b.setChecked(d == days)
        self.tracking.set_days(days) if self.tracking._cache is not None else setattr(self.tracking, "days", days)

    def _sync_settings(self):
        r = self.ebay_route()
        for k, b in self.route_btns.items():
            b.setChecked(k == r)
        for k, b in self.theme_btns.items():
            b.setChecked(k == TH.THEME)
        self.size_lbl.setText(f"{TH.BASE_PT} pt")
        tpl = str(self.cfg.value("ebay_template", ""))
        self.tpl_lbl.setText(tpl if tpl else "Not chosen yet: Seller Hub > Reports > Uploads > Get template > "
                             "Listings > Create new drafts")

    def pick_template(self):
        tpl, _ = QFileDialog.getOpenFileName(self, "eBay Create new drafts template",
                                             os.path.expanduser("~/Downloads"), "CSV files (*.csv)")
        if tpl:
            self.cfg.setValue("ebay_template", tpl)
            self._sync_settings()

    def _section_index(self):
        return self.rcol.currentIndex()

    def _open_section(self, k):
        self.rcol.setCurrentIndex(k)

    def _pick_side(self, side):
        if self.cur is None:
            self._show_side()
            return
        if self.cur.side != side:
            self.toggle_side()
        self._show_side()

    def toggle_theme(self):
        set_theme("dark" if TH.THEME == "light" else "light")
        self.cfg.setValue("theme", TH.THEME)
        self._skin()
        for j in self.jobs:
            self._label(j)
        self._show_side()
        if self.stage == "list":
            self.list_page.refresh()
        if self.stage == "settings":
            self._sync_settings()
            self.tracking.refresh(reuse=True)

    def _auto_icon(self):
        """On: the ink circle with the icon in the paper colour; off: a plain pill.
        Set here rather than through the theme list, which would paint it the text colour."""
        self.c_auto.setIcon(make_icon("upload", 40, _icon_color("ink" if self.c_auto.isChecked() else "text")))

    def _skin(self):
        """Pieces drawn with theme colours rather than styled."""
        self._auto_icon()
        self.theme_btn.setIcon(make_icon("sun" if TH.THEME == "dark" else "moon", 40, _icon_color("text")))
        ico = make_icon("shutter", 40, TH.T["ink_text"])
        self.shutter_btn.setIcon(ico)
        from PySide6.QtCore import QSize
        self.shutter_btn.setIconSize(QSize(40, 40))
        self.shutter_btn.setStyleSheet(f"QPushButton {{ background:{TH.T['ink']}; border:4px solid {LIME}; "
                                       f"border-radius:48px; }} QPushButton:hover {{ background:{TH.T['ink']}; }}")
        logo = self.findChild(QLabel, "logo")
        if logo is not None:
            logo.setPixmap(_logo_pixmap(34))
        self.listw.viewport().update()

    def open_palette(self):
        acts = [
            ("Add photos…", "", self.add_dialog),
            ("Fronts and backs…", "", self.sort_sides),
            ("Identify the photo open, or the ones selected", "Shift+I", self.identify_now),
            ("Add exported folders to list on eBay…", "", lambda: self.list_folders([])),
            ("Carousels from edited photos…", "", self.add_carousel_photos),
            ("Connect or disconnect the camera", "K", self.toggle_camera),
            ("Go to Shoot", "L", lambda: self.go("shoot")),
            ("Go to Edit", "E", lambda: self.go("edit")),
            ("Go to List", "Cmd+L", lambda: self.go("list")),
            ("Go to Store: sales and listings", "Cmd+Y", lambda: self.go("store")),
            ("Go to Market: price movers and alerts", "Shift+Cmd+M", lambda: self.go("market")),
            ("Scan market prices now", "", lambda: (self.go("market"), self.market_page.scan())),
            ("Go to 3D", "D", lambda: self.go("view3d")),
            ("Identify this card", "I", self.open_identify),
            ("Close-up framing for Instagram", "P", self.open_ig),
            ("See this card in 3D, export a 360° video", "D", self.open_3d),
            ("Condition report for this card", "Ctrl+R", lambda: self.condition_report()),
            ("Go to Reports: condition reports for chosen cards", "", lambda: self.go("reports")),
            ("Upload this card to eBay (unpublished)", "", self.ebay_upload),
            ("Make an eBay draft for this card", "", self.ebay_draft_current),
            ("Review and publish on eBay…", "", self.ebay_review),
            ("Drafts file for every exported card…", "", self.fill_drafts),
            ("eBay account…", "", self.ebay_account),
            ("Listing route: upload unpublished (API)", "", lambda: self.set_ebay_route("direct")),
            ("Listing route: Seller Hub drafts", "", lambda: self.set_ebay_route("drafts")),
            ("Export all remaining", "", self.export_all),
            ("Auto-upload finished cards on or off", "", lambda: self.c_auto.toggle()),
            ("Next photo that needs you", "", self.next_attention),
            ("Copy the title", "", self.copy_title),
            ("Copy the description", "", self.copy_desc),
            ("Copy the centering", "", self.copy_centering),
            ("Crop settings", "", lambda: (self.go("edit"), self._open_section(1))),
            ("Tone and presets", "", lambda: (self.go("edit"), self._open_section(2))),
            ("Lens profile", "", lambda: self.go("shoot")),
            ("Shipments: tracking numbers, USPS timeline", "", lambda: self.go("ship")),
            ("Measure lens distortion from the session", "", lambda: self.measure_lens()),
            ("Output, Instagram and save folder", "", lambda: self.open_settings("Output")),
            ("Tracking: cards per day, grades, eras, prices", "", lambda: self.open_settings("Tracking")),
            ("eBay settings", "", lambda: self.open_settings("eBay")),
            ("Choose the save folder…", "", self.pick_dir),
            ("Show or hide the filmstrip", "Cmd+\\", self.toggle_left),
            ("Light or dark theme", "", self.toggle_theme),
            ("Larger text", "Cmd+=", lambda: self.ui_size(1)),
            ("Smaller text", "Cmd+-", lambda: self.ui_size(-1)),
            ("Default text size", "Cmd+0", lambda: self.ui_size(0)),
            ("Clear the photo list", "", self.clear_jobs),
        ]
        d = CommandPalette(self, acts)
        g = self.geometry()
        d.move(g.x() + (g.width() - d.width()) // 2, g.y() + 120)
        d.q.setFocus()
        d.exec()
