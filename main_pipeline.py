"""CardCrop window, part: the background pipeline while you shoot.

As each front lands in pair or batch shooting, its edges are found (as before) and then, on a
single low-priority thread so the camera never waits, the card is straightened, its number read
and looked up, and its price fetched. By the time you press E, the cards CardCrop is sure of are
named, priced and marked ready, and Ready exports all of them at once; what is left is the
review: weak edges, a card it could not read, or a number that fits several cards.

A mixin of app.Main; every method runs with self as the main window."""
from __future__ import annotations

import engine
from PySide6.QtCore import QThread, QThreadPool

from ui_tasks import IdentifyTask

ATTENTION = ("⚠", "!", "✕", "?")      # filmstrip marks that need you


class PipelineMixin:
    def _pipe_pool(self):
        if getattr(self, "bg_pool", None) is None:
            self.bg_pool = QThreadPool(self)
            self.bg_pool.setMaxThreadCount(1)             # one card at a time, behind everything else
            self.bg_pool.setThreadPriority(QThread.LowPriority)
        return self.bg_pool

    def _pipe_wants(self, j):
        """A front shot as part of a pair or batch, found, not yet named or read."""
        return (j in self.jobs and j.quad is not None and getattr(j, "_new_card", False)
                and not j.card_name.strip() and not j.card_info and not j.ig_only and not j.done
                and not getattr(j, "id_tried", False) and self.c_auto_id.isChecked())

    def pipe_detected(self, j):
        """Called once a photo's edges are found: reads the front in the background."""
        if not self._pipe_wants(j):
            return
        j.id_tried, j.id_auto, j.id_bg = True, True, True
        t = IdentifyTask(self.db, j, None, str(self.cfg.value("id_lang", "en")),
                         game=str(self.cfg.value("id_game", "pokemon")),
                         prep=lambda j=j: self._pipe_core(j))
        t.sig.done.connect(self._pipe_identified)
        self._pipe_pool().start(t)
        self._label(j)
        self._pipe_busy = getattr(self, "_pipe_busy", 0) + 1
        if getattr(self, "_pipe_run", None) is None:
            self._pipe_run = {"read": 0, "sure": 0}
        self._pipe_show()

    def _pipe_core(self, j):
        """Runs on the background thread: the straightened card, then the full photo let go again
        unless you have it open."""
        core = self._upright_core(j)
        if j is not self.cur:
            try:
                j.release()
            except Exception:  # noqa: BLE001
                pass
        return core

    def _pipe_show(self):
        box = getattr(self, "pipe_hud_box", None)
        if box is None:
            return
        n = self._pipe_busy
        if n:
            self.pipe_hud.start(f"Reading {n} card{'s' if n != 1 else ''}…")
        else:
            run = self._pipe_run or {"read": 0, "sure": 0}
            unsure = run["read"] - run["sure"]
            self.pipe_hud.finish(f"Read {run['read']} card{'s' if run['read'] != 1 else ''}"
                                 + (f", {unsure} to pick" if unsure else ""), ok=not unsure)
            self._pipe_run = None
        box.show()
        box.adjustSize()
        self.live_isl._place()

    def _pipe_identified(self, job, res):
        job.id_bg = False
        self._identified(job, res)              # sure: named, and its back takes the name
        self._pipe_busy = max(0, getattr(self, "_pipe_busy", 1) - 1)
        run = getattr(self, "_pipe_run", None) or {"read": 0, "sure": 0}
        self._pipe_run = run
        run["read"] += 1
        if job.card_info:
            run["sure"] += 1
            info = job.card_info
            self.pipe_hud.step(f"{info.get('name_en') or info.get('name', '')} {info.get('number', '')}".strip())
        else:
            self.pipe_hud.step(f"{job.stem}: " + ("pick the card" if getattr(job, "id_results", None)
                                                  else "number not read"))
        self._pipe_show()
        if job.card_info:
            info = job.card_info
            key = (info.get("id"), info.get("language", "en"))
            if key not in getattr(self, "_sugg_cache", {}):
                self._fetch_sugg(info, key, job.card_name.strip())   # priced before you get to List
        elif job in self.jobs:
            job.id_unsure = bool(getattr(job, "id_results", None))
        self._label(job)
        self._update_summary()

    # ---------- the review: what CardCrop is sure of goes out together
    def ready_jobs(self):
        """Photos of cards that need nothing from you: every side found with strong edges (or set by
        hand), the card identified, nothing exported yet."""
        groups = {}
        for j in self.jobs:
            if j.done or j.error or j.ig_only:
                continue
            nm = j.card_name.strip()
            if nm:
                groups.setdefault(nm, []).append(j)
        out = []
        for nm, js in groups.items():
            if not any(x.card_info for x in js):
                continue
            if any(x.quad is None or (x.confidence < 0.8 and not x.edited) for x in js):
                continue
            if any(getattr(x, "_pair_of", None) is not None and x._pair_of not in js for x in js):
                continue
            # a pair shot but its back not taken yet is not ready
            if any(getattr(x, "_new_card", False) for x in js) and not any(x.side == "back" for x in js) \
                    and getattr(self, "_pair_front", None) in js:
                continue
            out += js
        return out

    def export_ready(self):
        todo = self.ready_jobs()
        if not todo:
            self.notice("Nothing is ready on its own yet: cards are ready once both sides have strong "
                        "edges and the card is identified.", "info")
            return
        cards = len({j.card_name.strip() for j in todo})
        self.notice(f"Exporting {cards} ready card{'s' if cards != 1 else ''} ({len(todo)} photos)…", "info", secs=3)
        self.export_all(todo)

    def first_attention(self):
        return next((i for i, x in enumerate(self.jobs)
                     if not x.done and getattr(x, "mark", "") in ATTENTION), None)

    # ---------- fronts and backs put right, then read again
    def identify_jobs(self, jobs):
        """Reads each photo's card number in the background, one at a time, as the pipeline does for a
        new front; a sure match names it, and its back with it."""
        n = 0
        for j in jobs:
            if j not in self.jobs or j.done or j.ig_only or j.quad is None:
                continue
            j.id_tried, j.id_auto, j.id_bg = True, True, True
            t = IdentifyTask(self.db, j, None, str(self.cfg.value("id_lang", "en")),
                             game=str(self.cfg.value("id_game", "pokemon")),
                             prep=lambda j=j: self._pipe_core(j))
            t.sig.done.connect(self._pipe_identified)
            self._pipe_pool().start(t)
            self._label(j)
            self._pipe_busy = getattr(self, "_pipe_busy", 0) + 1
            n += 1
        if n:
            if getattr(self, "_pipe_run", None) is None:
                self._pipe_run = {"read": 0, "sure": 0}
            self._pipe_show()
        return n

    def identify_now(self):
        """The Identify button: reads the selected photos again, or the one open (which asks you to pick
        when the number fits several cards)."""
        rows = sorted({i.row() for i in self.listw.selectedIndexes()})
        jobs = [self.jobs[r] for r in rows if 0 <= r < len(self.jobs)]
        if len(jobs) > 1:
            for j in jobs:
                self._forget_card(j)
            n = self.identify_jobs(jobs)
            self.statusBar().showMessage(f"Reading {n} card{'s' if n != 1 else ''} again…")
            return
        if self.cur is not None:
            self._forget_card(self.cur, keep_typed=True)
            self.run_identify(self.cur, auto=False)

    def _forget_card(self, j, keep_typed=True):
        """Drops the card a photo was named for, unless you typed the name yourself."""
        auto = (not j.card_name.strip() or j.card_name == getattr(j, "auto_name", None)
                or getattr(j, "inherited", False))
        if keep_typed and not auto:
            return False
        j.card_name, j.card_info, j.auto_name, j.inherited = "", None, None, False
        j.id_tried, j.id_results, j.id_unsure = False, None, False
        if getattr(j, "mark", "") == "?":
            j.mark = ""
        return True

    def sort_sides(self):
        """Fronts and backs, as tiles: fix a missed back and every card after it in one go. The window
        stays open while the fronts are read, showing each card as it is named."""
        from ui_dialogs import SidesDialog
        jobs = [j for j in self.jobs if not j.done and not j.ig_only]
        if not jobs:
            self.notice("Nothing to sort: every photo here is exported already.", "info")
            return
        SidesDialog(self, jobs, self._thumb_pm).exec()

    def apply_sides(self, jobs, sides, reread=False, pairs=None):
        """Each front starts a card; each back joins its front (one you paired by hand, else the nearest
        front before it with no back yet) and takes its name. Fronts whose card is unknown, or that were
        not fronts before, are read again in the background. Returns the photos being read."""
        own = engine.pair_backs(sides, pairs)
        self._pair_front = None                   # whatever was waiting for its back is settled here
        for j, sd in zip(jobs, sides):
            j._named = True                       # never renamed again on opening from the next-up name
            if sd == "front":
                was_front = j.side == "front" and getattr(j, "_pair_of", None) is None \
                    and not getattr(j, "inherited", False)
                if not (not reread and was_front and bool(j.card_info)):
                    self._forget_card(j)
                j.side, j._new_card, j._pair_of = "front", True, None
        fronts = [j for j, sd in zip(jobs, sides) if sd == "front"]
        orphans = 0
        for i, (j, sd) in enumerate(zip(jobs, sides)):
            if sd != "back":
                continue
            self._forget_card(j, keep_typed=False)   # a back is always named after its front
            j.side, j._new_card = "back", False
            f = jobs[own[i]] if i in own else None
            j._pair_of = f
            if f is None:
                orphans += 1
            elif f.card_name.strip():
                j.card_name, j.auto_name, j.inherited = f.card_name, f.card_name, True
                j.card_info = dict(f.card_info) if f.card_info else None
        for j in jobs:
            self._label(j)
        todo = [f for f in fronts if not f.card_info and not f.card_name.strip()]
        n = self.identify_jobs(todo)
        reading = [f for f in todo if getattr(f, "id_bg", False)]
        if self.cur in jobs:
            self.name_edit.setText(self.cur.card_name)
            self._show_side()
            self._show_listing()
        self.save_session()
        self._update_next()
        msg = f"{len(fronts)} front{'s' if len(fronts) != 1 else ''}, {len(jobs) - len(fronts)} backs"
        msg += f"; reading {n} card{'s' if n != 1 else ''}" if n else ""
        if orphans:
            msg += f"; {orphans} back{'s have' if orphans != 1 else ' has'} no front before it"
        self.notice(msg, "warn" if orphans else "ok", secs=6)
        if hasattr(self, "list_page") and self.stage == "list":
            self.list_page.refresh()
        return reading

