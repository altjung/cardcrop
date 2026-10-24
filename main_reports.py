"""CardCrop window, part: Condition reports, made only when asked for.

A mixin of app.Main; every method runs with self as the main window."""
from __future__ import annotations

import cv2
import ebay
import engine
import json
import listing
import numpy as np
import os
import ui_base as TH
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QVBoxLayout
from engine import FORMATS
from ui_base import LIME, subprocess_reveal
from ui_dialogs import CalibrateDialog


class ReportsMixin:
    # --- condition reports, made only when asked for
    def _source_roots(self):
        saved = self.cfg.value("source_folders", []) or []
        saved = [saved] if isinstance(saved, str) else list(saved)
        cal = self.cfg.value("calib_folders", []) or []
        cal = [cal] if isinstance(cal, str) else list(cal)
        return [r for r in dict.fromkeys([self.out_dir] + saved + cal) if r and os.path.isdir(r)]

    def open_centering(self, item):
        """Reports, Centering, on a live listing: its exported folder when CardCrop has one, else its own photos
        from eBay. Publish then adds the report to that listing."""
        self.go("reports")
        rp = self.reports_page
        rp.set_mode("centering")
        rp.centering.open_live(dict(item))

    def prepare_live(self, item):
        """A live listing ready to render: this session's photos of it if you have them open
        (your corrected edges), else its export folder, found or asked for."""
        it = dict(item)
        ss = self.session_sides(it)
        if ss:
            it["sides"] = ss
            it["folder"] = self.card_folder_for(it, ask=False)
        else:
            it["folder"] = self.card_folder_for(it)
            ss = self.session_sides(it)        # the folder's name can match a card open in Edit
            if ss:
                it["sides"] = ss
        return it

    def session_sides(self, item):
        """Front and back from this session's photos when they are the listing's card (matched by
        SKU or folder name): your own corrected edges then make the video or report."""
        sku, folder = item.get("sku") or "", item.get("folder") or ""
        keys = {sku, os.path.basename(folder.rstrip(os.sep)), ebay.sku_for(os.path.basename(folder.rstrip(os.sep)))}
        keys.discard("")
        for name in dict.fromkeys(j.card_name.strip() for j in self.jobs if j.card_name.strip()):
            if {name, engine.safe_name(name), ebay.sku_for(engine.safe_name(name))} & keys:
                f_, b_ = self._card_sides(name)
                if f_ is not None or b_ is not None:
                    return f_, b_
        return None

    def card_folder_for(self, item, ask=True):
        """The exported folder of a live listing's card: remembered, found by SKU under your output
        and source folders, or, when ask is set, picked by you. "" means use the listing's photos."""
        import calibrate
        iid = item.get("id", "")
        try:
            known = json.loads(str(self.cfg.value("live_folders", "{}")) or "{}")
        except ValueError:
            known = {}
        if iid in known and os.path.isdir(known[iid]):
            return known[iid]
        sku = item.get("sku") or ""
        if sku:
            if getattr(self, "_folder_index", None) is None or getattr(self, "_folder_roots", None) != self._source_roots():
                self._folder_roots = self._source_roots()
                idx = {}
                for k, v in calibrate._listing_folders(self._folder_roots).items():
                    # eBay's SKU is the folder name made SKU-safe (raifort-sv08.5-142 is raifort-sv08-5-142)
                    for key in (k, ebay.sku_for(k), ebay.sku_for(os.path.basename(v[0]))):
                        idx.setdefault(key, v[0])
                self._folder_index = idx
            if sku in self._folder_index:
                return self._folder_index[sku]
        if not ask:
            return ""
        box = QMessageBox(self)
        box.setWindowTitle("Card folder not found")
        box.setText(f"CardCrop could not find the exported folder for “{item.get('title', '')[:70]}”.\n\n"
                    "Its folder has the full-size, already straightened photos, which make a much cleaner "
                    "video or report than the listing's photos.")
        b_pick = box.addButton("Choose folder…", QMessageBox.AcceptRole)
        box.addButton("Use the listing's photos", QMessageBox.RejectRole)
        box.setDefaultButton(b_pick)
        box.exec()
        if box.clickedButton() is not b_pick:
            return ""
        d = QFileDialog.getExistingDirectory(self, f"The folder for {item.get('title', '')[:50]}",
                                             self._source_roots()[-1] if self._source_roots() else "")
        if not d:
            return ""
        known[iid] = d
        self.cfg.setValue("live_folders", json.dumps(known))
        # its parent is searched from now on, so the rest of that batch is found on its own
        parent = os.path.dirname(os.path.dirname(d)) or os.path.dirname(d)
        saved = self.cfg.value("source_folders", []) or []
        saved = [saved] if isinstance(saved, str) else list(saved)
        if parent not in saved and parent not in self._source_roots():
            self.cfg.setValue("source_folders", saved + [parent])
        self._folder_index = None
        return d

    def calibrated_or_ask(self) -> bool:
        """Reports only run once the scoring has been calibrated on your own graded cards."""
        import calibrate
        if calibrate.ready()[0]:
            return True
        self.calibrate_reports(first=True)
        return calibrate.ready()[0]

    def calibrate_reports(self, first=False):
        CalibrateDialog(self, first=first).exec()
        if getattr(self, "reports_page", None) is not None:
            self.reports_page.show_calibration()

    def _report_for(self, name, folder=None, info=None):
        """Measures a card's sides and draws its report. Returns (PIL image, findings) or None.
        With a folder, the card is read from that folder's exported photos (anywhere on disk)."""
        import grading
        front, back = self._sides_from_folder(folder) if folder else self._card_sides(name)
        if front is None and back is None:
            return None
        sides = {}
        for side, img in (("front", front), ("back", back)):
            if img is None:
                continue
            sd = grading.analyze_side(img, side, engine.measure_centering(img))
            if side == "back":
                info = next((x.card_info for x in self.jobs if x.card_name.strip() == name and x.card_info), None) or {}
                game = info.get("game") or "pokemon"
                grading.remember_back(sd["_img"], game)
                sd["surface"] = grading.back_surface(sd, game)
            sides[side] = sd
        info = info or next((x.card_info for x in self.jobs if x.card_name.strip() == name and x.card_info), None)
        if not info:                               # an earlier export: its saved listing knows the card
            fold = folder or os.path.join(self.out_dir, engine.safe_name(name))
            try:
                lj = next((f for f in os.listdir(fold) if f.endswith("_listing.json")), None)
                with open(os.path.join(fold, lj), encoding="utf-8") as f:
                    info = (json.load(f) or {}).get("info") or {}
            except (OSError, ValueError, TypeError):
                info = {}
        title = listing.name_of(info) if info else name
        num = (f"#{info.get('number')}" + (f"/{info.get('set_total')}" if info.get("set_total") else "")) \
            if info.get("number") else ""
        subtitle = "  ·  ".join(x for x in (listing.set_of(info) if info else "", num) if x)
        res = grading.combine(sides.get("front"), sides.get("back"))
        im = grading.render_report(f"{title} {num}".strip() if num else title, subtitle,
                                   sides.get("front"), sides.get("back"))
        for x in self.jobs:
            if x.card_name.strip() == name:
                x.grade = res
        return im, res

    def _save_report(self, name, im, folder=None):
        folder = folder or os.path.join(self.out_dir, engine.safe_name(name))
        safe = engine.safe_name(os.path.basename(folder.rstrip(os.sep)))
        os.makedirs(folder, exist_ok=True)
        for old in os.listdir(folder):
            if "_12_grade" in old:
                os.remove(os.path.join(folder, old))
        path = os.path.join(folder, f"{safe}_12_grade{FORMATS[self.settings.out_format][1]}")
        engine.imwrite(path, cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR), self.settings.out_format)
        self._mark_changed(name)                   # an auto-upload or re-upload picks the new photo up
        return path

    def _report_last_shot(self):
        j = next((x for x in reversed(self.jobs) if getattr(x, "from_camera", False)), None)
        name = j.card_name.strip() if j is not None else ""
        if not name:
            self.notice("Name the card in the last shot first (it is named when you identify its front).", "info")
            return
        self.condition_report(name)

    def condition_report(self, name=None):
        """One card's report, previewed; Add to listing photos saves it as the last photo."""
        if name is None:
            name = self.cur.card_name.strip() if self.cur is not None else ""
        if not name:
            self.notice("Name the card first (identify it, or type its name), then make its report.", "info")
            return
        if not self.calibrated_or_ask():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            got = self._report_for(name)
        except Exception as e:  # noqa: BLE001
            got = None
            self.notice(f"The report could not be made: {e}", "error")
        finally:
            QApplication.restoreOverrideCursor()
        if got is None:
            self.notice("Set this card's corners first (front, back or both), then make its report.", "info")
            return
        im, _res = got
        self._show_grade()
        d = QDialog(self)
        d.setWindowTitle(f"Condition report · {name}")
        v = QVBoxLayout(d)
        v.setContentsMargins(16, 16, 16, 16)
        lab = QLabel()
        q = QImage(im.tobytes(), im.width, im.height, 3 * im.width, QImage.Format_RGB888).copy()
        side = min(760, int((QApplication.primaryScreen().availableGeometry().height() - 160)))
        lab.setPixmap(QPixmap.fromImage(q).scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        v.addWidget(lab)
        bb = QHBoxLayout()
        bb.addStretch(1)
        b_close = QPushButton("Close")
        b_close.clicked.connect(d.reject)
        b_add = QPushButton("Add to listing photos", objectName="primary")
        b_add.setToolTip("Saved as the card's last photo (12), so it uploads with the listing")
        b_add.clicked.connect(d.accept)
        bb.addWidget(b_close)
        bb.addWidget(b_add)
        v.addLayout(bb)
        if d.exec() == QDialog.Accepted:
            path = self._save_report(name, im)
            self.notice(f"Report added to {name}'s listing photos", "ok",
                        action=("Show", lambda p_=path: subprocess_reveal(p_)))

    def batch_reports(self, names, folders=None, infos=None, save_to=None):
        """Reports for the selected cards, each saved as its last listing photo. folders (same order)
        reads and saves each card in that folder instead of the save folder. save_to (same order) keeps
        each report at that path instead, made but not yet added."""
        names = [n for n in names if n]
        folders = folders or [None] * len(names)
        infos = infos or [None] * len(names)
        if not names or not self.calibrated_or_ask():
            return
        prog = QProgressDialog("Making condition reports…", "Cancel", 0, len(names), self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        done, missing, mismatch = 0, [], []
        for i, n in enumerate(names):
            if prog.wasCanceled():
                break
            prog.setLabelText(f"Condition report {i + 1} of {len(names)}: {n}")
            prog.setValue(i)
            QApplication.processEvents()
            try:
                got = self._report_for(n, folders[i], infos[i])
            except Exception:  # noqa: BLE001
                got = None
            if got is None:
                missing.append(n)
                continue
            if save_to:
                os.makedirs(os.path.dirname(save_to[i]), exist_ok=True)
                cv2.imwrite(save_to[i], cv2.cvtColor(np.asarray(got[0]), cv2.COLOR_RGB2BGR),
                            [cv2.IMWRITE_JPEG_QUALITY, 94])
            else:
                self._save_report(n, got[0], folders[i])
            done += 1
            import grading
            band = grading.band_of(grading.points(got[1])[0])[0]
            listed = next((x.condition for x in self.jobs if x.card_name.strip() == n and x.condition), "")
            if listed and listed != band:
                mismatch.append(f"{n}: report lands in {band}, set to {listed}")
        prog.close()
        self.notice(f"{done} condition report(s) " + ("made: look them over, then Add to listings" if save_to
                                                      else "added to the listing photos")
                    + (f"; {len(missing)} card(s) had no straightened photo" if missing else "")
                    + (f"; {len(mismatch)} disagree with the condition set (Details)" if mismatch else ""),
                    "ok" if not (missing or mismatch) else "warn", "\n".join(mismatch + missing))
        if self.stage == "list":
            self.list_page.refresh()
        if self.stage == "reports":
            self.reports_page.refresh()
        return done

    def _write_extras(self, name):
        """After a side is exported: refresh the hero and the listing files for that card."""
        name = name.strip()
        if not name:
            return
        jobs = [x for x in self.jobs if x.card_name.strip() == name and x.done]
        front = next((x.hero_core for x in jobs if x.side == "front" and x.hero_core is not None), None)
        back = next((x.hero_core for x in jobs if x.side == "back" and x.hero_core is not None), None)
        if self.settings.hero and (front is not None or back is not None):
            # the hero is a large composite written to disk: off the UI thread, so the window keeps
            # moving while a batch's heroes are made (it froze at the end of a long export)
            from PySide6.QtCore import QThreadPool
            from ui_tasks import CallTask

            def hero_done(_r, err):
                if err:
                    self.statusBar().showMessage(f"Hero image failed: {err}")
            t = CallTask(engine.write_hero, self.out_dir, name, front, back, self.settings)
            t.then(hero_done)
            QThreadPool.globalInstance().start(t)
        if front is not None and back is not None:
            for x in jobs:                 # pair complete: free the memory
                x.hero_core = None
        L = self._listing_for(name)
        if L is not None:
            listing.save(L, os.path.join(self.out_dir, engine.safe_name(name)), engine.safe_name(name))
        QTimer.singleShot(0, lambda n=name: self._maybe_auto_upload(n))

    def fill_drafts(self):
        found = listing.load_all(self.out_dir)
        if not found:
            self.notice("No listings yet: identify and export some cards first. Listings are saved next to "
                        "their photos in the output folder.", "warn")
            return
        tpl = str(self.cfg.value("ebay_template", ""))
        if not tpl or not os.path.exists(tpl):
            tpl, _ = QFileDialog.getOpenFileName(
                self, "Choose the eBay drafts template (Seller Hub > Reports > Uploads > Get template > "
                "Listings > Create new drafts)", os.path.expanduser("~/Downloads"), "CSV files (*.csv)")
            if not tpl:
                return
            self.cfg.setValue("ebay_template", tpl)
        out = os.path.join(self.out_dir, "ebay_drafts_upload.csv")
        try:
            rep_ = listing.fill_ebay_template(tpl, found, out)
        except Exception as e:  # noqa: BLE001
            self.notice("Could not fill the drafts template.", "error", str(e))
            return
        listing.export_csv(found, os.path.join(self.out_dir, "listings_overview.csv"))
        blank = rep_["required_left_blank"]
        det = (f"{out}\n\nUpload it in Seller Hub > Reports > Uploads > Upload template. This file has no photo "
               "links; for drafts with photos use Make Seller Hub draft, which uploads them first.")
        if blank:
            det += "\n\nRequired columns left for you to fill in eBay: " + ", ".join(h.lstrip('*') for h in blank[:8])
        subprocess_reveal(out)
        self.notice(f"Drafts file written with {rep_['rows']} card(s); Finder is showing it.", "ok", det)

    def on_name(self, text):
        if self.cur is not None:
            self.cur.card_name = text
            self._label(self.cur)
            self._show_price()

    def toggle_side(self):
        if self.cur is None:
            return
        self.cur.side = "back" if self.cur.side == "front" else "front"
        self._show_side()
        self._label(self.cur)

    def _show_grade(self):
        """One line under the condition chips: what the report found, in its own plain words."""
        import grading
        j = self.cur
        name = j.card_name.strip() if j is not None else ""
        res = next((x.grade for x in self.jobs if x.card_name.strip() == name and getattr(x, "grade", None)), None) \
            if name else None
        if not res and name:                  # exported in an earlier session: read the saved measurements
            folder = os.path.join(self.out_dir, engine.safe_name(name))
            f_, b_ = (grading.load_side(folder, engine.safe_name(name), sd) for sd in ("front", "back"))
            if f_ or b_:
                res = grading.combine(f_, b_)
        if not res or not res.get("subgrades"):
            self.grade_lbl.hide()
            return
        good = {"Sharp", "Clean", "Well centered"}
        bits = []
        for k in grading.CATEGORIES:
            w = grading.status(k, res["subgrades"].get(k))
            if w == "Not assessed":
                continue
            col = LIME if w in good and TH.THEME == "dark" else (TH.T["text"] if w in good else TH.T["need"])
            bits.append(f"{k} <span style='color:{col}'>{w.lower()}</span>")
        score, _ded = grading.points(res)
        code, _name = grading.band_of(score)
        listed = self._card_condition() if self.cur is not None else ""
        warn = ""
        if listed and listed != code:
            warn = (f"<br><span style='color:{TH.T['need']}'>The report lands in {code}, but this card is set to "
                    f"{listed}. Check before listing.</span>")
        self.grade_lbl.setText(f"Report: <b>{score}/100</b>, lands in {code} · " + " · ".join(bits) + warn)
        self.grade_lbl.show()

    def _show_side(self):
        if hasattr(self, "grade_lbl"):
            self._show_grade()
        side = self.cur.side if self.cur else "front"
        for k, b in self.seg_side.items():
            b.setChecked(k == side)
        cond = self._card_condition() if self.cur else ""
        back = self.cur is not None and side == "back"
        for code, b in self.cond_btns.items():
            b.setChecked(code == cond)
            b.setEnabled(back)
        self.cond_cap.setText("Condition" if back else
                              ("Condition · set on the back" if cond else "Condition · not set yet, set on the back"))
        self.cond_cap.setStyleSheet("" if (back or cond or self.cur is None) else f"color:{TH.T['need']};")
        self.strip_cond.setText(cond)

    def _card_condition(self):
        j = self.cur
        if j is None:
            return ""
        name = j.card_name.strip()
        same = [x for x in self.jobs if name and x.card_name.strip() == name] or [j]
        return next((x.condition for x in same if x.condition), "")

    def set_condition(self, code):
        j = self.cur
        if j is None or j.side != "back" or self.stack.currentWidget() is self.live:
            return
        code = "" if j.condition == code else code       # clicking the lit grade clears it
        self._mark_changed(j.card_name.strip())
        # the grade belongs to the card, so both sides carry it into the listing
        same = [x for x in self.jobs if j.card_name.strip() and x.card_name.strip() == j.card_name.strip()]
        for x in same or [j]:
            x.condition = code
            self._label(x)
        j.condition = code
        self._label(j)
        self._show_side()
        self._show_listing()                 # the title can change with the grade (CLEAN)
        self.statusBar().showMessage(f"Condition: {listing.CONDITIONS[code][0]} ({code})" if code
                                     else "Condition cleared")

    def push_undo(self):
        j = self.cur
        if j is None or j.quad is None:
            return
        if not hasattr(j, "undo_stack"):
            j.undo_stack, j.redo_stack = [], []
        j.undo_stack.append((j.quad.copy(), j.rotate, j.edited))
        del j.undo_stack[:-100]
        j.redo_stack.clear()
        self._tick = getattr(self, "_tick", 0) + 1
        self._edit_tick = self._tick

    def _restore(self, src, dst):
        j = self.cur
        if j is None or not getattr(j, src, None):
            return
        getattr(j, dst).append((j.quad.copy(), j.rotate, j.edited))
        j.quad, j.rotate, j.edited = getattr(j, src).pop()
        if self.editor.view_rot != j.rotate % 360:
            self.editor.set_view_rotation(j.rotate)
        self.editor.set_quad(j.quad)
        self._label(j)
        self._show_conf()
        self.update_preview()
        self.measure_timer.start()

    def undo(self):
        # like the Finder: the last thing done comes back first, a removal or an edge change
        rm = getattr(self, "_rm_undo", [])
        if rm and rm[-1][0] > getattr(self, "_edit_tick", 0):
            tick, taken = rm.pop()
            self._put_back(taken)
            self._rm_redo = getattr(self, "_rm_redo", []) + [(tick, taken)]
            return
        self._restore("undo_stack", "redo_stack")

    def redo(self):
        rd = getattr(self, "_rm_redo", [])
        if rd:
            tick, taken = rd.pop()
            rows = [self.jobs.index(j) for _, j in taken if j in self.jobs]
            self.remove_jobs(rows, undoable=False)
            self._rm_undo.append((tick, [(r, j) for r, (_, j) in zip(rows, taken)]))
            return
        self._restore("redo_stack", "undo_stack")

    def measure_current(self):
        """Centering at full resolution; runs after edits settle, not mid-drag."""
        j = self.cur
        if j is None or j.quad is None:
            return
        try:
            card = engine.warp_card(j.source(), j.quad, self.settings, j.rotate)
        except Exception:  # noqa: BLE001
            return
        m = engine.margin_for(j.quad, self.settings)
        H, W = card.shape[:2]
        core = card[m:H - m, m:W - m]
        c = engine.measure_centering(core)
        j.centering = c
        if c is None:
            self.cent_lbl.setText("No border found")
            self.cent_lbl.setStyleSheet("background: rgba(255,255,255,30); color: #E6E6E8;")
            self.card_lbl.set_frame(None)
            return
        self.cent_lbl.setText("LR %d/%d · TB %d/%d" % (*c.lr, *c.tb))
        self.cent_lbl.setStyleSheet("")
        self.card_lbl.set_frame(((m + c.left) / W, (m + c.top) / H,
                                 (W - m - c.right) / W, (H - m - c.bottom) / H))

    def copy_centering(self):
        if self.cur is not None and self.cur.centering is not None:
            QApplication.clipboard().setText(self.cur.centering.text())
            self.statusBar().showMessage("Copied: " + self.cur.centering.text())
