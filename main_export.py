"""CardCrop window, part: Export presets and exporting.

A mixin of app.Main; every method runs with self as the main window."""
from __future__ import annotations

import engine
import json
from PySide6.QtCore import QThreadPool, QTimer, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
from ui_base import to_qimage
from ui_tasks import DetectTask, ExportAllTask


class ExportMixin:
    def _user_presets(self) -> dict:
        try:
            return json.loads(str(self.cfg.value("user_presets", "")) or "{}")
        except ValueError:
            return {}

    def _refresh_presets(self, select=None):
        c = self.preset_combo
        c.blockSignals(True)
        c.clear()
        c.addItem("Choose a preset…", None)
        for name in self.BUILTIN_PRESETS:
            c.addItem(name, f"builtin:{name}")
        users = self._user_presets()
        if users:
            c.insertSeparator(c.count())
            for name in sorted(users, key=str.lower):
                c.addItem(f"★ {name}", f"user:{name}")
        idx = c.findData(select) if select else 0
        c.setCurrentIndex(max(0, idx))
        c.blockSignals(False)
        self.b_pdel.setEnabled(bool(users))

    def _current_preset_values(self) -> dict:
        return {k: getattr(self.settings, k) for k in self.PRESET_KEYS}

    def save_preset(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Name for these settings:")
        name = name.strip()
        if not ok or not name:
            return
        users = self._user_presets()
        if name in users and QMessageBox.question(self, "Replace preset",
                                                  f"Replace your preset “{name}”?") != QMessageBox.Yes:
            return
        users[name] = self._current_preset_values()
        self.cfg.setValue("user_presets", json.dumps(users))
        self._refresh_presets(f"user:{name}")
        self.statusBar().showMessage(f"Saved preset “{name}”")

    def delete_preset(self):
        data = self.preset_combo.currentData()
        users = self._user_presets()
        if not data or not data.startswith("user:"):
            names = sorted(users, key=str.lower)
            if not names:
                return
            name, ok = QInputDialog.getItem(self, "Delete preset", "Which of your presets?", names, 0, False)
            if not ok:
                return
        else:
            name = data.split(":", 1)[1]
        if QMessageBox.question(self, "Delete preset", f"Delete your preset “{name}”?") != QMessageBox.Yes:
            return
        users.pop(name, None)
        self.cfg.setValue("user_presets", json.dumps(users))
        self._refresh_presets()

    def _preset_chosen(self, idx):
        data = self.preset_combo.itemData(idx)
        if not data:
            return
        kind, name = data.split(":", 1)
        vals = (self.BUILTIN_PRESETS if kind == "builtin" else self._user_presets()).get(name)
        if vals:
            self.apply_preset(vals)
            self.statusBar().showMessage(f"Preset “{name}” applied")

    def apply_preset(self, v: dict):
        """Set every control, which in turn updates the settings and the preview."""
        def setv(widget, value):
            widget.setValue(int(round(value)))
        if "corner_frac" in v: setv(self.s_corner, v["corner_frac"] * 100)  # noqa: E701
        if "margin_px" in v: setv(self.s_margin, v["margin_px"])  # noqa: E701
        for key, box in (("lock_ratio", self.c_ratio), ("flatten", self.c_flat), ("auto_portrait", self.c_port), ("hero", self.c_hero),
                         ("ig", self.c_ig), ("corners", self.c_corners)):
            if key in v:
                box.setChecked(bool(v[key]))
        if "corner_px" in v:
            self.c_up.setChecked(int(v["corner_px"]) > 0)
        for key, combo in (("out_format", self.fmt), ("hero_bg", self.hero_bg), ("hero_sides", self.hero_sides)):
            if key in v:
                i = combo.findData(v[key])
                if i >= 0:
                    combo.setCurrentIndex(i)
        for k in engine.EDIT_KEYS:
            if k in v:
                setv(self.edit_sliders[k], float(v[k]) * 100)
        lens_changed = False
        if "lens_profile" in v or "lens_raw_only" in v:
            want = (v.get("lens_profile", self.settings.lens_profile),
                    bool(v.get("lens_raw_only", self.settings.lens_raw_only)))
            i = next((n for n in range(self.lens_combo.count())
                      if tuple(self.lens_combo.itemData(n) or ()) == want), -1)
            if i < 0 and not want[0]:
                i = 0
            if i >= 0 and i != self.lens_combo.currentIndex():
                self.lens_combo.blockSignals(True); self.lens_combo.setCurrentIndex(i); self.lens_combo.blockSignals(False)
                lens_changed = True
        if "lens_k1" in v and int(round(v["lens_k1"] * 100)) != self.s_lens.value():
            self.s_lens.blockSignals(True); self.s_lens.setValue(int(round(v["lens_k1"] * 100))); self.s_lens.blockSignals(False)
            lens_changed = True
        self.on_settings()
        if lens_changed:
            self.on_lens()           # re-detects every photo, so only when the lens really changed

    def on_edit_slider(self, key, v):
        setattr(self.settings, key, v / 100)
        self.cfg.setValue(key, v / 100)
        self.preview_timer.start()
        if not hasattr(self, "_thumb_tone_timer"):
            self._thumb_tone_timer = QTimer(self, singleShot=True, interval=350)
            self._thumb_tone_timer.timeout.connect(self._retone_thumbs)
        self._thumb_tone_timer.start()

    def _retone_thumbs(self):
        """The filmstrip and the List show the photos with the edits you just made."""
        for j in self.jobs:
            self._label(j)
        lp = getattr(self, "list_page", None)
        if lp is not None and lp.isVisible() and hasattr(lp, "refresh"):
            lp.refresh()

    def reset_edits(self):
        for sl in self.edit_sliders.values():
            sl.setValue(0)

    def on_settings(self, *_):
        self.settings.corner_frac = self.s_corner.value() / 100
        self.settings.lock_ratio = self.c_ratio.isChecked()
        self.settings.margin_px = self.s_margin.value()
        self.settings.corner_px = 1600 if self.c_up.isChecked() else 0
        self.settings.auto_portrait = self.c_port.isChecked()
        self.settings.flatten = self.c_flat.isChecked()
        self.settings.hero = self.c_hero.isChecked()
        self.settings.hero_sides = self.hero_sides.currentData()
        for w_ in (self.hero_sides, self.hero_bg):
            w_.setEnabled(self.settings.hero)
        self.settings.ig = self.c_ig.isChecked()
        self.settings.corners = self.c_corners.isChecked()
        self.s_corner.setEnabled(self.settings.corners)
        for lbl in self.corner_lbls:          # no corners exported, none previewed
            lbl.setVisible(self.settings.corners)
        self.settings.hero_bg = self.hero_bg.currentData()
        self.settings.out_format = self.fmt.currentData()
        self._save_cfg()
        self.update_preview()
        self.measure_timer.start()

    def on_lens(self, *_):
        k1 = self.s_lens.value() / 100
        prof, raw_only = self.lens_combo.currentData() or ("", True)
        if (abs(k1 - self.settings.lens_k1) < 1e-9 and prof == self.settings.lens_profile
                and raw_only == self.settings.lens_raw_only):
            return
        self.settings.lens_k1 = k1
        self.settings.lens_profile, self.settings.lens_raw_only = prof, raw_only
        self._save_cfg()
        if hasattr(self, "lens_state"):
            self._show_lens_fit()
        # every quad lives in corrected coordinates, so they all go stale
        for j in self.jobs:
            if j is not self.cur:
                j.quad, j.edited = None, False
                j.release()
                self._label(j)
        if self.cur is not None:
            row = self.jobs.index(self.cur)
            self.cur.quad, self.cur.edited = None, False
            self.cur.release()
            self.cur = None
            self.select(row)
        for j in self.jobs:
            if j.quad is None and j is not self.cur:
                t = DetectTask(j, keep=False)
                t.sig.done.connect(self.on_detected)
                self.pool.start(t)

    def update_preview(self):
        j = self.cur
        if j is None or j.quad is None or self.proxy is None:
            return
        small, k = self.proxy
        card = engine.warp_card(small, j.quad * k, self.settings, j.rotate, margin_scale=k)
        card = engine.adjust(card, self.settings, scale=k)
        self.card_lbl.set_q(to_qimage(card))
        tl, tr, bl, br = engine.corner_crops(card, self.settings.corner_frac)
        for lbl, c in zip(self.corner_lbls, (tl, tr, bl, br)):
            lbl.set_q(to_qimage(c))
        w, h = engine.output_size(j.quad, self.settings)
        m = engine.margin_for(j.quad, self.settings)
        w, h = w + 2 * m, h + 2 * m
        if self.settings.auto_portrait and w > h and j.rotate % 360 == 0:
            w, h = h, w
        if j.rotate % 180:
            w, h = h, w
        native = int(min(w, h) * self.settings.corner_frac)
        up = self.settings.corner_px
        corners = f"{up} px square (from {native} px)" if up and native < up else f"{native} px square"
        corners = corners if self.settings.corners else "not exported"
        self.statusBar().showMessage(f"Output {w} × {h} px · corners {corners}")

    # --- export
    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.out_dir)
        if d:
            self.out_dir = d
            self._show_dir()
            self._save_cfg()

    def _show_dir(self):
        self.dir_lbl.setText(f"Saving to: {self.out_dir}")

    def _save_cfg(self):
        for k, v in (("lens_k1", self.settings.lens_k1), ("lens_profile", self.settings.lens_profile),
                     ("lens_raw_only", self.settings.lens_raw_only), ("lens_fit", self.settings.lens_fit), ("flatten", self.settings.flatten), ("corner_frac", self.settings.corner_frac),
                     ("lock_ratio", self.settings.lock_ratio), ("out_format", self.settings.out_format), ("margin_px", self.settings.margin_px), ("corner_px", self.settings.corner_px),
                     ("auto_portrait", self.settings.auto_portrait),
                     ("hero", self.settings.hero), ("hero_sides", self.settings.hero_sides), ("hero_bg", self.settings.hero_bg), ("grade", self.settings.grade),
                     ("ig", self.settings.ig), ("corners", self.settings.corners), ("detail", self.settings.detail), ("ig_crop", json.dumps(list(self.settings.ig_crop))),
                     ("out_dir", self.out_dir)):
            self.cfg.setValue(k, v)

    def _sync_export_label(self):
        n = len({i.row() for i in self.listw.selectedIndexes()})
        self.b_export.setText(f"Export {n} selected  ↵" if n > 1 else "Export and next  ↵")

    def export_current(self):
        if self.stack.currentWidget() is self.live:
            return                        # Enter does nothing while framing; Space shoots
        rows = sorted({i.row() for i in self.listw.selectedIndexes()})
        if len(rows) > 1:
            # several photos picked on the filmstrip: export just those, together, exported before or not
            todo = [self.jobs[r] for r in rows if 0 <= r < len(self.jobs) and not self.jobs[r].error]
            if todo:
                self.notice(f"Exporting the {len(todo)} selected photos…", "info", secs=3)
                self.export_all(todo)
            return
        j = self.cur
        if j is None:
            return
        self.settings.ig = self.c_ig.isChecked()      # the box is the truth, always
        # the Carousel only button is the truth: a photo marked in an earlier session, or exported while
        # it was on, used to stay carousel only after the button went off
        j.ig_only = self.c_carousel_mode.isChecked()
        if j.ig_only:
            if j.quad is None:
                self.statusBar().showMessage("Still finding the card; the slides will be written as soon as it is found")
            self._start_ig(j)               # carousel only: no eBay files, no tone edits
            self.next_name, self.next_side, self.next_info = "", "front", None
            j.ig_state = "writing"
            j.done = True
            self._label(j)
            nxt = next((i for i, x in enumerate(self.jobs) if not x.done), None)
            if nxt is not None:
                self.listw.setCurrentRow(nxt)
            return
        if j.quad is None:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            paths = j.export(self.out_dir)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            self.notice("Export failed.", "error", str(e))
            return
        QApplication.restoreOverrideCursor()
        self._label(j)
        self.last_quad = j.quad.copy()
        self.last_size = (self.editor.qimg.height(), self.editor.qimg.width()) if self.editor.qimg else None
        # a named front is usually followed by its back
        if j.card_name.strip() and j.side == "front":
            self.next_name, self.next_side = j.card_name, "back"
            self.next_info = j.card_info
        else:
            self.next_name, self.next_side, self.next_info = "", "front", None
        self._write_extras(j.card_name)
        if j.ig_core is not None and self.settings.ig:
            self._start_ig(j)
        else:
            j.ig_core = None
        label = f"{j.card_name.strip()} {j.side}" if j.card_name.strip() else j.stem
        self.statusBar().showMessage(f"Saved {len(paths)} files for {label}")
        self.chime("export")
        nm = j.card_name.strip()
        both = bool(nm) and {x.side for x in self.jobs if x.card_name.strip() == nm and x.done} >= {"front", "back"}
        left = any(not x.done and not x.error for x in self.jobs)
        if self.tether.is_connected and both and not (self.c_batch.isChecked() and left):
            self.show_live(True)         # both sides of this card are out: straight back to shooting the next
            return
        nxt = next((i for i, x in enumerate(self.jobs) if not x.done and i > self.jobs.index(j)), None)
        if nxt is None:
            nxt = next((i for i, x in enumerate(self.jobs) if not x.done), None)
        if nxt is not None:
            self.listw.setCurrentRow(nxt)
        elif self.tether.is_connected:
            self.show_live(True)         # queue finished: straight back to framing the next card

    def export_all(self, todo=None):
        todo = todo if todo is not None else [j for j in self.jobs if not j.done and not j.error]
        if not todo:
            return
        self.settings.ig = self.c_ig.isChecked()
        for j in todo:
            j.ig_only = self.c_carousel_mode.isChecked()
        if self.cur is not None:
            self.cur.release()
        self._exporting = True
        self.b_all.setEnabled(False)
        self.b_export.setEnabled(False)
        self._batch_names = {j.card_name.strip() for j in todo if j.card_name.strip()}
        t = ExportAllTask(todo, self.out_dir)
        t.sig.progress.connect(self._all_progress)
        t.sig.done.connect(self._exported_one)
        # exports run on a line of their own, so they never queue behind identifying, thumbnails or
        # eBay lookups (which share the general pool and can keep it busy for a while)
        if not hasattr(self, "export_pool"):
            self.export_pool = QThreadPool(self)
            self.export_pool.setMaxThreadCount(1)
        self.b_export.setText(f"Exporting 1 of {len(todo)}…")
        self.export_pool.start(t)

    def _exported_one(self, j, err):
        if j in self.jobs:
            self._label(j)

    def _all_progress(self, i, n, name):
        if i < n:
            self.b_export.setText(f"Exporting {i + 1} of {n}…")
            self.statusBar().showMessage(f"Exporting {name} ({i + 1} of {n})")
        if i >= n:
            self._sync_export_label()
            if self.tether.is_connected and not (self.c_batch.isChecked()
                                                 and any(not x.done and not x.error for x in self.jobs)):
                QTimer.singleShot(0, lambda: self.show_live(True))      # tethered: back to shooting
            self._exporting = False
            self.b_all.setEnabled(True)
            self.b_export.setEnabled(True)
            if n and any(j.done for j in self.jobs):
                self.chime("export")
            bad = sum(1 for j in self.jobs if j.error)
            # only the cards in this batch, one per turn of the event loop: every card of the session
            # at once, each with its hero and listing files, held the window frozen for minutes
            names = sorted(n for n in getattr(self, "_batch_names", set())
                           if any(x.done and x.card_name.strip() == n for x in self.jobs))
            self._batch_names = set()

            def extras_next(rest=names):
                if rest:
                    self._write_extras(rest[0])
                    QTimer.singleShot(0, lambda r=rest[1:]: extras_next(r))
            extras_next()
            self.statusBar().showMessage(f"Exported {n} photo(s)" + (f", {bad} failed" if bad else ""))
            self._relabel()
            S = self._summary()
            ready = S["cards"] - len(S["need"])
            msg = f"Exported {n} photo(s): {ready} card(s) ready to list"
            if S["need"]:
                msg += f", {len(S['need'])} need something first"
            if bad:
                msg += f", {bad} failed"
            det = "\n".join(f"{k}: needs {', '.join(v)}" for k, v in sorted(S["need"].items()))
            self.notice(msg, "warn" if (S["need"] or bad) else "ok", det,
                        ("Next ⚠", self.next_attention) if (S["need"] or bad) else None)
            ph = getattr(self, "phone", None)
            if ph is not None:
                ph.notify("export", "Export finished", msg, "/#review")
        else:
            self.statusBar().showMessage(f"Exporting {i + 1} of {n}: {name}")
