"""Shipments: tracking numbers from your eBay sales and ones you add by hand, each with a nickname you can
change, the carrier's scan history read from USPS's tracking API, and a link to the carrier's own page.

Kept in tracking.json in CardCrop's data folder. Every package has a timeline that merges the carrier's
scans with what happened on this Mac (added, imported from a sale, renamed, number corrected), newest
first. USPS scans need a free USPS developer app (developers.usps.com: its Consumer Key and Secret go in
the Shipments page's USPS API settings); without one, everything else works and the link opens USPS's page.

No Qt here: the page (ui_ship.py) calls these, and the network calls run off the UI thread."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

USPS_TOKEN = "https://apis.usps.com/oauth2/v3/token"
USPS_TRACK = "https://apis.usps.com/tracking/v3/tracking/{}?expand=DETAIL"
LINKS = {
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels={}",
    "UPS": "https://www.ups.com/track?tracknum={}",
    "FedEx": "https://www.fedex.com/fedextrack/?trknbr={}",
    "DHL": "https://www.dhl.com/us-en/home/tracking/tracking-express.html?tracking-id={}",
}
STALE = 30 * 60              # seconds before a package still moving is asked about again
STAGES = ("Label created", "Shipped", "In transit", "Out for delivery", "Delivered")
PICKUP_STAGES = ("Awaiting pickup", "Picked up")
NOT_YET = "Not in USPS's system yet"


def stages_of(it: dict) -> tuple:
    return PICKUP_STAGES if it.get("pickup") else STAGES


_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")


def nice_date(text) -> str:
    """USPS's expected delivery, however it was worded ("Expected Delivery on: Saturday 24 October 2026 ...",
    "2026-10-24", "October 24, 2026"), as "Sat, Oct 24"; the text tidied when no date can be found in it."""
    import datetime as dt
    t = str(text or "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    d = None
    if m:
        d = dt.date(int(m[1]), int(m[2]), int(m[3]))
    else:
        mm = re.search(r"(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})", t, re.I) or \
            re.search(r"(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})", t, re.I)
        if mm:
            a, b, y = mm.groups()
            day, mon = (a, b) if a.isdigit() else (b, a)
            try:
                d = dt.date(int(y), _MONTHS.index(mon.lower()) + 1, int(day))
            except ValueError:
                d = None
    return f"{d:%a, %b} {d.day}" if d else tidy(t, 40)


def direction_of(it: dict) -> str:
    """"out" for what you send (your eBay sales), "in" for what comes to you; numbers added by hand are
    taken as coming to you unless you say otherwise."""
    return it.get("direction") or ("out" if it.get("source") == "ebay" else "in")


def tidy(text, limit: int = 160) -> str:
    """One line, single spaces, cut at a word near the limit: errors read off web pages come ragged."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"
_LOCK = threading.Lock()


# ------------------------------------------------------------------ numbers and carriers
def clean(number: str) -> str:
    """A tracking number as carriers want it: letters and digits only, upper case."""
    return re.sub(r"[^0-9A-Za-z]", "", str(number or "")).upper()


def carrier_of(number: str) -> str:
    try:
        import ebay
        return ebay.guess_carrier(number)
    except Exception:  # noqa: BLE001
        return "USPS"


def carrier_name(given: str, number: str) -> str:
    """eBay's ShippingCarrierUsed (USPS, UPS, FedEx, DHL, sometimes with a service tacked on) or the number's shape."""
    g = str(given or "").upper()
    for name in ("USPS", "UPS", "FEDEX", "DHL"):
        if name in g:
            return {"FEDEX": "FedEx"}.get(name, name)
    return carrier_of(number)


def link(number: str, carrier: str = "") -> str:
    n = clean(number)
    return LINKS.get(carrier or carrier_of(n), LINKS["USPS"]).format(urllib.parse.quote(n))


# ------------------------------------------------------------------ the store
def _path() -> str:
    import identify
    return os.path.join(identify._cache_dir(), "tracking.json")


def load() -> list[dict]:
    try:
        with open(_path(), encoding="utf-8") as f:
            return list(json.load(f).get("items", []))
    except (OSError, ValueError):
        return []


