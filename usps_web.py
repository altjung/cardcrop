"""USPS scans without an API key: tools.usps.com read in a hidden built-in browser (Qt WebEngine, Chromium).

USPS turns away plain requests from programs (HTTP 403, "Access Denied") and only lets a real browser
through, so the tracking page is loaded the way Safari would load it, its own scripts are let run, and the
history is read off the finished page, one package at a time. Its cookies are kept in CardCrop's data
folder, as a browser keeps them. When USPS changes its page or turns this away too, the package shows the
reason and Open on USPS and the status you set by hand still work.

Qt WebEngine has to be loaded before the app starts (app.main does that); available() says whether it was."""
from __future__ import annotations

import json
import os
import re

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

import shiptrack as st

try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    _OK = True
except Exception:  # noqa: BLE001
    _OK = False

# the history's own markup where USPS uses it, the page's visible text as the fallback
JS = r"""(function(){
  function q(el, s){ var e = el.querySelector(s); return e ? (e.textContent || "") : ""; }
  var steps = [].slice.call(document.querySelectorAll('.tb-step')).map(function(el){
    return {status: q(el, '.tb-status-detail') || q(el, '.tb-status'), date: q(el, '.tb-date'), loc: q(el, '.tb-location')};
  });
  var eta = q(document, '.expected_delivery') || q(document, '.eta_snip') || q(document, '.day');
  var banner = q(document, '.red-banner') || q(document, '.tracking-notification') || q(document, '.banner-content');
  var text = document.body ? document.body.innerText : "";
  return JSON.stringify({steps: steps, eta: eta, banner: banner, text: text.slice(0, 30000),
                         title: document.title, ready: document.readyState});
})()"""
POLLS = 14            # seconds to wait for the history to appear after the page loads
TIMEOUT = 45000       # milliseconds for one package, start to finish


def available() -> bool:
    return _OK


class UspsWeb(QObject):
    """Reads packages one after another; finished carries {package id: parsed answer or {"error": ...}}."""
    finished = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        import identify
        self.profile = QWebEngineProfile("cardcrop-usps", self)            # named: cookies persist
        base = os.path.join(identify._cache_dir(), "usps-web")
        self.profile.setPersistentStoragePath(os.path.join(base, "storage"))
        self.profile.setCachePath(os.path.join(base, "cache"))
        ua = re.sub(r"\s*QtWebEngine/\S+", "", self.profile.httpUserAgent())   # look like plain Chrome
        self.profile.setHttpUserAgent(ua)
        self.page = QWebEnginePage(self.profile, self)
        self.page.loadFinished.connect(self._loaded)
        self.queue, self.results, self.cur, self.tries = [], {}, None, 0
        self.poll = QTimer(self, interval=1000)
        self.poll.timeout.connect(self._ask)
        self.watchdog = QTimer(self, singleShot=True, interval=TIMEOUT)
        self.watchdog.timeout.connect(lambda: self._done({"error": "USPS's page did not finish loading"}))

    def busy(self) -> bool:
        return self.cur is not None or bool(self.queue)

    def start(self, todo):
        """todo: [(package id, number)]."""
        have = {p for p, _ in self.queue} | ({self.cur[0]} if self.cur else set())
        self.queue += [x for x in todo if x[0] not in have]
        if self.cur is None:
            self._next()

    def _next(self):
        if not self.queue:
            res, self.results = self.results, {}
            self.page.setUrl(QUrl("about:blank"))
            self.finished.emit(res)
            return
        self.cur = self.queue.pop(0)
        self.tries = 0
        self.watchdog.start()
        self.page.load(QUrl(st.link(self.cur[1], "USPS")))

    def _loaded(self, ok):
        if self.cur is None:
            return
        if not ok:
            return self._done({"error": "USPS's page did not load (offline, or USPS turned the browser away)"})
        if not self.poll.isActive():
            self.poll.start()

    def _ask(self):
        if self.cur is None:
            return self.poll.stop()
        self.tries += 1
        self.page.runJavaScript(JS, 0, self._got)

    def _got(self, raw):
        if self.cur is None:
            return
        try:
            d = json.loads(raw) if isinstance(raw, str) else {}
        except ValueError:
            d = {}
        text = (d.get("text") or "") + " " + (d.get("title") or "")
        if "Access Denied" in text:
            return self._done({"error": "USPS turned the built-in browser away (Access Denied). "
                                        "Open on USPS still works, and you can set the status by hand"})
        r = st.parse_usps_page(d)
        if "error" not in r or self.tries >= POLLS:
            self._done(r)

    def _done(self, r):
        self.poll.stop()
        self.watchdog.stop()
        if self.cur is not None:
            self.results[self.cur[0]] = r
        self.cur = None
        QTimer.singleShot(1500, self._next)          # a pause between packages, as a person would leave
