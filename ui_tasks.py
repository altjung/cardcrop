"""CardCrop background work: every QRunnable the window hands to a thread pool."""
from __future__ import annotations

import cv2
import ebay
import engine
import identify
import json
import listing
import numpy as np
import os
import re
import time
from PySide6.QtCore import QObject, QRunnable, Signal
from engine import Job

# ------------------------------------------------------------------ workers
class _Signals(QObject):
    done = Signal(object, object)      # job, error-or-None
    progress = Signal(int, int, str)


def make_thumb(job):
    """A small upright picture of the card for the filmstrip and the List stage."""
    src = job.source()
    k = 240.0 / max(src.shape[:2])
    small = cv2.resize(src, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    if job.quad is not None:
        # straightened exactly as the export is (same upright turn for cards shot sideways),
        # so the thumbnail always faces the way the listing photo will
        q = np.asarray(job.quad, np.float32) * k
        st = getattr(job, "settings", None)
        s_ = engine.Settings(lock_ratio=getattr(st, "lock_ratio", True), margin_px=0,
                             auto_portrait=getattr(st, "auto_portrait", True))
        t = engine.warp_card(small, q, s_, job.rotate)
        t = cv2.resize(t, (72, 100) if t.shape[0] >= t.shape[1] else (100, 72), interpolation=cv2.INTER_AREA)
    else:
        t = small
    # the untoned picture is kept: the filmstrip and List tone it with the current edits as they show it
    job.thumb_base = engine.to8(t)
    job.thumb = job.thumb_base
    job._tone_key = None
    job._thumb_quad = None if job.quad is None else np.asarray(job.quad, np.float32).copy()


class ThumbOnlyTask(QRunnable):
    """A restored photo's filmstrip picture, keeping the edges you set (no new detection)."""

    def __init__(self, job):
        super().__init__()
        self.job, self.sig = job, _Signals()

    def run(self):
        err = None
        try:
            make_thumb(self.job)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        self.job.release()
        try:
            self.sig.done.emit(self.job, err)
        except RuntimeError:
            pass


class DetectTask(QRunnable):
    """Detect in the background so the queue is ready before you reach it."""

    def __init__(self, job: Job, keep: bool):
        super().__init__()
        self.job, self.keep, self.sig = job, keep, _Signals()

    def run(self):
        err = None
        try:
            self.job.detect()
            make_thumb(self.job)
        except Exception as e:  # noqa: BLE001
            err = str(e)
            self.job.error = err
        if not self.keep:
            self.job.release()
        try:
            self.sig.done.emit(self.job, err)
        except RuntimeError:          # window closed while detecting
            pass


class IGTask(QRunnable):
    """Writes a card's Instagram slides in the background (they are 110 MP each)."""

    def __init__(self, job, out_dir):
        super().__init__()
        self.job, self.out_dir, self.sig = job, out_dir, _Signals()

    def run(self):
        err, paths = None, []
        try:
            j = self.job
            if j.ig_only:
                paths = j.carousel(self.out_dir)       # detects the card itself if needed
                j.release()
            elif j.ig_core is None:            # adjusting an already exported card: render it again
                card, _ = j.render()
                m = engine.margin_for(j.quad, j.settings)
                core = card[m:card.shape[0] - m, m:card.shape[1] - m] if m else card
                j.ig_core = engine.to8(core).copy()
                j.release()
            if not j.ig_only:
                paths = j.write_instagram(self.out_dir)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(self.job, (paths, err))
        except RuntimeError:
            pass


class EbayUploadTask(QRunnable):
    """Photos, card details and an unpublished offer, off the UI thread."""

    class Sig(QObject):
        progress = Signal(str)
        done = Signal(object, object)       # sku, (offer_id, error)

    def __init__(self, client, job_name, folder, L, price, policies, zip_code, out_dir, need_location,
                 package=None):
        super().__init__()
        self.package = package
        self.c, self.name, self.folder, self.L = client, job_name, folder, L
        self.price, self.policies, self.zip, self.out_dir = price, policies, zip_code, out_dir
        self.need_location = need_location
        self.sig = EbayUploadTask.Sig()

    def run(self):
        base = ebay.sku_for(self.name)
        recs = ebay.load_records(self.out_dir)
        rec = recs.get(base) or {}
        sku = rec.get("sku") or base
        step = ""
        fresh = False
        try:
            # another copy of this card already live under this SKU: writing to it would only rewrite that
            # listing (its photos, title and quantity) and Publish would then report it live. This copy
            # gets a SKU of its own, so it becomes a listing of its own.
            step = "checking eBay for a listing of this card already"
            existing = self.c.offer_for(sku)
            ours = existing is not None and existing.get("offerId") == rec.get("offer_id") \
                and rec.get("status") != "published"
            if existing is not None and existing.get("status") == "PUBLISHED" and not ours:
                used = {base} | {r.get("sku") for r in recs.values() if r.get("sku")}
                for n in range(2, 100):
                    cand = ebay.copy_sku(base, n)
                    if cand not in used and self.c.offer_for(cand) is None:
                        sku = cand
                        break
                else:
                    raise ebay.EbayError("Every SKU for another copy of this card is taken")
                if rec:                    # the copy already live keeps its own record
                    lid = rec.get("listing_id") or (existing.get("listing") or {}).get("listingId", "")
                    ebay.save_record(self.out_dir, f"{base}@{lid or existing.get('offerId')}", rec, replace=True)
                fresh = True
                self.sig.progress.emit(f"This card is already live on eBay: this copy gets its own listing ({sku})")
            if self.need_location:
                step = "setting your ship-from location"
                self.sig.progress.emit("Setting your ship-from location…")
                self.c.ensure_location(self.zip)
            photos = ebay.listing_photos(self.folder)
            if not photos:
                raise ebay.EbayError("No exported photos found in the card's folder")
            urls = []
            for i, p in enumerate(photos, 1):
                step = f"uploading photo {i} ({os.path.basename(p)})"
                self.sig.progress.emit(f"Uploading photo {i} of {len(photos)}…")
                urls.append(self.c.upload_image(p))
            self.sig.progress.emit("Creating the listing (unpublished)…")
            aspects = {k: v for k, v in self.L["specifics"].items() if k not in ("Card Condition", "Graded")}
            cond_id = listing.CONDITIONS[self.L["condition"]][2]
            step = "saving the card details (inventory item)"
            self.c.put_item(sku, self.L["title"], self.L["description_text"], aspects, urls, cond_id,
                            package=self.package)
            step = "creating the unpublished listing (offer)"
            known = "" if fresh or rec.get("status") == "published" else rec.get("offer_id", "")
            oid = self.c.upsert_offer(sku, self.price, self.L["description_html"], self.policies,
                                      known_offer_id=known,
                                      store_category=(self.L.get("store_category") or ("", ""))[1],
                                      store_category2=(self.L.get("store_category2") or ("", ""))[1])
            ebay.save_record(self.out_dir, base, {
                "name": self.name, "title": self.L["title"], "price": self.price, "sku": sku,
                "condition": self.L["condition"], "photos": len(urls), "offer_id": oid,
                "status": "unpublished", "uploaded": time.strftime("%Y-%m-%d %H:%M")}, replace=fresh)
            res = (oid, None)
        except Exception as e:  # noqa: BLE001
            res = (None, f"While {step}: {e}" if step else str(e))
        try:
            self.sig.done.emit(sku, res)
        except RuntimeError:
            pass


class EbayPhotosTask(QRunnable):
    """Puts one card's photos on eBay's picture hosting, for a Seller Hub draft."""

    class Sig(QObject):
        progress = Signal(str)
        done = Signal(object, object)       # urls, error

    def __init__(self, client, folder):
        super().__init__()
        self.c, self.folder = client, folder
        self.sig = EbayPhotosTask.Sig()

    def run(self):
        urls, err = [], None
        try:
            photos = ebay.listing_photos(self.folder)
            if not photos:
                raise ebay.EbayError("No photos found in the folder")
            for i, p in enumerate(photos, 1):
                self.sig.progress.emit(f"Uploading photo {i} of {len(photos)}…")
                try:
                    urls.append(self.c.upload_image(p))
                except Exception as e:  # noqa: BLE001
                    raise ebay.EbayError(f"While uploading photo {i} ({os.path.basename(p)}): {e}")
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(urls, err)
        except RuntimeError:
            pass


class PriceTask(QRunnable):
    """Live price check for one card, off the UI thread."""

    class Sig(QObject):
        done = Signal(object, object)       # key, result

    def __init__(self, client, db, info, key, sku="", pc_token=""):
        super().__init__()
        self.c, self.db, self.info, self.key = client, db, info, key
        self.sku, self.pc_token = sku, pc_token
        self.sig = PriceTask.Sig()

    def run(self):
        try:
            import sales
            r = ebay.suggest_price(self.c, self.db, self.info, own=sales.unit_prices(self.sku),
                                   pc_token=self.pc_token)
        except Exception as e:  # noqa: BLE001
            r = {"suggested": None, "error": str(e)}
        try:
            self.sig.done.emit(self.key, r)
        except RuntimeError:
            pass


class DraftsSubmitTask(QRunnable):
    """Sends the drafts file to eBay and waits for it to become Seller Hub drafts."""

    class Sig(QObject):
        progress = Signal(str)
        done = Signal(object, object)       # result dict, error

    def __init__(self, client, path):
        super().__init__()
        self.c, self.path = client, path
        self.sig = DraftsSubmitTask.Sig()

    def run(self):
        res, err = None, None
        try:
            res = ebay.submit_drafts_file(self.c, self.path, self.sig.progress.emit)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(res, err)
        except RuntimeError:
            pass


class FolderIdTask(QRunnable):
    """Works out which card each exported folder holds, off the UI thread."""

    class Sig(QObject):
        done = Signal(int, object)

    def __init__(self, db, row, folder):
        super().__init__()
        self.db, self.row, self.folder = db, row, folder
        self.sig = FolderIdTask.Sig()

    def run(self):
        info = None
        try:
            names = [os.path.basename(self.folder)] + [os.path.splitext(f)[0] for f in os.listdir(self.folder)]
            for n in names:
                c = self.db.from_slug(n)
                if c is not None:
                    info = c.to_dict()
                    break
        except Exception:  # noqa: BLE001
            info = None
        try:
            self.sig.done.emit(self.row, info)
        except RuntimeError:
            pass


def folder_listing_info(folder):
    """What an exported card folder already says about itself: the card (from a
    saved listing), the condition (from the back's file names) and centering."""
    info, cond, cent = None, "", {}
    for f in os.listdir(folder):
        if f.endswith("_listing.json"):
            try:
                with open(os.path.join(folder, f), encoding="utf-8") as fh:
                    d = json.load(fh)
                info = d.get("info") or info
                cond = d.get("condition") or cond
                cent = d.get("centering") or cent
            except (OSError, ValueError):
                pass
    if not cond:
        for f in sorted(os.listdir(folder)):
            m = re.search(r"_(NM|LP|MP|HP|DMG)(?=[._]|$)", os.path.splitext(f)[0])
            if m:
                cond = m.group(1)
                break
    return info, cond, cent


def looks_exported(folder):
    try:
        fs = os.listdir(folder)
    except OSError:
        return False
    return any(re.search(r"_\d{2}_(front|back|hero)", f) or f.endswith("_listing.json") for f in fs)


class ExportAllTask(QRunnable):
    def __init__(self, jobs, out_dir):
        super().__init__()
        self.jobs, self.out_dir, self.sig = jobs, out_dir, _Signals()

    def run(self):
        n = len(self.jobs)
        for i, j in enumerate(self.jobs):
            self.sig.progress.emit(i, n, os.path.basename(j.path))
            try:
                if j.quad is None:
                    j.detect()
                if j.ig_only:
                    j.carousel(self.out_dir)
                    j.ig_state = "done"
                else:
                    j.export(self.out_dir)
                    if j.settings.ig:              # the carousel only while its box is ticked
                        j.write_instagram(self.out_dir)
                    j.ig_core = None
            except Exception as e:  # noqa: BLE001
                j.error = str(e)
            finally:
                j.release()
            try:
                self.sig.done.emit(j, j.error or None)
            except RuntimeError:
                return                             # the window closed while this was running
        try:
            self.sig.progress.emit(n, n, "")
        except RuntimeError:
            pass


class IdentifyTask(QRunnable):
    """Read the collector number and look the card up, off the UI thread."""

    def __init__(self, db, job, card, lang, query=None, game="pokemon", prep=None):
        super().__init__()
        self.db, self.job, self.card, self.lang, self.query = db, job, card, lang, query
        self.game = game
        self.prep = prep           # makes the upright card off the UI thread when card is None
        self.edition = getattr(job, "id_edition", "") if job is not None else ""
        self.sig = _Signals()

    def run(self):
        reading, results, err = None, [], None
        if self.card is None and self.prep is not None:
            try:
                self.card = self.prep()
            except Exception as e:  # noqa: BLE001
                self.sig.done.emit(self.job, (None, [], f"could not straighten the photo: {e}"))
                return
        try:
            # a photo already named for its card (thundurus-ex-bwp-bw81.jpg) needs no reading
            if self.query is None and self.job is not None:
                info = self.db.from_slug(self.job.stem)
                if info is not None:
                    self.sig.done.emit(self.job, (identify.Reading(raw=self.job.stem), [info], None))
                    return
            if self.query is None:
                try:
                    reading = identify.read_number(self.card)
                except ImportError:
                    # card reader not installed: say so, and let name search do the work
                    self.sig.done.emit(self.job, (None, [], "no-ocr"))
                    return
                q = reading.text()
                if not q:            # One Piece prints OP01-001 SEC in the same strip
                    code, mark = identify.op_code_from_ocr(reading.raw)
                    q = (code + " " + mark).strip() if code else ""
                if not q:            # Yu-Gi-Oh! prints LOB-EN005 under the art, whatever the usual game
                    code, self.edition = identify.read_ygo_line(self.card)
                    q = code
                    reading.raw = (reading.raw + " " + q).strip()
            else:
                q = self.query
            if q:
                # the card's own language first (read off the photo), then the one you chose, then
                # English, then Japanese: a Chinese card is found in Chinese whatever you typed
                order, cl = [self.lang], None
                # a name you search for is looked up in the language you picked, and only that one;
                # reading the photo is what may look across languages
                if self.game == "pokemon" and not identify.detect_game(q) and self.query is None:
                    cl = getattr(self.job, "card_lang", None) if self.job is not None else None
                    if cl is None and self.card is not None:
                        cl = identify.card_language(reading.raw) if reading is not None else "en"
                        if cl == "en":
                            cl = identify.read_language(self.card)
                        if self.job is not None:
                            self.job.card_lang = cl
                    order = identify.lang_order(cl or "en", self.lang)
                    if self.query is None:
                        # read off the photo: if the number fits nothing in its language, it may be
                        # a card in another one
                        order += [lg for lg in ("ja", "zh-tw", "zh-cn", "ko") if lg not in order]
                tries = [q] + ([f"{n_}/{t_}" for n_, t_ in (getattr(reading, "alts", None) or [])]
                               if self.query is None else [])
                own = order[0] if (cl or "en") != "en" else None
                pools = []
                for lg in order:
                    found = []
                    for qq in tries:                     # the next most likely readings too
                        found = self.db.search(qq, lg, self.game)
                        if found:
                            if qq != q and reading is not None:
                                reading.number, reading.total = qq.split("/")
                            break
                    if found:
                        pools.append((lg, found))
                        # the card's own language, read off the photo, settles it; otherwise one number
                        # can be a card in several languages (006/165 is Charizard ex in English, Chinese
                        # and Japanese), so every language is asked and the photo picks below
                        if lg == own or self.query is not None or self.game != "pokemon":
                            break
                results = [c for _lg, f in pools for c in f]
                if len(pools) > 1 and self.card is not None:
                    results = self.db.rank_by_image(self.card, results)
            if results and results[0].game in ("yugioh", "onepiece"):
                for r in results:
                    if r.game == "yugioh" and self.edition:
                        r.edition = self.edition
                if len(results) > 1 and self.card is not None:
                    # one code, many versions: the photo picks the alternate art, manga or parallel
                    results = self.db.rank_by_image(self.card, results)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(self.job, (reading, results, err))
        except RuntimeError:
            pass                                  # window closed while the lookup ran


class ThumbTask(QRunnable):
    def __init__(self, db, info, row):
        super().__init__()
        self.db, self.info, self.row, self.sig = db, info, row, _Signals()

    def run(self):
        self.sig.done.emit(self.row, self.db.image_bytes(self.info, "low"))


class StoreTask(QRunnable):
    class Sig(QObject):
        done = Signal(object, object)       # data, error

    def __init__(self, client):
        super().__init__()
        self.c, self.sig = client, StoreTask.Sig()

    def run(self):
        data, err = None, None
        try:
            data = self.c.my_store()
        except Exception as e:  # noqa: BLE001
            err = str(e)
        if data is not None:
            try:
                data["traffic"] = self.c.traffic(30)
            except Exception as e:  # noqa: BLE001
                data["traffic_err"] = "reconnect" if str(e) == "RECONNECT" else str(e)
        try:
            self.sig.done.emit(data, err)
        except RuntimeError:
            pass


class ImgTask(QRunnable):
    class Sig(QObject):
        done = Signal(object, object)       # url, bytes

    def __init__(self, db, url, client=None, item_id=""):
        super().__init__()
        self.db, self.url, self.sig = db, url, ImgTask.Sig()
        self.client, self.item_id = client, item_id

    def run(self):
        key, url, data = self.url, self.url, None
        if key.startswith("item:") and self.client is not None:
            try:
                url = self.client.item_picture(self.item_id)
            except Exception:  # noqa: BLE001
                url = ""
        if url and not url.startswith("item:"):
            data = self.db._cached_image(url)
        try:
            self.sig.done.emit(key, data)
        except RuntimeError:
            pass


class _Relay(QObject):
    """Lives on the UI thread, so a worker's result is handled there; kept alive until it fires."""
    alive = set()

    def __init__(self, cb):
        super().__init__()
        self.cb = cb
        _Relay.alive.add(self)

    def fire(self, *a):
        _Relay.alive.discard(self)
        self.cb(*a)


class CallTask(QRunnable):
    """Runs one function off the UI thread and hands back its result or its error.
    Connect with task.then(callback); the callback runs on the UI thread."""

    class Sig(QObject):
        done = Signal(object, str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args, self.sig = fn, args, CallTask.Sig()
        self._keep = self.sig

    def then(self, cb):
        r = _Relay(cb)
        r._sig = self.sig                         # the signal object outlives the runnable
        self.sig.done.connect(r.fire)
        return self

    def run(self):
        res, err = None, ""
        try:
            res = self.fn(*self.args)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(res, err)
        except RuntimeError:
            pass


class _CardRelay(QObject):
    """Created on the UI thread for one card, so a worker's signals arrive here (queued) with
    the card's name attached, whatever order the uploads finish in."""

    def __init__(self, main, name):
        super().__init__(main)
        self.m, self.name = main, name

    def progress(self, msg):
        self.m._card_progress(self.name, msg)

    def done(self, _sku, res):
        self.m._card_uploaded(self.name, res)

    def published(self, _name, err):
        self.m._card_published(self.name, err)


class EbayPublishTask(QRunnable):
    """Puts one unpublished offer live."""

    class Sig(QObject):
        done = Signal(object, object)       # name, error or None

    def __init__(self, client, name, offer_id, out_dir):
        super().__init__()
        self.c, self.name, self.oid, self.out_dir = client, name, offer_id, out_dir
        self.sig = EbayPublishTask.Sig()

    def run(self):
        err = None
        try:
            off = self.c.get_offer(self.oid)
            if off.get("status") == "PUBLISHED":
                lid = (off.get("listing") or {}).get("listingId", "")
                raise ebay.EbayError(
                    f"Not published: this offer is already your live listing {lid}, so publishing would only "
                    "update it. An upload before 3.7.16 wrote this copy onto it, replacing that listing's photos; "
                    "check the listing on eBay, then upload this card again and it gets a listing of its own.")
            lid = self.c.publish(self.oid)
            ebay.save_record(self.out_dir, ebay.sku_for(engine.safe_name(self.name)),
                             {"status": "published", "listing_id": lid,
                              "published": time.strftime("%Y-%m-%d %H:%M")})
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(self.name, err)
        except RuntimeError:
            pass


class MarketScanTask(QRunnable):
    class Sig(QObject):
        progress = Signal(int, int, str)
        done = Signal(object)                # history

    def __init__(self, client, db, items):
        super().__init__()
        self.c, self.db, self.items, self.sig = client, db, items, MarketScanTask.Sig()
        self.stop = False

    def run(self):
        import market
        h = None
        try:
            h = market.scan(self.c, self.db, self.items, lambda i, n, m: self._emit(i, n, m), lambda: self.stop)
        except Exception as e:  # noqa: BLE001
            self._emit(0, 0, f"Scan failed: {e}")
        try:
            self.sig.done.emit(h)
        except RuntimeError:
            pass

    def _emit(self, i, n, m):
        try:
            self.sig.progress.emit(i, n, m)
        except RuntimeError:
            pass


class PriceSetTask(QRunnable):
    class Sig(QObject):
        done = Signal(str, float, str)       # key, price, error

    def __init__(self, client, key, sku, price, item_id=""):
        super().__init__()
        self.c, self.key, self.sku, self.price, self.sig = client, key, sku, price, PriceSetTask.Sig()
        self.item_id = item_id

    def run(self):
        err = ""
        try:
            self.c.change_price(self.item_id, self.sku, self.price)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(self.key, self.price, err)
        except RuntimeError:
            pass


def live_sides(client, db, item):
    """Front and back of a live listing: from the card's exported folder when there is one
    (full size, already flat), else from the listing's own photos."""
    import grading
    if item.get("sides"):                         # this session's photos, with your corrected edges
        return item["sides"]
    if item.get("folder") and os.path.isdir(item["folder"]):
        import calibrate
        f_, b_ = calibrate._sides_from_folder(item["folder"])
        if f_ is not None or b_ is not None:
            return f_, b_
    urls, sku = client.item_pictures(item["id"])
    item["sku"] = item.get("sku") or sku
    imgs = []
    for u in urls[:8]:                            # the main photos come first
        data = db._cached_image(u)
        imgs.append(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None)
    front, back = grading.sides_from_photos(imgs)
    if front is None and back is None:
        raise RuntimeError("no whole-card photo of the front or back found in this listing")
    return front, back


class CalibrateTask(QRunnable):
    """Measures every card you have given a condition and fits the report's scoring to you."""

    class Sig(QObject):
        progress = Signal(int, int, str)
        done = Signal(object, str, object)         # model, error, problems

    def __init__(self, client, db, folders, store):
        super().__init__()
        self.c, self.db, self.folders, self.store = client, db, folders, store
        self.sig = CalibrateTask.Sig()
        self.stop = False

    def _emit(self, sig, *a):
        try:
            sig.emit(*a)
        except RuntimeError:
            pass

    def run(self):
        import calibrate
        problems, model, err = [], None, ""
        try:
            store = self.store
            if self.c is not None and not store:
                self._emit(self.sig.progress, 0, 0, "Reading your eBay listings")
                store = self.c.my_store()
            samples = calibrate.gather(self.c, self.db, self.folders, store,
                                       progress=lambda i, n, t: self._emit(self.sig.progress, i, n, t),
                                       cancelled=lambda: self.stop, log=problems.append)
            if not self.stop:
                self._emit(self.sig.progress, 0, 0, "Fitting the scoring to your grades")
                model = calibrate.fit(samples)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        self._emit(self.sig.done, model, err, problems)


class LiveSidesTask(QRunnable):
    class Sig(QObject):
        done = Signal(object, object, object, str)     # item, front, back, error

    def __init__(self, client, db, item):
        super().__init__()
        self.c, self.db, self.item, self.sig = client, db, item, LiveSidesTask.Sig()

    def run(self):
        f = b = None
        err = ""
        try:
            f, b = live_sides(self.c, self.db, self.item)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(self.item, f, b, err)
        except RuntimeError:
            pass


class VideoUploadTask(QRunnable):
    """Uploads a turntable MP4 and attaches it to the listing, then waits a little for eBay to process it."""

    class Sig(QObject):
        done = Signal(str, str, str)               # item id, final status, error

    def __init__(self, client, item, path):
        super().__init__()
        self.c, self.item, self.path, self.sig = client, item, path, VideoUploadTask.Sig()

    def run(self):
        status, err = "", ""
        try:
            vid = self.c.upload_video(self.path, self.item.get("title", ""))
            self.c.attach_video(self.item["id"], self.item.get("sku", ""), vid)
            for _ in range(12):                    # about a minute; it goes live on eBay's side regardless
                status = self.c.video_status(vid)
                if status in ("LIVE", "BLOCKED", "PROCESSING_FAILED"):
                    break
                time.sleep(5)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(self.item["id"], status, err)
        except RuntimeError:
            pass


class LiveReportTask(QRunnable):
    """A live listing's photos, downloaded, measured and drawn into a report (off the UI thread);
    with add=True the report is also uploaded and added as the listing's last photo."""

    class Sig(QObject):
        done = Signal(str, object, str, str)       # item id, PIL image, saved path, error

    def __init__(self, client, db, item, add=False, out_path=""):
        super().__init__()
        self.c, self.db, self.item, self.add, self.out_path = client, db, item, add, out_path
        self.sig = LiveReportTask.Sig()

    def run(self):
        import grading
        iid, im, err, path = self.item["id"], None, "", ""
        try:
            front, back = live_sides(self.c, self.db, self.item)
            sides = {}
            for side, img in (("front", front), ("back", back)):
                if img is None:
                    continue
                sd = grading.analyze_side(img, side, engine.measure_centering(img))
                if side == "back":
                    grading.remember_back(sd["_img"])
                    sd["surface"] = grading.back_surface(sd)
                sides[side] = sd
            title = self.item.get("title", "")
            im = grading.render_report(title, "Live on eBay", sides.get("front"), sides.get("back"))
            if self.out_path:
                os.makedirs(os.path.dirname(self.out_path), exist_ok=True)
                im.convert("RGB").save(self.out_path, quality=95)
                path = self.out_path
            if self.add:
                self.c.add_listing_photo(iid, self.item.get("sku", ""), path)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(iid, im, path, err)
        except RuntimeError:
            pass


class AddLivePhotoTask(QRunnable):
    class Sig(QObject):
        done = Signal(str, str)                    # item id, error

    def __init__(self, client, item, path, replace=""):
        super().__init__()
        self.c, self.item, self.path, self.sig = client, item, path, AddLivePhotoTask.Sig()
        self.replace, self.url = replace, ""

    def run(self):
        err = ""
        try:
            self.url = self.c.add_listing_photo(self.item["id"], self.item.get("sku", ""), self.path,
                                                self.replace) or ""
        except Exception as e:  # noqa: BLE001
            err = str(e)
        try:
            self.sig.done.emit(self.item["id"], err)
        except RuntimeError:
            pass
