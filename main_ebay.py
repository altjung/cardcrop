"""CardCrop window, part: eBay: the List stage, store categories, publishing, Instagram and listings.

A mixin of app.Main; every method runs with self as the main window."""
from __future__ import annotations

import cv2
import ebay
import engine
import identify
import json
import listing
import os
import re
import sys
import time
import ui_base as TH
from PySide6.QtCore import QThread, QThreadPool, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QLabel, QMessageBox, QSpinBox, QVBoxLayout
from ui_base import subprocess_reveal, to_qimage
from ui_dialogs import EbayAccountDialog, EbayReviewDialog, FolderListDialog, IGDialog, IdentifyDialog
from ui_tasks import CallTask, EbayPhotosTask, EbayPublishTask, EbayUploadTask, IGTask, PriceSetTask, PriceTask, _CardRelay, _Relay
from ui_viewer3d import Viewer3D
from ui_widgets import Island, _price_line, _short_needs, has_corner_photos


class EbayMixin:
    # --- the batch as cards (List stage)
    def _tone_key(self):
        return tuple(round(float(getattr(self.settings, k)), 3) for k in engine.EDIT_KEYS)

    def _thumb_pm(self, j):
        base = getattr(j, "thumb_base", None)
        if base is not None and getattr(j, "_tone_key", None) != self._tone_key():
            # the picture as it will be exported: your tone edits on it, never the raw
            j.thumb = engine.to8(engine.adjust(base, self.settings, scale=0.04)) if self.settings.has_edits() \
                else base
            j._tone_key = self._tone_key()
        t = getattr(j, "thumb", None)
        if t is None:
            return None
        pm = getattr(j, "_thumb_pm", None)
        if pm is None or getattr(j, "_thumb_src", None) is not t:
            pm = QPixmap.fromImage(to_qimage(t))
            j._thumb_pm, j._thumb_src = pm, t
        return pm

    def _card_names(self):
        out = []
        for x in self.jobs:
            n = x.card_name.strip()
            if n and n not in out and not x.ig_only:
                out.append(n)
        return out

    def _cards(self):
        prices, out = self._prices(), []
        for name in self._card_names():
            same = [x for x in self.jobs if x.card_name.strip() == name]
            front = next((x for x in same if x.side == "front"), same[0])
            info = next((x.card_info for x in same if x.card_info), None)
            title, num, set_, key = name, "", "", None
            if info:
                try:
                    ci = identify.CardInfo(**info)
                    title = ci.name_en or ci.name or name
                    num = ci.number + (f"/{ci.set_total}" if ci.set_total and "/" not in ci.number else "")
                    set_ = " · ".join(x for x in (ci.set_name_en or ci.set_name, ci.rarity) if x)
                except TypeError:
                    pass
                key = (info.get("id"), info.get("language", "en"))
            cond = next((x.condition for x in same if x.side == "back" and x.condition), "") or \
                next((x.condition for x in same if x.condition), "")
            price = float(prices.get(name, 0) or 0)
            folder = os.path.join(self.out_dir, engine.safe_name(name))
            photos = len(ebay.listing_photos(folder)) if os.path.isdir(folder) else 0
            igd = os.path.join(folder, "instagram")
            ig = os.path.isdir(igd) and any(f.lower().endswith(".jpg") for f in os.listdir(igd))
            tag = self._ebay_tag(name)
            need = self._needs(name, prices)
            busy = self._batch_state.get(name)
            if busy:
                sk, st, tip = ("need" if busy.startswith("Failed") else "idle"), busy, busy
            elif tag == "eBay: live":
                sk, st, tip = "live", "Live", ""
            elif tag == "eBay: sold":
                sk, st, tip = "sold", "Sold", "Sold on eBay. Have another copy? Tick it and Upload to list it again"
            elif tag == "eBay: unpublished":
                sk, st, tip = "unpub", "Unpublished", "Publish it from Review and publish"
            elif tag == "eBay: draft":
                sk, st, tip = "draft", "Draft", "In the drafts file for Seller Hub"
            elif not photos:
                sk, st, tip = "need", "Export first", "Export the front and back in Edit"
            elif need:
                sk, st, tip = "need", "Needs " + _short_needs(need), "Before listing: " + ", ".join(need)
            else:
                sk, st, tip = "ready", "Ready", ""
            r = self._sugg_cache.get(key) if key else None
            if key and r is None:
                self._fetch_sugg(info, key, name)
            sugg = (r or {}).get("suggested")
            out.append({"name": name, "title": title, "num": num, "set": set_, "cond": cond, "price": price,
                        "sugg": sugg, "market": ebay.market_of(r), "sugg_text": f"≈ {sugg:.2f}" if sugg else ("checking…" if key and r is None
                                                                                         else ""),
                        "store": "  +  ".join(c_[1].strip("/").replace("/", " › ") for c_ in
                                              (self.store_category_for(name), self.store_category_for(name, 2))
                                              if c_),
                        "photos": photos, "ig": ig, "folder": folder, "status_key": sk, "status": st,
                        "status_tip": tip, "pm": self._thumb_pm(front), "front": front})
        return out

    def _price_task(self, info, key, name=""):
        return PriceTask(self.ebay_client(), self.db, info, key, sku=engine.safe_name(name) if name else "",
                         pc_token=str(self.cfg.value("pc_token", "") or ""))

    def _fetch_sugg(self, info, key, name=""):
        if key in self._sugg_pending:
            return
        self._sugg_pending.add(key)
        if not hasattr(self, "price_pool"):
            self.price_pool = QThreadPool(self)
            self.price_pool.setMaxThreadCount(2)
        t = self._price_task(info, key, name)
        t.sig.done.connect(self._sugg_done)
        self.price_pool.start(t)

    def _autofill_price(self, key, r):
        """A card with no price of yours takes the suggestion, so a batch arrives in List priced.
        A price you set is never touched (Settings > App)."""
        sugg = (r or {}).get("suggested")
        if not sugg or str(self.cfg.value("price_autofill", "true")).lower() not in ("true", "1"):
            return
        prices = self._prices()
        auto = set(json.loads(str(self.cfg.value("prices_auto", "[]")) or "[]"))
        for x in self.jobs:
            info = x.card_info or {}
            nm = x.card_name.strip()
            if (nm and (info.get("id"), info.get("language", "en")) == key and not prices.get(nm)
                    and self._ebay_tag(nm) in ("", "eBay: sold")):   # never a card already up
                self._set_price(nm, sugg)
                auto.add(nm)
                prices[nm] = sugg
        self.cfg.setValue("prices_auto", json.dumps(sorted(auto)))

    def _sugg_done(self, key, r):
        self._sugg_pending.discard(key)
        self._sugg_cache[key] = r
        self._autofill_price(key, r)
        if self.stage == "list":
            if not hasattr(self, "_list_timer"):
                self._list_timer = QTimer(self, singleShot=True, interval=300)
                self._list_timer.timeout.connect(self.list_page.refresh)
            self._list_timer.start()

    def push_price(self, label, item_id, sku, price, done=None):
        """Changes a listing's price on eBay, whatever made it, in the background."""
        c = self.ebay_client()
        if c is None or not c.signed_in():
            self.notice("Connect eBay in Settings > eBay to change prices on eBay.", "warn")
            return False
        t = PriceSetTask(c, label, sku, float(price), item_id)

        def finished(key, pr, err):
            if err:
                self.notice(f"{key}: eBay did not take ${pr:,.2f}: {err}", "error")
            else:
                self.notice(f"{key} is now ${pr:,.2f} on eBay", "ok", secs=3)
                for a in (getattr(self, "store_page", None) and (self.store_page.data or {}).get("active", [])) or []:
                    if (item_id and a.get("id") == item_id) or (sku and a.get("sku") == sku):
                        a["price"] = pr
            if done:
                done(err)
        r = _Relay(finished)
        r._sig = t.sig
        t.sig.done.connect(r.fire)
        QThreadPool.globalInstance().start(t)
        self.notice(f"Updating {label} on eBay to ${float(price):,.2f}…", "info", secs=2)
        return True

    def _set_price(self, name, v):
        self._mark_changed(name)
        p = self._prices()
        p[name] = round(float(v), 2)
        self.cfg.setValue("prices", json.dumps(p))
        if self.cur is not None and self.cur.card_name.strip() == name:
            self.price.blockSignals(True)
            self.price.setValue(v)
            self.price.blockSignals(False)
            self._show_listing()
        self._relabel(name)

    def open_card(self, name):
        same = [i for i, x in enumerate(self.jobs) if x.card_name.strip() == name]
        if not same:
            return
        i = next((i for i in same if self.jobs[i].side == "front"), same[0])
        self.go("edit")
        self.listw.setCurrentRow(i)

    def _batch_ready(self, names, need_photos=True):
        """Splits names into what can go now and why the rest cannot."""
        ok, problems = [], []
        for name in names:
            L = self._listing_for(name)
            folder = os.path.join(self.out_dir, engine.safe_name(name))
            price = float(self._prices().get(name, 0) or 0)
            miss = [w for w, good in (("identifying", L is not None),
                                      ("a condition", bool(L and L.get("condition"))),
                                      ("a price", price > 0),
                                      ("exported photos", (not need_photos) or
                                       (os.path.isdir(folder) and bool(ebay.listing_photos(folder)))))
                    if not good]
            if miss:
                problems.append(f"{name}: needs {', '.join(miss)}")
            else:
                ok.append((name, folder, L, price))
        return ok, problems

    def _ebay_ready_client(self):
        c = self.ebay_client()
        if not c or not c.signed_in():
            self.notice("Connect eBay first: add your keys and sign in.", "warn")
            self.ebay_account()
            return None
        return c

    def set_auto_upload(self, on):
        self.cfg.setValue("auto_upload", on)
        if on:
            c = self.ebay_client()
            if not c or not c.signed_in():
                self.notice("Auto-upload needs eBay: sign in under eBay account.", "warn",
                            action=("Open", self.ebay_account))
            else:
                self.notice("Auto-upload is on: finished cards go up unpublished as you move on. "
                            "Publish them from List when the batch is done.", "ok")
                for n in self._card_names():
                    self._maybe_auto_upload(n)

    def _mark_changed(self, name):
        """A price or grade changed on a card that is already up but unpublished: send it again."""
        if name and self._ebay_tag(name) == "eBay: unpublished":
            self._dirty = getattr(self, "_dirty", set()) | {name}

    def _maybe_auto_upload(self, name):
        if not name or not self.c_auto.isChecked():
            return
        if name in getattr(self, "_uploading_names", set()):
            return
        tag = self._ebay_tag(name)
        dirty = name in getattr(self, "_dirty", set())
        if tag and not (dirty and tag == "eBay: unpublished"):
            return
        same = [x for x in self.jobs if x.card_name.strip() == name]
        sides = {x.side for x in same if x.done}
        if not {"front", "back"} <= sides or any(x.ig_only for x in same):
            return                                 # wait until both sides are exported
        if self._needs(name):
            return
        c = self.ebay_client()
        if not c or not c.signed_in():
            return
        self._dirty = getattr(self, "_dirty", set()) - {name}
        self.batch_upload([name], quiet=True, update=dirty)

    def _video_settings(self):
        """How the 360° listing videos are made (Add video in Store, Market and Reports)."""
        import card3d
        w = Island()
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(12)
        v.addWidget(QLabel("The 360° videos made by Add video in Store, Market and Reports. Each is saved as an "
                           "MP4 in the card's folder and uploaded to the listing", objectName="small"))
        f = QFormLayout()
        f.setSpacing(10)
        cfg = self.cfg

        def combo(key, items, default, cast=str):
            c = QComboBox()
            for data, label in items:
                c.addItem(label, data)
            cur = cfg.value(key, default)
            try:
                cur = cast(cur)
            except (TypeError, ValueError):
                cur = default
            c.setCurrentIndex(max(0, c.findData(cur)))
            c.currentIndexChanged.connect(lambda _i: cfg.setValue(key, c.currentData()))
            c.setFixedWidth(340)
            return c
        f.addRow("Size", combo("3d_size", [(i, lbl) for i, (_wh, lbl) in enumerate(Viewer3D.SIZES)], 0, int))
        f.addRow("Frame rate", combo("3d_fps", [(30, "30 fps"), (60, "60 fps"), (120, "120 fps")], 30, int))
        f.addRow("Quality", combo("3d_quality", [("standard", "Standard H.264"),
                                                 ("high", "High H.264, supersampled")], "standard"))
        f.addRow("Motion", combo("3d_motion", Viewer3D.MOTIONS, "loop"))
        f.addRow("Camera", combo("3d_camera", Viewer3D.CAMERAS, ""))
        for key, label in (("3d_mblur", "Motion blur (8 times slower to render)"),
                           ("3d_focuspull", "Pull focus onto the card at the start")):
            cb = QCheckBox(label)
            cb.setChecked(str(cfg.value(key, "0")) == "1")
            cb.toggled.connect(lambda on, k=key: cfg.setValue(k, "1" if on else "0"))
            f.addRow("", cb)
        f.addRow("Entrance", combo("3d_video_entrance", [("", "None")] +
                                   [(k, lbl) for k, (lbl, _fn) in card3d.ENTRANCES.items()], ""))
        f.addRow("Outro", combo("3d_video_outro", [("", "None")] +
                                [(k, lbl) for k, (lbl, _fn) in card3d.OUTROS.items()], ""))
        f.addRow("Background", combo("3d_bg", Viewer3D.BGS, "#18181A"))
        secs = QSpinBox()
        secs.setRange(2, 30)
        secs.setSuffix(" s")
        secs.setValue(int(cfg.value("3d_secs", 6)))
        secs.valueChanged.connect(lambda x: cfg.setValue("3d_secs", x))
        secs.setFixedWidth(120)
        f.addRow("Length", secs)
        v.addLayout(f)
        note = QLabel("4K at 120 fps takes a few minutes per card to render. eBay re-encodes listing videos for "
                      "its apps, so 4K and 120 fps pay off in the MP4 you keep and post elsewhere; when a video "
                      "is over eBay's 150 MB limit, a smaller copy is uploaded and yours is kept as made.",
                      objectName="small")
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch(1)
        return w

    # ---------- eBay Store categories
    def store_cats(self):
        try:
            return [tuple(x) for x in json.loads(str(self.cfg.value("store_cat_list", "[]")) or "[]")]
        except ValueError:
            return []

    def refresh_store_cats(self, then=None):
        c = self._ebay_ready_client() if hasattr(self, "_ebay_ready_client") else self.ebay_client()
        if c is None or not c.signed_in():
            return
        self.notice("Reading your eBay Store categories…", "info", secs=2)

        def done(cats, err):
            if err:
                self.notice(f"Store categories could not be read: {err}", "error")
                return
            self.cfg.setValue("store_cat_list", json.dumps(cats))
            self.notice(f"{len(cats)} store categories.", "ok", secs=3)
            if then:
                then()
        t = CallTask(c.store_categories)
        t.then(done)
        QThreadPool.globalInstance().start(t)

    @staticmethod
    def _store_keys(slot):
        return ("store_cats", "store_cat_default") if slot == 1 else ("store_cats2", "store_cat_default2")

    def _store_map(self, slot=1):
        try:
            return json.loads(str(self.cfg.value(self._store_keys(slot)[0], "{}")) or "{}")
        except ValueError:
            return {}

    def store_category_for(self, name, slot=1):
        """(id, path) of the store category a card lists into (slot 1, or the second, slot 2): its own
        choice, else the default."""
        v = self._store_map(slot).get(name) if name else None
        if v is None:
            try:
                v = json.loads(str(self.cfg.value(self._store_keys(slot)[1], "null")) or "null")
            except ValueError:
                v = None
        return tuple(v) if v and v[1] else None

    def set_store_category(self, names, cat, slot=1):
        """cat: (id, path), ('', '') for none, or None to follow the default. names=None sets the default.
        slot 2 is the second store category a listing can also show in."""
        which = "" if slot == 1 else "second "
        if names is None:
            self.cfg.setValue(self._store_keys(slot)[1], json.dumps(list(cat) if cat else None))
            self.notice(f"New listings' {which}store category: {cat[1].strip('/').replace('/', ' › ')}"
                        if cat and cat[1] else f"New listings get no {which}store category", "ok", secs=3)
            self._sync_store_default()
            return
        m = self._store_map(slot)
        for n in names:
            if cat is None:
                m.pop(n, None)
            else:
                m[n] = list(cat)
        self.cfg.setValue(self._store_keys(slot)[0], json.dumps(m))
        # cards CardCrop already put on eBay move straight away
        c = self.ebay_client()
        on = [n for n in names if self._ebay_tag(n) in ("eBay: live", "eBay: unpublished")]
        if on and c is not None and c.signed_in():
            for n in on:
                cur, cur2 = self.store_category_for(n), self.store_category_for(n, 2)
                t = CallTask(c.set_store_category, ebay.live_sku(self.out_dir, engine.safe_name(n)), cur[1] if cur else "",
                             cur2[1] if cur2 else "")
                t.then(lambda _r, err, n=n: self.notice(f"{n}: the store category did not change on eBay: {err}",
                                                        "error") if err else None)
                QThreadPool.globalInstance().start(t)
        if hasattr(self, "list_page"):
            self.list_page.refresh()

    def store_cat_menu(self, menu, names):
        """Fills a menu with your store categories, for the given cards (None: the default): the first
        category, then a second one the listing also shows in."""
        menu.clear()
        for slot, label in ((1, "First category"), (2, "Second category")):
            cur = self.store_category_for(names[0], slot) if names and len(names) == 1 else (
                self.store_category_for(None, slot) if names is None else None)
            sub = menu.addMenu(label + (f":  {cur[1].strip('/').replace('/', ' › ')}" if cur else ""))
            self._store_cat_items(sub, names, slot)
        menu.addSeparator()
        menu.addAction("Read my store categories from eBay", lambda: self.refresh_store_cats())

    def _store_cat_items(self, menu, names, slot):
        cats = self.store_cats()
        cur = self.store_category_for(names[0], slot) if names and len(names) == 1 else (
            self.store_category_for(None, slot) if names is None else None)
        if names is not None:
            d = self.store_category_for(None, slot)
            menu.addAction("Use the default" + (f" ({d[1].strip('/').replace('/', ' › ')})" if d else " (none)"),
                           lambda: self.set_store_category(names, None, slot))
        menu.addAction("No store category", lambda: self.set_store_category(names, ("", ""), slot))
        menu.addSeparator()
        if not cats:
            a = menu.addAction("No categories yet: read them from eBay")
            a.setEnabled(False)
        for cid, path in cats:
            depth = path.count("/") - 1
            a = menu.addAction("      " * depth + path.rsplit("/", 1)[-1],
                               lambda cid=cid, path=path: self.set_store_category(names, (cid, path), slot))
            a.setCheckable(True)
            a.setChecked(bool(cur) and cur[1] == path)

    def _sync_store_default(self):
        if getattr(self, "b_store_def", None) is not None:
            d, d2 = self.store_category_for(None), self.store_category_for(None, 2)
            self.b_store_def.setText("Default store category:  " + (d[1].strip("/").replace("/", " › ") if d
                                                                   else "none")
                                     + (f"  ·  second: {d2[1].strip('/').replace('/', ' › ')}" if d2 else ""))

    def list_reupload(self, name):
        """Sends a card to eBay again: after a failed upload, or after its listing was deleted on eBay."""
        sku = ebay.sku_for(engine.safe_name(name))
        tag = self._ebay_tag(name)
        title = name
        if tag == "eBay: unpublished":
            self.batch_upload([name], update=True)     # the same unpublished listing, sent again
            return
        if tag == "eBay: live":
            if QMessageBox.question(self, "Upload again",
                                    f"CardCrop has {title} as live on eBay. Uploading again makes a second "
                                    "listing unless the first one was ended or deleted. Upload it again?") \
                    != QMessageBox.Yes:
                return
        ebay.forget_record(self.out_dir, sku)
        self._rec_cache = None
        self.batch_upload([name])
        self.list_page.refresh()

    def list_remove(self, names):
        """Takes cards out of CardCrop (for ones you listed by hand), with the photos left on disk.
        A copy CardCrop uploaded but never published can be deleted from eBay at the same time."""
        names = [n for n in names if n]
        if not names:
            return
        recs = self._records()
        unpub = [n for n in names if recs.get(ebay.sku_for(engine.safe_name(n)), {}).get("offer_id")
                 and recs.get(ebay.sku_for(engine.safe_name(n)), {}).get("status") != "published"]
        live = [n for n in names if self._ebay_tag(n) == "eBay: live"]
        one = len(names) == 1
        box = QMessageBox(self)
        box.setWindowTitle("Remove from CardCrop")
        box.setText((f"Remove {names[0]} from CardCrop?" if one else f"Remove {len(names)} cards from CardCrop?")
                    + " The photos stay in their folders, and Cmd+Z brings "
                    + ("it" if one else "them") + " back.")
        info = []
        if live:
            info.append(("It is" if one else f"{len(live)} are") + " live on eBay from CardCrop; that listing "
                        "stays up. End it from Store, Listings, if it is the double.")
        box.setInformativeText("\n\n".join(info))
        chk = None
        if unpub:
            chk = QCheckBox(("Also delete CardCrop's unpublished copy on eBay" if len(unpub) == 1 else
                             f"Also delete CardCrop's {len(unpub)} unpublished copies on eBay")
                            + " (this part cannot be undone)")
            chk.setChecked(True)
            box.setCheckBox(chk)
        b_rm = box.addButton("Remove", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(b_rm)
        box.exec()
        if box.clickedButton() is not b_rm:
            return
        if chk is not None and chk.isChecked():
            c = self.ebay_client()
            if c is not None and c.signed_in():
                for n in unpub:
                    sku = ebay.sku_for(engine.safe_name(n))

                    def gone(_r, err, sku=sku, n=n):
                        if err and "25710" not in err and "not found" not in err.lower():
                            self.notice(f"The eBay copy of {n} was not deleted: {err}", "error")
                            return
                        ebay.forget_record(self.out_dir, sku)
                        self._rec_cache = None
                        self.notice(f"Deleted CardCrop's unpublished copy of {n} on eBay.", "ok", secs=4)
                    t = CallTask(c.delete_item, sku)
                    t.then(gone)
                    QThreadPool.globalInstance().start(t)
            else:
                self.notice("Sign in to eBay to delete the unpublished copies; the cards are removed here.", "warn")
        rows = [i for i, x in enumerate(self.jobs) if x.card_name.strip() in set(names)]
        self.list_page.selected -= set(names)
        self.remove_jobs(rows)
        self.list_page.refresh()

    def batch_upload(self, names, quiet=False, update=False, relist=False):
        c = self.ebay_client() if quiet else self._ebay_ready_client()
        if c is None or not c.signed_in():
            return
        pols = {k: str(self.cfg.value(f"ebay_pol_{k}", "")) for k in ("fulfillment", "return", "payment")}
        zip_code = str(self.cfg.value("ebay_zip", ""))
        if not all(pols.values()) or not zip_code:
            if not quiet or not getattr(self, "_told_policies", False):
                self._told_policies = quiet
                self.notice("Choose your shipping, return and payment policies and ship-from ZIP in eBay account….",
                            "warn", action=("Open", self.ebay_account))
            return
        busy = set(getattr(self, "_uploading_names", set()))
        # a card already on eBay, or already on its way, is never sent again by accident
        asked = list(names)
        names = [n for n in names if n not in busy and
                 (not self._ebay_tag(n) or (update and self._ebay_tag(n) == "eBay: unpublished")
                  or (relist and self._ebay_tag(n) in ("eBay: sold", "eBay: live")))]   # another copy of the card
        if not names and asked and not quiet:
            on = [n for n in asked if self._ebay_tag(n) == "eBay: unpublished"]
            self.notice(f"{len(on)} card(s) are already on eBay, unpublished: use Publish to put them live."
                        if on else "Those cards are already on eBay or uploading.", "info",
                        action=("Publish", lambda o=on: self.batch_publish(o)) if on else None)
            return
        ok, problems = self._batch_ready(names)
        if problems and not quiet:
            self.notice(f"{len(problems)} card(s) are not ready" + (f"; the other {len(ok)} are uploading."
                                                                   if ok else "."),
                        "warn", "\n".join(problems))
        if not ok:
            return
        if not hasattr(self, "net_pool"):
            self.net_pool = QThreadPool(self)
            self.net_pool.setThreadPriority(QThread.LowPriority)   # never at the live view's expense
            self.net_pool.setMaxThreadCount(1)
        need_loc = str(self.cfg.value("ebay_location_zip", "")) != zip_code
        self._uploading_names = busy | {n for n, *_ in ok}
        if not busy:
            self._batch_counts = {"ok": 0, "failed": 0}
        self._relays = getattr(self, "_relays", [])
        for k, (name, folder, L, price) in enumerate(ok):
            t = EbayUploadTask(c, name, folder, L, price, pols, zip_code, self.out_dir, need_loc and k == 0,
                               self.ebay_package())
            r = _CardRelay(self, name)             # lives on the UI thread, so each card hears only its own news
            t.sig.progress.connect(r.progress)
            t.sig.done.connect(r.done)
            self._relays.append(r)
            self._batch_state[name] = "Waiting…"
            self.net_pool.start(t)
        self.list_page.selected -= {n for n, *_ in ok}
        self.list_page.refresh()

    def _card_progress(self, name, msg):
        self._batch_state[name] = msg
        if self.stage == "list":
            self.list_page.refresh_status(name)

    def _card_uploaded(self, name, res):
        oid, err = res
        self._uploading_names.discard(name)
        if err:
            self._batch_state[name] = f"Failed: {err}"
            self._batch_counts["failed"] += 1
        else:
            self._batch_state.pop(name, None)
            self._batch_counts["ok"] += 1
            self.cfg.setValue("ebay_location_zip", str(self.cfg.value("ebay_zip", "")))
        self._relabel(name)
        if not self._uploading_names:
            n, f = self._batch_counts["ok"], self._batch_counts["failed"]
            self._relays = []
            if n:
                self.chime("listed")
            if self.c_auto.isChecked() and self.stage != "list" and not f:
                self.statusBar().showMessage(f"Auto-upload: {n} card(s) on eBay, unpublished")
                self.list_page.refresh()
                return
            self.notice(f"{n} card(s) are on eBay, unpublished" +
                        (f"; {f} failed: tick them and upload again" if f else ". Tick them and press Publish."),
                        "warn" if f else "ok")
        self.list_page.refresh()

    def batch_publish(self, names):
        c = self._ebay_ready_client()
        if c is None:
            return
        recs = ebay.load_records(self.out_dir)
        todo = [(n, recs[ebay.sku_for(engine.safe_name(n))]["offer_id"]) for n in names
                if (recs.get(ebay.sku_for(engine.safe_name(n))) or {}).get("offer_id")
                and recs[ebay.sku_for(engine.safe_name(n))].get("status") != "published"]
        if not todo:
            return
        total = sum(float(self._prices().get(n, 0) or 0) for n, _ in todo)
        if QMessageBox.question(self, "Publish on eBay",
                                f"Put {len(todo)} listing(s) live on eBay now, ${total:,.2f} in all?") \
                != QMessageBox.Yes:
            return
        if not hasattr(self, "net_pool"):
            self.net_pool = QThreadPool(self)
            self.net_pool.setThreadPriority(QThread.LowPriority)   # never at the live view's expense
            self.net_pool.setMaxThreadCount(1)
        self._publishing = {n for n, _ in todo}
        self._pub_counts = {"ok": 0, "failed": 0}
        self._relays = getattr(self, "_relays", [])
        for name, oid in todo:
            t = EbayPublishTask(c, name, oid, self.out_dir)
            r = _CardRelay(self, name)
            t.sig.done.connect(r.published)
            self._relays.append(r)
            self._batch_state[name] = "Publishing…"
            self.net_pool.start(t)
        self.list_page.selected -= self._publishing
        self.list_page.refresh()

    def _card_published(self, name, err):
        self._publishing.discard(name)
        if err:
            self._batch_state[name] = f"Failed: {err}"
            self._pub_counts["failed"] += 1
        else:
            self._batch_state.pop(name, None)
            self._pub_counts["ok"] += 1
        self._relabel(name)
        if not self._publishing:
            n, f = self._pub_counts["ok"], self._pub_counts["failed"]
            if n:
                self.chime("listed")
            self.notice(f"{n} card(s) are live on eBay" + (f"; {f} could not be published" if f else ""),
                        "warn" if f else "ok")
        self.list_page.refresh()

    def batch_drafts(self, names):
        c = self._ebay_ready_client()
        if c is None:
            return
        tpl = str(self.cfg.value("ebay_template", ""))
        if not tpl or not os.path.exists(tpl):
            tpl, _ = QFileDialog.getOpenFileName(
                self, "eBay drafts template (Seller Hub > Reports > Uploads > Get template > Listings > "
                "Create new drafts)", os.path.expanduser("~/Downloads"), "CSV files (*.csv)")
            if not tpl:
                return
            self.cfg.setValue("ebay_template", tpl)
        ok, problems = self._batch_ready(names)
        if problems:
            self.notice(f"{len(problems)} card(s) are not ready" + (f"; drafting the other {len(ok)}." if ok else "."),
                        "warn", "\n".join(problems))
        if not ok:
            return
        self._dq, self._drafts, self._tpl, self._dclient = list(ok), [], tpl, c
        for name, *_ in ok:
            self._batch_state[name] = "Waiting…"
        self.list_page.refresh()
        self._draft_next()

    def _draft_next(self):
        if not self._dq:
            self._write_batch_drafts()
            return
        name, folder, L, price = self._dq[0]
        self._batch_state[name] = "Uploading photos…"
        t = EbayPhotosTask(self._dclient, folder)
        t.sig.progress.connect(self._draft_progress)
        t.sig.done.connect(self._draft_done)
        if not hasattr(self, "net_pool"):
            self.net_pool = QThreadPool(self)
            self.net_pool.setThreadPriority(QThread.LowPriority)   # never at the live view's expense
            self.net_pool.setMaxThreadCount(1)
        self.net_pool.start(t)
        self.list_page.refresh()

    def _draft_progress(self, msg):
        if self._dq:
            self._batch_state[self._dq[0][0]] = msg
            self.list_page.refresh() if self.stage == "list" else None

    def _draft_done(self, urls, err):
        name, folder, L, price = self._dq.pop(0)
        if err:
            self._batch_state[name] = f"Failed: {err}"
        else:
            names = {k: str(self.cfg.value(f"ebay_pol_{k}_name", "")) for k in ("fulfillment", "return", "payment")}
            self._drafts.append(dict(L, extra=listing.draft_extras(urls, price, str(self.cfg.value("ebay_zip", "")),
                                                                   names, self.ebay_package(),
                                                                   L.get("store_category"),
                                                                   L.get("store_category2"))))
            ebay.save_record(self.out_dir, ebay.sku_for(engine.safe_name(name)), {
                "name": name, "title": L["title"], "price": price, "condition": L.get("condition", ""),
                "photos": len(urls), "drafted": time.strftime("%Y-%m-%d %H:%M")})
            self._batch_state.pop(name, None)
            self._relabel(name)
        self._draft_next()

    def _write_batch_drafts(self):
        self.list_page.refresh()
        if not self._drafts:
            return
        out = os.path.join(self.out_dir, f"ebay_drafts_{time.strftime('%Y%m%d-%H%M')}.csv")
        try:
            os.makedirs(self.out_dir, exist_ok=True)
            rep_ = listing.fill_ebay_template(self._tpl, self._drafts, out)
        except Exception as e:  # noqa: BLE001
            self.notice("Could not write the drafts file.", "error", str(e))
            return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        subprocess_reveal(out)
        QDesktopServices.openUrl(QUrl("https://www.ebay.com/sh/reports/uploads"))
        blank = [h.lstrip("*") for h in rep_["required_left_blank"]]
        self.notice(f"{rep_['rows']} card(s) are in {os.path.basename(out)}, photos already on eBay. "
                    "Press Upload template in Seller Hub and choose it.", "ok",
                    "Finder is showing the file and Seller Hub's Uploads page is open. The cards then appear in "
                    "your eBay Drafts." + ("\n\nColumns CardCrop could not fill: " + ", ".join(blank[:8])
                                           if blank else ""))

    def batch_ig(self, names):
        n = 0
        for name in names:
            front = next((x for x in self.jobs if x.card_name.strip() == name and x.side == "front"
                          and x.quad is not None), None)
            if front is not None:
                self._start_ig(front)
                n += 1
        self.notice(f"Writing Instagram slides for {n} card(s) in the background." if n
                    else "Nothing to make slides from: the cards need a detected front.", "info" if n else "warn")

    # --- eBay
    def _prices(self) -> dict:
        try:
            return json.loads(str(self.cfg.value("prices", "")) or "{}")
        except ValueError:
            return {}

    def on_price(self, v):
        j = self.cur
        if j is None or not j.card_name.strip():
            return
        p = self._prices()
        p[j.card_name.strip()] = round(float(v), 2)
        self.cfg.setValue("prices", json.dumps(p))
        self._mark_changed(j.card_name.strip())
        self._show_listing()                 # the title can change with the price (CLEAN)
        self._relabel(j.card_name.strip())

    def check_price(self, force=False):
        j = self.cur
        info = j.card_info if j else None
        if not info:
            self.price_info.setText("")
            self.b_use_price.setEnabled(False)
            return
        key = (info.get("id"), info.get("language", "en"))
        if not force and getattr(self, "_price_key", None) == key:
            return
        self._price_key, self._suggested, self._market = key, None, None
        self._sync_quick()
        self.b_use_price.setEnabled(False)
        self.price_info.setText("Checking eBay and TCGplayer prices…")
        if not hasattr(self, "price_pool"):
            self.price_pool = QThreadPool(self)
            self.price_pool.setMaxThreadCount(2)
        t = self._price_task(info, key, j.card_name.strip())
        t.sig.done.connect(self._price_done)
        self.price_pool.start(t)

    def _price_done(self, key, r):
        if hasattr(self, "_sugg_cache"):
            self._sugg_cache[key] = r
        self._autofill_price(key, r)
        if key != getattr(self, "_price_key", None):
            return                       # moved on to another card meanwhile
        self._suggested = r.get("suggested")
        self._market = ebay.market_of(r)
        self._sync_quick()
        self.price_info.setText(_price_line(r))
        self.price_info.setToolTip(re.sub(r"<[^>]+>", "", ebay.price_summary(r)).replace("  ·  ", "\n"))
        self.b_use_price.setEnabled(bool(self._suggested))
        self.b_use_price.setText(f"Use ${self._suggested:.2f}" if self._suggested else "Use suggested")

    def quick_price(self, kind):
        v = ebay.price_shortcut(kind, self.price.value(), getattr(self, "_market", None))
        if v is not None:
            self.price.setValue(v)

    def _sync_quick(self):
        m = getattr(self, "_market", None)
        for k, b in getattr(self, "price_quick", {}).items():
            b.setEnabled(bool(m) if k != "ceil" else True)
            if k == "m0":
                b.setText(f"Market ${m:.2f}" if m else "Market")

    def use_suggested(self):
        if getattr(self, "_suggested", None):
            self.price.setValue(self._suggested)

    def _show_price(self):
        self.check_price()
        j = self.cur
        self.price.blockSignals(True)
        self.price.setValue(float(self._prices().get(j.card_name.strip(), 0)) if j and j.card_name.strip() else 0)
        self.price.blockSignals(False)
        self._ebay_status()

    def ebay_package(self):
        return {k: float(self.cfg.value(f"ebay_pkg_{k}", d)) for k, d in (("oz", 3.0), ("l", 6.0), ("w", 4.0),
                                                                          ("h", 1.0))}

    def ebay_route(self):
        r = str(self.cfg.value("ebay_route", "direct"))
        return r if r in self.ROUTES else "direct"

    def set_ebay_route(self, route):
        self.cfg.setValue("ebay_route", route)
        self._route_ui()

    def _route_ui(self):
        r = self.ebay_route()
        other = "drafts" if r == "direct" else "direct"
        self.a_other.setText(("Make a Seller Hub draft instead" if other == "drafts"
                              else "Upload unpublished (API) instead"))
        self.a_route[r].setChecked(True)
        if hasattr(self, "list_page") and self.stage == "list":
            self.list_page.refresh()

    def ebay_primary(self):
        (self.ebay_upload if self.ebay_route() == "direct" else self.ebay_draft_current)()

    def ebay_other(self):
        (self.ebay_draft_current if self.ebay_route() == "direct" else self.ebay_upload)()

    def ebay_draft_current(self):
        j = self.cur
        name = j.card_name.strip() if j else ""
        folder = os.path.join(self.out_dir, engine.safe_name(name)) if name else ""
        if not name or not os.path.isdir(folder):
            self.notice("Export the card first, or use List exported folders… in the ⋯ menu for folders "
                        "you exported earlier.", "warn")
            return
        self.list_folders([folder])

    def ebay_client(self):
        app_id, runame = str(self.cfg.value("ebay_app_id", "")), str(self.cfg.value("ebay_runame", ""))
        if not (app_id and runame):
            return None
        c = getattr(self, "_ebay", None)       # keep one client so its 2-hour access token is reused
        if c is None or (c.app_id, c.runame) != (app_id, runame):
            c = self._ebay = ebay.Client(app_id, runame)
        return c

    def _ebay_status(self):
        c = self.ebay_client()
        self.ebay_state.setText("signed in" if c and c.signed_in() else "not connected")
        j = self.cur
        rec = ebay.load_records(self.out_dir).get(ebay.sku_for(engine.safe_name(j.card_name))) \
            if j and j.card_name.strip() else None
        if rec and not getattr(self, "_uploading", False):
            self.ebay_msg.setText("Live on eBay" if rec.get("status") == "published"
                                  else f"Uploaded, not published ({rec.get('uploaded', '')}). "
                                       "Uploading again updates it.")
        elif not getattr(self, "_uploading", False):
            self.ebay_msg.setText("")

    def list_folders(self, folders):
        if not folders:
            d = QFileDialog.getExistingDirectory(self, "A card folder, or a folder of card folders", self.out_dir)
            if not d:
                return
            folders = [d]
        FolderListDialog(self, folders).exec()
        self._ebay_status()
        self._relabel()

    def ebay_account(self):
        EbayAccountDialog(self, self.cfg).exec()
        self._ebay = None                       # keys or sign-in may have changed
        self._ebay_status()

    def ebay_review(self):
        c = self.ebay_client()
        if not c or not c.signed_in():
            self.ebay_account()
            return
        EbayReviewDialog(self, c, self.out_dir).exec()
        self._ebay_status()
        self._relabel()

    def ebay_upload(self):
        j = self.cur
        c = self.ebay_client()
        if not c or not c.signed_in():
            self.notice("Connect eBay first: add your keys and sign in.", "warn")
            self.ebay_account()
            return
        name = j.card_name.strip() if j else ""
        L = self._listing_for(name) if name else None
        folder = os.path.join(self.out_dir, engine.safe_name(name)) if name else ""
        problems = []
        if L is None:
            problems.append("Identify the card (I) so it has a title and details.")
        if not name or not os.path.isdir(folder) or not ebay.listing_photos(folder):
            problems.append("Export the card first (front and back), so there are photos to upload.")
        if L is not None and not L.get("condition"):
            problems.append("Set the condition on the back photo (NM, LP, MP, HP or DMG); eBay requires it.")
        if self.price.value() <= 0:
            problems.append("Enter a price.")
        pols = {k: str(self.cfg.value(f"ebay_pol_{k}", "")) for k in ("fulfillment", "return", "payment")}
        if not all(pols.values()) or not str(self.cfg.value("ebay_zip", "")):
            problems.append("Choose your shipping, return and payment policies and ship-from ZIP in Account….")
        if problems:
            self.notice("Not ready to upload: " + " ".join(problems), "warn", secs=12)
            return
        zip_code = str(self.cfg.value("ebay_zip", ""))
        need_loc = str(self.cfg.value("ebay_location_zip", "")) != zip_code
        t = EbayUploadTask(c, name, folder, L, self.price.value(), pols, zip_code, self.out_dir, need_loc,
                           self.ebay_package())
        t.sig.progress.connect(self.ebay_msg.setText)
        t.sig.done.connect(self._ebay_uploaded)
        self._uploading = True
        self.b_upload.setEnabled(False)
        self.ebay_msg.setText("Starting upload…")
        if not hasattr(self, "net_pool"):
            self.net_pool = QThreadPool(self)
            self.net_pool.setThreadPriority(QThread.LowPriority)   # never at the live view's expense
            self.net_pool.setMaxThreadCount(1)
        self.net_pool.start(t)

    def _ebay_uploaded(self, sku, res):
        oid, err = res
        self._uploading = False
        self.b_upload.setEnabled(True)
        if err:
            self.ebay_msg.setText(f"<span style='color:{TH.WARN}'>Upload failed: {err}</span>")
            self.ebay_msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return
        self.cfg.setValue("ebay_location_zip", str(self.cfg.value("ebay_zip", "")))
        self._relabel()
        self.chime("listed")
        self.ebay_msg.setText(f"<span style='color:{TH.OK}'>Uploaded to eBay, not published.</span> "
                              "Review and publish… when you are ready.")
        self.statusBar().showMessage(f"{sku} is on eBay as an unpublished listing")

    # --- Instagram
    def _start_ig(self, j):
        # its own queue, so slides never wait behind photos still being detected
        if not hasattr(self, "ig_pool"):
            self.ig_pool = QThreadPool(self)
            self.ig_pool.setThreadPriority(QThread.LowPriority)   # never at the live view's expense
            self.ig_pool.setMaxThreadCount(1)
        j.ig_state = "writing"
        t = IGTask(j, self.out_dir)
        t.sig.done.connect(self._ig_done)
        self.ig_pool.start(t)
        self._label(j)
        self.statusBar().showMessage("Writing Instagram slides in the background…")

    def _ig_done(self, j, res):
        paths, err = res
        if j in self.jobs:
            j.ig_state = "error" if err else ("done" if paths else "")
            if err:
                j.error = f"Instagram slides failed: {err}"
            self._label(j)
        if err:
            self.statusBar().showMessage(f"Instagram slides failed for {os.path.basename(j.path)}: {err}")
        elif paths:
            self.statusBar().showMessage(f"Instagram slides saved: {os.path.basename(paths[0])[:-9]}  ·  "
                                         f"{os.path.dirname(paths[0])}")

    def set_carousel_mode(self, on):
        self.cfg.setValue("carousel_mode", on)
        if on:
            self.next_name, self.next_side, self.next_info = "", "front", None
        for j in self.jobs:                 # photos already waiting follow the mode, and off is off for every photo
            if not j.done or not on:
                j.ig_only = on
                if on and getattr(j, "inherited", False):     # undo a guess that it was the last card's back
                    j.card_name, j.side, j.card_info, j.inherited = "", "front", None, False
                    j.id_tried = False
                self._label(j)
        self.statusBar().showMessage("Carousel only: Enter writes just the Instagram slides" if on
                                     else "Carousel only is off: Enter exports for eBay again")

    def add_carousel_photos(self):
        exts = " ".join(f"*{x} *{x.upper()}" for x in sorted(engine.IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Edited photos to turn into Instagram carousels", "",
                                                f"Images ({exts})")
        if not files:
            return
        if not self.c_carousel_mode.isChecked():
            self.c_carousel_mode.setChecked(True)
        n = len(self.jobs)
        self.add_paths(files, ig_only=True)
        wanted = {os.path.abspath(f) for f in files}
        for j in self.jobs:                 # already listed (dragged in earlier): convert them
            if os.path.abspath(j.path) in wanted:
                j.ig_only, j.done = True, False
                self._label(j)
        first = next((i for i, j in enumerate(self.jobs) if os.path.abspath(j.path) in wanted), n)
        self.listw.setCurrentRow(min(first, len(self.jobs) - 1))
        self.statusBar().showMessage("Check the corners, P frames the close-up, Enter writes the slides "
                                     "(or Export all for the whole batch)")

    def _card_sides(self, name):
        """Front and back pictures of a card for the 3D view, cut exactly at the card's
        edge: straightened from this session's shots with the current tone, or, for a
        card exported earlier, found again inside its exported photo."""
        out = {"front": None, "back": None}
        found = {}
        for side in ("front", "back"):
            found[side] = next((x for x in self.jobs if x.card_name.strip() == name and name and x.side == side),
                               None)
        # a back not named yet is the photo right after its front (the order you shoot in), and
        # the other way round; carousel shots and photos named as another card are never taken
        for have, want, step in (("front", "back", 1), ("back", "front", -1)):
            if found[have] is not None and found[want] is None:
                i = self.jobs.index(found[have]) + step
                if 0 <= i < len(self.jobs):
                    x = self.jobs[i]
                    if not x.card_name.strip() and not x.ig_only:
                        found[want] = x
        for side in ("front", "back"):
            j = found[side]
            if j is None:
                continue
            if j.quad is None:
                try:
                    j.detect()
                except Exception:  # noqa: BLE001
                    continue
            try:
                img = self._upright_core(j)
                if self.settings.has_edits():
                    img = engine.adjust(img, self.settings)
                out[side] = img
            except Exception:  # noqa: BLE001
                pass
        folder = os.path.join(self.out_dir, engine.safe_name(name)) if name else ""
        shown = getattr(getattr(self, "viewer3d", None), "_shown", {}).get(name)
        if shown is not None:                       # a card shown from elsewhere: its own pictures
            out["front"] = out["front"] if out["front"] is not None else shown[0]
            out["back"] = out["back"] if out["back"] is not None else shown[1]
        if folder and os.path.isdir(folder) and (out["front"] is None or out["back"] is None):
            f_, b_ = self._sides_from_folder(folder, need=[k for k, v in out.items() if v is None])
            out["front"] = out["front"] if out["front"] is not None else f_
            out["back"] = out["back"] if out["back"] is not None else b_
        return out["front"], out["back"]

    def _market_tick(self):
        """The nightly scan: runs once a day at the chosen hour, or as soon as CardCrop is open
        again after a missed night. The very first time it only starts the clock."""
        import datetime as dt
        hour = int(self.cfg.value("market_hour", 0))
        if hour < 0 or self.market_page.scanning():
            return
        now = dt.datetime.now()
        due = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if now < due:
            due -= dt.timedelta(days=1)
        last = float(self.cfg.value("market_last_scan", 0) or 0)
        if not last:
            self.cfg.setValue("market_last_scan", time.time())
            return
        if last < due.timestamp():
            self.market_page.scan(quiet=True)

    def _market_done(self, n_alert, n, quiet):
        msg = (f"Market scan: {n_alert} of {n} cards need a price check" if n_alert
               else f"Market scan: all {n} cards match the market")
        if self.stage != "market" and n_alert:
            self.market_dot.show()
        self.notice(msg, "warn" if n_alert else "ok", action=("Open", lambda: self.go("market")) if n_alert else None)
        ph = getattr(self, "phone", None)
        if ph is not None and n_alert:
            ph.notify("market", "Market scan", msg, "/#store")
        if quiet and n_alert and sys.platform == "darwin":
            import subprocess
            try:
                subprocess.Popen(["osascript", "-e", f'display notification "{msg}" with title "CardCrop"'])
            except Exception:  # noqa: BLE001
                pass

    def _sides_from_folder(self, folder, need=("front", "back")):
        """Front and back straightened from a card folder's exported photos (found again inside them)."""
        import stats
        out = {"front": None, "back": None}
        try:
            files = sorted(os.listdir(folder))
        except OSError:
            return None, None
        for f in files:
            mm = stats.MAIN_PHOTO_RE.search(f)
            if not mm or f.startswith(".") or mm.group(2) not in need or out[mm.group(2)] is not None:
                continue
            try:
                import grading
                img = engine.imread(os.path.join(folder, f))
                got = grading.card_from_photo(img)      # an export is already the card: never re-cut it
                if got is not None:
                    out[mm.group(2)] = got[0]
            except Exception:  # noqa: BLE001
                continue
        return out["front"], out["back"]

    def open_3d(self, name=None):
        if name is None:
            name = self.cur.card_name.strip() if self.cur is not None else ""
        self.go("view3d")
        if name and name != self.viewer3d.name:
            self.viewer3d.load(name)

    def open_ig(self):
        j = self.cur
        if j is None or j.quad is None or self.stack.currentWidget() is self.live:
            return
        # the close-up belongs to the front; from a back, use its front's framing
        front = next((x for x in self.jobs if x.side == "front" and j.card_name.strip()
                      and x.card_name.strip() == j.card_name.strip()), j)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            core = engine.to8(self._upright_core(front))
            k = min(1.0, 1400 / core.shape[0])
            small = cv2.resize(core, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else core
            if self.settings.has_edits():                  # the slides as they will be saved: edits on
                small = engine.to8(engine.adjust(small, self.settings, scale=k))
        finally:
            QApplication.restoreOverrideCursor()
        dlg = IGDialog(self, small, front.ig_crop or self.settings.ig_crop, self.settings.ig_crop)
        if dlg.exec() != QDialog.Accepted:
            return
        front.ig_crop = dlg.crop()
        if dlg.c_default.isChecked():
            self.settings.ig_crop = dlg.crop()
            self._save_cfg()
        if front.ig_only:
            if front.done:
                self._start_ig(front)
            else:
                self.statusBar().showMessage("Close-up saved; Enter writes the slides")
        elif not front.card_name.strip():
            self.statusBar().showMessage("Close-up saved; name the card to export its Instagram slides")
        elif front.done:
            self._start_ig(front)          # already exported: write the slides now
        else:
            self.statusBar().showMessage("Close-up saved; the slides are written when you export this front")

    def open_identify(self):
        j = self.cur
        if j is None:
            return
        query = getattr(j, "id_reading", "") or (j.card_info or {}).get("name", "")
        if not query and re.search(r"[a-z].*-.*\d", j.stem, re.I):
            query = re.sub(r"[-_]+", " ", j.stem)        # a file named for its card: search by that name
        try:
            photo = self._upright_core(j) if j.quad is not None else None
        except Exception:  # noqa: BLE001
            photo = None
        # the dialog opens in the card's own language when it has been read (or identified) as another one
        lang = str(self.cfg.value("id_lang", "en"))
        known = (j.card_info or {}).get("language") or {"zh": "zh-tw"}.get(getattr(j, "card_lang", ""),
                                                                            getattr(j, "card_lang", ""))
        if known in identify.LANGS:
            lang = known
        dlg = IdentifyDialog(self, self.db, query, lang,
                             getattr(j, "id_results", None), photo=photo, edition=getattr(j, "id_edition", ""),
                             current=j.card_info)
        if dlg.exec() == QDialog.Accepted and dlg.choice is not None:
            self.cfg.setValue("id_lang", dlg.lang.currentData())
            self._apply_info(j, dlg.choice, explicit=True)
            self.editor.setFocus()

    def _apply_info(self, j, info, explicit=False):
        j.card_info = info.to_dict()
        if info.game == "yugioh" and not j.card_info.get("edition") and getattr(j, "id_edition", ""):
            j.card_info["edition"] = j.id_edition
        # never overwrite a name you typed yourself, unless you picked a card in the dialog
        if explicit or not j.card_name or j.card_name == getattr(j, "auto_name", None):
            j.card_name = info.slug()
            j.auto_name = j.card_name
        if j is self.cur:
            self.name_edit.setText(j.card_name)
            self._show_listing()
        self._label(j)
        for x in self.jobs:                    # its back, shot straight after it, takes the same card
            if getattr(x, "_pair_of", None) is j and (not x.card_name or x.card_name == getattr(x, "auto_name", None)):
                x.card_name, x.side, x.auto_name = j.card_name, "back", j.card_name
                x.card_info = dict(j.card_info)
                self._label(x)

    # --- listing
    def _listing_for(self, name):
        """Listing for a card name from whichever side carries the identification."""
        jobs = [x for x in self.jobs if x.card_name.strip() == name]
        info = next((x.card_info for x in jobs if x.card_info), None)
        if info is None:
            return None
        cent = {x.side: x.centering.text().replace("Centering ", "") for x in jobs if x.centering}
        cond = next((x.condition for x in jobs if x.side == "back" and x.condition), "") or \
            next((x.condition for x in jobs if x.condition), "")
        price = float(self._prices().get(name, 0) or 0)
        folder = os.path.join(self.out_dir, engine.safe_name(name))
        corners = has_corner_photos(folder) if os.path.isdir(folder) and any(x.done for x in jobs) \
            else self.settings.corners
        L = listing.build(info, engine.safe_name(name), cent, self.title_overrides.get(name, ""), cond, price,
                          corners)
        L["store_category"] = self.store_category_for(name)
        L["store_category2"] = self.store_category_for(name, 2)
        return L

    def _show_listing(self):
        self._show_price()
        j = self.cur
        info = j.card_info if j else None
        if not info:
            self.b_en.hide()
            self.b_lang.hide()
            self.card_lbl_info.setText("Press I to identify it, or type its name below" if j else "")
            self.strip_id.setText("Not identified" if j else "No card")
            self.card_meta.setText(j.card_name if j and j.card_name else "")
            self.card_num.setText("")
            self.title_edit.setText("")
            self.title_count.setText("")
            return
        L = self._listing_for(j.card_name.strip()) or listing.build(info, j.card_name, {})
        self.b_en.setVisible(listing.needs_english_name(info))
        ci = identify.CardInfo(**{k: v for k, v in info.items() if k in identify.CardInfo.__dataclass_fields__})
        self.card_lbl_info.setText("")
        self.strip_id.setText(ci.name_en or ci.name)
        lang = identify.LANGS.get(ci.language, ci.language.upper() if ci.language else "")
        self.card_meta.setText(" · ".join(x for x in (ci.set_name_en or ci.set_name, ci.rarity) if x))
        self.b_lang.setText(f"{lang or 'English'} ▾")
        self.b_lang.show()
        self.card_num.setText(ci.number.split("/")[0])
        self.card_num.setToolTip(ci.number + (f"/{ci.set_total}" if ci.set_total else ""))
        self.title_edit.setText(L["title"])
        self.title_edit.setCursorPosition(0)
        self._count()

    def set_game(self, game):
        """The game being shot and identified, from Shoot or Settings; both show the same choice."""
        if game not in identify.GAMES:
            return
        self.cfg.setValue("id_game", game)
        for k, b in getattr(self, "game_btns", {}).items():
            b.setChecked(k == game)
        gp = getattr(self, "game_pick", None)
        if gp is not None and gp.currentData() != game:
            gp.blockSignals(True)
            gp.setCurrentIndex(max(0, gp.findData(game)))
            gp.blockSignals(False)

    def set_card_language(self, lang):
        """Changes the identified card's language (both sides), keeping everything else it was
        identified as; the title and item specifics follow."""
        j = self.cur
        if j is None or not j.card_info:
            return
        name = j.card_name.strip()
        jobs = [x for x in self.jobs if name and x.card_name.strip() == name and x.card_info] or [j]
        for x in jobs:
            info = dict(x.card_info)
            info["language"] = lang
            if lang != "en" and not info.get("name_en") and info.get("name", "").isascii():
                info["name_en"] = info["name"]          # keep listing it by the English name it had
            x.card_info = info
        if name:
            self._mark_changed(name)
            self._relabel(name)
        self._show_listing()
        self.statusBar().showMessage(f"{name or 'Card'}: {identify.LANGS.get(lang, lang)}")

    def _count(self):
        n = len(self.title_edit.text())
        col = TH.WARN if n > listing.TITLE_MAX else TH.MUTED
        self.title_count.setText(f"<span style='color:{col}'>{n}/{listing.TITLE_MAX}</span>")

    def on_title(self, text):
        if self.cur is not None and self.cur.card_name.strip():
            self.title_overrides[self.cur.card_name.strip()] = text
        self._count()

    def copy_title(self):
        QApplication.clipboard().setText(self.title_edit.text())
        self.statusBar().showMessage("Title copied")

    def copy_desc(self):
        j = self.cur
        L = self._listing_for(j.card_name.strip()) if j and j.card_name.strip() else None
        if L is None:
            self.statusBar().showMessage("Identify the card first (I) to build a description")
            return
        QApplication.clipboard().setText(L["description_text"])
        self.statusBar().showMessage("Description copied")
