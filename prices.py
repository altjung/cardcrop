"""Price sources beyond eBay's live listings.

PriceCharting (optional, needs your own API token from a paid PriceCharting subscription) gives
an ungraded card value worked out from completed sales. Its answers are cached for a day, which
is how often PriceCharting updates them, and its rule of one call a second is kept."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

import identify

_LOCK = threading.Lock()
_LAST = [0.0]
DAY = 86400


def _cache_path() -> str:
    return os.path.join(identify._cache_dir(), "pricecharting.json")


def _cache() -> dict:
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(c: dict) -> None:
    try:
        with open(_cache_path() + ".tmp", "w", encoding="utf-8") as f:
            json.dump(c, f)
        os.replace(_cache_path() + ".tmp", _cache_path())
    except OSError:
        pass


def _get(url: str) -> dict:
    with _LOCK:                                      # PriceCharting asks for one call a second
        wait = 1.05 - (time.time() - _LAST[0])
        if wait > 0:
            time.sleep(wait)
        _LAST[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "CardCrop"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _num(s) -> str:
    return re.sub(r"^0+(?=\d)", "", str(s or "").split("/")[0].strip()).lower()


def pricecharting(token: str, info: dict) -> dict | None:
    """{'loose': dollars, 'name': product, 'set': console} for this card, or None."""
    token = (token or "").strip()
    if not token or not info:
        return None
    name = info.get("name_en") or info.get("name", "")
    number = _num(info.get("number", ""))
    set_ = info.get("set_name_en") or info.get("set_name", "")
    key = f"{info.get('id', '')}|{info.get('language', 'en')}"
    c = _cache()
    hit = c.get(key)
    if hit and time.time() - hit.get("t", 0) < DAY:
        return hit.get("v")
    q = " ".join(x for x in (name, number, set_) if x)
    if info.get("language") == "ja":
        q += " japanese"
    d = _get("https://www.pricecharting.com/api/products?" + urllib.parse.urlencode({"t": token, "q": q}))
    if d.get("status") == "error":
        raise RuntimeError(d.get("error-message") or "PriceCharting refused the request")
    best = None
    for p in d.get("products") or []:
        pname = str(p.get("product-name", ""))
        console = str(p.get("console-name", ""))
        if "pokemon" not in console.lower() and info.get("game", "pokemon") == "pokemon":
            continue
        if number and not re.search(rf"#\s*0*{re.escape(number)}\b", pname.lower()):
            continue                                  # PriceCharting writes "Charizard ex #6"
        if (info.get("language") == "ja") != ("japanese" in console.lower()):
            continue
        if set_ and set_.lower().split()[0] not in console.lower():
            if best is not None:
                continue
        loose = p.get("loose-price")
        if loose:
            best = {"loose": round(int(loose) / 100, 2), "name": pname, "set": console}
            if set_ and set_.lower().split()[0] in console.lower():
                break
    c[key] = {"t": time.time(), "v": best}
    _save(c)
    return best
