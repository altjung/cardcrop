"""CardCrop window, part: The batch on the filmstrip: adding photos, selection, editing, naming, undo, saved spots and identification.

A mixin of app.Main; every method runs with self as the main window."""
from __future__ import annotations

import time
import cv2
import ebay
import engine
import json
import listing
import numpy as np
import os
import ui_base as TH
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QListWidgetItem, QMenu
from engine import Job
from ui_base import DEFAULT_PT, HANDLE, STATUS, TIPS_CORNERS, TIPS_SHAPE, set_ui_pt, subprocess_reveal, to_qimage
from main_pipeline import ATTENTION
from ui_tasks import DetectTask, IdentifyTask, ThumbOnlyTask, looks_exported
from ui_widgets import _short_needs, rounded_pixmap


class QueueMixin:
    # --- queue
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        dirs = [p for p in paths if os.path.isdir(p)]
        # exported card folders (or a folder of them) go to eBay listing, not back into the editor
        exported = [d for d in dirs if looks_exported(d) or
                    any(looks_exported(os.path.join(d, x)) for x in os.listdir(d)
                        if os.path.isdir(os.path.join(d, x)))]
        if exported:
            self.list_folders(exported)
            paths = [p for p in paths if p not in exported]
        if paths:
            self.add_paths(paths)

    def add_dialog(self):
        exts = " ".join(f"*{x} *{x.upper()}" for x in sorted(engine.IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Add card photos", "", f"Images ({exts})")
        self.add_paths(files)

    def _pair_from_name(self, j):
        """A photo named as one side of a card (CardCrop's own name_02_front / name_03_back_NM, or
        plainly "name front" / "name back") is put to that card and side, with what its export
        folder knows (the identified card, its condition), so a pair arrives already matched."""
        stem = os.path.splitext(os.path.basename(j.path))[0]
        m = self._SIDE_RE.match(stem)
        if not m or not m.group("stem").strip(" _-."):
            return
        name = m.group("stem").strip(" _-.")
        j.side = m.group("side").lower()
        j.card_name = name
        cond = (m.group("cond") or "").upper()
        folder = os.path.dirname(j.path)
        try:
            lj = next((f for f in os.listdir(folder) if f.endswith("_listing.json") and not f.startswith("._")), None)
            L = json.load(open(os.path.join(folder, lj), encoding="utf-8")) if lj else {}
        except (OSError, ValueError):
            L = {}
        if (L.get("info") or {}).get("id") and not j.card_info:
            j.card_info = L["info"]
        if j.side == "back":
            j.condition = cond or (L.get("condition") or "").upper()
        if L.get("price") and not float(self._prices().get(name, 0) or 0):
            try:
                p_ = self._prices()
                p_[name] = round(float(L["price"]), 2)
                self.cfg.setValue("prices", json.dumps(p_))
            except (TypeError, ValueError):
                pass

    def add_paths(self, paths, ig_only=False):
        known = {j.path for j in self.jobs}
        new = [p for p in engine.expand_paths(paths) if p not in known]
        paired = 0
        for p in new:
            j = Job(p, settings=self.settings)
            j.ig_only = ig_only or self.c_carousel_mode.isChecked()
            if not j.ig_only:
                self._pair_from_name(j)
                paired += bool(j.card_name)
            self.jobs.append(j)
            it = QListWidgetItem()
            self.listw.addItem(it)
            self._label(j)
            t = DetectTask(j, keep=False)
            t.sig.done.connect(self.on_detected)
            self.pool.start(t)
        if new and self.cur is None and not getattr(self, "_hold_live", False):
            self.listw.setCurrentRow(len(self.jobs) - len(new))
        self.statusBar().showMessage(f"Added {len(new)} photo(s)")
        if paired:
            self.notice(f"{paired} of {len(new)} photos were matched to their card and side by name.", "ok", secs=4)

    def clear_jobs(self):
        if self.jobs:
            self.remove_jobs(list(range(len(self.jobs))))

    def _film_menu(self, pos):
        it = self.listw.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.listw.setCurrentItem(it)
        n = len(self.listw.selectedIndexes()) or 1
        menu = QMenu(self)
        menu.addAction("Identify" if n == 1 else f"Identify {n} photos", self.identify_now)
        menu.addAction("Fronts and backs…", self.sort_sides)
        menu.addSeparator()
        menu.addAction("Remove from the list" if n == 1 else f"Remove {n} photos from the list",
                       self.remove_selected)
        menu.addAction("Show in Finder", lambda p=self.jobs[self.listw.row(it)].path: subprocess_reveal(p))
        menu.exec(self.listw.viewport().mapToGlobal(pos))

    def remove_selected(self):
        rows = sorted({i.row() for i in self.listw.selectedIndexes()})
        if not rows and 0 <= self.listw.currentRow() < len(self.jobs):
            rows = [self.listw.currentRow()]
        if rows:
            self.remove_jobs(rows)

    def remove_jobs(self, rows, undoable=True):
        """Takes photos off the filmstrip (the files stay where they are). Cmd+Z puts them back."""
        rows = sorted(r for r in set(rows) if 0 <= r < len(self.jobs))
        if not rows:
            return
        taken = [(r, self.jobs[r]) for r in rows]
        was_cur = self.cur is not None and any(j is self.cur for _, j in taken)
        keep_at = rows[0]
        self.listw.blockSignals(True)
        for r in reversed(rows):
            self.jobs.pop(r)
            self.listw.takeItem(r)
        self.listw.blockSignals(False)
        if undoable:
            self._tick = getattr(self, "_tick", 0) + 1
            self._rm_undo = getattr(self, "_rm_undo", [])
            self._rm_undo.append((self._tick, taken))
            del self._rm_undo[:-50]
            self._rm_redo = []
        if was_cur:
            self.cur.release()
            self.cur = None
            if self.jobs:
                self.listw.setCurrentRow(min(keep_at, len(self.jobs) - 1))
                self.select(self.listw.currentRow())
            else:
                self.editor.clear()
                self.card_lbl.set_q(None)
                for l in self.corner_lbls:
                    l.set_q(None)
                self.title.setText("Drop card photos to start")
                self.conf_lbl.setText("")
        n = len(taken)
        self.notice(f"Removed {n} photo{'s' if n != 1 else ''} from the list. Cmd+Z brings "
                    f"{'it' if n == 1 else 'them'} back; your files are untouched.", "info", secs=5)
        self._update_summary()

    def _put_back(self, taken):
        self.listw.blockSignals(True)
        for r, j in sorted(taken, key=lambda t: t[0]):
            r = min(r, len(self.jobs))
            self.jobs.insert(r, j)
            self.listw.insertItem(r, QListWidgetItem())
        self.listw.blockSignals(False)
        for _, j in taken:
            self._label(j)
        self.listw.clearSelection()
        first = self.jobs.index(taken[0][1])
        self.listw.setCurrentRow(first)
        for _, j in taken:
            it = self.listw.item(self.jobs.index(j))
            if it is not None:
                it.setSelected(True)
        n = len(taken)
        self.notice(f"Put back {n} photo{'s' if n != 1 else ''}.", "ok", secs=3)
        self._update_summary()

    def _label(self, j: Job):
        if j not in self.jobs:                   # taken off the filmstrip while it was working
            return
        i = self.jobs.index(j)
        it = self.listw.item(i)
        if it is None:
            return
        file_ = os.path.basename(j.path)
        if j.error:
            mark, key, state = "✕", "error", "Failed"
        elif j.done:
            mark, key, state = "✓", "ready", "Exported"
        elif j.quad is None:
            mark, key, state = "…", "idle", "Detecting"
        elif j.confidence < 0.8 and not j.edited:
            mark, key, state = "!", "need", "Check the edges"
        else:
            mark, key, state = "●", "idle", "To export"
        nm = j.card_name.strip()
        name = nm or file_
        info = j.card_info or next((x.card_info for x in self.jobs if nm and x.card_name.strip() == nm
                                    and x.card_info), None)
        if info:
            name = info.get("name_en") or info.get("name") or name
        side = "Front" if j.side == "front" else "Back"
        cond = self._card_condition_of(nm) if nm else j.condition
        side_line = f"{side} · {cond}" if cond else (side if nm else "Not named")
        tip = j.error or ("Check this one: weak edges" if mark == "!" else j.path)
        extra = []
        if j.side == "back" and j.condition:
            extra.append(j.condition)
        strong = False
        if j.ig_only:
            st_ = getattr(j, "ig_state", "")
            side_line = "Carousel only"
            state = {"writing": "Writing slides…", "done": "Slides saved"}.get(st_, state)
            extra.append(state)
            if st_ == "writing":
                mark, key = "…", "idle"
            elif st_ == "done":
                key = "ready"
        elif not nm and getattr(j, "id_bg", False):
            state = "Reading the card…"
        elif not nm and getattr(j, "id_unsure", False) and j.quad is not None:
            mark, key, state = "?", "need", "Pick the card"
            tip = "Its number fits several cards: press I to choose"
            strong = True
        elif nm:
            tag = self._ebay_tag(nm)
            if tag:
                extra.append(tag)
                state = tag.replace("eBay: ", "eBay ")
                key = {"eBay: live": "live", "eBay: draft": "draft", "eBay: sold": "sold"}.get(tag, "unpub")
            need = self._needs(nm) if j.done else []
            if need and not tag:
                mark, key = "⚠", "need"
                state = "Needs " + _short_needs(need)
                extra.append(state)
                tip = "Before listing: " + ", ".join(need)
                strong = True
        if mark in ("✕", "!"):
            strong = True
        j.mark = mark
        it.setText(f"{mark}   {('F' if j.side == 'front' else 'B') + ' · ' + nm if nm else file_}" +
                   (f"\n      {' · '.join(extra)}" if extra else ""))
        prev = it.data(Qt.UserRole) or {}
        pm = self._thumb_pm(j)
        now = time.time()
        row_t = prev.get("row_t", now)                       # a new tile slides in once
        had = prev.get("pm") is not None and not prev["pm"].isNull()
        pm_t = prev.get("pm_t", 0) if had else (now if pm is not None and not pm.isNull() else 0)
        if not prev or (pm_t == now):
            self.strip_pulse.kick()
        if j.error:
            ms = "failed"
        elif j.done:
            ms = "done"
        elif j.quad is None or getattr(j, "id_bg", False):
            ms = "running"
        elif mark in ATTENTION:
            ms = "need"
        else:
            ms = "pending"
        m_t = prev.get("m_t", now) if prev.get("mstate") == ms else now
        it.setData(Qt.UserRole, {"name": name, "side": side_line, "state": state, "strong": strong,
                                 "color": STATUS.get(key, STATUS["idle"]), "pm": pm,
                                 "row_t": row_t, "pm_t": pm_t, "mstate": ms, "m_t": m_t})
        if ms == "running" or m_t == now:
            self.strip_pulse.kick(0.6 if ms != "running" else 1.2)
        it.setToolTip(tip)
        if getattr(j, "from_camera", False) and self.jobs and j is next(
                (x for x in reversed(self.jobs) if getattr(x, "from_camera", False)), None):
            self.last_thumb.setPixmap(rounded_pixmap(self._thumb_pm(j), 44, 60, 5))
            self.hud_last.show()
            self.last_l1.setText(f"Last shot · {name} {side.lower()}" if nm else "Last shot")
            self.last_l2.setText(f"{file_} · " + (f"edges {j.confidence:.0%}" if j.quad is not None else "detecting"))
            self.live_isl._place()
        self.sum_timer.start()

    def set_english_name(self):
        j = self.cur
        info = j.card_info if j else None
        if not info:
            return
        text, ok = QInputDialog.getText(self, "English name",
                                        f"The English name for {info.get('name', '')} {info.get('number', '')}, "
                                        "as it should appear in the eBay title:", text=info.get("name_en", ""))
        text = listing.en(text)
        if not ok or not text:
            return
        nm = j.card_name.strip()
        for x in self.jobs:
            if x is j or (nm and x.card_name.strip() == nm):
                if x.card_info:
                    x.card_info["name_en"] = text
        self._show_listing()
        self._relabel(nm or None)
        if nm:
            self._write_extras(nm)

    def _card_condition_of(self, name):
        same = [x for x in self.jobs if x.card_name.strip() == name]
        return next((x.condition for x in same if x.side == "back" and x.condition), "") or \
            next((x.condition for x in same if x.condition), "")

    # --- batch state
    def _records(self):
        """eBay records, re-read only when the file changes."""
        p = ebay.record_path(self.out_dir)
        try:
            mt = os.path.getmtime(p)
        except OSError:
            return {}
        c = getattr(self, "_rec_cache", None)
        if not c or c[0] != (p, mt):
            self._rec_cache = c = ((p, mt), ebay.load_records(self.out_dir))
        return c[1]

    def _sold_skus(self):
        """SKUs that sold (from the sales ledger) and are no longer listed with copies left."""
        if getattr(self, "_sold_cache", None) is None:
            import sales
            sold = {s.get("sku") for s in sales.entries() if s.get("sku")}
            active = {a.get("sku") for a in (self.store_page.data or {}).get("active", [])
                      if a.get("sku") and int(a.get("qty") or 0) > 0}
            self._sold_cache = sold - active
        return self._sold_cache

    def _ebay_tag(self, name):
        sku = ebay.sku_for(engine.safe_name(name))
        rec = self._records().get(sku, {})
        if rec.get("status") == "published":
            return "eBay: sold" if (rec.get("sku") or sku) in self._sold_skus() else "eBay: live"
        if rec.get("offer_id"):
            return "eBay: unpublished"
        return "eBay: draft" if rec.get("drafted") else ""

    def _needs(self, name, prices=None):
        """What a card still lacks before it can be listed."""
        same = [x for x in self.jobs if x.card_name.strip() == name]
        if not same or all(x.ig_only for x in same):
            return []
        prices = self._prices() if prices is None else prices
        out = []
        info = next((x.card_info for x in same if x.card_info), None)
        if not info:
            out.append("identify it (I)")
        elif listing.needs_english_name(info):
            out.append("an English name")
        if not any(x.condition for x in same):
            out.append("a condition (set on the back)")
        if not float(prices.get(name, 0) or 0) > 0:
            out.append("a price")
        return out

    def _relabel(self, name=None):
        for x in self.jobs:
            if name is None or x.card_name.strip() == name:
                self._label(x)

    def _summary(self):
        prices = self._prices()
        names = {x.card_name.strip() for x in self.jobs if x.card_name.strip() and not x.ig_only}
        done = sum(1 for x in self.jobs if x.done)
        need = {n: self._needs(n, prices) for n in names
                if any(x.done for x in self.jobs if x.card_name.strip() == n)}
        need = {n: v for n, v in need.items() if v}
        tags = [self._ebay_tag(n) for n in names]
        return {"photos": len(self.jobs), "cards": len(names), "exported": done, "need": need,
                "live": tags.count("eBay: live"), "sold": tags.count("eBay: sold"), "unpub": tags.count("eBay: unpublished"),
                "drafts": tags.count("eBay: draft"), "failed": sum(1 for x in self.jobs if x.error)}

    def _fit_rows(self):
        pass                                     # filmstrip tiles have a fixed size

    def _update_summary(self):
        has = bool(self.jobs)
        self.listw.setVisible(has)
        self.film_empty.setVisible(not has)
        for f in (self.pip, self.hud_conf, self.tools_row, self.hud_file):
            f.setVisible(has)
        self.empty_hint.setVisible(not has)
        self.canvas_isl._place()
        cards = self._cards() if has else []
        ready = sum(1 for c in cards if c["status_key"] == "ready")
        need = sum(1 for c in cards if c["status_key"] == "need")
        live = sum(1 for c in cards if c["status_key"] in ("live", "unpub", "draft"))
        self.stat_lbls["ready"].setText(f"{ready:02d}")
        self.stat_lbls["need"].setText(f"{need:02d}")
        self.stat_lbls["live"].setText(f"{live:02d}")
        warn = sum(1 for x in self.jobs if getattr(x, "mark", "") in ATTENTION)
        rc = len({x.card_name.strip() for x in self.ready_jobs()})
        self.b_ready.setText(f"Ready  {rc}")
        self.b_ready.setVisible(rc > 0)
        self.b_next_warn.setVisible(bool(warn))
        todo = sum(1 for x in self.jobs if not x.done and not x.error)
        self.b_all.setText(f"All  {todo}" if todo else "All")
        if not getattr(self, "_exporting", False):
            self.b_all.setEnabled(bool(todo))
        self.batch_lbl.setText(f"{len(self.jobs)} photos · {len(cards)} cards · {need} need you")
        self._update_next()

    def next_attention(self):
        n = len(self.jobs)
        start = self.listw.currentRow()
        for k in range(1, n + 1):
            i = (start + k) % n
            if getattr(self.jobs[i], "mark", "") in ATTENTION:
                self.listw.setCurrentRow(i)
                return

    def on_detected(self, job: Job, err):
        if job in self.jobs:
            self._label(job)
            self.pipe_detected(job)
            if getattr(job, "from_camera", False):
                self._check_exposure(job)
            if job is self.cur and not job.edited and job.quad is not None:
                self._maybe_reuse(job, (self.editor.qimg.height(), self.editor.qimg.width()) if self.editor.qimg else None)
                self.editor.set_quad(job.quad)
                self.measure_timer.start()
                self._show_conf()
                self.update_preview()

    def _shutter_for(self, stops):
        """The camera's shutter speed that lets in about 2^stops times the light, or None."""
        import math
        combo = getattr(self, "cam_combos", {}).get("shutter")
        if combo is None or not combo.isEnabled() or combo.count() < 2:
            return None

        def secs(v):
            num, den = (int(v) >> 16), (int(v) & 0xFFFF)
            return num / den if num and den else None
        cur = secs(combo.currentData())
        if not cur:
            return None
        want = cur * 2 ** stops
        best = None
        for i in range(combo.count()):
            s_ = secs(combo.itemData(i))
            if s_ and s_ <= max(1.0, cur):               # a tethered tripod shot is fine up to a second
                d = abs(math.log2(s_ / want))
                if best is None or d < best[0]:
                    best = (d, i)
        return None if best is None or best[1] == combo.currentIndex() else best[1]

    def _check_exposure(self, j):
        """A dark capture is the main cause of soft, grainy card photos: brightening it afterwards
        lifts the sensor noise with it. Say so the moment it lands, with the fix one click away."""
        under = float(getattr(j, "expo_under", 0.0) or 0.0)
        if under < 0.8:
            return
        import time as _t
        last = getattr(self, "_expo_told", (0.0, 0.0))
        if _t.time() - last[0] < 90 and abs(last[1] - under) < 0.5:
            return                                      # already said for this setup
        self._expo_told = (_t.time(), under)
        idx = self._shutter_for(under)
        combo = getattr(self, "cam_combos", {}).get("shutter")
        msg = (f"{os.path.basename(j.path)} is {under:.1f} stops darker than it should be, so it will look grainy "
               f"and soft once brightened. Let in about {2 ** under:.0f}× the light")
        if idx is not None:
            msg += f": shutter {combo.itemText(idx)} instead of {combo.currentText()}."
            self.notice(msg, "warn", action=(f"Use {combo.itemText(idx)}",
                                             lambda i=idx: (combo.setCurrentIndex(i), self.cam_set("shutter", i))))
        else:
            self.notice(msg + " (a slower shutter, or more light; keep ISO at 100).", "warn")

    # --- selection
    def step(self, d):
        r = self.listw.currentRow() + d
        if 0 <= r < len(self.jobs):
            self.listw.setCurrentRow(r)

    def select(self, row):
        if self.cur is not None and self.cur is not (self.jobs[row] if 0 <= row < len(self.jobs) else None):
            prev = self.cur
            tq = getattr(prev, "_thumb_quad", None)
            if prev.quad is not None and (tq is None or np.abs(np.asarray(prev.quad, np.float32) - tq).max() > 0.5):
                # its filmstrip picture is redrawn from the edges you set, straightened and toned
                t_ = ThumbOnlyTask(prev)
                t_.sig.done.connect(self.on_detected)
                self.pool.start(t_)
            self.cur.release()
            left = self.cur.card_name.strip()
            if left and (row < 0 or row >= len(self.jobs) or self.jobs[row].card_name.strip() != left):
                QTimer.singleShot(0, lambda n=left: self._maybe_auto_upload(n))    # moving on from a card
        if not (0 <= row < len(self.jobs)):
            return
        j = self.jobs[row]
        self.cur = j
        if self.stack.currentWidget() is self.live:
            self.show_live(False)
        self.title.setText(os.path.basename(j.path))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            src = j.source()
            if j.quad is None:
                j.detect()
                self._label(j)
        except Exception as e:  # noqa: BLE001
            j.error = str(e)
            self._label(j)
            self.editor.clear()
            self.statusBar().showMessage(f"Could not open: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        if not getattr(j, "_named", False) and not j.done:
            j._named = True
            # a carousel photo is its own card, never the back of the previous one
            pf = getattr(j, "_pair_of", None)
            if not j.card_name and not j.ig_only and pf is not None and pf.card_name.strip():
                # shot as the back of the photo before it: takes that card's name, whatever was exported last
                j.card_name, j.side, j.inherited = pf.card_name, "back", True
                if pf.card_info:
                    j.card_info = dict(pf.card_info)
            elif pf is not None:
                j.side = "back"                   # its front is not named yet: named with it later
            elif getattr(j, "_new_card", False):
                j.side = "front"                  # the front of a new pair: a card of its own
            elif not j.card_name and not j.ig_only:
                j.card_name, j.side = self.next_name, self.next_side
                j.inherited = bool(self.next_name)
                if self.next_side == "back" and self.next_info:
                    j.card_info = dict(self.next_info)
        self._maybe_reuse(j, src.shape)
        self.cent_lbl.setText("Centering …")
        self.card_lbl.set_frame(None)
        self.name_edit.setText(j.card_name)
        self._show_side()
        self.editor.view_rot = j.rotate % 360
        self.editor.set_image(to_qimage(src))
        mode = getattr(j, "mode", None)
        if mode is None:   # first visit: nothing found means start from a card shape
            mode = "shape" if (j.confidence == 0 and not j.edited and not getattr(j, "reused", False)) else "corners"
        self._set_mode(mode)
        self.editor.set_quad(j.quad)
        k = min(1.0, self.PREVIEW_MAX / max(src.shape[:2]))
        small = cv2.resize(engine.to8(src), None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else engine.to8(src)
        self.proxy = (small, k)
        self._show_conf()
        self.update_preview()
        self.measure_timer.start()
        self._show_listing()
        # the photo has the keys (I identifies, Enter exports); click the name field to type a name
        self.editor.setFocus()
        if (not j.card_name and not j.card_info and j.side == "front" and not j.done
                and self.c_auto_id.isChecked() and not getattr(j, "id_tried", False)):
            self.run_identify(j, auto=True)

    def _show_conf(self):
        j = self.cur
        if j is None or j.quad is None:
            self.conf_lbl.setText("")
            return
        if j.edited:
            self.conf_lbl.setText(f"<span style='color:{TH.OK}'>Adjusted by hand</span>")
        elif getattr(j, "reused", False):
            self.conf_lbl.setText(f"<span style='color:{TH.WARN}'>Not found: used {j.reused}</span>")
        elif j.confidence == 0:
            self.conf_lbl.setText(f"<span style='color:{TH.WARN}'>Not found: drag the card outline</span>")
        elif j.confidence >= 0.8:
            self.conf_lbl.setText(f"<span style='color:{TH.OK}'>Edges locked {j.confidence:.0%}</span>")
        else:
            self.conf_lbl.setText(f"<span style='color:{TH.WARN}'>Weak edges {j.confidence:.0%}: check corners</span>")

    # --- editing
    def on_edit(self):
        if self.cur is None:
            return
        self.cur.quad = self.editor.quad()
        self.cur.edited = True
        self.card_lbl.set_frame(None)
        self.preview_timer.start()

    def on_commit(self):
        if self.cur is None:
            return
        q = self.editor.quad()
        # Arrow-key nudges and shape-mode moves end here without passing through on_edit, so this is
        # where they count as yours too; left unmarked, a detection still running in the background
        # put the found corners back over them.
        if q is not None and (self.cur.quad is None or not np.allclose(q, self.cur.quad, atol=0.01)):
            self.cur.edited = True
        self.cur.quad = q
        self._label(self.cur)
        self._show_conf()
        self.update_preview()
        self.measure_timer.start()

    def redetect(self):
        if self.cur is None:
            return
        self.push_undo()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.cur.detect(force=True)
            self.cur.reused = False
        finally:
            QApplication.restoreOverrideCursor()
        self.editor.set_quad(self.cur.quad)
        self._label(self.cur)
        self._show_conf()
        self.update_preview()
        self.measure_timer.start()

    def rotate(self):
        if self.stack.currentWidget() is self.live:
            self.rotate_live(1)
            return
        if self.cur is None:
            return
        self.push_undo()
        self.cur.rotate = (self.cur.rotate + 90) % 360
        self.editor.set_view_rotation(self.cur.rotate)
        self.update_preview()
        self.measure_timer.start()

    # --- fallback, naming, undo, centering
    def _maybe_reuse(self, j: Job, shape):
        """Detection came up empty: start from the last card's corners when the
        photo is the same size (same camera spot), else from a card outline."""
        if j.edited or j.quad is None or j.confidence >= 0.5:
            return
        if self.last_quad is not None and shape is not None and tuple(shape[:2]) == self.last_size:
            j.quad = self.last_quad.copy()
            j.reused = "last corners"
        elif 1 in self.spots and shape is not None and j.confidence == 0:
            j.quad = self.spots[1] * np.array([shape[1], shape[0]], np.float32)
            j.reused = "spot 1"

    def card_shape(self):  # noqa: D401
        """Reset the outline to an upright card centred in the photo."""
        if self.cur is None or self.editor.qimg is None:
            return
        self.push_undo()
        q = engine.card_outline(self.editor.qimg.width(), self.editor.qimg.height())
        self.cur.quad, self.cur.edited = q, True
        self.cent_lbl.setText("Centering …")
        self._set_mode("shape")
        self.editor.set_quad(q)
        self.on_commit()

    # --- saved spots
    def _refresh_spots(self):
        for i, b in enumerate(self.spot_btns, 1):
            filled = i in self.spots
            b.setStyleSheet(f"background:{HANDLE}; color:#111; font-weight:700;" if filled else "color:#77777E;")
            b.setToolTip(f"Spot {i}: press {i} to jump here, Cmd+{i} to overwrite" if filled
                         else f"Spot {i} is empty: Cmd+{i} or Shift+click saves the current corners")

    def spot_clicked(self, i):
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.MetaModifier):
            self.save_spot(i)
        else:
            self.apply_spot(i)

    def save_spot(self, i):
        if self.stack.currentWidget() is self.live:
            if self.live.guide is not None:
                self.live_spots[i] = self.live.guide.copy()
                self.cfg.setValue(f"lv_spot_{i}", json.dumps(self.live.guide.tolist()))
                self.statusBar().showMessage(f"Saved this overlay as preset {i}")
            return
        if self.cur is None or self.cur.quad is None or self.editor.qimg is None:
            return
        W, H = self.editor.qimg.width(), self.editor.qimg.height()
        norm = self.cur.quad / np.array([W, H], np.float32)
        self.spots[i] = norm
        self.cfg.setValue(f"spot_{i}", json.dumps(norm.tolist()))
        self._refresh_spots()
        self.statusBar().showMessage(f"Saved these corners as spot {i}")

    def apply_spot(self, i):
        if self.stack.currentWidget() is self.live:
            if i in self.live_spots:
                self.live.guide = self.live_spots[i].copy()
                self._guide_edited(self.live.guide)
                self.live.update()
                self.statusBar().showMessage(f"Overlay preset {i}")
            else:
                self.statusBar().showMessage(f"Overlay preset {i} is empty: Cmd+{i} saves the current overlay")
            return
        if self.cur is None or self.editor.qimg is None:
            return
        if i not in self.spots:
            self.statusBar().showMessage(f"Spot {i} is empty: press Cmd+{i} to save the current corners there")
            return
        self.push_undo()
        W, H = self.editor.qimg.width(), self.editor.qimg.height()
        q = self.spots[i] * np.array([W, H], np.float32)
        self.cur.quad, self.cur.edited = q, True
        self._set_mode("corners")      # a spot is exact corners, not a card rectangle
        self.editor.set_quad(q)
        self.on_commit()
        self.statusBar().showMessage(f"Jumped to spot {i}")

    def cycle_loupe(self):
        f = self.editor.cycle_loupe()
        self.cfg.setValue("loupe_field", self.editor.field_idx)
        self.statusBar().showMessage(f"Loupe shows about {2 * f * 63:.0f} mm around the corner")
        self.editor.viewport().update()

    def _set_mode(self, mode):
        self.editor.set_mode(mode)
        if self.cur is not None:
            self.cur.mode = mode
        self.mode_corners.setChecked(mode != "shape")
        self.mode_shape.setChecked(mode == "shape")
        self.tips.setText(TIPS_SHAPE if mode == "shape" else TIPS_CORNERS)
        self.editor.setToolTip(self.tips.text())

    def _pick_mode(self, mode):
        cur = "shape" if self.mode_shape.isChecked() and not self.mode_corners.isChecked() else "corners"
        if getattr(self.cur, "mode", cur) != mode:
            self.toggle_mode()
        else:
            self._set_mode(mode)

    def toggle_mode(self):
        """Corners <-> card shape. Entering shape mode snaps the current outline
        to the nearest true card rectangle; leaving it frees the corners again."""
        if self.cur is None or self.cur.quad is None:
            return
        self.push_undo()
        self._set_mode("corners" if self.editor.mode == "shape" else "shape")
        self.cur.quad = self.editor.quad()
        self.cur.edited = True
        self.on_commit()

    def notice(self, text, kind="info", details="", action=None, secs=None):
        if (getattr(self, "stage", "") == "shoot" and self.tether.is_connected and kind in ("ok", "info")
                and not details and not action):
            # shooting tethered: news goes to the status line, never a toast over the live view
            self.statusBar().showMessage(text, int((secs or 8) * 1000))
            return
        self.banner.show_msg(text, kind, details, action, secs)

    def ui_size(self, d):
        """Cmd+= larger, Cmd+- smaller, Cmd+0 back to the default; remembered."""
        pt = set_ui_pt(DEFAULT_PT if d == 0 else TH.BASE_PT + d)
        self.cfg.setValue("ui_pt", pt)
        self.card_num.setStyleSheet(f"font-size:{pt + 8}pt;")
        self.update()
        self.sum_timer.start()
        if self.stage == "list":
            self.list_page.refresh()
        self.statusBar().showMessage(f"Text size {pt} pt  (Cmd+= larger, Cmd+- smaller, Cmd+0 default)")

    def toggle_left(self):
        """Cmd+\\ hides the filmstrip for more canvas."""
        vis = not self.left_panel.isVisible()
        self.left_panel.setVisible(vis)
        self.cfg.setValue("left_open", vis)

    # --- identification
    def _upright_core(self, j):
        src = j.source()
        s = engine.Settings(lock_ratio=self.settings.lock_ratio, margin_px=0,
                            auto_portrait=self.settings.auto_portrait, lens_k1=self.settings.lens_k1,
                            lens_profile=self.settings.lens_profile, lens_raw_only=self.settings.lens_raw_only,
                            lens_fit=self.settings.lens_fit)
        return engine.warp_card(src, j.quad, s, j.rotate)

    def run_identify(self, j, auto=False):
        j.id_tried = True
        try:
            card = self._upright_core(j)
        except Exception:  # noqa: BLE001
            return
        self.card_lbl_info.setText("Reading the card number…")
        j.id_auto = auto
        t = IdentifyTask(self.db, j, card, str(self.cfg.value("id_lang", "en")),
                         game=str(self.cfg.value("id_game", "pokemon")))
        # a bound method of this window, so Qt delivers the result on the UI thread
        t.sig.done.connect(self._identified)
        self.pool.start(t)

    def _identified(self, job, res):
        auto = getattr(job, "id_auto", True)
        reading, results, err = res
        job.id_reading = reading.text() if reading else ""
        if not job.id_reading and results and results[0].game != "pokemon":
            job.id_reading = results[0].number            # the code that was read
        job.id_edition = next((r.edition for r in results if r.edition), "")
        job.id_results = results
        sure = len(results) == 1 or (len(results) > 1 and self.db.sure_match(results))
        if job is not self.cur:
            if sure and not job.card_name:
                self._apply_info(job, results[0])
            return
        if err == "no-ocr":
            self.card_lbl_info.setText("The number reader is not installed. Press I to search by name.")
        elif err:
            self.card_lbl_info.setText(f"Lookup failed ({err}). Press I to search by name.")
        elif sure:
            self._apply_info(job, results[0])
            how = "  ·  matched to your photo out of " + str(len(results)) if len(results) > 1 else ""
            self.statusBar().showMessage(f"Identified {results[0].label()}{how}  ·  press I to change")
        elif results:
            same = len({(r.number, r.image) for r in results}) == 1 and results[0].game == "yugioh"
            self.card_lbl_info.setText(
                f"Read {job.id_reading}: printed in {len(results)} rarities. Press I and pick the one in your hand."
                if same else f"Read {job.id_reading}: {len(results)} possible cards. Press I to choose.")
            if not auto:
                self.open_identify()
        else:
            what = f"Read {job.id_reading}, but" if job.id_reading else "Could not read the card number, and"
            self.card_lbl_info.setText(f"{what} no card matched. Press I to search by name.")
