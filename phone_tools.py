"""The phone console's bigger tools, kept apart from the plumbing in phone_link.py:

shot review   the last shots with their found corners, dragged on the phone and written back to the job
price check   a photo from the phone's own camera, straightened, read and priced by CardCrop
selling       unpublished uploads to publish, buyers' offers to answer, sales to mark shipped
push          notifications for sales, offers, market alerts and finished exports (phone_push.py)

PhoneLink mixes this in; everything here runs either on a handler thread (HTTP) or, through
self.later and self.call_main, on the UI thread."""
from __future__ import annotations

import json
import os
import secrets
import urllib.parse
import threading
import time

import cv2
import numpy as np

import ebay
import engine
import phone_push

ATTN = ("⚠", "!", "✕", "?")
LISTING_CMDS = ("listings", "listing", "listing_save", "listing_end", "listing_video", "listing_report", "batch_cat",
                "policies", "bulk_price", "market_match", "search", "market_dismiss")
EXPORT_CMDS = ("export_opts", "ig_get", "ig_set", "card_video", "surface")
PHOTO_CMDS = ("rotate", "side", "rename", "identify", "tone", "tone_reset", "preset", "edits")
PAGE = 20
VIDEO_EXTS = (".mp4", ".mov")
KINDS = ("sales", "offers", "market", "export")


def _enc(img, long_edge, q=84) -> bytes:
    h, w = img.shape[:2]
    s = long_edge / max(h, w)
    if s < 1:
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", engine.to8(img), [cv2.IMWRITE_JPEG_QUALITY, q])
    return buf.tobytes() if ok else b""


def _cw(p, r):
    """Normalised point turned clockwise r quarter turns, the way warp_card turns the card."""
    u, v = p
    for _ in range(r % 4):
        u, v = 1 - v, u
    return u, v


def _ccw(p, r):
    u, v = p
    for _ in range(r % 4):
        u, v = v, 1 - u
    return u, v


def _json(obj, status=200):
    return status, "application/json", json.dumps(obj, default=str).encode()