def save(items: list[dict]):
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "items": items}, f, indent=1)
    os.replace(tmp, _path())                 # never a half-written file if the app quits mid-save


def _log(it: dict, text: str, when: float | None = None):
    it.setdefault("log", []).append({"t": when or time.time(), "text": text})


def find(items, pid: str) -> dict | None:
    return next((x for x in items if x["id"] == pid), None)


def by_number(items, number: str) -> dict | None:
    n = clean(number)
    return next((x for x in items if x["number"] == n), None)


def add_manual(number: str, nickname: str = "", direction: str = "in") -> tuple[dict | None, str]:
    """A tracking number typed in. Returns (package, error)."""
    n = clean(number)
    if len(n) < 8:
        return None, "That does not look like a tracking number"
    with _LOCK:
        items = load()
        old = by_number(items, n)
        if old:
            return old, f"Already tracking it as “{old['nickname']}”"
        it = {"id": uuid.uuid4().hex[:12], "number": n, "carrier": carrier_of(n), "nickname": nickname.strip() or n,
              "source": "manual", "direction": "out" if direction == "out" else "in",
              "added": time.time(), "archived": False, "status": "", "delivered": False,
              "expected": "", "events": [], "log": [], "checked": 0, "error": ""}
        _log(it, "Added by hand")
        items.insert(0, it)
        save(items)
    return it, ""


def import_ebay(sold: list[dict]) -> int:
    """Every eBay sale with a tracking number becomes a package once; later imports only refresh the sale's
    details, so a nickname you gave it stays. Returns how many were new."""
    new = 0
    with _LOCK:
        items = load()
        for s in sold or []:
            n = clean(s.get("tracking", ""))
            if len(n) < 8 and s.get("pickup") and s.get("order"):
                n = "PICKUP" + clean(s["order"])            # a local pickup has no tracking: its order stands in
            if len(n) < 8:
                continue
            sale = {k: s.get(k, "") for k in ("id", "title", "buyer", "date", "order", "url", "price")}
            it = by_number(items, n)
            if it is None:
                title = (s.get("title") or "eBay sale").strip()
                nick = f"{title[:30].rstrip()}{'…' if len(title) > 30 else ''}" + (f" · {s['buyer']}" if s.get("buyer") else "")
                it = {"id": uuid.uuid4().hex[:12], "number": n, "carrier": carrier_name(s.get("carrier"), n), "nickname": nick,
                      "source": "ebay", "added": time.time(), "archived": False, "status": "", "delivered": False,
                      "expected": "", "events": [], "log": [], "checked": 0, "error": "", "ebay": sale,
                      "pickup": bool(s.get("pickup"))}
                if it["pickup"]:
                    it["carrier"] = "Pickup"
                _log(it, "Imported from your eBay sales" + (" (local pickup)" if it["pickup"] else ""))
                if s.get("date"):
                    _log(it, f"Sold to {s.get('buyer') or 'a buyer'} on eBay", _iso(s["date"]))
                items.insert(0, it)
                new += 1
            else:
                it["ebay"] = {**it.get("ebay", {}), **sale}
                if s.get("carrier") and not it.get("carrier_manual") and not it.get("pickup"):
                    it["carrier"] = carrier_name(s["carrier"], n)          # eBay's word over the number's shape
                if s.get("pickup") and not it.get("pickup"):
                    it.update(pickup=True, carrier="Pickup", error="")
            if it.get("pickup") and s.get("picked_up") and it.get("stage_manual") is None and not it.get("delivered"):
                it["delivered"] = True
                _log(it, "Picked up (eBay)")
        save(items)
    return new


def stage_of(it: dict) -> int:
    """Where a package is, 0 to 4 along STAGES: the one you set by hand, else read from its latest scan."""
    last = len(stages_of(it)) - 1
    if it.get("stage_manual") is not None:
        return min(last, int(it["stage_manual"]))
    if it.get("delivered"):
        return last
    if it.get("pickup"):
        return 0
    ev = it.get("events") or []
    top = (ev[0]["text"] if ev else it.get("status", "")).lower()
    if "out for delivery" in top:
        return 3
    if any(w in top for w in ("transit", "arrived", "departed", "processed", "facility", "on its way", "moving",
                              "available for pickup", "notice left")):
        return 2
    if any(w in top for w in ("accepted", "picked up", "origin", "shipping partner", "dropped off", "in possession")):
        return 1
    if ev and "label" not in top and "pre-shipment" not in top:
        return 2
    return 1 if (it.get("ebay") or {}).get("shipped") else 0


