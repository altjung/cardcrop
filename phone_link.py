"""CardCrop's phone console, the app side: what the phone may see and do, answered on the UI thread.

The server (phone_server.py) runs on background threads and never touches the window; everything it
needs from the app comes through PhoneLink, a QObject living on the UI thread, by a queued signal.
HTTP requests that need an answer wait for it (call_main); WebSocket commands do not wait.

Pairing: the Phone pane in Settings shows a QR code and a six-digit code. The QR opens the setup page
(plain HTTP, port 8744), which installs CardCrop's certificate authority once and then opens the
console; the console trades the code for a device token kept on the phone, and the app keeps only a
hash of each token, so a lost phone is removed from Settings and never works again."""
from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import sys
import threading
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QImage

import phone_server as ps
from phone_tools import PhoneTools

PAIR_LIFE = 15 * 60          # a pairing code works for 15 minutes, once


def _base():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def _jpeg(img: QImage, long_edge=0, q=78) -> bytes:
    if img is None or img.isNull():
        return b""
    if long_edge and max(img.width(), img.height()) > long_edge:
        img = img.scaled(long_edge, long_edge, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPEG", q)
    return bytes(ba)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PhoneLink(PhoneTools, QObject):
    _call = Signal(object)
    changed = Signal()           # devices or connections changed: the Settings pane redraws

    def __init__(self, main):
        super().__init__(main)
        self.m = main
        self._call.connect(self._run, Qt.QueuedConnection)
        self.static_dir = os.path.join(_base(), "mobile")
        self.font_dir = os.path.join(_base(), "fonts")
        self.server = ps.PhoneServer(self, self._cert_folder())
        self.pair_code, self.pair_until = "", 0.0
        self._frame_at = 0.0
        self._thumbs = {}            # job key -> (pixmap cache key, jpeg)
        self._sides = {}             # card name -> (time, front jpeg, back jpeg)
        self._push = QTimer(self, singleShot=True, interval=250)
        self._push.timeout.connect(self._push_now)
        self._dirty = set()
        self._wired = False
        self._last = {}                  # what each kind of message last said, so polls send only changes
        self._poll = QTimer(self, interval=2000)
        self._poll.timeout.connect(self._poll_now)
        self._polls = 0
        self.tools_init()

    # ------------------------------------------------------------ settings and lifecycle
    def _cert_folder(self):
        import identify
        return os.path.join(os.path.dirname(identify._cache_dir()), "phone")

    def enabled(self):
        return str(self.m.cfg.value("phone_on", "false")).lower() in ("true", "1")

    def set_enabled(self, on: bool):
        self.m.cfg.setValue("phone_on", "true" if on else "false")
        if on:
            self.start()
        else:
            self.server.stop()
            self.changed.emit()

    def start(self) -> bool:
        ok = self.server.start()
        if ok:
            self._wire()
            self.new_code()
        self.changed.emit()
        return ok

    def stop(self):
        self.server.stop()

    def _wire(self):
        if self._wired:
            return
        self._wired = True
        t = self.m.tether
        t.frame.connect(self._on_frame)
        t.connected.connect(lambda *_: self.dirty("status"))
        t.disconnected.connect(lambda: self.dirty("status"))
        t.props.connect(lambda *_: self.dirty("status"))
        t.focus.connect(lambda s: self.server.broadcast({"t": "focus", "state": s}))
        t.shot.connect(lambda: self.server.broadcast({"t": "shot"}))
        t.file.connect(lambda *_: QTimer.singleShot(600, lambda: (self.dirty("status"), self.dirty("queue"))))
        self._poll.start()

    def new_code(self):
        self.pair_code = f"{secrets.randbelow(1_000_000):06d}"
        self.pair_until = time.time() + PAIR_LIFE
        self.changed.emit()

    def hosts(self) -> list:
        """The addresses the phone can use, (key, host, what it is good for), the default first:
        Tailscale's name works anywhere both are signed in; the Bonjour name works on your Wi-Fi and
        survives the router handing the Mac a new address; the bare address works on any network."""
        out = []
        ts = self.server.ts or {}
        if ts.get("name") or ts.get("ip"):
            out.append(("tailscale", ts.get("name") or ts.get("ip"), "Tailscale, works anywhere"))
        out.append(("local", ps.host_name(), "this Wi-Fi, by name"))
        ip = next((i for i in (self.server.ips or ps.lan_addresses()) if not i.startswith("100.")), "127.0.0.1")
        out.append(("ip", ip, "this Wi-Fi, by address"))
        return out

    def host(self) -> str:
        want = str(self.m.cfg.value("phone_host", "auto"))
        hs = self.hosts()
        return next((h for k, h, _ in hs if k == want), hs[0][1])

    def set_host(self, key):
        self.m.cfg.setValue("phone_host", key)
        self.changed.emit()

    def url_setup(self):
        return f"http://{self.host()}:{ps.HTTP_PORT}/setup?pair={self.pair_code}"

    def url_console(self):
        return f"https://{self.host()}:{ps.HTTPS_PORT}/"

    # ------------------------------------------------------------ devices
    def devices(self) -> dict:
        try:
            return json.loads(str(self.m.cfg.value("phone_devices", "") or "{}"))
        except ValueError:
            return {}

    def _save_devices(self, d):
        self.m.cfg.setValue("phone_devices", json.dumps(d))
        self.changed.emit()

    def forget(self, h):
        d = self.devices()
        d.pop(h, None)
        self._save_devices(d)
        self.drop_push_for(h)
        for c in self.server.clients():
            if _hash(c.token) == h:
                c.send_json({"t": "unpaired"})
                c.close()

    def valid_token(self, token) -> bool:
        if not token or not isinstance(token, str):
            return False
        return self.call_main(lambda: _hash(token) in self.devices(), False)

    def _pair(self, code, name):
        if not self.pair_code or time.time() > self.pair_until or not secrets.compare_digest(str(code), self.pair_code):
            return None
        token = secrets.token_urlsafe(32)
        d = self.devices()
        d[_hash(token)] = {"name": (name or "iPhone")[:40], "added": time.time(), "seen": time.time()}
        self._save_devices(d)
        self.new_code()                  # used once
        self.m.notice(f"{name or 'A phone'} is paired with CardCrop", "info", secs=3)
        return token

    def connected_names(self):
        d = self.devices()
        return [d.get(_hash(c.token), {}).get("name", "Phone") for c in self.server.clients()]

    # ------------------------------------------------------------ thread bridge
    def _run(self, item):
        fn, ev, box = item
        try:
            box.append(fn())
        except Exception as e:  # noqa: BLE001
            box.append(e)
        if ev is not None:
            ev.set()

    def call_main(self, fn, default=None, timeout=8.0):
        if threading.current_thread() is threading.main_thread():
            try:
                return fn()
            except Exception:  # noqa: BLE001
                return default
        ev, box = threading.Event(), []
        self._call.emit((fn, ev, box))
        if not ev.wait(timeout) or not box or isinstance(box[0], Exception):
            return default
        return box[0]

    def later(self, fn):
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            self._call.emit((fn, None, []))

    # ------------------------------------------------------------ setup page (plain HTTP)
    def setup_page(self, q) -> str:
        code = (q.get("pair") or [""])[0]
        code = code if code.isdigit() and len(code) == 6 else ""
        host = self.call_main(self.host, "127.0.0.1")
        console = f"https://{host}:{ps.HTTPS_PORT}/" + (f"#pair={code}" if code else "")
        return SETUP_HTML.replace("{{CONSOLE}}", html.escape(console)).replace("{{HOST}}", html.escape(host))

    # ------------------------------------------------------------ HTTP API (handler threads)
    def http(self, method, path, q, body, token):
        if path == "/api/pair" and method == "POST":
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                req = {}
            tok = self.call_main(lambda: self._pair(req.get("code", ""), str(req.get("name", ""))))
            if not tok:
                return 403, "application/json", b'{"error":"That code did not work. Check the six digits in CardCrop > Settings > Phone."}'
            return 200, "application/json", json.dumps({"token": tok}).encode()
        if not self.valid_token(token):
            return 401, "application/json", b'{"error":"unpaired"}'
        parts = path.split("/")
        if path.startswith("/api/thumb/") and len(parts) == 4:
            key = parts[3].rsplit(".", 1)[0]
            try:
                data = self._thumb(key)
            except Exception:  # noqa: BLE001
                data = b""
            return (200, "image/jpeg", data) if data else (404, "text/plain", b"")
        if path.startswith("/api/card/") and len(parts) == 5:
            import urllib.parse
            name, side = urllib.parse.unquote(parts[3]), parts[4].rsplit(".", 1)[0]
            data = self._side(name, side)
            return (200, "image/jpeg", data) if data else (404, "text/plain", b"")
        r = self.tool_http(method, path, q, body, token)
        if r is not None:
            return r
        return 404, "text/plain", b"not here"

    def _job_key(self, j):
        k = getattr(j, "_phone_key", None)
        if k is None:
            k = j._phone_key = secrets.token_hex(4)
        return k

    def _back_key(self, name):
        """The back's own small picture, from the session's back photo of this card: the same quick
        thumbnail the filmstrip shows, never the full straightening the 3D view needs."""
        back = next((x for x in self.m.jobs if x.card_name.strip() == name and x.side == "back"), None)
        if back is None:                       # a back shot straight after its front, not named yet
            front = next((x for x in self.m.jobs if x.card_name.strip() == name and x.side == "front"), None)
            back = next((x for x in self.m.jobs if getattr(x, "_pair_of", None) is front and front is not None), None)
        return self._job_key(back) if back is not None else ""

    def _job(self, key):
        return next((j for j in self.m.jobs if getattr(j, "_phone_key", None) == key), None)

    def _thumb(self, key):
        j = self._job(key)
        if j is None:
            return b""
        # the filmstrip's own small picture, as it shows it (toned when the Mac has toned it), encoded here on
        # the server's thread: waiting on the window, which is busy while a batch develops, timed the
        # picture out and the phone drew a broken image
        arr = getattr(j, "thumb", None)
        if arr is None:
            arr = getattr(j, "thumb_base", None)
        if arr is None:
            return b""
        hit = self._thumbs.get(key)
        if hit and hit[0] is arr:
            return hit[1]
        import cv2
        import engine
        ok, buf = cv2.imencode(".jpg", engine.to8(arr), [cv2.IMWRITE_JPEG_QUALITY, 85])
        data = buf.tobytes() if ok else b""
        self._thumbs[key] = (arr, data)
        return data

    def _side(self, name, side):
        hit = self._sides.get(name)
        if not hit or time.time() - hit[0] > 30:
            pics = self.call_main(lambda: self.m._card_sides(name), (None, None), timeout=45)
            import cv2
            enc = []
            for img in pics or (None, None):
                if img is None:
                    enc.append(b"")
                    continue
                h, w = img.shape[:2]
                s = 1024 / max(h, w)
                if s < 1:
                    img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
                # the straightened card comes as 16-bit from a RAW, or as floats once tone edits are on: a
                # JPEG needs 8-bit, and without this the phone got a black card
                import engine
                ok, buf = cv2.imencode(".jpg", engine.to8(img), [cv2.IMWRITE_JPEG_QUALITY, 88])
                enc.append(buf.tobytes() if ok else b"")
            hit = self._sides[name] = (time.time(), enc[0], enc[1])
        return hit[1] if side == "front" else hit[2] if side == "back" else b""

    # ------------------------------------------------------------ live view
    def _on_frame(self, img):
        now = time.monotonic()
        if now - self._frame_at < 0.125:
            return
        watchers = [c for c in self.server.clients() if c.wants_frames]
        if not watchers:
            return
        self._frame_at = now
        rot = int(getattr(getattr(self.m, "live", None), "rot", 0) or 0) % 360
        if rot:                                    # the way the Mac's live view is turned, so a card stands upright
            from PySide6.QtGui import QTransform
            img = img.transformed(QTransform().rotate(rot))
        data = _jpeg(img, 640, 70)
        for c in watchers:
            c.send_binary(data)

    # ------------------------------------------------------------ WebSocket (handler threads)
    def ws_open(self, conn):
        def hello():
            d = self.devices()
            h = _hash(conn.token)
            if h in d:
                d[h]["seen"] = time.time()
                self._save_devices(d)
            conn.send_json({"t": "hello", "app": getattr(sys.modules.get("app"), "APP_VERSION", ""),
                            "host": ps.host_name()})
            conn.send_json(self._status())
            conn.send_json(self._queue())
            conn.send_json(self._store())
        self.later(hello)

    def ws_close(self, conn):
        self.later(self.changed.emit)

    def ws_message(self, conn, obj):
        t = obj.get("t")
        if t == "live":
            conn.wants_frames = bool(obj.get("on"))
            return
        if t == "ping":
            conn.send_json({"t": "pong"})
            return
        self.later(lambda: self._command(conn, obj))

    def _say(self, conn, text, kind="info"):
        conn.send_json({"t": "toast", "text": text, "kind": kind})

    def _command(self, conn, o):
        m, t = self.m, o.get("t")
        if t == "shoot":
            if not m.tether.is_connected:
                return self._say(conn, "No camera connected to CardCrop", "error")
            m.tether.shoot(af=True)
        elif t == "af":
            if m.tether.is_connected:
                m.tether.autofocus()
        elif t == "cam":
            key, idx = o.get("key"), int(o.get("idx", -1))
            combo = m.cam_combos.get(key)
            if combo is not None and 0 <= idx < combo.count() and combo.isEnabled():
                combo.setCurrentIndex(idx)          # the desktop control follows and sets the camera
                m.cam_set(key, idx)
        elif t == "batch":
            m.c_batch.setChecked(bool(o.get("on")))
            self.dirty("status")
        elif t == "next_side":
            m.set_next_side("back" if o.get("side") == "back" else "front")
            self.dirty("status")
        elif t == "pick":
            j = self._job(o.get("job", ""))
            res = getattr(j, "id_results", None) if j is not None else None
            i = int(o.get("i", -1))
            if not res or not 0 <= i < len(res):
                return self._say(conn, "That card is no longer waiting", "error")
            m._apply_info(j, res[i], explicit=True)
            j.id_unsure = False
            if getattr(j, "mark", "") == "?":
                j.mark = ""
            m._label(j)
            self._say(conn, f"Named {j.card_name}")
            self.dirty("queue")
        elif t == "cond":
            self._set_condition(str(o.get("name", "")), str(o.get("code", "")))
        elif t == "price":
            name, v = str(o.get("name", "")), o.get("v")
            try:
                v = round(float(v), 2)
            except (TypeError, ValueError):
                return
            if name and v >= 0:
                m._set_price(name, v)
                self.dirty("queue")
        elif t == "export_ready":
            m.export_ready()
        elif t == "listing_price":
            sp = m.store_page
            item = next((a for a in (sp.data or {}).get("active", []) if a.get("id") == o.get("id")), None)
            try:
                v = round(float(o.get("price")), 2)
            except (TypeError, ValueError):
                v = 0
            if item is None or v <= 0:
                return self._say(conn, "Could not find that listing", "error")
            sp.listings.quick(item, {"price": v})
            item["price"] = v
            self._say(conn, f"Updating to ${v:,.2f} on eBay…")
            QTimer.singleShot(4000, lambda: self.dirty("store"))
        elif t in ("card_upload", "card_publish"):
            name = str(o.get("name", ""))
            if not any(x.card_name.strip() == name for x in m.jobs):
                return self._say(conn, "That card is no longer in the session", "error")
            from PySide6.QtWidgets import QMessageBox
            real = QMessageBox.question
            QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)   # confirmed on the phone
            try:
                if t == "card_upload":
                    m.batch_upload([name])
                    self._say(conn, "Uploading to eBay as unpublished…")
                else:
                    m.batch_publish([name])
                    self._say(conn, "Putting it live on eBay…")
            finally:
                QMessageBox.question = real
            QTimer.singleShot(1500, lambda: self.dirty("queue"))
        elif t == "listing_qty":
            sp = m.store_page
            item = next((a for a in (sp.data or {}).get("active", []) if a.get("id") == o.get("id")), None)
            try:
                v = max(0, int(o.get("qty")))
            except (TypeError, ValueError):
                v = -1
            if item is None or v < 0:
                return self._say(conn, "Could not find that listing", "error")
            sp.listings.quick(item, {"available": v})
            item["qty"] = v
            self._say(conn, f"Updating to {v} available on eBay…")
        elif self.tool_command(conn, o):
            pass
        elif t == "refresh":
            what = o.get("what", "")
            if what == "store":
                sp = m.store_page
                if o.get("force") or sp.stale():
                    # the phone's Refresh reads eBay again on the Mac too, so both show the same store
                    sp.after_fetch = getattr(sp, "after_fetch", []) + [lambda: (self.dirty("store"),
                                                                              self.server.broadcast({"t": "listings_changed"}))]
                    sp.refresh()
                    if m.stage == "list":
                        m.list_page.refresh()
                conn.send_json(self._store())
            elif what == "queue":
                m._relabel()
                if m.stage == "list":
                    m.list_page.refresh()
                conn.send_json(self._queue())
            else:
                conn.send_json(self._status())

    def _set_condition(self, name, code):
        m = self.m
        import listing
        if code and code not in listing.CONDITIONS:
            return
        same = [x for x in m.jobs if name and x.card_name.strip() == name]
        if not same:
            return
        m._mark_changed(name)
        for x in same:
            x.condition = code
            m._label(x)
        if m.cur in same:
            m._show_side()
            m._show_listing()
        self.dirty("queue")

    # ------------------------------------------------------------ what the phone is shown
    def dirty(self, what):
        if not self.server.clients():
            return
        self._dirty.add(what)
        if not self._push.isActive():
            self._push.start()

    def _push_now(self):
        todo, self._dirty = self._dirty, set()
        for what in todo:
            self._send_if_new(what, force=True)

    def _send_if_new(self, what, force=False):
        msg = {"status": self._status, "queue": self._queue, "store": self._store}[what]()
        sig = json.dumps(msg, sort_keys=True, default=str)
        if force or self._last.get(what) != sig:
            self._last[what] = sig
            self.server.broadcast(msg)

    def _poll_now(self):
        """Catches what changes without a signal (marks from the pipeline, a price typed on the Mac,
        the store refreshing): status every 2 s, the queue every 4 s, the store every 10 s."""
        self._polls += 1
        self.tools_tick(self._polls)
        if not self.server.clients():
            self._last.clear()
            return
        self._send_if_new("status")
        if self._polls % 2 == 0:
            self._send_if_new("queue")
        if self._polls % 5 == 0:
            self._send_if_new("store")

    def _status(self):
        m = self.m
        cam = {}
        for key, combo in getattr(m, "cam_combos", {}).items():
            if key not in ("fnumber", "shutter", "iso", "ev", "wb", "kelvin"):
                continue
            cam[key] = {"items": [combo.itemText(i) for i in range(combo.count())],
                        "cur": combo.currentIndex(), "on": combo.isEnabled() and combo.count() > 0}
        return {"t": "status", "camera": bool(m.tether.is_connected), "model": m.tether.model or "",
                "cam": cam, "batch": m.c_batch.isChecked(), "next": m.next_lbl.text(),
                "photos": len(m.jobs), "attention": sum(1 for j in m.jobs if getattr(j, "mark", "") in ("⚠", "!", "✕", "?"))}

    def _queue(self):
        import listing
        m = self.m
        cards = []
        try:
            all_cards = m._cards()
        except Exception:  # noqa: BLE001
            all_cards = []
        listed = 0
        cards3d = [{"name": c["name"], "title": c["title"], "thumb": self._job_key(c["front"]) if c.get("front") else ""}
                   for c in all_cards]
        for c in all_cards:
            if c["status_key"] in ("live", "sold"):      # on eBay already: off the review list, as in List
                listed += 1
                continue
            cards.append({"name": c["name"], "title": c["title"], "num": c["num"], "set": c["set"],
                          "cond": c["cond"], "price": c["price"], "sugg": c["sugg"], "market": c.get("market"), "status": c["status"],
                          "status_key": c["status_key"], "thumb": self._job_key(c["front"]) if c.get("front") else "",
                          "back_thumb": self._back_key(c["name"]),
                          "tip": c.get("status_tip") or (c["status"] if len(c["status"]) > 26 else ""),
                          "short": ("Failed" if c["status"].startswith("Failed") else c["status"])[:26]})
        waiting = []
        for j in m.jobs:
            res = getattr(j, "id_results", None)
            if not res or not getattr(j, "id_unsure", False) or j.card_name.strip():
                continue
            waiting.append({"job": self._job_key(j), "stem": j.stem, "candidates": [
                {"i": i, "label": r.label(), "img": (r.image if r.image.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                                                     else (r.image + "/low.png") if r.image else "")}
                for i, r in enumerate(res[:8])]})
        conds = [{"code": k, "label": v[0]} for k, v in listing.CONDITIONS.items()]
        return {"t": "queue", "cards": cards, "listed": listed, "cards3d": cards3d, "waiting": waiting, "conds": conds, "recent": self.recent_shots(),
                "ready": len({j.card_name.strip() for j in m.ready_jobs()}) if hasattr(m, "ready_jobs") else 0}

    def _store(self):
        d = self.m.store_page.data or {}
        active, sold = d.get("active", []), d.get("sold", [])
        return {"t": "store", "fetched": d.get("fetched", 0),
                "active_count": len(active),
                "active_value": round(sum(float(a.get("price") or 0) * max(1, int(a.get("qty") or 1)) for a in active), 2),
                "sold": [{k: s.get(k) for k in ("id", "title", "price", "date", "image", "paid", "shipped",
                                                 "txn", "order", "tracking", "buyer", "sku")}
                         for s in sold[:40]],
                "unpublished": self.unpublished(), "offers": self.offers,
                "offers_at": self.offers_at, "offers_err": self.offers_err,
                "ebay": self.ebay_ready(),
                "sold_total": round(sum(float(s.get("price") or 0) for s in sold), 2),
                "to_ship": sum(1 for s in sold if s.get("paid") and not s.get("shipped")),
                "insights": self.insights(), "overview": self._safe_overview()}

    def _safe_overview(self):
        try:
            return self.overview()
        except Exception:  # noqa: BLE001
            return None