class PhoneTools:
    def tools_init(self):
        self.offers, self.offers_at, self.offers_err = [], 0.0, ""
        self._offers_busy = False
        self._scans = {}                    # scan id -> {"results": [...], "card": jpeg, "at": time}
        self._shots = {}                    # job key -> (quad, rot, jpeg, w, h) of the photo last sent
        self._vapid = None
        self._sales_seen = None

    # ================================================================ HTTP
    def tool_http(self, method, path, q, body, token):
        parts = path.split("/")
        key = parts[3].rsplit(".", 1)[0] if len(parts) == 4 else ""
        if path.startswith("/api/files/") and len(parts) == 4:
            return _json({"files": [{"i": i, "file": os.path.basename(f), "group": g, "kb": kb}
                                    for i, (f, g, kb) in enumerate(self._card_files(urllib.parse.unquote(parts[3])))]})
        if path.startswith("/api/file/") and len(parts) == 5:
            return self._card_file(urllib.parse.unquote(parts[3]), parts[4].rsplit(".", 1)[0])
        if path.startswith("/api/shot/") and key:
            return self._shot_info(key)
        if path.startswith("/api/photo/") and key:
            hit = self._shots.get(key)
            return (200, "image/jpeg", hit[2]) if hit else (404, "text/plain", b"")
        if path.startswith("/api/upright/") and key:
            data = self._upright(key)
            return (200, "image/jpeg", data) if data else (404, "text/plain", b"")
        if path == "/api/scan" and method == "POST":
            return self._scan(body)
        if path.startswith("/api/scan/img/") and len(parts) == 5:
            s = self._scan_mem(parts[4].rsplit(".", 1)[0])
            return (200, "image/jpeg", s["card"]) if s and s.get("card") else (404, "text/plain", b"")
        if path == "/api/scans":
            import scans
            return _json(scans.page(int((q.get("page") or ["0"])[0] or 0), 20, (q.get("q") or [""])[0]))
        if path.startswith("/api/scan/open/") and len(parts) == 5:
            return self._scan_open(parts[4])
        if path == "/api/scan/delete" and method == "POST":
            import scans
            sid = str(json.loads(body or b"{}").get("scan", ""))
            scans.delete(sid)
            self._scans.pop(sid, None)
            return _json({"ok": True})
        if path == "/api/scan/pick" and method == "POST":
            req = json.loads(body or b"{}")
            return self._scan_price(req.get("scan", ""), int(req.get("i", 0)))
        if path == "/api/scan/search" and method == "POST":
            req = json.loads(body or b"{}")
            return self._scan_search(req.get("scan", ""), str(req.get("q", "")).strip())
        if path.startswith("/api/listing/") and path.endswith("/video") and method == "POST" and len(parts) == 5:
            return self._video_upload(parts[3], body, q)
        if path.startswith("/api/report/") and len(parts) == 4 and path.endswith(".jpg"):
            return self._report(urllib.parse.unquote(parts[3][:-4]))
        if path.startswith("/api/report/") and path.endswith("/save") and method == "POST" and len(parts) == 5:
            return self._report_save(urllib.parse.unquote(parts[3]))
        if path == "/api/video/save" and method == "POST":
            return self._video_save(body, (q.get("name") or ["card-3d.mp4"])[0])
        if path.startswith("/api/saleimg/") and key:
            data = self._sale_img(key, (q.get("sku") or [""])[0])
            return (200, "image/jpeg", data) if data else (404, "text/plain", b"")
        if path == "/api/push/key":
            return _json({"key": self.vapid().public_b64})
        if path == "/api/push/subscribe" and method == "POST":
            req = json.loads(body or b"{}")
            return _json(self.call_main(lambda: self._subscribe(token, req.get("sub") or {}, req.get("kinds")),
                                        {"ok": False}))
        if path == "/api/push/unsubscribe" and method == "POST":
            req = json.loads(body or b"{}")
            self.call_main(lambda: self._unsubscribe(req.get("endpoint", "")))
            return _json({"ok": True})
        if path == "/api/push/test" and method == "POST":
            req = json.loads(body or b"{}")
            ok = self.call_main(lambda: self._push_test(req.get("endpoint", "")), False)
            return _json({"ok": bool(ok)})
        return None

    # ================================================================ commands (UI thread)
    def tool_command(self, conn, o) -> bool:
        t = o.get("t")
        if t == "quad":
            self._set_quad(conn, o.get("job", ""), o.get("quad") or [])
        elif t == "redetect":
            self._redetect(conn, o.get("job", ""))
        elif t == "retake":
            self._retake(conn, o.get("job", ""))
        elif t == "publish":
            self._publish(conn, str(o.get("sku", "")))
        elif t == "offers":
            self.fetch_offers(conn)
        elif t == "offer":
            self._answer_offer(conn, o)
        elif t == "ship":
            self._ship(conn, o)
        elif t in LISTING_CMDS or t in PHOTO_CMDS or t in EXPORT_CMDS:
            getattr(self, "_c_" + t)(conn, o)
        else:
            return False
        return True

    def tools_tick(self, n):
        """Every 2 s: new sales checked every 10 s, offers every 5 minutes, and the store read
        again every 10 minutes while a phone wants to hear about sales."""
        subs = self.push_subs()
        wants = {k for s in subs.values() for k in s.get("kinds", [])}
        if n % 5 == 0:
            self._check_sales()
        if n % 150 == 1 and (self.server.clients() or "offers" in wants) and self.ebay_ready():
            self.fetch_offers()
        if n % 300 == 0 and "sales" in wants and self.ebay_ready():
            sp = self.m.store_page
            if sp.stale():
                sp.refresh()

    # ================================================================ shot review
    def recent_shots(self, n=8):
        m, out = self.m, []
        for j in reversed(m.jobs):
            if j.ig_only:
                continue
            out.append({"job": self._job_key(j), "stem": j.stem, "side": j.side, "name": j.card_name.strip(),
                        "mark": getattr(j, "mark", ""), "found": j.quad is not None, "edited": bool(j.edited),
                        "conf": round(float(j.confidence or 0), 2), "under": round(float(getattr(j, "expo_under", 0) or 0), 1),
                        "thumb": self._job_key(j), "done": bool(j.done)})
            if len(out) >= n:
                break
        return out

    def _shot_info(self, key):
        """The photo as shot, turned the way it was framed, with its corners in that frame (0..1)."""
        j = self.call_main(lambda: self._job(key))
        if j is None:
            return 404, "text/plain", b""
        try:
            src = j.source()
        except Exception as e:  # noqa: BLE001
            return _json({"error": f"Could not read the photo: {e}"}, 500)
        H, W = src.shape[:2]
        r = (j.rotate // 90) % 4
        img = np.ascontiguousarray(np.rot90(src, k=-r)) if r else src
        data = _enc(img, 1600, 82)
        quad = None
        if j.quad is not None:
            quad = [list(_cw((float(x) / W, float(y) / H), r)) for x, y in np.asarray(j.quad, np.float32)]
        dh, dw = img.shape[:2]
        self._shots[key] = (quad, r, data, dw, dh)
        return _json({"job": key, "w": dw, "h": dh, "quad": quad, "rot": r, "stem": j.stem, "side": j.side,
                      "conf": round(float(j.confidence or 0), 2), "edited": bool(j.edited),
                      "under": round(float(getattr(j, "expo_under", 0) or 0), 1), "mark": getattr(j, "mark", ""),
                      "name": j.card_name.strip()})

    def _upright(self, key):
        j = self.call_main(lambda: self._job(key))
        if j is None or j.quad is None:
            return b""
        try:
            src = j.source()
            k = min(1.0, 1800 / max(src.shape[:2]))
            small = cv2.resize(src, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else src
            s_ = engine.Settings(lock_ratio=j.settings.lock_ratio, margin_px=0, auto_portrait=j.settings.auto_portrait)
            card = engine.warp_card(small, np.asarray(j.quad, np.float32) * k, s_, j.rotate)
            if self.m.settings.has_edits():
                card = engine.adjust(card, self.m.settings)
            return _enc(card, 1000, 86)
        except Exception:  # noqa: BLE001
            return b""

    def _set_quad(self, conn, key, pts):
        m = self.m
        j = self._job(key)
        if j is None or len(pts) != 4:
            return self._say(conn, "That photo is no longer in the session", "error")
        src = j._src
        if src is None:
            hit = self._shots.get(key)
            if not hit:
                return self._say(conn, "Open the photo again and retry", "error")
            dw, dh = hit[3], hit[4]
            W, H = (dh, dw) if hit[1] % 2 else (dw, dh)
        else:
            H, W = src.shape[:2]
        r = (j.rotate // 90) % 4
        q = []
        for p in pts:
            u, v = _ccw((min(1.0, max(0.0, float(p[0]))), min(1.0, max(0.0, float(p[1])))), r)
            q.append([u * W, v * H])
        q = engine.order_quad(np.array(q, np.float32))
        if j is m.cur:
            m.push_undo()
        j.quad, j.edited = q, True
        self._refresh_job(j)
        self._say(conn, "Corners saved on the Mac")

    def _refresh_job(self, j):
        m = self.m
        try:
            from ui_tasks import make_thumb
            make_thumb(j)
        except Exception:  # noqa: BLE001
            pass
        if j is m.cur:
            m.editor.set_quad(j.quad)
            m.update_preview()
        m._label(j)
        self.dirty("queue")
        self.server.broadcast({"t": "shot_update", "job": self._job_key(j)})

    def _redetect(self, conn, key):
        j = self._job(key)
        if j is None:
            return

        def work():
            try:
                j.detect(force=True)
            except Exception as e:  # noqa: BLE001
                msg = f"Could not find the card: {e}"      # e is gone once the except block ends
                return self.later(lambda: self._say(conn, msg, "error"))
            self.later(lambda: (self._refresh_job(j), self._say(conn, f"Found the edges again ({j.confidence:.0%} sure)")))
        threading.Thread(target=work, daemon=True).start()

    def _retake(self, conn, key):
        """Takes the shot off the session and sets the next shot to replace it, front or back."""
        m = self.m
        j = self._job(key)
        if j is None or j not in m.jobs:
            return
        if getattr(m, "_pair_front", None) is j:
            m._pair_front = None                       # the next shot is this card's front again
        else:
            front = getattr(j, "_pair_of", None)
            if j.side == "back" and front is not None and front in m.jobs:
                m._pair_front = front                  # the next shot is the back again
        m.remove_jobs([m.jobs.index(j)])
        m._update_next()
        self.dirty("queue")
        self.dirty("status")
        self._say(conn, "Removed. The next shot replaces it")

    # ================================================================ price check
    def _ctx(self):
        m = self.m
        return {"db": m.db, "lang": str(m.cfg.value("id_lang", "en")), "game": str(m.cfg.value("id_game", "pokemon")),
                "client": m.ebay_client(), "pc": str(m.cfg.value("pc_token", "") or "")}

    def _identify_card(self, card, query=None):
        from ui_tasks import IdentifyTask
        from PySide6.QtCore import Qt
        c = self.call_main(self._ctx)
        if c is None:
            return None, [], "CardCrop is busy"
        t = IdentifyTask(c["db"], None, card, c["lang"], query=query, game=c["game"])
        box = []
        t.sig.done.connect(lambda _j, res: box.append(res), Qt.DirectConnection)
        t.run()
        return box[0] if box else (None, [], "no answer")

    def _price(self, info):
        from ui_tasks import PriceTask
        from PySide6.QtCore import Qt
        import sales
        c = self.call_main(self._ctx)
        d = info.to_dict()
        sku = engine.safe_name(info.slug())
        t = PriceTask(c["client"], c["db"], d, (d.get("id"), d.get("language", "en")), sku=sku, pc_token=c["pc"])
        box = []
        t.sig.done.connect(lambda _k, r: box.append(r), Qt.DirectConnection)
        t.run()
        r = box[0] if box else {}
        e, tcg, pc = r.get("ebay") or {}, r.get("tcgplayer") or {}, r.get("pricecharting") or {}
        own = r.get("own") or sales.summary(sales.unit_prices(sku))
        lines = []
        if own:
            lines.append(["You sold", f"${own['median']:.2f} median of {own['count']}, last ${own['last']:.2f}"])
        if isinstance(pc, dict) and pc.get("loose"):
            lines.append(["PriceCharting", f"${float(pc['loose']):.2f} ungraded"])
        if isinstance(tcg, dict) and tcg.get("market"):
            lines.append(["TCGplayer", f"${float(tcg['market']):.2f} market"])
        if e.get("count"):
            lines.append(["eBay asks", f"{e['count']} listed, low ${e['low']:.2f}, median ${e['median']:.2f}"])
        return {"suggested": r.get("suggested"), "basis": r.get("basis", ""), "lines": lines,
                "market": ebay.market_of(r),
                "error": r.get("error", "")}

    def _cands(self, results):
        out = []
        for i, r in enumerate(results[:8]):
            img = r.image if r.image.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) else \
                (r.image + "/low.png" if r.image else "")
            out.append({"i": i, "label": r.label(), "name": r.name_en or r.name, "img": img})
        return out

    def _scan(self, body):
        arr = np.frombuffer(body or b"", np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR) if arr.size else None
        if img is None:
            return _json({"error": "That photo did not arrive"}, 400)
        quad, conf = engine.detect_card(img)
        card = engine.warp_card(img, quad, engine.Settings(margin_px=0)) if conf > 0.25 else img
        sid = secrets.token_hex(5)
        reading, results, err = self._identify_card(card)
        self._scans = {k: v for k, v in self._scans.items() if time.time() - v["at"] < 1800}
        jpg = _enc(card, 900)
        self._scans[sid] = {"results": results, "card": jpg, "at": time.time()}
        import scans
        scans.add(sid, jpg, results, reading.text() if reading else "")      # kept for good, beside your other data
        out = {"scan": sid, "found": conf > 0.25, "read": reading.text() if reading else "",
               "candidates": self._cands(results), "error": {"no-ocr": "The number reader is not installed on the "
                                                            "Mac: search by name instead"}.get(err, err or "")}
        if results:
            out["price"] = self._price(results[0])
            out["pick"] = 0
            scans.update(sid, pick=0, price=out["price"])
        return _json(out)

    def _scan_mem(self, sid):
        """A check from this run, or one kept on disk from any earlier run of CardCrop."""
        s = self._scans.get(sid)
        if s is None:
            import scans
            rec = scans.get(sid)
            if rec is not None:
                s = self._scans[sid] = {"results": scans.results(rec), "card": scans.image(sid), "at": rec["at"]}
        return s

    def _scan_price(self, sid, i):
        import scans
        s = self._scan_mem(sid)
        if not s or not 0 <= i < len(s["results"]):
            return _json({"error": "That check is no longer kept: take the photo again"}, 404)
        price = self._price(s["results"][i])
        scans.update(sid, pick=i, price=price)
        return _json({"scan": sid, "pick": i, "price": price})

    def _scan_open(self, sid):
        import scans
        rec = scans.get(sid)
        if rec is None:
            return _json({"error": "That check is no longer kept"}, 404)
        res = scans.results(rec)
        return _json({"scan": sid, "at": rec["at"], "read": rec.get("read", ""), "candidates": self._cands(res),
                      "pick": rec.get("pick"), "price": rec.get("price"), "found": True, "stored": True})

    def _scan_search(self, sid, q):
        if not q:
            return _json({"error": "Type a name or a number"}, 400)
        s = self._scan_mem(sid) if sid else None
        card = None
        if s and s.get("card"):
            arr = np.frombuffer(s["card"], np.uint8)
            card = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        _reading, results, err = self._identify_card(card, query=q)
        import scans
        if not s:
            sid = secrets.token_hex(5)
            s = self._scans[sid] = {"results": [], "card": b"", "at": time.time()}
            scans.add(sid, b"", [], q)
        s["results"] = results
        scans.update(sid, results=[r.to_dict() for r in results], pick=0 if results else None, read=q)
        out = {"scan": sid, "candidates": self._cands(results), "error": err or ("" if results else "Nothing found")}
        if results:
            out["price"] = self._price(results[0])
            out["pick"] = 0
            scans.update(sid, price=out["price"])
        return _json(out)

    # ================================================================ selling
    def ebay_ready(self):
        try:
            c = self.m.ebay_client()
            return bool(c and c.signed_in())
        except Exception:  # noqa: BLE001
            return False

    def unpublished(self):
        import ebay
        try:
            recs = ebay.load_records(self.m.out_dir)
        except Exception:  # noqa: BLE001
            return []
        out = [{"sku": k, "title": r.get("title", k), "price": float(r.get("price", 0) or 0),
                "condition": r.get("condition", ""), "photos": r.get("photos", ""), "uploaded": r.get("uploaded", "")}
               for k, r in recs.items() if r.get("offer_id") and r.get("status") != "published"]
        return sorted(out, key=lambda x: x["uploaded"], reverse=True)

    def _bg(self, conn, work, done, fail="eBay did not take it"):
        """work() on a thread, then done(result) on the UI thread, or a toast with eBay's reason."""
        def run():
            try:
                res = work()
            except Exception as e:  # noqa: BLE001
                msg = f"{fail}: {e}"
                return self.later(lambda: self._say(conn, msg, "error") if conn else self.m.notice(msg, "warn"))
            self.later(lambda: done(res))
        threading.Thread(target=run, daemon=True).start()

    def _publish(self, conn, sku):
        import ebay
        c = self.m.ebay_client()
        rec = ebay.load_records(self.m.out_dir).get(sku, {})
        if not (c and c.signed_in()) or not rec.get("offer_id"):
            return self._say(conn, "Nothing to publish there, or eBay is not connected", "error")

        def done(lid):
            ebay.save_record(self.m.out_dir, sku, {"status": "published", "listing_id": lid,
                                                   "published": time.strftime("%Y-%m-%d %H:%M")})
            self.m._relabel()
            self._say(conn, f"Live on eBay: {rec.get('title', sku)[:40]}")
            self.dirty("store")
            self.dirty("queue")
        self._bg(conn, lambda: c.publish(rec["offer_id"]), done, "Could not publish")

    def fetch_offers(self, conn=None):
        if self._offers_busy:
            return
        c = self.m.ebay_client()
        if not (c and c.signed_in()):
            if conn:
                self._say(conn, "Connect eBay on the Mac first", "error")
            return
        self._offers_busy = True

        def work():
            try:
                return c.best_offers(), ""
            except Exception as e:  # noqa: BLE001
                return None, str(e)

        def done(res):
            self._offers_busy = False
            offers, err = res
            self.offers_err = err
            if offers is not None:
                old = {o["id"] for o in self.offers}
                first = not self.offers_at
                self.offers, self.offers_at = offers, time.time()
                if not first:
                    for o in offers:
                        if o["id"] not in old:
                            self.notify("offers", f"Offer ${o['price']:.2f}", f"{o['title'][:70]} (asking ${o['ask']:.2f})",
                                        "/#store")
            self.dirty("store")
        self._bg(None, work, done)

    def _answer_offer(self, conn, o):
        c = self.m.ebay_client()
        action = {"accept": "Accept", "decline": "Decline", "counter": "Counter"}.get(o.get("action"))
        off = next((x for x in self.offers if x["id"] == o.get("id")), None)
        if not (c and action and off):
            return self._say(conn, "That offer is no longer open", "error")
        counter = float(o.get("counter") or 0)
        if action == "Counter" and counter <= 0:
            return self._say(conn, "Enter a counter price", "error")

        def done(_r):
            self.offers = [x for x in self.offers if x["id"] != off["id"]]
            word = {"Accept": "Accepted", "Decline": "Declined", "Counter": f"Countered at ${counter:.2f}"}[action]
            self._say(conn, f"{word}: {off['title'][:40]}")
            self.dirty("store")
            if action == "Accept":
                QT = __import__("PySide6.QtCore", fromlist=["QTimer"]).QTimer
                QT.singleShot(8000, self.m.store_page.refresh)
        self._bg(conn, lambda: c.respond_offer(off["item"], off["id"], action, counter), done, "eBay refused the answer")

    def _ship(self, conn, o):
        import ebay
        c = self.m.ebay_client()
        sp = self.m.store_page
        sold = (sp.data or {}).get("sold", [])
        sale = next((s for s in sold if s.get("id") == o.get("id") and (s.get("txn") or "") == (o.get("txn") or "")), None)
        if not (c and c.signed_in()) or sale is None:
            return self._say(conn, "Could not find that sale. Refresh the store and try again", "error")
        if not (sale.get("txn") or sale.get("order")):
            return self._say(conn, "This sale was read before CardCrop kept order numbers: refresh the store first", "error")
        tracking = "".join(str(o.get("tracking", "")).split()).upper()
        carrier = o.get("carrier") or (ebay.guess_carrier(tracking) if tracking else "")

        def done(_r):
            sale["shipped"], sale["tracking"] = True, tracking
            try:
                sp.show_data()
            except Exception:  # noqa: BLE001
                pass
            self._say(conn, "Marked shipped" + (f" with {carrier} tracking" if tracking else ""))
            self.dirty("store")
        self._bg(conn, lambda: c.mark_shipped(sale["id"], sale.get("txn", ""), tracking, carrier, sale.get("order", "")),
                 done, "eBay did not mark it shipped")

    def _check_sales(self):
        sold = (self.m.store_page.data or {}).get("sold", [])
        if not sold:
            return
        keys = {f"{s.get('id')}:{s.get('txn') or s.get('date')}": s for s in sold}
        if self._sales_seen is None:
            try:
                self._sales_seen = set(json.loads(str(self.m.cfg.value("phone_sales_seen", "") or "[]")))
            except ValueError:
                self._sales_seen = set()
            if not self._sales_seen:                 # the first look only learns what is already sold
                self._sales_seen = set(keys)
                self.m.cfg.setValue("phone_sales_seen", json.dumps(sorted(self._sales_seen)[-400:]))
                return
        new = [s for k, s in keys.items() if k not in self._sales_seen]
        if not new:
            return
        self._sales_seen |= set(keys)
        self.m.cfg.setValue("phone_sales_seen", json.dumps(sorted(self._sales_seen)[-400:]))
        for s in new[:5]:
            self.notify("sales", f"Sold for ${float(s.get('price') or 0):,.2f}", (s.get("title") or "")[:90], "/#store")
        self.dirty("store")

    # ================================================================ push
    def vapid(self):
        if self._vapid is None:
            self._vapid = phone_push.Vapid(self._cert_folder())
        return self._vapid

    def push_subs(self) -> dict:
        try:
            return json.loads(str(self.m.cfg.value("phone_push", "") or "{}"))
        except ValueError:
            return {}

    def _save_subs(self, d):
        self.m.cfg.setValue("phone_push", json.dumps(d))

    def _subscribe(self, token, sub, kinds):
        from phone_link import _hash
        if not sub.get("endpoint") or not (sub.get("keys") or {}).get("p256dh"):
            return {"ok": False, "error": "The phone did not give a subscription"}
        d = self.push_subs()
        d[sub["endpoint"]] = {"sub": {"endpoint": sub["endpoint"], "keys": sub["keys"]},
                              "kinds": [k for k in (kinds or KINDS) if k in KINDS],
                              "device": _hash(token), "added": time.time()}
        self._save_subs(d)
        return {"ok": True, "kinds": d[sub["endpoint"]]["kinds"]}

    def _unsubscribe(self, endpoint):
        d = self.push_subs()
        if d.pop(endpoint, None) is not None:
            self._save_subs(d)

    def drop_push_for(self, device_hash):
        d = self.push_subs()
        keep = {k: v for k, v in d.items() if v.get("device") != device_hash}
        if len(keep) != len(d):
            self._save_subs(keep)

    def _push_test(self, endpoint):
        s = self.push_subs().get(endpoint)
        if not s:
            return False
        self._send_push([(endpoint, s["sub"])], {"title": "CardCrop", "body": "Notifications work.", "url": "/"})
        return True

    def notify(self, kind, title, body, url="/"):
        """Sends to every phone that asked for this kind, off the UI thread."""
        targets = [(ep, s["sub"]) for ep, s in self.push_subs().items() if kind in s.get("kinds", [])]
        if targets:
            self._send_push(targets, {"title": title, "body": body, "url": url, "kind": kind, "at": time.time()})

    def _send_push(self, targets, msg, sender=None):
        v = self.vapid()
        send = sender or phone_push.send

        def run():
            gone = []
            for ep, sub in targets:
                st = send(v, sub, msg)
                if st in (404, 410):
                    gone.append(ep)
            if gone:
                self.later(lambda: [self._unsubscribe(ep) for ep in gone])
        threading.Thread(target=run, daemon=True).start()


    # ================================================================ live listings, a page at a time
    def _lv(self):
        return self.m.store_page.listings

    def _c_listings(self, conn, o):
        """One page of live listings, searched, filtered and sorted exactly as the Mac's Store does."""
        lv = self._lv()
        items = list(lv.items or (self.m.store_page.data or {}).get("active", []))
        q = str(o.get("q", "")).strip().lower()
        cat = o.get("cat", None)
        sort = int(o.get("sort", 0) or 0)
        _n, key, rev = lv.SORTS[sort if 0 <= sort < len(lv.SORTS) else 0]
        from ui_store import listing_filter, time_left
        f = {k: v for k, v in (o.get("f") or {}).items() if k in ("pmin", "pmax", "ends", "age", "watch")}
        rows = [a for a in items if (not q or q in a.get("title", "").lower() or q in (a.get("sku") or "").lower())
                and lv._in_cat(a, cat) and listing_filter(a, f)]
        rows.sort(key=key, reverse=rev)
        size = max(5, min(60, int(o.get("size", PAGE) or PAGE)))
        pages = max(1, -(-len(rows) // size))
        page = max(0, min(pages - 1, int(o.get("page", 0) or 0)))
        keep = ("id", "title", "price", "image", "watchers", "qty", "url", "sku", "store_cat", "store_cat2")
        out = [dict({k: a.get(k) for k in keep}, cats=lv.cat_names(a), left=time_left(a))
               for a in rows[page * size:(page + 1) * size]]
        cats = [{"id": None, "label": "All categories"},
                {"id": "", "label": f"No store category ({sum(1 for a in items if lv._in_cat(a, ''))})"}]
        for cid, path in self.m.store_cats():
            cats.append({"id": cid, "label": "  " * (path.count("/") - 1) + path.rsplit("/", 1)[-1]
                         + f" ({sum(1 for a in items if lv._in_cat(a, cid))})", "path": path})
        conn.send_json({"t": "listings", "page": page, "pages": pages, "total": len(rows), "all": len(items),
                        "size": size, "rows": out, "sorts": [s_[0] for s_ in lv.SORTS], "sort": sort, "cats": cats,
                        "value": round(sum(float(a.get("price") or 0) * max(1, int(a.get("qty") or 1)) for a in items), 2),
                        "ids": [a.get("id") for a in rows] if o.get("want_ids") else None})

    def _item(self, iid):
        lv = self._lv()
        return next((a for a in list(lv.items or (self.m.store_page.data or {}).get("active", []))
                     if a.get("id") == iid), None)

    def _client_or_say(self, conn):
        c = self.m.ebay_client()
        if not (c and c.signed_in()):
            self._say(conn, "Connect eBay on the Mac first", "error")
            return None
        return c

    def _c_listing(self, conn, o):
        c = self._client_or_say(conn)
        iid = str(o.get("id", ""))
        if c is None or not iid:
            return

        def done(d):
            d = dict(d)
            d["cats"] = [{"id": cid, "label": path.strip("/").replace("/", " › ")} for cid, path in self.m.store_cats()]
            d["policies"] = getattr(self._lv(), "_policies", None)
            mrow = next((r for r in (getattr(self.m.market_page, "rows", None) or []) if r.get("item_id") == iid), None)
            d["market"] = (mrow or {}).get("sugg") or (mrow or {}).get("market")
            conn.send_json({"t": "listing", "id": iid, "d": d})
            if d["policies"] is None:
                self._c_policies(conn, {})
        self._bg(conn, lambda: c.listing_details(iid), done, "Could not read this listing")

    def _c_policies(self, conn, o):
        lv = self._lv()
        c = self._client_or_say(conn)
        if c is None:
            return

        def done(pols):
            lv._policies = pols or []
            conn.send_json({"t": "policies", "policies": lv._policies})
        self._bg(conn, c.fulfillment_policies, done, "Could not read your shipping policies")

    def _c_listing_save(self, conn, o):
        """The phone's changes, checked the way the Mac's editor checks them, then sent to eBay."""
        import listing as _listing
        c = self._client_or_say(conn)
        iid = str(o.get("id", ""))
        item = self._item(iid)
        if c is None or item is None:
            return self._say(conn, "That listing is no longer live", "error") if c else None
        raw, ch = o.get("ch") or {}, {}
        if "title" in raw:
            t_ = str(raw["title"]).strip()[:80]
            if not t_:
                return self._say(conn, "A listing needs a title", "error")
            ch["title"] = t_
        for k in ("price", "auto_accept", "auto_decline"):
            if k in raw:
                try:
                    ch[k] = round(max(0.0, float(raw[k])), 2)
                except (TypeError, ValueError):
                    return self._say(conn, f"That {k.replace('_', ' ')} is not a number", "error")
        if "price" in ch and ch["price"] <= 0:
            return self._say(conn, "The price has to be above zero", "error")
        if "available" in raw:
            ch["available"] = max(0, int(raw["available"]))
        if raw.get("condition") in _listing.CONDITIONS:
            ch["condition"] = raw["condition"]
        if "best_offer" in raw:
            ch["best_offer"] = bool(raw["best_offer"])
            ch.setdefault("auto_accept", 0.0)
            ch.setdefault("auto_decline", 0.0)
            if ch["best_offer"] and ch["auto_accept"] and ch["auto_decline"] >= ch["auto_accept"]:
                return self._say(conn, "Auto-decline has to be below auto-accept", "error")
        if raw.get("ship_policy_set"):
            ch["ship_policy_set"] = str(raw["ship_policy_set"])
        if "store_cat" in raw or "store_cat2" in raw:
            paths = dict(self.m.store_cats())
            a, b = raw.get("store_cat", item.get("store_cat") or ""), raw.get("store_cat2", item.get("store_cat2") or "")
            ch["store_cat"], ch["store_cat2"] = (a or "", paths.get(a, "")), (b or "", paths.get(b, ""))
        if not ch:
            return self._say(conn, "Nothing changed")
        lv = self._lv()

        def done(_r):
            lv._apply_local(iid, ch)
            lv.fill()
            if (lv.cur or {}).get("id") == iid:
                lv.loaded = None
                lv.select(iid)
            self._say(conn, "Saved to eBay")
            self._c_listing(conn, {"id": iid})
            self.dirty("store")
        self._bg(conn, lambda: c.revise_listing(iid, item.get("sku", ""), dict(ch)), done, "eBay did not take it")

    def _c_listing_end(self, conn, o):
        c = self._client_or_say(conn)
        iid = str(o.get("id", ""))
        item = self._item(iid)
        if c is None or item is None:
            return
        lv, sp = self._lv(), self.m.store_page

        def done(_r):
            lv.items = [a for a in lv.items if a.get("id") != iid]
            if sp.data:
                sp.data["active"] = [a for a in sp.data.get("active", []) if a.get("id") != iid]
            if (lv.cur or {}).get("id") == iid:
                lv.cur, lv.loaded = None, None
                lv.show_editor(None)
            lv.fill()
            self._say(conn, "Listing ended")
            conn.send_json({"t": "listing_gone", "id": iid})
            self.dirty("store")
        self._bg(conn, lambda: c.end_listing(iid, item.get("sku", "")), done, "Not ended")

    def _c_listing_video(self, conn, o):
        item = self._item(str(o.get("id", "")))
        if item is None or self._client_or_say(conn) is None:
            return
        self.m.reports_page.add_videos([{"key": f"live:{item['id']}", "live": dict(item)}], ask=False)
        self._say(conn, "Rendering the 360° video on the Mac; it is added to the listing when done")

    def _c_listing_report(self, conn, o):
        import calibrate
        from ui_reports import LiveReportTask, _Relay
        item = self._item(str(o.get("id", "")))
        c = self._client_or_say(conn)
        if item is None or c is None:
            return
        if not calibrate.ready()[0]:
            return self._say(conn, "Condition reports need calibrating once on the Mac: Reports > Calibrate", "error")
        rp = self.m.reports_page
        d = {"key": f"live:{item['id']}", "live": dict(item)}
        t = LiveReportTask(c, self.m.db, self.m.prepare_live(item), add=True, out_path=rp._live_path(d))
        r = _Relay(lambda iid, im, path, err: self._say(
            conn, f"Report not added: {err}" if err else "Condition report added as the listing's last photo",
            "error" if err else "info"))
        r._sig = t.sig
        t.sig.done.connect(r.fire)
        self._lv().pool.start(t)
        self._keep = getattr(self, "_keep", []) + [r]
        self._say(conn, "Making the condition report on the Mac…")

    def _c_batch_cat(self, conn, o):
        lv = self._lv()
        ids = {str(x) for x in o.get("ids") or []}
        slot = 2 if int(o.get("slot", 1) or 1) == 2 else 1
        cid = o.get("cat") or ""
        if not ids or self._client_or_say(conn) is None:
            return
        cat = (cid, dict(self.m.store_cats()).get(cid, "")) if cid else ("", "")
        lv.ticked = ids & {a.get("id") for a in lv.items}
        lv._sync_ticks()
        from PySide6.QtWidgets import QMessageBox
        real = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)   # you confirmed on the phone
        try:
            lv.batch_category(slot, cat)
        finally:
            QMessageBox.question = real
        self._say(conn, f"Moving {len(lv.ticked)} listings…")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(5000, lambda: conn.send_json({"t": "listings_changed"}))

    def _video_upload(self, iid, body, q):
        import os
        item = self.call_main(lambda: self._item(iid))
        if item is None:
            return _json({"error": "That listing is no longer live"}, 404)
        if not body or len(body) < 1000:
            return _json({"error": "The video did not arrive"}, 400)
        ext = ".mov" if (q.get("ext") or [""])[0].lower() == "mov" else ".mp4"
        folder = os.path.join(self.m.out_dir, "Videos")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"phone-{engine.safe_name(item.get('sku') or iid)}-{int(time.time())}{ext}")
        with open(path, "wb") as f:
            f.write(body)
        self.later(lambda: self.m.reports_page.upload_existing_video(dict(item), path))
        return _json({"ok": True})

    # ================================================================ photo edits (the Edit stage's controls)
    def _c_edits(self, conn, o=None):
        m = self.m
        tone = {k: m.edit_sliders[k].value() for k in engine.EDIT_KEYS}
        tone["detail"] = m.s_detail.value()
        presets = [m.preset_combo.itemText(i) for i in range(m.preset_combo.count())]
        conn.send_json({"t": "edits", "tone": tone, "presets": presets, "preset": m.preset_combo.currentIndex(),
                        "ranges": {k: [m.edit_sliders[k].minimum(), m.edit_sliders[k].maximum()] for k in engine.EDIT_KEYS}
                        | {"detail": [0, 100]}})

    def _photo(self, conn, o):
        j = self._job(o.get("job", ""))
        if j is None:
            self._say(conn, "That photo is no longer in the session", "error")
        return j

    def _c_rotate(self, conn, o):
        m, j = self.m, self._photo(conn, o)
        if j is None:
            return
        if j is m.cur:
            m.push_undo()
        j.rotate = (j.rotate + 90 * (1 if int(o.get("dir", 1)) >= 0 else -1)) % 360
        if j is m.cur:
            m.editor.set_view_rotation(j.rotate)
        self._refresh_job(j)

    def _c_side(self, conn, o):
        m, j = self.m, self._photo(conn, o)
        if j is None:
            return
        j.side = "back" if j.side == "front" else "front"
        if j is m.cur:
            m._show_side()
        self._refresh_job(j)

    def _c_rename(self, conn, o):
        m, j = self.m, self._photo(conn, o)
        if j is None:
            return
        name = str(o.get("name", "")).strip()[:120]
        j.card_name = name
        if j is m.cur:
            m.name_edit.setText(name)
            m._show_price()
        self._refresh_job(j)

    def _identify_job(self, j, q):
        """A name or number search for a photo of the session, ranked against the photo itself."""
        card = None
        try:
            card = self.m._upright_core(j)
        except Exception:  # noqa: BLE001
            pass
        return self._identify_card(card, query=q)

    def _c_identify(self, conn, o):
        j = self._photo(conn, o)
        q = str(o.get("q", "")).strip()
        if j is None or not q:
            return

        def work():
            return self._identify_job(j, q)

        def done(res):
            _reading, results, err = res
            j.id_results = results
            j.id_unsure = bool(results)
            conn.send_json({"t": "identify", "job": self._job_key(j), "candidates": self._cands(results),
                            "error": err or ("" if results else "Nothing found for that")})
        self._bg(conn, work, done, "The search failed")

    def _c_tone(self, conn, o):
        m = self.m
        k, v = str(o.get("key", "")), int(o.get("v", 0))
        if k == "detail":
            m.s_detail.setValue(v)
        elif k in m.edit_sliders:
            m.edit_sliders[k].setValue(v)
        else:
            return
        for j in m.jobs:
            j._tone_key = None
        self.dirty("queue")

    def _c_tone_reset(self, conn, o):
        self.m.reset_edits()
        self._c_edits(conn)

    def _c_preset(self, conn, o):
        m = self.m
        i = int(o.get("i", -1))
        if 0 <= i < m.preset_combo.count():
            m.preset_combo.setCurrentIndex(i)
            m._preset_chosen(i)
        self._c_edits(conn)


    # ================================================================ round four: pictures for sales, insights, bulk edits
    def _sale_img(self, iid, sku):
        """A sold card's picture: your own exported front when CardCrop listed it, else eBay's photo."""
        import os
        import engine as _e
        cache = getattr(self, "_sale_imgs", None)
        if cache is None:
            cache = self._sale_imgs = {}
        if iid in cache:
            return cache[iid]
        data = b""
        if sku:
            folder = os.path.join(self.m.out_dir, sku)
            if os.path.isdir(folder):
                import ebay
                ph = ebay.listing_photos(folder)
                fr = next((p for p in ph if "_02_front" in p or "_01_hero" in p), ph[0] if ph else None)
                if fr:
                    try:
                        data = _enc(_e.imread(fr), 300, 82)
                    except Exception:  # noqa: BLE001
                        data = b""
        if not data:
            c = self.call_main(self.m.ebay_client)
            try:
                url = c.item_picture(iid) if c is not None and c.signed_in() else ""
                raw = self.m.db._cached_image(url) if url else None
                if raw:
                    arr = np.frombuffer(raw, np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    data = _enc(img, 300, 82) if img is not None else b""
            except Exception:  # noqa: BLE001
                data = b""
        cache[iid] = data
        return data

    def insights(self):
        """What the Overview leads with: sales over the last 14 days and the cards the market says to reprice."""
        import datetime as dt
        now = time.time()
        hit = getattr(self, "_ins", None)
        if hit and now - hit[0] < 60:
            return hit[1]
        sold = (self.m.store_page.data or {}).get("sold", [])
        today = dt.date.today()
        per = [0.0] * 14
        for x in sold:
            try:
                d = dt.datetime.fromisoformat(str(x.get("date", "")).replace("Z", "+00:00")).astimezone().date()
            except ValueError:
                continue
            k = (today - d).days
            if 0 <= k < 14:
                per[13 - k] += float(x.get("price") or 0)
        week, prev = sum(per[7:]), sum(per[:7])
        alerts = []
        try:
            mp = self.m.market_page
            rows = mp.rows or mp.analyze()
            for r in sorted((r for r in rows if r.get("alerts") and r.get("sugg")), key=lambda r: -abs(r.get("gap") or 0))[:12]:
                kind = next((k for k, _t in r["alerts"] if k in ("raise", "lower")), "")
                gone = self._dismissed().get(r["key"])
                if kind and not (gone is not None and abs(float(gone) - float(r["sugg"])) < 0.01):
                    alerts.append({"key": r["key"], "title": r.get("title", r["key"]), "mine": r.get("mine") or 0,
                                   "sugg": r["sugg"], "kind": kind, "basis": r.get("basis", ""),
                                   "item_id": r.get("item_id", ""), "url": r.get("url", ""), "image": r.get("image", "")})
        except Exception:  # noqa: BLE001
            pass
        out = {"spark": [round(v, 2) for v in per], "week": round(week, 2), "prev": round(prev, 2), "alerts": alerts}
        self._ins = (now, out)
        return out

    def overview(self):
        """The rest of the Mac's Store overview, for the phone: the figures under each tile, the sales
        trend by day and by week, eBay's traffic card, and the most watched and newest listings."""
        import datetime as dt
        d = self.m.store_page.data or {}
        active, sold = d.get("active", []), d.get("sold", [])
        today = dt.date.today()
        per = {}
        for x in sold:
            try:
                day = dt.datetime.fromisoformat(str(x.get("date", "")).replace("Z", "+00:00")).astimezone().date()
            except ValueError:
                continue
            per[day] = per.get(day, 0.0) + float(x.get("price") or 0)
        days = [today - dt.timedelta(days=59 - i) for i in range(60)]
        start = today - dt.timedelta(days=today.weekday() + 7 * 11)
        weeks = [start + dt.timedelta(days=7 * w) for w in range(12)]
        trend = {"daily": [round(per.get(x, 0.0), 2) for x in days],
                 "daily_lbl": [x.strftime("%a %d %b") for x in days],
                 "weekly": [round(sum(v for k, v in per.items() if a <= k < a + dt.timedelta(days=7)), 2) for a in weeks],
                 "weekly_lbl": ["Week of " + a.strftime("%d %b") for a in weeks]}

        def row(a, sub):
            return {"id": a.get("id", ""), "title": a.get("title", ""), "price": float(a.get("price") or 0),
                    "image": a.get("image", ""), "url": a.get("url", ""), "watchers": int(a.get("watchers") or 0),
                    "start": a.get("start", ""), "sub": sub}
        watched = sorted((a for a in active if a.get("watchers")), key=lambda a: -int(a["watchers"]))[:8]
        fresh = sorted(active, key=lambda a: str(a.get("start", "")), reverse=True)[:8]
        n = len(sold)
        total = sum(float(x.get("price") or 0) for x in sold)
        return {"sold_count": n, "sold_avg": round(total / n, 2) if n else 0.0,
                "watchers": sum(int(a.get("watchers") or 0) for a in active),
                "watched_listings": sum(1 for a in active if a.get("watchers")),
                "trend": trend, "traffic": traffic_summary(d.get("traffic"), d.get("traffic_err")),
                "most_watched": [row(a, "watching") for a in watched],
                "just_listed": [row(a, "new") for a in fresh]}

    def _dismissed(self) -> dict:
        try:
            return json.loads(str(self.m.cfg.value("phone_market_dismissed", "") or "{}"))
        except ValueError:
            return {}

    def _c_market_dismiss(self, conn, o):
        """Suggestions put away: each stays away until the market's suggested price for that card changes."""
        mp = self.m.market_page
        sugg = {r.get("key"): r.get("sugg") for r in (mp.rows or [])}
        d = self._dismissed()
        for k in o.get("keys") or []:
            if sugg.get(k) is not None:
                d[k] = sugg[k]
        self.m.cfg.setValue("phone_market_dismissed", json.dumps(d))
        self._ins = None
        self.dirty("store")

    def _c_market_match(self, conn, o):
        mp = self.m.market_page
        r = next((r for r in (mp.rows or []) if r.get("key") == o.get("key")), None)
        if r is None or not r.get("sugg"):
            return self._say(conn, "That market price is gone; scan the market again on the Mac", "error")
        mp.use_price(r)
        self._ins = None
        self._say(conn, f"Price set to ${float(r['sugg']):,.2f}" + (" and sent to eBay" if r.get("status") == "live" else ""))
        self.dirty("store")

    @staticmethod
    def new_price(old, mode, v):
        """A listing's new price for a bulk change: mode pct (v percent up or down) or amt (v dollars)."""
        p = old * (1 + v / 100) if mode == "pct" else old + v
        return max(0.99, round(p, 2))

    def _c_bulk_price(self, conn, o):
        lv = self._lv()
        ids = {str(x) for x in o.get("ids") or []}
        mode = "pct" if o.get("mode") == "pct" else "amt"
        try:
            v = float(o.get("v"))
        except (TypeError, ValueError):
            return self._say(conn, "Type a percentage or an amount", "error")
        items = [a for a in lv.items if a.get("id") in ids]
        c = self._client_or_say(conn)
        if c is None or not items or not v:
            return
        plan = [(a, self.new_price(float(a.get("price") or 0), mode, v)) for a in items]

        def work():
            bad = []
            for a, p in plan:
                try:
                    c.revise_listing(a["id"], a.get("sku", ""), {"price": p})
                except Exception as e:  # noqa: BLE001
                    bad.append(f"{a.get('title', '')[:30]}: {e}")
            return bad

        def done(bad):
            for a, p in plan:
                if not any(b.startswith(a.get("title", "")[:30]) for b in bad):
                    lv._apply_local(a["id"], {"price": p})
            lv.fill()
            self._say(conn, f"{len(plan) - len(bad)} prices changed on eBay" + (f"; {len(bad)} did not: {bad[0]}" if bad else ""),
                      "error" if bad else "info")
            conn.send_json({"t": "listings_changed"})
            self.dirty("store")
        self._say(conn, f"Changing {len(plan)} prices on eBay…")
        self._bg(conn, work, done, "The price change failed")

    def _c_search(self, conn, o):
        """One search across this session's cards, your live listings and your sales."""
        q = str(o.get("q", "")).strip().lower()
        if not q:
            return conn.send_json({"t": "search", "q": "", "cards": [], "live": [], "sold": []})
        try:
            cards = [{"name": c["name"], "title": c["title"], "thumb": self._job_key(c["front"]) if c.get("front") else "",
                      "status": c["status"], "price": c["price"]}
                     for c in self.m._cards() if q in (c["title"] + " " + c["name"]).lower()][:8]
        except Exception:  # noqa: BLE001
            cards = []
        d = self.m.store_page.data or {}
        live = [{k: a.get(k) for k in ("id", "title", "price", "image", "qty", "url", "sku")}
                for a in d.get("active", []) if q in (a.get("title", "") + " " + (a.get("sku") or "")).lower()][:12]
        sold = [{k: x.get(k) for k in ("id", "title", "price", "date", "sku", "shipped", "paid")}
                for x in d.get("sold", []) if q in (x.get("title") or "").lower()][:12]
        conn.send_json({"t": "search", "q": q, "cards": cards, "live": live, "sold": sold})


    def _video_save(self, body, name):
        """A 3D video recorded on the phone, kept on the Mac in the export folder's Videos."""
        import os
        if not body or len(body) < 1000:
            return _json({"error": "The video did not arrive"}, 400)
        base, ext = os.path.splitext(os.path.basename(name))
        ext = ext.lower() if ext.lower() in (".mp4", ".webm", ".mov") else ".mp4"
        folder = os.path.join(self.m.out_dir, "Videos")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{engine.safe_name(base) or 'card-3d'}-{time.strftime('%Y%m%d-%H%M%S')}{ext}")
        with open(path, "wb") as f:
            f.write(body)
        self.later(lambda: self.m.notice(f"A 3D video from the phone is in Videos: {os.path.basename(path)}", "ok", secs=4))
        return _json({"ok": True, "path": path})


    # ================================================================ export from the phone: options, carousel framing, full photos
    def _c_export_opts(self, conn, o):
        """The Export stage's settings, read or set through the Mac's own controls, so on_settings saves them."""
        m, s = self.m, o.get("set") or {}
        boxes = {"corners": m.c_corners, "upscale": m.c_up, "hero": m.c_hero, "ig": m.c_ig}
        for k_, box in boxes.items():
            if k_ in s:
                box.setChecked(bool(s[k_]))
        if "corner" in s:
            m.s_corner.setValue(max(15, min(50, int(s["corner"]))))
        for k_, combo in (("fmt", m.fmt), ("hero_sides", m.hero_sides), ("hero_bg", m.hero_bg)):
            if k_ in s and combo.findData(s[k_]) >= 0:
                combo.setCurrentIndex(combo.findData(s[k_]))
        if s:
            m.on_settings()
        conn.send_json({"t": "export_opts", **{k_: box.isChecked() for k_, box in boxes.items()},
                        "corner": m.s_corner.value(), "fmt": m.fmt.currentData(), "hero_bg": m.hero_bg.currentData(), "hero_sides": m.hero_sides.currentData(),
                        "hero_sides_opts": [[m.hero_sides.itemData(i), m.hero_sides.itemText(i)] for i in range(m.hero_sides.count())],
                        "fmts": [[m.fmt.itemData(i), m.fmt.itemText(i)] for i in range(m.fmt.count())],
                        "hero_bgs": [[m.hero_bg.itemData(i), m.hero_bg.itemText(i)] for i in range(m.hero_bg.count())]})

    def _ig_front(self, conn, name):
        name = str(name).strip()
        j = next((x for x in self.m.jobs if x.card_name.strip() == name and x.side == "front"
                  and x.quad is not None), None)
        if j is None:
            self._say(conn, "This card has no front with its corners set in the session", "error")
        return j

    def _c_ig_get(self, conn, o):
        j = self._ig_front(conn, o.get("name", ""))
        if j is None:
            return
        st = self.m.settings
        conn.send_json({"t": "ig", "name": j.card_name.strip(), "crop": list(j.ig_crop or st.ig_crop),
                        "default": list(st.ig_crop), "aspect": 2 * engine.IG_W / engine.IG_H, "on": st.ig})

    def _c_ig_set(self, conn, o):
        m, j = self.m, self._ig_front(conn, o.get("name", ""))
        if j is None:
            return
        try:
            l_, t_, w_ = (float(v) for v in o.get("crop", []))
        except (TypeError, ValueError):
            return
        crop = (max(0.0, min(1.0, l_)), max(0.0, min(1.0, t_)), max(0.2, min(1.0, w_)))
        j.ig_crop = crop
        if o.get("default"):
            m.settings.ig_crop = crop
            m._save_cfg()
        if j.done:
            m._start_ig(j)              # already exported: write the slides now, as the Mac does
            self._say(conn, "Writing the carousel on the Mac")
        else:
            self._say(conn, "Framing saved; the slides are written when this card exports")
        m._label(j)

    def _c_surface(self, conn, o):
        """The surface the cards lie on: shoot it empty and cards are found as what differs from it, which
        holds a dark border on a dark mat; also reports how evenly it is lit. do: get, shoot or clear."""
        import level
        m, do = self.m, str(o.get("do", "get"))
        if do == "level":
            # the phone's four readings, mat and camera each twice: measured and kept on the Mac
            try:
                rep = level.measure(o.get("reads") or [], float(o.get("span") or level.SPAN_MM))
            except (TypeError, ValueError) as e:
                rep = {"on": False, "error": str(e)}
            if rep.get("on"):
                level.save(rep)
                if hasattr(m, "_refresh_level"):
                    m._refresh_level(force=True)
            return conn.send_json({"t": "level", **rep})
        if do == "level_clear":
            level.clear()
            if hasattr(m, "_refresh_level"):
                m._refresh_level(force=True)
            return conn.send_json({"t": "level", "on": False, "quiet": True})
        if do == "clear":
            engine.clear_surface()
        elif do == "shoot":
            if not m.tether.is_connected:
                return self._say(conn, "No camera connected to CardCrop", "error")

            def done(rep):
                conn.send_json({"t": "surface", **rep, "level": level.load(), "shot": True})
            m._surface_next = done
            m.tether.shoot(af=True)
            return
        conn.send_json({"t": "surface", **engine.surface_report(), "level": level.load(), "quiet": bool(o.get("quiet"))})

    def _c_card_video(self, conn, o):
        """The Mac's 360° video of a session card, rendered with your 3D export settings into the card's
        folder, then offered to the phone to save."""
        m = self.m
        name = str(o.get("name", "")).strip()
        front, back = m._card_sides(name) if name else (None, None)
        if front is None and back is None:
            return self._say(conn, "This card has no straightened photo to make a video from", "error")
        if getattr(self, "_video_busy", False):
            return self._say(conn, "The Mac is still rendering the last video", "error")
        self._video_busy = True
        back_to = m.stage
        m.go("view3d")
        m.viewer3d.show_images(name[:40], front, back)
        self._say(conn, "Rendering the 360° video on the Mac…")

        def render():
            slug = engine.safe_name(name)
            path = os.path.join(m.out_dir, slug, f"{slug}_360.mp4")
            err = ""
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                if not m.viewer3d.render_saved(path, lambda i, n: True):
                    err = "The render stopped"
            except Exception as e:  # noqa: BLE001
                err = f"The video could not be rendered: {e}"
            finally:
                self._video_busy = False
                m.go(back_to)
            if err or not os.path.isfile(path):
                return self._say(conn, err or "The video was not written", "error")
            files = self._card_files(name)
            i = next((k_ for k_, (p, _g, _kb) in enumerate(files) if os.path.samefile(p, path)), -1)
            conn.send_json({"t": "card_video", "name": name, "i": i, "file": os.path.basename(path),
                            "kb": os.path.getsize(path) // 1024})
        from PySide6.QtCore import QTimer
        QTimer.singleShot(700, render)           # let the 3D view start before rendering, as the Mac does

    def _card_files(self, name):
        """A card's exported photos, the listing's first and then each subfolder's (instagram, corners),
        as (path, group, size in kB)."""
        folder = os.path.join(self.m.out_dir, engine.safe_name(name.strip()))
        if not name.strip() or not os.path.isdir(folder):
            return []
        exts = (".png", ".jpg", ".jpeg", ".tif", ".tiff") + VIDEO_EXTS
        out = []
        for sub in [""] + sorted(d for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d))
                                 and not d.startswith(".")):
            here = os.path.join(folder, sub)
            for f in sorted(os.listdir(here)):
                p = os.path.join(here, f)
                if f.lower().endswith(exts) and not f.startswith(".") and os.path.isfile(p):
                    group = "video" if f.lower().endswith(VIDEO_EXTS) else (sub or "listing")
                    out.append((p, group, os.path.getsize(p) // 1024))
        return out

    def _card_file(self, name, i):
        """One exported photo at full size, as a JPEG the phone can save: a JPEG goes as it is, a PNG or
        TIFF (16-bit, float, with a transparent edge) is flattened onto white and written at quality 95."""
        import cv2
        files = self._card_files(name)
        try:
            path = files[int(i)][0]
        except (ValueError, IndexError):
            return 404, "text/plain", b""
        if path.lower().endswith((".jpg", ".jpeg") + VIDEO_EXTS):
            kind = "video/quicktime" if path.lower().endswith(".mov") else \
                "video/mp4" if path.lower().endswith(VIDEO_EXTS) else "image/jpeg"
            with open(path, "rb") as f:
                return 200, kind, f.read()
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH)
        if img is None:
            return 404, "text/plain", b""
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        alpha = None
        if img.shape[2] == 4:
            alpha = img[:, :, 3:4]
            img = img[:, :, :3]
        x = engine.to8(img)
        if alpha is not None:
            a = alpha.astype(np.float32) / (65535.0 if alpha.dtype == np.uint16 else 1.0 if alpha.dtype.kind == "f" else 255.0)
            x = (x.astype(np.float32) * a + 255.0 * (1 - a)).clip(0, 255).astype(np.uint8)
        ok, buf = cv2.imencode(".jpg", x, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return (200, "image/jpeg", buf.tobytes()) if ok else (500, "text/plain", b"")

    # ================================================================ condition reports from the phone
    def _report(self, name):
        import calibrate
        if not calibrate.ready()[0]:
            return _json({"error": "Condition reports need calibrating once on the Mac: Reports > Calibrate."}, 409)
        got = self.call_main(lambda: self.m._report_for(name), None, timeout=90)
        if got is None:
            return _json({"error": "Set this card's corners on both sides first, then make its report."}, 404)
        im, _res = got
        self._reports = getattr(self, "_reports", {})
        self._reports[name] = im
        import io
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=88)
        return 200, "image/jpeg", buf.getvalue()

    def _report_save(self, name):
        im = getattr(self, "_reports", {}).get(name)
        if im is None:
            return _json({"error": "Make the report again first"}, 404)
        path = self.call_main(lambda: self.m._save_report(name, im), None, timeout=30)
        return _json({"ok": bool(path), "path": path or ""})


def traffic_summary(tr, err=None):
    """eBay's traffic report reduced to what the Store shows: impressions, click-through, page views
    and conversion for the last 30 days, each with its change on the 30 before and a value a day for
    the last 14, and where the page views came from. The same arithmetic as the Mac's Traffic card."""
    import datetime as dt
    if not tr:
        return {"err": "reconnect" if err == "reconnect" else (str(err) if err else "")}
    days, split = tr.get("days", []), tr.get("split", "")
    cur = [v for k, v in days if k > split]
    prev = [v for k, v in days if k <= split]

    def tot(rows, key, alt=None):
        if alt and rows and not any(key in r for r in rows):
            key = alt
        return sum(r.get(key, 0.0) for r in rows)

    def figures(rows):
        impr = tot(rows, "TOTAL_IMPRESSION_TOTAL", "LISTING_IMPRESSION_TOTAL")
        si, sv = tot(rows, "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE"), tot(rows, "LISTING_VIEWS_SOURCE_SEARCH_RESULTS_PAGE")
        views, tx = tot(rows, "LISTING_VIEWS_TOTAL"), tot(rows, "TRANSACTION")
        return {"impr": impr, "ctr": (sv / si * 100) if si else 0.0, "views": views,
                "conv": (tx / views * 100) if views else 0.0}

    a, b = figures(cur), (figures(prev) if prev else None)

    def series(key):
        out = []
        for r in cur[-14:]:
            if key == "impr":
                out.append(r.get("TOTAL_IMPRESSION_TOTAL", r.get("LISTING_IMPRESSION_TOTAL", 0.0)))
            elif key == "views":
                out.append(r.get("LISTING_VIEWS_TOTAL", 0.0))
            elif key == "ctr":
                i_ = r.get("LISTING_IMPRESSION_SEARCH_RESULTS_PAGE", 0.0)
                out.append(r.get("LISTING_VIEWS_SOURCE_SEARCH_RESULTS_PAGE", 0.0) / i_ if i_ else 0.0)
            else:
                v_ = r.get("LISTING_VIEWS_TOTAL", 0.0)
                out.append(r.get("TRANSACTION", 0.0) / v_ if v_ else 0.0)
        return [round(float(v), 4) for v in out]

    metrics = []
    for key, label in (("impr", "Listing impressions"), ("ctr", "Click-through rate"),
                       ("views", "Listing page views"), ("conv", "Sales conversion rate")):
        pct = key in ("ctr", "conv")
        change, up = "", None
        if b is not None:
            if pct:
                dd = a[key] - b[key]
                change, up = f"{abs(dd):.1f} pts", (None if abs(dd) < 0.05 else dd > 0)
            elif b[key]:
                dd = (a[key] - b[key]) / b[key] * 100
                change, up = f"{abs(dd):.1f}%", (None if abs(dd) < 0.05 else dd > 0)
            elif a[key]:
                change, up = "new", True
        metrics.append({"key": key, "label": label, "value": f"{a[key]:.1f}%" if pct else f"{a[key]:,.0f}",
                        "change": change, "up": up, "series": series(key)})
    parts = (("Search", "LISTING_VIEWS_SOURCE_SEARCH_RESULTS_PAGE"), ("Other eBay", "LISTING_VIEWS_SOURCE_OTHER_EBAY"),
             ("Store", "LISTING_VIEWS_SOURCE_STORE"), ("Direct", "LISTING_VIEWS_SOURCE_DIRECT"),
             ("External", "LISTING_VIEWS_SOURCE_OFF_EBAY"))
    sources = []
    if any("LISTING_VIEWS_SOURCE_OFF_EBAY" in r for r in cur):
        sources = [{"name": k, "views": round(tot(cur, m_))} for k, m_ in parts]
    try:
        s0 = dt.date.fromisoformat(split) + dt.timedelta(days=1)
        e0 = dt.date.fromisoformat(tr.get("end", ""))
        span = f"{s0.strftime('%b %d')} to {e0.strftime('%b %d')}"
    except ValueError:
        span = "The last 30 days"
    return {"metrics": metrics, "sources": sources,
            "note": f"{span}, Pacific time; changes against the 30 days before."
                    + ("" if b is not None else " No earlier period to compare.")}
