"""CardCrop window, part: Shooting: the tethered camera, live view framing aids, live analysis and saved camera settings.

A mixin of app.Main; every method runs with self as the main window."""
from __future__ import annotations

import engine
import json
import numpy as np
import os
import tether
import time
import ui_base as TH
from PySide6.QtCore import QItemSelectionModel, QThreadPool, QTimer, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QColorDialog, QInputDialog
from ui_live import GRIDS, analyze_live, qimage_to_bgr, thumb_change
from ui_tasks import CallTask


class ShootMixin:
    # --- camera
    def set_next_side(self, side: str):
        """Turn the next shot into a front or a back by hand. A back belongs to the latest front that
        has none yet; a front starts a new card."""
        batch = self.c_batch.isChecked() and not self.c_carousel_mode.isChecked()
        pair = (self.c_pair.isChecked() or batch) and not self.c_carousel_mode.isChecked()
        if side == "front":
            if pair:
                self._pair_front = None
            else:
                self.next_name, self.next_side, self.next_info = "", "front", None
            self._update_next()
            return
        # only fronts still being worked on: an exported card's front never takes a new back
        fronts = [x for x in self.jobs if not x.ig_only and not x.done
                  and (x.side == "front" or getattr(x, "_new_card", False))]

        def has_back(f):
            nm = f.card_name.strip()
            return any(getattr(x, "_pair_of", None) is f or (nm and x is not f and x.card_name.strip() == nm
                                                             and x.side == "back") for x in self.jobs)
        open_ = [f for f in fronts if not has_back(f)]
        f = open_[-1] if open_ else None
        if f is None:
            self.notice("Every front still to export has its back already: shoot a front first, or fix the pairs in "
                        "Fronts and backs." if fronts else "No front to pair a back with yet: shoot the front first.",
                        "info", secs=5)
            self._update_next()
            return
        if pair:
            self._pair_front = f
        else:
            named = [x for x in fronts if x.card_name.strip() and not has_back(x)] or \
                [x for x in fronts if x.card_name.strip()]
            if not named:
                self.notice("Name or identify the front first: its back takes the name from it.", "info", secs=5)
                self._update_next()
                return
            f = named[-1]
            self.next_name, self.next_side, self.next_info = f.card_name.strip(), "back", f.card_info
        self._update_next()

    def toggle_camera(self):
        if self.tether.is_connected:
            self.show_live(False)
            self.tether.disconnect_camera()
            return
        if not self.tether.available():
            self.notice("The camera bridge is not installed yet.", "warn",
                        "Build it once, in Terminal:\n\ncd ~/Documents/cardcrop\n./tether/build_tether.sh\n\n"
                        "It uses Sony's Camera Remote SDK from your Downloads folder.")
            return
        self.cam_btn.setText("Connecting…")
        self.cam_btn.setEnabled(False)
        self.tether.connect_camera()
        QTimer.singleShot(20000, self._cam_connect_timeout)

    def _cam_connect_timeout(self):
        if not self.tether.is_connected:
            self.cam_btn.setEnabled(True)
            self.cam_btn.setText("Connect camera")

    def _cam_status(self, msg):
        self.statusBar().showMessage(msg)
        if not self.tether.is_connected and ("No camera" in msg or "Could not" in msg or "did not" in msg):
            self.cam_btn.setEnabled(True)
            self.cam_btn.setText("Connect camera")

    def _cam_connected(self, model):
        name = {"ILCE-6700": "Sony a6700"}.get(model, model)
        self.cam_lbl.setText(name)
        self.cam_btn.setEnabled(True)
        self.cam_btn.setText("Disconnect camera   K")
        self.cam_state.setText("Connected")
        self.connect_card.hide()
        self.statusBar().showMessage(f"Connected to {name}. Shots go to {tether.captures_dir()}")
        self.show_live(True)

    def _cam_disconnected(self):
        self.cam_btn.setEnabled(True)
        self.cam_btn.setText("Connect camera   K")
        self.cam_state.setText("Not connected")
        self.cam_lbl.setText("Camera")
        if self.stage == "shoot":
            self.connect_card.show()
            self.live_isl._place()
            self.live.message = "Live view is off"
            self.live.update()
        self.statusBar().showMessage("Camera disconnected")

    def _cam_props(self, changed):
        for key, prop in changed.items():
            if key == "battery":
                self.cam_lbl.setText(f"{self.cam_lbl.text().split('  ·')[0]}  ·  {tether.fmt('battery', prop['cur'])}")
                continue
            if key == "mode":
                mode = tether.fmt("mode", prop["cur"])
                base = self.cam_lbl.text().split("  ·")
                self.cam_lbl.setText("  ·  ".join([base[0], f"Mode {mode}"] + [b.strip() for b in base[1:]
                                                                               if "Mode" not in b]))
                continue
            combo = self.cam_combos.get(key)
            if combo is None:
                continue
            vals = tether.options(prop)
            if prop["cur"] not in vals:
                vals = [prop["cur"]] + vals
            combo.blockSignals(True)
            combo.clear()
            for v in vals:
                combo.addItem(tether.fmt(key, v, prop.get("type", 0)), v)
            combo.setCurrentIndex(max(0, vals.index(prop["cur"])))
            combo.setEnabled(bool(prop.get("writable")) and len(vals) > 1)
            combo.blockSignals(False)
            # the list opens wide enough for its longest value, whatever the tile's width
            v = combo.view()
            v.setTextElideMode(Qt.ElideNone)
            v.ensurePolished()
            widest = max((max(v.fontMetrics().horizontalAdvance(combo.itemText(i)),
                              combo.fontMetrics().horizontalAdvance(combo.itemText(i)))
                          for i in range(combo.count())), default=0)
            v.setMinimumWidth(int(widest * 1.15) + 72)
        # Kelvin only means something while white balance is set to Kelvin
        wb, kv = self.tether.state.get("wb"), self.tether.state.get("kelvin")
        if kv is not None:
            self.cam_combos["kelvin"].setEnabled(bool(kv.get("writable")) and wb is not None
                                                 and wb["cur"] == 0x0100)

    def cam_set(self, key, idx):
        v = self.cam_combos[key].itemData(idx)
        if v is not None:
            self.tether.set(key, v)

    def _default_guide(self):
        """An upright card filling 70% of the frame height, sensor-normalised."""
        img = self.live.img
        W, H = (img.width(), img.height()) if img is not None else (1024, 680)
        return engine.card_outline(W, H) / np.array([W, H], np.float32)

    def _guide_edited(self, g):
        self.cfg.setValue("lv_guide", json.dumps(np.asarray(g).tolist()))

    def set_show_guide(self, on):
        self.live.show_guide = on
        self.cfg.setValue("lv_show_guide", on)
        self.live.update()

    def toggle_guide(self):
        if self.stack.currentWidget() is self.live:
            self.c_guide.setChecked(not self.c_guide.isChecked())

    def reset_guide(self):
        self.live.guide = self._default_guide()
        self._guide_edited(self.live.guide)
        self.live.update()

    def _job_guide(self, j):
        """A job's detected card corners as a live overlay (sensor-normalised)."""
        if j is None or j.quad is None:
            return None
        try:
            h, w = j.source().shape[:2]
        except Exception:  # noqa: BLE001
            return None
        return np.asarray(j.quad, np.float32) / np.array([w, h], np.float32)

    def match_last_shot(self):
        if self.stack.currentWidget() is not self.live:
            return
        shots = [j for j in self.jobs if getattr(j, "from_camera", False) and j.quad is not None]
        g = self._job_guide(shots[-1] if shots else self.cur)
        if g is None:
            self.statusBar().showMessage("No shot to match yet")
            return
        self.live.guide = g
        self._guide_edited(g)
        self.live.update()
        self.statusBar().showMessage("Overlay moved to where the last card was detected")

    def show_live(self, on):
        if on:
            # back to shooting: the next photo is a new card, so nothing carries over from the last one
            self.listw.clearSelection()
            if self.c_pair.isChecked():
                self.next_name, self.next_side, self.next_info = "", "front", None
        self.go("shoot" if on else "edit")

    # --- live view framing aids
    def set_grid(self, name):
        if not hasattr(self, "live"):
            return
        self.live.grid = name
        self.cfg.setValue("lv_grid", name)
        self.live.update()

    def cycle_grid(self):
        if self.stack.currentWidget() is not self.live:
            return
        i = (GRIDS.index(self.live.grid) + 1) % len(GRIDS) if self.live.grid in GRIDS else 0
        self.grid_combo.setCurrentText(GRIDS[i])
        self.statusBar().showMessage(f"Grid: {GRIDS[i]}")

    def set_grid_width(self, name):
        if not hasattr(self, "live"):
            return
        self.live.grid_width = name
        self.cfg.setValue("lv_grid_width", name)
        self.live.update()

    def _swatch(self):
        c = self.live.grid_color
        self.color_btn.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},{c.alpha()});"
                                     f" border:1px solid {TH.T['line']}; border-radius:10px;")

    def pick_grid_color(self):
        c = QColorDialog.getColor(self.live.grid_color, self, "Grid colour", QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self.live.grid_color = c
            self.cfg.setValue("lv_grid_color", c.name(QColor.HexArgb))
            self._swatch()
            self.live.update()

    def rotate_live(self, step):
        self.live.rotate_view(step)
        self.cfg.setValue("lv_rot", self.live.rot)
        self.zoom_btn.setText("1x")
        self.statusBar().showMessage(f"View rotated {self.live.rot}°; new shots open turned the same way")

    def cycle_zoom(self):
        nxt = {1.0: 2.0, 2.0: 4.0}.get(round(self.live.zoom), 1.0)
        self.live.set_zoom(nxt)
        self.zoom_btn.setText(f"{nxt:g}x")

    def toggle_cam_settings(self):
        vis = not self.cam_grid.isVisible()
        self.cam_grid.setVisible(vis)
        self.cam_set_btn.setChecked(vis)
        self.cfg.setValue("cam_settings", vis)

    def _cam_frame(self, img):
        if self.stack.currentWidget() is self.live:
            self.live.set_frame(img)
            self._live_tick(img)

    # ---------- live analysis: edges, centering, peaking, auto-capture
    def _live_flags(self):
        if not hasattr(self, "live"):
            return
        self.live.show_edges = self.c_edges.isChecked()
        self.live.loupe = self.c_loupe.isChecked()
        if not self.c_peak.isChecked():
            self.live.peak = None
        if not (self.c_edges.isChecked() or self.c_autoshot.isChecked() or self.c_loupe.isChecked()):
            self.live.live_quad = None
        self._auto.update(state="wait", since=0.0, prev=None, shot_thumb=None, gone=0)
        self.live.auto_text = ("Auto-capture: place a card" if self.c_autoshot.isChecked() else "")
        self.live.auto_frac = 0.0
        self.live.update()

    def _live_tick(self, img):
        card = self.c_edges.isChecked() or self.c_autoshot.isChecked() or self.c_loupe.isChecked()
        peak = self.c_peak.isChecked()
        if not (card or peak) or self._lv_busy or time.time() - self._lv_last < 0.15:
            return
        self._lv_busy, self._lv_last = True, time.time()
        try:
            frame = qimage_to_bgr(img)
        except Exception:  # noqa: BLE001
            self._lv_busy = False
            return
        t = CallTask(analyze_live, frame, card, peak)
        t.then(self._live_result)
        QThreadPool.globalInstance().start(t)

    def _live_result(self, res, err):
        self._lv_busy = False
        if err or not res or self.stage != "shoot":
            return
        w, h = res["size"]
        lv = self.live
        if res["quad"] is not None:
            lv.live_quad = np.asarray(res["quad"], np.float32) / np.array([w, h], np.float32)
        else:
            lv.live_quad = None
        lv.live_conf, lv.live_cent = res["conf"], res["cent"]
        if res["peak"] is not None:
            a = np.ascontiguousarray(res["peak"])
            lv.peak = QImage(a.data, a.shape[1], a.shape[0], a.shape[1] * 4, QImage.Format_RGBA8888).copy()
        if self.c_autoshot.isChecked():
            self._auto_step(res)
        lv.update()

    def _auto_step(self, res):
        """Shoots a card once it has sat still with its edges locked, then waits for the next card:
        the old one taken away, or a different one in its place."""
        a, lv, now = self._auto, self.live, time.time()
        if not self.tether.is_connected:
            lv.auto_text, lv.auto_frac = "Auto-capture: connect the camera", 0.0
            return
        q = lv.live_quad
        sure = q is not None and res["conf"] >= 0.8
        still = False
        if sure and a["prev"] is not None:
            still = float(np.max(np.linalg.norm(q - a["prev"], axis=1))) < 0.006
        a["prev"] = q if sure else None
        if a["state"] == "shot":
            if not sure:
                a["gone"] += 1
                if a["gone"] >= 2:                     # taken away: ready for the next one
                    a.update(state="wait", shot_thumb=None, gone=0)
                    lv.auto_text, lv.auto_frac = "Auto-capture: place the next card", 0.0
                return
            a["gone"] = 0
            if still and thumb_change(res["thumb"], a["shot_thumb"]) > 0.35:
                a.update(state="wait")                 # swapped for a different card in the same spot
            else:
                lv.auto_text, lv.auto_frac = "Shot. Swap the card", 0.0
                return
        if not sure:
            a.update(state="wait", since=0.0)
            lv.auto_text = ("Auto-capture: place a card" if q is None or res["conf"] < 0.5
                            else "Auto-capture: finding the edges")
            lv.auto_frac = 0.0
            return
        if not still:
            a.update(state="settle", since=now)
            lv.auto_text, lv.auto_frac = "Hold still…", 0.0
            return
        if a["state"] != "settle":
            a.update(state="settle", since=now)
        hold = float(self.cfg.value("lv_auto_hold", 0.8))
        lv.auto_frac = (now - a["since"]) / hold
        lv.auto_text = "Hold still…"
        if now - a["since"] >= hold:
            a.update(state="shot", shot_thumb=res["thumb"], gone=0)
            lv.auto_text, lv.auto_frac = "Shooting…", 1.0
            self.cam_shoot()

    def _cam_presets(self):
        try:
            return json.loads(str(self.cfg.value("cam_presets", "{}")) or "{}")
        except ValueError:
            return {}

    def _fill_cam_presets(self):
        ps = self._cam_presets()
        self.cam_preset_combo.blockSignals(True)
        self.cam_preset_combo.clear()
        self.cam_preset_combo.addItem("Choose a saved setting" if ps else "None saved yet", None)
        for i, n in enumerate(ps):
            self.cam_preset_combo.addItem(f"{n}" + (f"   Cmd+{i + 1}" if i < 4 else ""), n)
        self.cam_preset_combo.blockSignals(False)

    def save_cam_preset(self):
        st = getattr(self.tether, "state", {}) or {}
        vals = {k: st[k]["cur"] for k in self.CAM_PRESET_KEYS if k in st and st[k].get("cur") is not None}
        if not vals:
            self.notice("Connect the camera first: the setting is read from it.", "warn")
            return
        name, ok = QInputDialog.getText(self, "Save camera setting", "Name, for example Holos or Regular cards:")
        if not ok or not name.strip():
            return
        ps = self._cam_presets()
        ps[name.strip()] = vals
        self.cfg.setValue("cam_presets", json.dumps(ps))
        self._fill_cam_presets()
        self.cam_preset_combo.setCurrentIndex(self.cam_preset_combo.findData(name.strip()))
        self.notice(f"Saved {name.strip()}.", "ok", secs=3)

    def delete_cam_preset(self):
        n = self.cam_preset_combo.currentData()
        if not n:
            return
        ps = self._cam_presets()
        ps.pop(n, None)
        self.cfg.setValue("cam_presets", json.dumps(ps))
        self._fill_cam_presets()

    def apply_cam_preset_n(self, i):
        names = list(self._cam_presets())
        if i < len(names):
            self.apply_cam_preset(names[i])
            self.cam_preset_combo.setCurrentIndex(self.cam_preset_combo.findData(names[i]))

    def apply_cam_preset(self, name):
        if not name:
            return
        vals = self._cam_presets().get(name)
        if not vals or not self.tether.is_connected:
            if vals:
                self.notice("Connect the camera to use a saved setting.", "warn")
            return
        st = getattr(self.tether, "state", {}) or {}
        skipped = []
        for k in self.CAM_PRESET_KEYS:                 # white balance before Kelvin, aperture before shutter
            if k not in vals or k not in st:
                continue
            if st[k].get("cur") == vals[k]:
                continue
            if not st[k].get("writable"):
                skipped.append(k)
                continue
            self.tether.set(k, int(vals[k]))
        self.notice(f"Camera set to {name}" + (f"; {', '.join(skipped)} could not be changed in this mode"
                                               if skipped else "."), "ok" if not skipped else "warn", secs=4)

    def _cam_focus(self, state):
        # the camera reports "idle" the moment the half-press is released, which would
        # wipe the confirmation before you see it; the overlay fades on its own instead
        if state in ("focused", "failed"):
            self.live.set_focus(state)

    def cam_af(self):
        if self.tether.is_connected:
            self.tether.autofocus()

    def cam_shoot(self):
        if not self.tether.is_connected:
            return
        if self.focusWidget() in (self.name_edit, self.title_edit):
            return
        self.tether.shoot(af=True)
        self.statusBar().showMessage("Focusing and shooting…")

    # --- lens: the profile, and a distortion measured from your own shots
    def _lens_fit(self) -> dict | None:
        return engine._fit_dict(getattr(self.settings, "lens_fit", ""))

    def _fill_lens_combo(self):
        c = self.lens_combo
        c.blockSignals(True)
        c.clear()
        c.addItem("No lens profile", ("", True))
        for key, prof in engine.LENS_PROFILES.items():
            c.addItem(f"{prof['name']}  ·  RAW only", (key, True))
            c.addItem(f"{prof['name']}  ·  all files", (key, False))
        fit = self._lens_fit()
        if fit:
            c.addItem(f"Measured from your shots  ·  {'RAW' if fit.get('kind') == 'raw' else 'camera JPEGs'}",
                      ("measured", True))
        want = (self.settings.lens_profile, True if self.settings.lens_profile == "measured" else self.settings.lens_raw_only)
        c.setCurrentIndex(max(0, next((i for i in range(c.count()) if tuple(c.itemData(i)) == want), 0)))
        c.blockSignals(False)

    def _show_lens_fit(self):
        fit = self._lens_fit()
        prof = self.settings.lens_profile
        self.lens_state.setText("Measured" if prof == "measured" and fit else "Lensfun" if prof in engine.LENS_PROFILES
                                else "Off")
        self.b_lens_forget.setEnabled(bool(fit))
        if not fit:
            self.lens_fit_lbl.setText("Not measured yet. Lensfun's profile is made at infinity focus, and a macro lens "
                                      "close to a card bows differently: Measure fits it to your own shots.")
            return
        px = fit.get("px", 0)
        self.lens_fit_lbl.setText(
            f"Measured from {fit.get('photos', '?')} photos ({'RAW' if fit.get('kind') == 'raw' else 'camera JPEGs'}): "
            f"card edges bowed {fit['rms_before'] * px:.2f} px, {fit['rms_after'] * px:.2f} px once straightened.")

    def _relens(self):
        """Apply a changed lens setting even when the combo's choice is the same (a new measurement)."""
        self.settings.lens_profile = None
        self.on_lens()
        self._show_lens_fit()

    def measure_lens(self):
        jobs = [j for j in self.jobs if os.path.isfile(j.path)]
        raw = [j for j in jobs if os.path.splitext(j.path)[1].lower() in engine.RAW_EXTS]
        other = [j for j in jobs if j not in raw]
        pick, kind = (raw, "raw") if len(raw) >= len(other) else (other, "jpeg")
        if len(pick) < 3:
            self.notice("Shoot or load at least three cards first, some near the corners of the frame", "error")
            return
        pick = pick[::max(1, len(pick) // 16)][:16]          # spread across the session, 16 at most
        self.b_lens_measure.setEnabled(False)
        self.b_lens_measure.setText("Measuring…")
        self.notice(f"Measuring the lens from {len(pick)} photos…")
        t = CallTask(_measure_lens_paths, [j.path for j in pick])
        t.then(lambda res, err: self._lens_measured(res, err, kind))
        QThreadPool.globalInstance().start(t)

    def _lens_measured(self, fit, err, kind):
        self.b_lens_measure.setEnabled(True)
        self.b_lens_measure.setText("Measure from session")
        if err or not fit or not fit.get("ok"):
            self.notice(err or (fit or {}).get("error") or "The lens could not be measured", "error")
            return
        old = self._lens_fit() or {}
        base = (self.settings.lens_profile if self.settings.lens_profile in engine.LENS_PROFILES
                else old.get("base") or next(iter(engine.LENS_PROFILES), ""))
        fit.update(kind=kind, base=base, at=time.time())
        b, a = fit["rms_before"] * fit["px"], fit["rms_after"] * fit["px"]
        if b < 0.5 or a > 0.75 * b:
            # one lens model has to straighten every card; when it cannot, the bow belongs to the cards
            self.notice(f"The lens is not what bows the cards: one correction for every photo only takes the edges "
                        f"from {b:.2f} to {a:.2f} px, so the bow changes card to card, which is the cards curling. "
                        "Straighten curled cards (Edit > Crop) fixes each card from its own sides. Nothing was changed.",
                        "info", secs=16)
            return
        else:
            self.notice(f"Lens measured: card edges bowed {b:.2f} px, {a:.2f} px once straightened. "
                        "New and re-read photos use it.", "ok", secs=10)
        if fit.get("reach", 1) < 0.7:
            self.notice("Every card sat near the middle of the frame, so only the main term was fitted: shoot a few "
                        "near the corners and measure again for the edges of the frame", "info", secs=12)
        self.settings.lens_fit = json.dumps(fit)
        self.settings.lens_profile = "measured"
        self._fill_lens_combo()
        self._relens()

    def forget_lens_fit(self):
        base = (self._lens_fit() or {}).get("base", "")
        self.settings.lens_fit = ""
        if self.settings.lens_profile == "measured":
            self.settings.lens_profile, self.settings.lens_raw_only = base, True
        self._fill_lens_combo()
        self._relens()

    def _refresh_level(self, force=False):
        """The level badge: the phone's reading of the mat against the camera, and beside it the tilt
        measured from the current card's own edges, when the photo says its focal length."""
        import level
        b = getattr(self, "_level_badge", None)
        if b is None:
            return
        if force or not hasattr(self, "_level_rep"):
            rep = level.load()
            self._level_rep = rep if rep.get("on") else None
        rep = self._level_rep
        j = getattr(self, "cur", None)
        key = (id(j), None if j is None or j.quad is None else j.quad.tobytes(), getattr(j, "_src", None) is not None)
        if force or key != getattr(self, "_level_key", None):
            self._level_key, self._level_photo = key, None
            if j is not None and j.quad is not None and getattr(j, "_src", None) is not None:
                try:                         # only from pixels already decoded: a RAW is never opened for this
                    h, w = j._src.shape[:2]
                    f = level.focal_px(j.path, w, h)
                    if f:
                        self._level_photo = level.tilt_from_quad(j.quad, w, h, f)
                except Exception:  # noqa: BLE001
                    self._level_photo = None
        elif not force:
            return
        photo = self._level_photo
        if rep is None and photo is None:
            b.setText("")
            return
        colour = {"good": TH.LIME, "ok": "#F2C14B", "bad": "#F26B4B"}.get((rep or {}).get("state"), "#FFFFFF")
        txt = f"Level {rep['deg']:.1f}°" if rep else "Level: not read"
        if rep and rep.get("lean_gap", 0) > level.LEAN_GAP:
            txt, colour = f"Level {rep['deg']:.1f}°, re-read", "#F2C14B"
        elif rep and rep["state"] == "bad":
            txt += ", re-shim"
        if photo is not None:
            txt += f"  ·  photo {photo:.1f}°"
        b.setText(txt)
        b.setStyleSheet(f"color: {colour}; font-size: 16px; font-weight: 700; padding: 0 10px;")
        if rep:
            b.setToolTip(rep.get("advice", ""))

    def chime(self, kind):
        """A small chime for a card captured, exported or listed, unless sounds are off in Settings."""
        if str(self.cfg.value("sounds", "true")).lower() in ("true", "1"):
            import sounds
            sounds.play(kind)

    def _cam_file(self, path):
        if getattr(self, "_surface_next", None):
            # the empty surface, shot from the phone's Surface page: kept for finding cards, not a card
            done, self._surface_next = self._surface_next, None
            try:
                rep = engine.set_surface(engine.Job(path, settings=self.settings).source())   # as cards are read
            except Exception as e:  # noqa: BLE001
                rep = {"on": False, "error": str(e)}
            self.live.flash()
            self.notice("Surface calibrated: cards are now found against it" if rep.get("on")
                        else f"The surface photo could not be read: {rep.get('error', '')}", "ok" if rep.get("on") else "error")
            done(rep)
            return
        QTimer.singleShot(0, self.save_session)      # every capture is on disk the moment it is handled
        self.live.flash()
        before = len(self.jobs)
        batch = self.c_batch.isChecked() and not self.c_carousel_mode.isChecked()
        pair = (self.c_pair.isChecked() or batch) and not self.c_carousel_mode.isChecked()
        pf = getattr(self, "_pair_front", None)
        if pf is not None and (pf not in self.jobs or pf.done or pf.side != "front"):
            # a front exported, removed or turned into a back since (Fronts and backs, Next up) is not waiting
            # for a back any more: this shot starts a card of its own
            self._pair_front = pf = None
        first = pair and pf is None
        self._hold_live = pair                 # neither side opens on its own: the front opens after the back
        try:
            self.add_paths([path])
        finally:
            self._hold_live = False
        if len(self.jobs) > before:
            self.chime("capture")
        if len(self.jobs) > before and first:
            # the front is in: stay in live view for its back, then edit the two together
            j = self.jobs[-1]
            j.rotate = self.live.rot
            j.from_camera = True
            self._pair_front = j
            j._new_card = True                    # a new card: never the back of whatever was exported last
            if self.c_follow.isChecked() and j.quad is not None and j.confidence >= 0.5:
                g = self._job_guide(j)
                if g is not None:
                    self.live.guide = g
                    self._guide_edited(g)
            self.listw.viewport().update()
            self._update_next()
            self.statusBar().showMessage(f"Captured the front ({os.path.basename(path)}): now shoot the back")
            return
        if pair:
            front, self._pair_front = getattr(self, "_pair_front", None), None
            if len(self.jobs) > before:
                b = self.jobs[-1]
                b.rotate = self.live.rot
                b.from_camera = True
                b.side = "back"                   # named after its front once the front is identified
                b._pair_of = front
            self._update_next()
            if batch:
                # batch shooting: straight on to the next card's front; edit and export them all later
                self.listw.viewport().update()
                n = sum(1 for x in self.jobs if getattr(x, "_new_card", False))
                self.statusBar().showMessage(f"Card {n}: front and back captured. Next card's front, or press "
                                             "E to edit the batch")
                return
            if front is not None and front in self.jobs:
                # crop and identify the front first, with nothing else left selected from before
                self.listw.setCurrentRow(self.jobs.index(front), QItemSelectionModel.ClearAndSelect)
                self.statusBar().showMessage("Both sides captured: set the front's edges and identify it, "
                                             "Enter exports and opens its back")
            return
        if len(self.jobs) > before:
            self.jobs[-1].rotate = self.live.rot      # open the shot the way it was framed
            self.jobs[-1].from_camera = True
            if self.c_follow.isChecked() and self.jobs[-1].quad is not None and self.jobs[-1].confidence >= 0.5:
                g = self._job_guide(self.jobs[-1])
                if g is not None:
                    self.live.guide = g
                    self._guide_edited(g)
            if self.cur is self.jobs[-1]:              # already opened by add_paths
                self.editor.set_view_rotation(self.live.rot)
                self.update_preview()
            self.listw.setCurrentRow(len(self.jobs) - 1, QItemSelectionModel.ClearAndSelect)   # review it now
        self.statusBar().showMessage(f"Captured {os.path.basename(path)}: Enter exports, L returns to live view")

    def closeEvent(self, e):
        self.cfg.setValue("window_geom", self.saveGeometry())
        self.save_session()
        self.tether.stop()
        if getattr(self, "phone", None) is not None:
            self.phone.stop()
        super().closeEvent(e)


def _measure_lens_paths(paths):
    """Off the UI thread: the card's four sides in each uncorrected photo, then one fit to all of them."""
    sides, radii, used = [], [], 0
    for p in paths:
        try:
            img = engine.imread(p)
        except Exception:  # noqa: BLE001
            continue
        ss = engine.clean_sides(engine.edge_samples(img), min(img.shape[:2]) / 2)
        if ss:
            sides += ss
            radii.append(min(img.shape[:2]) / 2)
            used += 1
    fit = engine.fit_distortion(sides)
    fit.update(photos=used, px=float(np.median(radii)) if radii else 0.0)
    return fit