SETUP_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Set up CardCrop</title><style>
:root{color-scheme:light dark;--bg:#F4F4F1;--card:#fff;--text:#111;--muted:#666;--ink:#111;--inkt:#fff;--line:#e3e3df}
@media (prefers-color-scheme:dark){:root{--bg:#0E0E10;--card:#18181B;--text:#EDEDEF;--muted:#9D9DA5;--ink:#F2F2EF;--inkt:#111;--line:#26262A}}
body{margin:0;background:var(--bg);color:var(--text);font:19px/1.45 -apple-system,system-ui,sans-serif;
padding:calc(env(safe-area-inset-top) + 24px) 20px calc(env(safe-area-inset-bottom) + 24px)}
h1{font-size:32px;margin:0 0 6px;letter-spacing:-.02em}p{margin:0 0 12px;color:var(--muted)}
ol{list-style:none;padding:0;margin:24px 0;counter-reset:s}
li{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:20px;margin:0 0 14px;counter-increment:s}
li:before{content:counter(s);display:inline-grid;place-items:center;width:34px;height:34px;border-radius:50%;
background:var(--ink);color:var(--inkt);font-weight:700;margin-bottom:10px}
b{color:var(--text)}a.btn{display:block;text-align:center;background:var(--ink);color:var(--inkt);text-decoration:none;
font-weight:650;padding:17px;border-radius:999px;margin-top:12px;font-size:19px}
.lime{background:#D6F24B!important;color:#111!important}</style></head><body>
<h1>CardCrop on your phone</h1><p>Three steps, once. After this the console opens straight from your home screen.</p>
<ol>
<li><b>Get CardCrop's profile.</b><p>Open this page in Safari (not Chrome or another app's browser). Safari asks to
download a configuration profile: tap Allow, then Close.</p>
<a class="btn" href="/cardcrop.mobileconfig">Download the profile</a></li>
<li><b>Install and trust it.</b><p>Open Settings: Profile Downloaded is at the top (or under General &gt; VPN &amp;
Device Management &gt; CardCrop). Tap Install; it says Not Verified because it is your own, which is expected.
Then Settings &gt; General &gt; About &gt; Certificate Trust Settings, and switch CardCrop on.</p></li>
<li><b>Open the console.</b><p>Then Share &gt; Add to Home Screen. The pairing code fills itself in.</p>
<a class="btn lime" href="{{CONSOLE}}">Open CardCrop console</a></li>
</ol><p>This only works on the same Wi-Fi as the Mac ({{HOST}}).</p></body></html>"""


# ------------------------------------------------------------------ Settings > Phone
def qr_pixmap(text, px=260):
    import io
    import segno
    from PySide6.QtGui import QPixmap
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=10, border=2, dark="#111111", light="#FFFFFF")
    pm = QPixmap()
    pm.loadFromData(buf.getvalue(), "PNG")
    return pm.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def phone_pane(main, link):
    from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
    from ui_widgets import Island
    w = Island()
    v = QVBoxLayout(w)
    v.setContentsMargins(28, 24, 28, 24)
    v.setSpacing(12)
    v.addWidget(QLabel("Shoot, review, price and look at cards in 3D from your iPhone, on the same Wi-Fi as this Mac",
                       objectName="small"))
    on = QCheckBox("Let my iPhone connect to CardCrop")
    on.setChecked(link.enabled())
    on.toggled.connect(link.set_enabled)
    v.addWidget(on)
    host_row = QHBoxLayout()
    host_pick = QComboBox()
    host_pick.setToolTip("The address the phone opens. Each one pairs separately, since the phone keeps its pairing "
                         "per address. With Tailscale on the Mac and the phone, its address works away from home too")
    host_pick.activated.connect(lambda _i: link.set_host(host_pick.currentData()))
    host_row.addWidget(QLabel("Phone connects by", objectName="small"))
    host_row.addWidget(host_pick)
    host_row.addStretch(1)
    v.addLayout(host_row)
    body = QWidget()
    g = QGridLayout(body)
    g.setContentsMargins(0, 8, 0, 0)
    g.setHorizontalSpacing(28)
    qr = QLabel()
    qr.setFixedSize(260, 260)
    g.addWidget(qr, 0, 0, 3, 1, Qt.AlignTop)
    steps = QLabel("1. Point the iPhone camera at the code and open the link.\n"
                   "2. Install CardCrop's certificate (once): download it, then Settings > General > "
                   "VPN & Device Management to install, and About > Certificate Trust Settings to switch it on.\n"
                   "3. Open the console, Share > Add to Home Screen, and open it from there.")
    steps.setWordWrap(True)
    g.addWidget(steps, 0, 1)
    code_row = QHBoxLayout()
    code = QLabel("", objectName="dotbig")
    code.setTextInteractionFlags(Qt.TextSelectableByMouse)
    b_new = QPushButton("New code")
    b_new.clicked.connect(link.new_code)
    code_row.addWidget(QLabel("Or type the code", objectName="small"))
    code_row.addWidget(code)
    code_row.addWidget(b_new)
    code_row.addStretch(1)
    g.addLayout(code_row, 1, 1)
    url = QLabel("", objectName="mono")
    url.setTextInteractionFlags(Qt.TextSelectableByMouse)
    url.setWordWrap(True)
    g.addWidget(url, 2, 1, Qt.AlignTop)
    g.setColumnStretch(1, 1)
    v.addWidget(body)
    v.addWidget(QLabel("Paired phones", objectName="small"))
    dev_box = QVBoxLayout()
    dev_box.setSpacing(6)
    v.addLayout(dev_box)
    err = QLabel("", objectName="small")
    err.setWordWrap(True)
    v.addWidget(err)
    v.addStretch(1)

    def redraw():
        running = link.server.running
        body.setVisible(running)
        if link.enabled() and not running:
            err.setText("The phone console could not start: " + (link.server.error or "unknown reason")
                        + ". Another app may be using port 8743 or 8744.")
        else:
            err.setText("")
        host_pick.blockSignals(True)
        host_pick.clear()
        want = str(main.cfg.value("phone_host", "auto"))
        for k, h, what in link.hosts():
            host_pick.addItem(f"{h}   ({what})", k)
        i = host_pick.findData(want)
        host_pick.setCurrentIndex(i if i >= 0 else 0)
        host_pick.blockSignals(False)
        host_pick.setEnabled(running)
        if running:
            qr.setPixmap(qr_pixmap(link.url_setup()))
            code.setText(link.pair_code)
            url.setText(f"Setup  {link.url_setup()}\nConsole  {link.url_console()}")
        while dev_box.count():
            it = dev_box.takeAt(0)
            if it.layout():
                while it.layout().count():
                    x = it.layout().takeAt(0).widget()
                    if x:
                        x.deleteLater()
            elif it.widget():
                it.widget().deleteLater()
        devs = link.devices()
        live = {_hash(c.token) for c in link.server.clients()}
        if not devs:
            dev_box.addWidget(QLabel("None yet", objectName="muted"))
        for h, d in sorted(devs.items(), key=lambda kv: -kv[1].get("seen", 0)):
            r = QHBoxLayout()
            seen = time.strftime("%d %b %H:%M", time.localtime(d.get("seen", 0)))
            r.addWidget(QLabel(d.get("name", "Phone")))
            pushes = sum(1 for x in link.push_subs().values() if x.get("device") == h)
            r.addWidget(QLabel(("connected now" if h in live else f"last seen {seen}")
                               + ("  ·  notifications on" if pushes else ""), objectName="small"))
            r.addStretch(1)
            b = QPushButton("Forget")
            b.clicked.connect(lambda _=False, h=h: link.forget(h))
            r.addWidget(b)
            dev_box.addLayout(r)

    link.changed.connect(redraw)
    redraw()
    return w