def parse_delivered(it: dict) -> bool:
    top = ((it.get("events") or [{}])[0].get("text") or "").lower()
    return "delivered" in top and "out for" not in top and "expected" not in top


def update(pid: str, **fields) -> tuple[dict | None, str]:
    """Rename (nickname), correct the number (manual packages; their scans start over), archive or restore."""
    with _LOCK:
        items = load()
        it = find(items, pid)
        if it is None:
            return None, "That package is gone"
        if "nickname" in fields:
            nick = str(fields["nickname"]).strip() or it["number"]
            if nick != it["nickname"]:
                _log(it, f"Renamed from “{it['nickname']}” to “{nick}”")
                it["nickname"] = nick
        if "number" in fields:
            n = clean(fields["number"])
            if len(n) < 8:
                return None, "That does not look like a tracking number"
            if n != it["number"]:
                other = by_number(items, n)
                if other is not None and other is not it:
                    return None, f"Already tracking that number as “{other['nickname']}”"
                _log(it, f"Number corrected from {it['number']} to {n}")
                it.update(number=n, carrier=carrier_of(n), events=[], status="", delivered=False, expected="",
                          checked=0, error="")
        if "carrier" in fields and fields["carrier"] in LINKS and fields["carrier"] != it.get("carrier"):
            _log(it, f"Carrier changed from {it.get('carrier')} to {fields['carrier']}")
            it.update(carrier=fields["carrier"], carrier_manual=True, error="", checked=0)
        if "direction" in fields and fields["direction"] in ("in", "out") and fields["direction"] != direction_of(it):
            it["direction"] = fields["direction"]
            _log(it, "Marked inbound, coming to you" if it["direction"] == "in" else "Marked outbound, going out")
        if "pickup" in fields and bool(fields["pickup"]) != bool(it.get("pickup")):
            it["pickup"] = bool(fields["pickup"])
            it.update(stage_manual=None, delivered=False, error="",
                      carrier="Pickup" if it["pickup"] else carrier_of(it["number"]))
            _log(it, "Marked as a local pickup" if it["pickup"] else "Marked as shipped, not a pickup")
        if "stage" in fields and fields["stage"] is None:          # back to what the scans say
            if it.get("stage_manual") is not None:
                _log(it, "Status set back to the carrier's scans")
            it.update(stage_manual=None, delivered=bool(it.get("events")) and parse_delivered(it))
            fields = {k: v for k, v in fields.items() if k != "stage"}
        if "stage" in fields:
            names = stages_of(it)
            k = max(0, min(len(names) - 1, int(fields["stage"])))
            if k != stage_of(it) or it.get("stage_manual") is None:
                _log(it, f"Marked {names[k].lower()} by hand")
            it.update(stage_manual=k, stage_t=time.time(), delivered=k == len(names) - 1)
        if "archived" in fields and bool(fields["archived"]) != it.get("archived", False):
            it["archived"] = bool(fields["archived"])
            _log(it, "Archived" if it["archived"] else "Back in the active list")
        save(items)
        return it, ""


def remove(pid: str):
    with _LOCK:
        save([x for x in load() if x["id"] != pid])


# ------------------------------------------------------------------ USPS
class UspsError(Exception):
    pass


_TOKEN = {"key": None, "token": "", "until": 0.0}


def _json(req, timeout=25) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        try:
            j = json.loads(body)
            msg = (j.get("error", {}) or {}).get("message") if isinstance(j.get("error"), dict) else \
                j.get("error_description") or j.get("error") or j.get("message")
        except ValueError:
            msg = body.strip()
        raise UspsError(f"USPS {e.code}: {msg or e.reason}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UspsError(f"Could not reach USPS: {getattr(e, 'reason', e)}") from None


def usps_token(key: str, secret: str) -> str:
    if not (key and secret):
        raise UspsError("Add your USPS API Consumer Key and Secret (USPS API… on this page)")
    if _TOKEN["key"] == key and _TOKEN["token"] and time.time() < _TOKEN["until"] - 60:
        return _TOKEN["token"]
    body = json.dumps({"client_id": key, "client_secret": secret, "grant_type": "client_credentials"}).encode()
    j = _json(urllib.request.Request(USPS_TOKEN, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"}))
    if not j.get("access_token"):
        raise UspsError("USPS did not hand back a token: check the Consumer Key and Secret")
    _TOKEN.update(key=key, token=j["access_token"], until=time.time() + float(j.get("expires_in") or 3600))
    return _TOKEN["token"]


def _get(d: dict, *names, default=""):
    """The first of several field names present, ignoring case (USPS has spelled them more than one way)."""
    low = {str(k).lower(): v for k, v in (d or {}).items()}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, ""):
            return v
    return default


def _iso(s) -> float:
    """Seconds since the epoch from an ISO timestamp, or from USPS's separate date and time; 0 when unreadable."""
    import datetime as dt
    s = str(s or "").strip()
    if not s:
        return 0.0
    for f in (lambda x: dt.datetime.fromisoformat(x.replace("Z", "+00:00")),
              lambda x: dt.datetime.strptime(x, "%B %d, %Y %I:%M %p"),
              lambda x: dt.datetime.strptime(x, "%B %d, %Y")):
        try:
            d = f(s)
            return d.timestamp()
        except ValueError:
            continue
    return 0.0


def parse_usps(j: dict) -> dict:
    """USPS's answer as {status, delivered, expected, events: [{t, text, place}]}, newest first. Reads the
    current JSON (trackingEvents with eventType and eventTimestamp) and the older TrackSummary/TrackDetail."""
    if isinstance(j.get("trackingResults"), list) and j["trackingResults"]:
        j = j["trackingResults"][0]
    raw = list(_get(j, "trackingEvents", "TrackDetail", "events", default=[]) or [])
    summ = _get(j, "TrackSummary", default=None)
    if isinstance(summ, dict):
        raw.insert(0, summ)
    events = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        text = str(_get(e, "eventType", "Event", "event", "description")).strip()
        ts = _get(e, "eventTimestamp", "GMTTimestamp", "eventDateTime")
        t = _iso(ts) if ts else _iso(f"{_get(e, 'EventDate', 'eventDate')} {_get(e, 'EventTime', 'eventTime')}".strip())
        place = ", ".join(str(x) for x in (_get(e, "eventCity", "EventCity"), _get(e, "eventState", "EventState")) if x)
        z = _get(e, "eventZIP", "eventZIPCode", "EventZIPCode")
        if z:
            place = f"{place} {z}".strip()
        if text:
            events.append({"t": t, "text": text.capitalize() if text.isupper() else text, "place": place})
    events.sort(key=lambda e: e["t"], reverse=True)
    status = str(_get(j, "statusCategory", "status", "statusSummary") or (events[0]["text"] if events else ""))
    top = (events[0]["text"] if events else status).lower()
    delivered = ("delivered" in top and "out for" not in top and "expected" not in top) or \
        str(_get(j, "statusCategory")).lower() == "delivered"
    return {"status": status, "delivered": delivered, "events": events,
            "expected": str(_get(j, "expectedDeliveryDate", "expectedDeliveryTimeStamp", "ExpectedDeliveryDate",
                                 "predictedDeliveryDate"))}


def fetch_usps(number: str, key: str, secret: str) -> dict:
    tok = usps_token(key, secret)
    req = urllib.request.Request(USPS_TRACK.format(urllib.parse.quote(clean(number))),
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
    return parse_usps(_json(req))


def due(ids=None, force: bool = False) -> list[tuple[str, str]]:
    """(id, number) of the USPS packages to ask about: the ones given, or every one still moving and not
    asked about for STALE seconds (all of them still moving when forced)."""
    with _LOCK:
        return [(x["id"], x["number"]) for x in load()
                if x.get("carrier") == "USPS" and not x.get("pickup") and (ids is not None and x["id"] in ids or ids is None
                and not x.get("archived") and not x.get("delivered")
                and (force or time.time() - x.get("checked", 0) > STALE))]


def apply(results: dict):
    """Writes {id: parsed answer or {"error": text}} into the packages."""
    with _LOCK:
        items = load()
        for pid, r in results.items():
            it = find(items, pid)
            if it is None:
                continue
            it["checked"] = time.time()
            if "error" in r:
                it["error"] = tidy(r["error"])
                continue
            it.update(status=r["status"], expected=r["expected"], events=r["events"] or it.get("events", []),
                      delivered=r["delivered"], error="")
            if r["events"] and r["events"][0]["t"] > it.get("stage_t", 0):
                it["stage_manual"] = None            # a newer scan than your mark takes over
        save(items)


def refresh(key: str, secret: str, ids=None, force: bool = False) -> dict:
    """Through USPS's API, off the UI thread. Returns {"checked": n, "errors": [..]}."""
    out, errors = {}, []
    for pid, number in due(ids, force):
        try:
            out[pid] = fetch_usps(number, key, secret)
        except UspsError as e:
            out[pid] = {"error": str(e)}
            errors.append(str(e))
            if "token" in str(e).lower() or "key" in str(e).lower() or " 401" in str(e):
                break                                  # bad credentials: no point asking about the rest
    apply(out)
    return {"checked": len(out), "errors": errors}


# ------------------------------------------------------------------ USPS's own page, read in a browser
def _page_time(s: str) -> float:
    import datetime as dt
    s = re.sub(r"\s+", " ", str(s or "")).strip().replace(" at ", ", ")
    for f in ("%B %d, %Y, %I:%M %p", "%B %d, %Y %I:%M %p", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(s, f).timestamp()
        except ValueError:
            continue
    return 0.0


_DATE = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December) "
                   r"\d{1,2}, \d{4}(,? (at )?\d{1,2}:\d{2} ?[ap]m)?$", re.I)


def parse_usps_page(d: dict) -> dict:
    """What the browser read off tools.usps.com: the history steps when the page's own markup was found,
    else its visible text, where each scan is a status line, a date line and a place line."""
    steps = [x for x in (d.get("steps") or []) if (x.get("status") or "").strip()]
    events = []
    for x in steps:
        st_ = re.sub(r"\s+", " ", x["status"]).strip()
        events.append({"t": _page_time(x.get("date", "")), "text": st_,
                       "place": re.sub(r"\s+", " ", x.get("loc") or "").strip()})
    if not events and d.get("text"):
        lines = [ln.strip() for ln in str(d["text"]).splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            if _DATE.match(ln) and i > 0:
                place = lines[i + 1] if i + 1 < len(lines) and re.search(r", [A-Z]{2}\b|\b\d{5}\b", lines[i + 1]) else ""
                events.append({"t": _page_time(ln), "text": lines[i - 1], "place": place})
    if not events:
        msg = tidy(d.get("error") or d.get("banner") or "")
        said = (msg + " " + str(d.get("text") or "")).lower()
        if any(w in said for w in ("tracking not available", "not yet in system", "label created, not yet",
                                   "not yet received the item", "status not available")):
            return {"status": NOT_YET, "events": [], "delivered": False, "expected": ""}   # waiting, not wrong
        return {"error": msg or "USPS's page showed no tracking history for this number yet"}
    events.sort(key=lambda e: e["t"], reverse=True)
    top = events[0]["text"].lower()
    return {"status": events[0]["text"], "events": events,
            "delivered": "delivered" in top and "out for" not in top and "expected" not in top,
            "expected": re.sub(r"\s+", " ", str(d.get("eta") or "")).strip()}


def timeline(it: dict) -> list[dict]:
    """Carrier scans and this Mac's own entries together, newest first: {t, text, place, kind}."""
    rows = [{**e, "kind": "scan"} for e in it.get("events", [])]
    rows += [{"t": e["t"], "text": e["text"], "place": "", "kind": "note"} for e in it.get("log", [])]
    return sorted(rows, key=lambda r: r["t"], reverse=True)
