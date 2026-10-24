"""Listing straight to eBay through its Sell APIs: sign in once, upload a card's
photos, and create the listing as an UNPUBLISHED offer that only goes live when
you press Publish.

Flow (eBay Inventory API):
  photos  -> Media API createImageFromFile -> eBay-hosted image URLs
  card    -> PUT inventory_item/{sku}   (title, aspects, condition, photos, quantity)
  listing -> POST offer                 (price, category, policies, description) = unpublished
  publish -> POST offer/{id}/publish    -> a live listing ID

Secrets (Cert ID, refresh token) live in the macOS Keychain, never in a file.
Nothing here imports Qt, so it can be tested without the app.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = os.environ.get("CARDCROP_EBAY_API", "https://api.ebay.com")
MEDIA = os.environ.get("CARDCROP_EBAY_MEDIA", "https://apim.ebay.com")
AUTH = os.environ.get("CARDCROP_EBAY_AUTH", "https://auth.ebay.com")
MARKETPLACE = "EBAY_US"
CATEGORY_ID = "183454"            # CCG Individual Cards (Pokémon)
BASE_SCOPES = ["https://api.ebay.com/oauth/api_scope",
               "https://api.ebay.com/oauth/api_scope/sell.inventory",
               "https://api.ebay.com/oauth/api_scope/sell.account"]
ANALYTICS_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly"
SCOPES = BASE_SCOPES + [ANALYTICS_SCOPE]
LOCATION_KEY = "cardcrop-home"
KEYCHAIN_SERVICE = "CardCrop eBay"
MAX_PHOTOS = 24
UPLOAD_LONG_EDGE = 4000            # eBay caps file size and width + height; 4000 px stays clear of both

# eBay ungraded trading card condition: the item condition plus a "Card Condition" descriptor
CONDITION_ENUM = "USED_VERY_GOOD"      # = condition ID 4000, ungraded, for trading cards
CARD_CONDITION_DESCRIPTOR = "40001"


def log_path() -> str:
    d = os.path.expanduser("~/Library/Logs/CardCrop") if sys.platform == "darwin" else _fallback_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "ebay.log")


def _log(lines):
    """A record of every eBay error, request included (tokens and secrets never are)."""
    try:
        p = log_path()
        if os.path.exists(p) and os.path.getsize(p) > 2_000_000:
            os.replace(p, p + ".old")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n".join([time.strftime("--- %Y-%m-%d %H:%M:%S")] + lines) + "\n")
    except OSError:
        pass


def _safe(t) -> str:
    """Only characters eBay takes in titles and item specifics (see listing.ebay_safe)."""
    import listing as _listing
    return _listing.ebay_safe(str(t))


def _is_pickup(code) -> bool:
    return (code or "").replace("_", "").lower() in ("pickup", "localpickup", "pickupinstore")


def policy_has_pickup(pol: dict) -> bool:
    """A shipping (fulfillment) policy offers local pickup: its switch, or a Pickup service in it."""
    return bool(pol.get("localPickup")) or any(
        _is_pickup(sv.get("shippingServiceCode")) for o in pol.get("shippingOptions") or []
        for sv in o.get("shippingServices") or [])


def policy_summary(pol: dict) -> str:
    """One line for a shipping policy: each service with its cost, local pickup, handling time."""
    names = {"USPSParcel": "USPS Ground Advantage", "USPSFirstClass": "USPS First Class",
             "USPSPriority": "USPS Priority", "FedExSmartPost": "FedEx Ground Economy",
             "USPSGroundAdvantage": "USPS Ground Advantage", "eBayStandardEnvelope": "eBay Standard Envelope"}
    bits = []
    for o in pol.get("shippingOptions") or []:
        for sv in sorted(o.get("shippingServices") or [], key=lambda x: x.get("sortOrder", 0)):
            code = sv.get("shippingServiceCode") or ""
            if _is_pickup(code):
                continue
            cost = "free" if sv.get("freeShipping") else (
                f"${float((sv.get('shippingCost') or {}).get('value', 0)):.2f}" if o.get("costType") == "FLAT_RATE"
                else "calculated")
            bits.append(f"{names.get(code, code)} {cost}")
    if policy_has_pickup(pol):
        bits.append("local pickup")
    ht = (pol.get("handlingTime") or {}).get("value")
    if ht is not None:
        bits.append(f"ships in {ht} day{'s' if ht != 1 else ''}" if ht else "ships same day")
    return " · ".join(bits)


class EbayError(Exception):
    def __init__(self, msg, status=0, errors=None):
        super().__init__(msg)
        self.status, self.errors = status, errors or []

    def ids(self):
        return {e.get("errorId") for e in self.errors}


# ------------------------------------------------------------------ secret storage
def _fallback_dir():
    d = os.path.expanduser("~/.cardcrop")
    os.makedirs(d, exist_ok=True)
    return d


def xml_escape(t: str) -> str:
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _report_day(v: str):
    """A day from the traffic report, whichever way eBay writes it."""
    import datetime as dt
    m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})", v)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^\w{3} (\w{3}) (\d{1,2}) .* (\d{4})$", v)
    if m:
        try:
            return dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
        except ValueError:
            return None
    return None


def secret_set(account: str, value: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
                        "-a", account, "-w", value], check=True, capture_output=True)
        return
    p = os.path.join(_fallback_dir(), f"secret_{account}")
    with open(p, "w") as f:
        f.write(value)
    os.chmod(p, 0o600)


def secret_get(account: str) -> str:
    if sys.platform == "darwin":
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
                            "-a", account, "-w"], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    p = os.path.join(_fallback_dir(), f"secret_{account}")
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return ""


def secret_delete(account: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account],
                       capture_output=True)
        return
    try:
        os.remove(os.path.join(_fallback_dir(), f"secret_{account}"))
    except OSError:
        pass


# ------------------------------------------------------------------ client
def sku_for(name: str) -> str:
    """Inventory SKUs: letters, digits, hyphen and underscore, 50 characters at most."""
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")
    return (s or "card")[:50]


def live_sku(out_dir: str, name_slug: str) -> str:
    """The SKU a card's current copy is listed under on eBay: its own when a copy of the same card was
    already live (pikachu-1-2), else the card's plain SKU. CardCrop's records stay keyed by the plain one."""
    base = sku_for(name_slug)
    return (load_records(out_dir).get(base) or {}).get("sku") or base


def copy_sku(base: str, n: int) -> str:
    """The SKU for another copy of the same card: the plain SKU with -2, -3 and so on, within 50 characters."""
    tail = f"-{n}"
    return base[:50 - len(tail)] + tail



def _put_body(item: dict) -> dict:
    """An inventory record as eBay accepts it back: only the fields a PUT takes, and the
    availability without the read-only allocation eBay adds when it returns one (sending that
    back makes publishing fail with 'Availability not found', error 25604)."""
    body = {k: v for k, v in item.items() if k in ("availability", "condition", "conditionDescription",
                                                   "packageWeightAndSize", "product", "conditionDescriptors")}
    av = (body.get("availability") or {}).get("shipToLocationAvailability") or {}
    q = av.get("quantity")
    if q is None:
        q = (av.get("allocationByFormat") or {}).get("fixedPrice", 1)
    body["availability"] = {"shipToLocationAvailability": {"quantity": int(q or 0)}}
    return body

class Client:
    def __init__(self, app_id: str, runame: str, cert_id: str | None = None):
        self.app_id = app_id.strip()
        self.runame = runame.strip()
        self._cert = cert_id
        self._access = ""
        self._access_until = 0.0

    # ---------------------------------------------------------- credentials
    @property
    def cert_id(self) -> str:
        if self._cert is None:
            self._cert = secret_get(f"cert:{self.app_id}")
        return self._cert or ""

    def save_cert(self, cert: str):
        self._cert = cert.strip()
        secret_set(f"cert:{self.app_id}", self._cert)

    @property
    def refresh_token(self) -> str:
        return secret_get(f"refresh:{self.app_id}")

    def signed_in(self) -> bool:
        return bool(self.app_id and self.cert_id and self.refresh_token)

    def granted(self) -> list:
        """The permissions the current sign-in was given. Sign-ins from before traffic
        reports existed have the first three only, and a refresh may not ask for more."""
        g = secret_get(f"scopes:{self.app_id}")
        return g.split() if g else list(BASE_SCOPES)

    def has_analytics(self) -> bool:
        return ANALYTICS_SCOPE in self.granted()

    def sign_out(self):
        secret_delete(f"refresh:{self.app_id}")
        secret_delete(f"scopes:{self.app_id}")
        self._access, self._access_until = "", 0.0

    def _basic(self):
        return "Basic " + base64.b64encode(f"{self.app_id}:{self.cert_id}".encode()).decode()

    # ---------------------------------------------------------- OAuth
    def auth_url(self) -> str:
        q = urllib.parse.urlencode({"client_id": self.app_id, "response_type": "code",
                                    "redirect_uri": self.runame, "scope": " ".join(SCOPES),
                                    "prompt": "login"}, quote_via=urllib.parse.quote)
        return f"{AUTH}/oauth2/authorize?{q}"

    @staticmethod
    def code_from(pasted: str) -> str:
        """The authorization code from whatever was pasted: the whole address-bar
        link from eBay's 'Authorization successfully completed' page, or the code."""
        pasted = pasted.strip()
        if "code=" in pasted:
            parsed = urllib.parse.urlparse(pasted)
            for part in (parsed.query, parsed.fragment, pasted.split("?", 1)[-1]):
                qs = urllib.parse.parse_qs(part)
                if qs.get("code"):
                    return qs["code"][0]
        return urllib.parse.unquote(pasted) if pasted.startswith("v%5E") else pasted

    def _token_request(self, form: dict) -> dict:
        body = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(f"{API}/identity/v1/oauth2/token", data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "Authorization": self._basic()})
        return self._send(req)

    def exchange(self, pasted: str) -> None:
        code = self.code_from(pasted)
        if not code:
            raise EbayError("No sign-in code found in what was pasted")
        d = self._token_request({"grant_type": "authorization_code", "code": code,
                                 "redirect_uri": self.runame})
        if not d.get("refresh_token"):
            raise EbayError("eBay did not return a sign-in token")
        secret_set(f"refresh:{self.app_id}", d["refresh_token"])
        secret_set(f"scopes:{self.app_id}", " ".join(SCOPES))
        self._access = d.get("access_token", "")
        self._access_until = time.time() + int(d.get("expires_in", 7200)) - 120

    def access_token(self) -> str:
        if self._access and time.time() < self._access_until:
            return self._access
        rt = self.refresh_token
        if not rt:
            raise EbayError("Not signed in to eBay")
        try:
            d = self._token_request({"grant_type": "refresh_token", "refresh_token": rt,
                                     "scope": " ".join(self.granted())})
        except EbayError as e:
            if e.status in (400, 401):
                raise EbayError("eBay sign-in has expired or was revoked: sign in again", e.status, e.errors)
            raise
        self._access = d["access_token"]
        self._access_until = time.time() + int(d.get("expires_in", 7200)) - 120
        return self._access

    # ---------------------------------------------------------- HTTP
    def _send(self, req, timeout=60, retries=0):
        """One request; eBay's servers throw the odd 500 or drop a connection under load,
        so idempotent requests and photo uploads try again a few times before giving up."""
        for attempt in range(retries + 1):
            try:
                return self._send_once(req, timeout)
            except EbayError as e:
                transient = not e.status or e.status >= 500 or e.status == 429
                if not transient or attempt == retries:
                    raise
                _log([f"retrying {req.get_method()} {req.full_url} after {e} (attempt {attempt + 2})"])
                time.sleep((2, 5, 10, 20)[min(attempt, 3)])

    def _send_once(self, req, timeout=60):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                out = json.loads(data) if data else {}
                if isinstance(out, dict):
                    out["_location"] = r.headers.get("Location", "")
                return out
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                d = json.loads(raw)
            except ValueError:
                d = {}
            errs = d.get("errors") or ([{"message": d.get("error_description") or d.get("error")}]
                                       if d.get("error") else [])

            def one(x):
                t = x.get("longMessage") or x.get("message") or ""
                params = ", ".join(f"{p.get('name')}={p.get('value')}" for p in (x.get("parameters") or []))
                return (f"[{x.get('errorId')}] " if x.get("errorId") else "") + t + (f" ({params})" if params else "")
            plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()
            msg = "; ".join(one(x) for x in errs) or plain[:200] or "no details"
            sent = ""
            if req.data and "oauth2/token" not in req.full_url and b"form-data" not in (req.data[:200] or b""):
                sent = req.data.decode("utf-8", "replace")[:4000]
            _log([f"{req.get_method()} {req.full_url}", f"HTTP {e.code}", f"response: {raw[:4000]}",
                  f"sent: {sent}" if sent else "sent: (photo or sign-in, not logged)"])
            raise EbayError(f"eBay said: {msg} (HTTP {e.code})", e.code, errs)
        except urllib.error.URLError as e:
            raise EbayError(f"Could not reach eBay: {e.reason}")

    def call(self, method: str, path: str, body=None, base: str = API, headers=None):
        h = {"Authorization": f"Bearer {self.access_token()}", "Accept": "application/json",
             "Content-Language": "en-US", "Accept-Language": "en-US"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        req = urllib.request.Request(base + path, data=data, method=method, headers=h)
        # creating things (POST) is not retried blindly: a retry after a lost reply could make two
        return self._send(req, retries=3 if method in ("GET", "PUT", "DELETE") else 0)

    # ---------------------------------------------------------- traffic (Analytics API)
    TRAFFIC_METRICS = ["TOTAL_IMPRESSION_TOTAL", "LISTING_IMPRESSION_TOTAL", "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE",
                       "LISTING_VIEWS_SOURCE_SEARCH_RESULTS_PAGE", "LISTING_VIEWS_TOTAL", "TRANSACTION"]
    # where page views came from; the four together with search results make up LISTING_VIEWS_TOTAL
    SOURCE_METRICS = ["LISTING_VIEWS_SOURCE_DIRECT", "LISTING_VIEWS_SOURCE_OFF_EBAY",
                      "LISTING_VIEWS_SOURCE_OTHER_EBAY", "LISTING_VIEWS_SOURCE_STORE"]

    def traffic(self, days: int = 30) -> dict:
        """Seller Hub's Traffic card, day by day: impressions, page views, search clicks and
        sales for the last `days` days and the same span before it, so changes can be shown.
        Counts only; the rates are worked out from them, which avoids guessing eBay's units."""
        import datetime as dt
        if not self.has_analytics():
            raise EbayError("RECONNECT")
        try:
            from zoneinfo import ZoneInfo
            today = dt.datetime.now(ZoneInfo("America/Los_Angeles")).date()   # eBay reports in Pacific time
        except Exception:  # noqa: BLE001
            today = dt.date.today()
        split = today - dt.timedelta(days=days)
        back = today - dt.timedelta(days=2 * days + 1)
        attempts = [(back, self.TRAFFIC_METRICS + self.SOURCE_METRICS),
                    (back, self.TRAFFIC_METRICS[1:] + self.SOURCE_METRICS),
                    (back, self.TRAFFIC_METRICS[1:]),
                    (split, self.TRAFFIC_METRICS[1:])]
        d, err, start = None, None, today
        for start, metrics in attempts:
            filt = f"marketplace_ids:{{{MARKETPLACE}}},date_range:[{start:%Y%m%d}..{today:%Y%m%d}]"
            q = urllib.parse.urlencode({"dimension": "DAY", "filter": filt, "metric": ",".join(metrics)},
                                       quote_via=urllib.parse.quote)
            try:
                d = self.call("GET", "/sell/analytics/v1/traffic_report?" + q)
                break
            except EbayError as e:
                err = e
                if e.status not in (400, 409):
                    raise
        if d is None:
            raise err
        keys = [m.get("key") for m in (d.get("header") or {}).get("metrics", [])]
        rows = []
        for i, r in enumerate(d.get("records") or []):
            dv = ((r.get("dimensionValues") or [{}])[0]).get("value", "")
            day = _report_day(str(dv)) or start + dt.timedelta(days=i)
            vals = {}
            for k, mv in zip(keys, r.get("metricValues") or []):
                try:
                    vals[k] = float(mv.get("value") or 0) if mv.get("applicable", True) else 0.0
                except (TypeError, ValueError):
                    vals[k] = 0.0
            rows.append([day.isoformat(), vals])
        rows.sort()
        return {"days": rows, "split": split.isoformat(), "start": start.isoformat(), "end": today.isoformat(),
                "updated": d.get("lastUpdatedDate", "")}

    # ---------------------------------------------------------- your store (Trading API)
    TRADING_NS = "{urn:ebay:apis:eBLBaseComponents}"

    def trading(self, call: str, inner: str):
        """One Trading API call with the signed-in user's OAuth token; returns the XML root."""
        import xml.etree.ElementTree as ET
        body = (f'<?xml version="1.0" encoding="utf-8"?><{call}Request xmlns="urn:ebay:apis:eBLBaseComponents">'
                f"{inner}</{call}Request>").encode()
        req = urllib.request.Request(f"{API}/ws/api.dll", data=body, method="POST", headers={
            "X-EBAY-API-CALL-NAME": call, "X-EBAY-API-SITEID": "0", "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
            "X-EBAY-API-IAF-TOKEN": self.access_token(), "Content-Type": "text/xml"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    root = ET.fromstring(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt == 2:
                    raise EbayError(f"eBay said HTTP {e.code} for {call}", e.code)
            except urllib.error.URLError as e:
                if attempt == 2:
                    raise EbayError(f"Could not reach eBay: {e.reason}")
            time.sleep(2 + 3 * attempt)
        ns = self.TRADING_NS
        if (root.findtext(f"{ns}Ack") or "") == "Failure":
            msgs = [e.findtext(f"{ns}LongMessage") or e.findtext(f"{ns}ShortMessage") or ""
                    for e in root.iter(f"{ns}Errors") if e.findtext(f"{ns}SeverityCode") == "Error"]
            raise EbayError("eBay said: " + ("; ".join(m for m in msgs if m) or f"{call} failed"))
        return root

    def shipments(self, days: int = 90, max_pages: int = 10) -> list[dict]:
        """Every tracking number on your orders from the last `days` (eBay allows 90), one entry each:
        tracking, carrier, the order, its first item's title, buyer, date, total and link. My eBay Selling
        leaves tracking out, so this reads GetOrders, where both the order's and each line's numbers live."""
        import datetime as _dt
        ns = self.TRADING_NS
        now = _dt.datetime.now(_dt.timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%S.000Z"
        span = (f"<CreateTimeFrom>{(now - _dt.timedelta(days=min(90, days))).strftime(fmt)}</CreateTimeFrom>"
                f"<CreateTimeTo>{now.strftime(fmt)}</CreateTimeTo>")
        out, seen = [], set()
        for page in range(1, max_pages + 1):
            root = self.trading("GetOrders", span + "<OrderRole>Seller</OrderRole><OrderStatus>All</OrderStatus>"
                                f"<Pagination><EntriesPerPage>100</EntriesPerPage><PageNumber>{page}</PageNumber>"
                                "</Pagination><DetailLevel>ReturnAll</DetailLevel>")
            for o in root.iter(f"{ns}Order"):
                txs = list(o.iter(f"{ns}Transaction"))
                first = txs[0].find(f"{ns}Item") if txs else None
                title = (first.findtext(f"{ns}Title") if first is not None else "") or "eBay order"
                if len(txs) > 1:
                    title += f" + {len(txs) - 1} more"
                item_id = first.findtext(f"{ns}ItemID") if first is not None else ""
                try:
                    total = float(o.findtext(f"{ns}Total") or 0)
                except ValueError:
                    total = 0.0
                svc = " ".join(x.text or "" for x in o.iter(f"{ns}ShippingService")).lower()
                pstat = (o.findtext(f"{ns}PickupMethodSelected/{ns}PickupStatus") or "").lower()
                pickup = "pickup" in svc or bool(pstat)
                base = {"id": item_id or "", "title": title, "buyer": o.findtext(f"{ns}BuyerUserID") or "",
                        "date": o.findtext(f"{ns}CreatedTime") or "", "order": o.findtext(f"{ns}OrderID") or "",
                        "url": f"https://www.ebay.com/itm/{item_id}" if item_id else "", "price": total,
                        "shipped": o.findtext(f"{ns}ShippedTime") or "", "pickup": pickup,
                        "picked_up": pickup and (pstat == "pickedup" or bool(o.findtext(f"{ns}ShippedTime")))}
                if pickup and not any(True for _ in o.iter(f"{ns}ShipmentTrackingNumber")):
                    out.append({**base, "tracking": "", "carrier": "Pickup"})     # one entry for the order
                for d in o.iter(f"{ns}ShipmentTrackingDetails"):
                    num = (d.findtext(f"{ns}ShipmentTrackingNumber") or "").replace(" ", "").upper()
                    if num and num not in seen:
                        seen.add(num)
                        out.append({**base, "tracking": num, "carrier": d.findtext(f"{ns}ShippingCarrierUsed") or ""})
            more = (root.findtext(f"{ns}HasMoreOrders") or "").lower() == "true"
            if not more:
                break
        return out

    # ------------------------------------------------------------ offers and shipping (phone console)
    def best_offers(self) -> list:
        """Every buyer's offer waiting on your active listings: id, item, title, the listing's price,
        the offer, the buyer, their message, quantity and when it expires."""
        ns = self.TRADING_NS
        root = self.trading("GetBestOffers", "<BestOfferStatus>Active</BestOfferStatus>"
                                             "<DetailLevel>ReturnAll</DetailLevel>")

        def tx(el, path, d=""):
            v = el.find("/".join(ns + p for p in path.split("/"))) if el is not None else None
            return v.text if v is not None and v.text is not None else d
        out = []
        for ib in root.iter(f"{ns}ItemBestOffers"):
            item = ib.find(f"{ns}Item")
            iid, title = tx(item, "ItemID"), tx(item, "Title")
            try:
                ask = float(tx(item, "BuyItNowPrice", "0") or tx(item, "SellingStatus/CurrentPrice", "0") or 0)
            except ValueError:
                ask = 0.0
            for bo in ib.iter(f"{ns}BestOffer"):
                if (tx(bo, "Status") or "Pending") not in ("Pending", "Active"):
                    continue
                try:
                    price = float(tx(bo, "Price", "0") or 0)
                except ValueError:
                    price = 0.0
                out.append({"id": tx(bo, "BestOfferID"), "item": iid, "title": title, "ask": ask, "price": price,
                            "buyer": tx(bo, "Buyer/UserID"), "feedback": tx(bo, "Buyer/FeedbackScore"),
                            "message": tx(bo, "BuyerMessage"), "qty": int(tx(bo, "Quantity", "1") or 1),
                            "expires": tx(bo, "ExpirationTime"), "kind": tx(bo, "BestOfferCodeType")})
        out.sort(key=lambda o: o["expires"])
        return out

    def respond_offer(self, item_id: str, offer_id: str, action: str, counter: float = 0.0, message: str = ""):
        """Accept, Decline or Counter one offer."""
        from xml.sax.saxutils import escape
        if action not in ("Accept", "Decline", "Counter"):
            raise EbayError(f"Unknown answer to an offer: {action}")
        inner = (f"<ItemID>{escape(item_id)}</ItemID><BestOfferID>{escape(offer_id)}</BestOfferID>"
                 f"<Action>{action}</Action>")
        if action == "Counter":
            inner += f'<CounterOfferPrice currencyID="USD">{counter:.2f}</CounterOfferPrice><CounterOfferQuantity>1</CounterOfferQuantity>'
        if message:
            inner += f"<SellerResponse>{escape(message[:250])}</SellerResponse>"
        self.trading("RespondToBestOffer", inner)

    CARRIERS = {"USPS": "USPS", "UPS": "UPS", "FedEx": "FedEx", "DHL": "DHL"}

    def mark_shipped(self, item_id: str, txn: str, tracking: str = "", carrier: str = "", order_line: str = ""):
        """Marks a sale shipped, with its tracking number when there is one, so the buyer sees it."""
        from xml.sax.saxutils import escape
        ids = (f"<OrderLineItemID>{escape(order_line)}</OrderLineItemID>" if order_line and not txn else
               f"<ItemID>{escape(item_id)}</ItemID><TransactionID>{escape(txn or '0')}</TransactionID>")
        ship = "<Shipped>true</Shipped>"
        if tracking:
            ship += ("<Shipment><ShipmentTrackingDetails>"
                     f"<ShipmentTrackingNumber>{escape(tracking.replace(' ', ''))}</ShipmentTrackingNumber>"
                     f"<ShippingCarrierUsed>{escape(self.CARRIERS.get(carrier, carrier or 'USPS'))}</ShippingCarrierUsed>"
                     "</ShipmentTrackingDetails></Shipment>")
        self.trading("CompleteSale", ids + ship)

    def item_pictures(self, item_id: str) -> tuple[list, str]:
        """Every photo of a listing (largest size) and its SKU, live or ended."""
        ns = self.TRADING_NS
        root = self.trading("GetItem", f"<ItemID>{item_id}</ItemID><OutputSelector>PictureDetails</OutputSelector>"
                                       "<OutputSelector>SKU</OutputSelector>")
        it = root.find(f"{ns}Item")
        urls = [e.text for e in (it.iter(f"{ns}PictureURL") if it is not None else []) if e.text]
        sku = it.findtext(f"{ns}SKU") if it is not None else ""
        return urls, sku or ""

    # eBay's card condition descriptor (40001) values, back to CardCrop's codes
    CONDITION_CODES = {"400010": "NM", "400011": "LP", "400015": "LP", "400012": "MP", "400016": "MP",
                       "400013": "HP", "400017": "HP"}

    def item_graded(self, item_id: str) -> tuple[list, str, str, str]:
        """A listing's photos, SKU, the condition you gave it (NM, LP, MP, HP, or "" when it has
        none, or is a professionally graded card) and its title."""
        ns = self.TRADING_NS
        root = self.trading("GetItem", f"<ItemID>{item_id}</ItemID><OutputSelector>PictureDetails</OutputSelector>"
                                       "<OutputSelector>SKU</OutputSelector><OutputSelector>Title</OutputSelector>"
                                       "<OutputSelector>ConditionID</OutputSelector>"
                                       "<OutputSelector>ConditionDescriptors</OutputSelector>")
        it = root.find(f"{ns}Item")
        if it is None:
            return [], "", "", ""
        urls = [e.text for e in it.iter(f"{ns}PictureURL") if e.text]
        code = ""
        if (it.findtext(f"{ns}ConditionID") or "") != "2750":          # 2750: graded by a grading company
            for dsc in it.iter(f"{ns}ConditionDescriptor"):
                if (dsc.findtext(f"{ns}Name") or "") == "40001":
                    code = self.CONDITION_CODES.get(dsc.findtext(f"{ns}Value") or "", "")
        return urls, it.findtext(f"{ns}SKU") or "", code, it.findtext(f"{ns}Title") or ""

    def add_listing_photo(self, item_id: str, sku: str, path: str, replace: str = "") -> str:
        """Uploads one photo and adds it as the listing's last photo, live. CardCrop's own listings
        are changed through their inventory record (eBay updates the live listing from it); others
        through a revise of the listing's pictures. replace: an earlier photo's address, taken out as this
        one goes in. Returns the new photo's eBay address."""
        url = self.upload_image(path)
        gone = {url, replace} - {""}
        if sku:
            try:
                item = self.call("GET", f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku)}")
            except EbayError as e:
                if e.status != 404:
                    raise
                item = None
            if item:
                prod = item.get("product") or {}
                imgs = [u for u in (prod.get("imageUrls") or []) if u not in gone][:MAX_PHOTOS - 1] + [url]
                prod["imageUrls"] = imgs
                body = _put_body(item)
                body["product"] = prod
                self.call("PUT", f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku)}", body)
                return url
        current, _ = self.item_pictures(item_id)
        pics = [u for u in current if u not in gone][:MAX_PHOTOS - 1] + [url]
        inner = "".join(f"<PictureURL>{xml_escape(u)}</PictureURL>" for u in pics)
        self.trading("ReviseFixedPriceItem", f"<Item><ItemID>{item_id}</ItemID>"
                                             f"<PictureDetails>{inner}</PictureDetails></Item>")
        return url

    # ---------------------------------------------------------- listing videos (Media API)
    # the video endpoints are on the media host under v1_beta; eBay's guide also names the main
    # host under v1, so that is tried when the first answers 404
    VIDEO_BASES = (f"{MEDIA}/commerce/media/v1_beta", f"{API}/commerce/media/v1")

    def _video_call(self, method, path, data=None, ctype="application/json", timeout=60, retries=1):
        last = None
        for base in self.VIDEO_BASES:
            headers = {"Authorization": f"Bearer {self.access_token()}", "Accept": "application/json"}
            if data is not None:
                headers["Content-Type"] = ctype
                headers["Content-Length"] = str(len(data))
            req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
            try:
                return self._send(req, timeout=timeout, retries=retries)
            except EbayError as e:
                if e.status != 404:
                    raise
                last = e
        raise last

    @staticmethod
    def video_title(title: str) -> str:
        """eBay refuses video titles with anything it reads as markup (an ampersand, angle brackets,
        quotes): those become words or spaces, leaving letters, digits and plain punctuation."""
        import unicodedata
        t = (title or "").replace("&", " and ")
        t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))
        t = re.sub(r"[^A-Za-z0-9 .,:;!?()/+\-#']", " ", t)
        t = re.sub(r"[#']", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        return (t or "Card video")[:80].rstrip()

    def upload_video(self, path: str, title: str) -> str:
        """Creates a video on eBay and uploads the MP4 into it; returns the video id."""
        size = os.path.getsize(path)
        if size > 157_286_400:
            raise EbayError("The video is over eBay's 150 MB limit")
        body = json.dumps({"title": self.video_title(title), "size": size, "classification": ["ITEM"],
                           "description": "360 degree view of the card"}).encode()
        d = self._video_call("POST", "/video", body)
        loc = d.get("_location", "")
        vid = loc.rstrip("/").split("/")[-1] if loc else d.get("videoId", "")
        if not vid:
            raise EbayError("eBay did not return a video id")
        with open(path, "rb") as f:
            data = f.read()
        self._video_call("POST", f"/video/{vid}/upload", data, "application/octet-stream", timeout=300, retries=2)
        return vid

    def video_status(self, vid: str) -> str:
        return self._video_call("GET", f"/video/{vid}", timeout=30, retries=2).get("status", "")

    def listing_videos(self, item_id: str, sku: str = "") -> list:
        """The video ids already on a listing, from its inventory record or the listing itself."""
        if sku:
            try:
                item = self.call("GET", f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku)}")
                ids = (item.get("product") or {}).get("videoIds") or []
                if ids:
                    return list(ids)
            except EbayError:
                pass
        ns = self.TRADING_NS
        it = self.trading("GetItem", f"<ItemID>{item_id}</ItemID><OutputSelector>VideoDetails</OutputSelector>"
                          ).find(f"{ns}Item")
        return [e.text for e in (it.iter(f"{ns}VideoID") if it is not None else []) if e.text]

    def attach_video(self, item_id: str, sku: str, vid: str) -> None:
        """Puts the video on the listing (replacing any earlier one); it shows once eBay has processed it."""
        if sku:
            try:
                item = self.call("GET", f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku)}")
            except EbayError as e:
                if e.status != 404:
                    raise
                item = None
            if item:
                prod = item.get("product") or {}
                prod["videoIds"] = [vid]
                body = _put_body(item)
                body["product"] = prod
                self.call("PUT", f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku)}", body)
                return
        self.trading("ReviseFixedPriceItem", f"<Item><ItemID>{item_id}</ItemID>"
                                             f"<VideoDetails><VideoID>{xml_escape(vid)}</VideoID></VideoDetails></Item>")

    def item_picture(self, item_id: str) -> str:
        """The picture of one listing, live or ended (My eBay's sold list carries none).
        Remembered on disk, since a listing's picture does not change."""
        import identify
        path = os.path.join(identify._cache_dir(), "pictures.json")
        try:
            with open(path, encoding="utf-8") as f:
                known = json.load(f)
        except (OSError, ValueError):
            known = {}
        if item_id in known:
            return known[item_id]
        ns = self.TRADING_NS
        root = self.trading("GetItem", f"<ItemID>{item_id}</ItemID><OutputSelector>PictureDetails</OutputSelector>")
        pd = root.find(f"{ns}Item/{ns}PictureDetails")
        url = ""
        if pd is not None:
            url = pd.findtext(f"{ns}GalleryURL") or pd.findtext(f"{ns}PictureURL") or ""
        url = re.sub(r"s-l\d+\.(jpg|webp|png)", "s-l300.jpg", url) if "ebayimg" in url else url
        known[item_id] = url
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(known, f)
        except OSError:
            pass
        return url

    def my_store(self, sold_days: int = 60, max_pages: int = 5) -> dict:
        """Active listings and sales from the last sold_days (eBay keeps 60 here), from My eBay Selling.
        Covers every listing on the account, made in CardCrop or anywhere else."""
        ns = self.TRADING_NS

        def t(el, path, default=""):
            v = el.find("/".join(ns + p for p in path.split("/")))
            return v.text if v is not None and v.text is not None else default

        def money(el, path):
            try:
                return float(t(el, path, "0") or 0)
            except ValueError:
                return 0.0

        active, sold = [], []
        for page in range(1, max_pages + 1):
            root = self.trading("GetMyeBaySelling", (
                "<ActiveList><Include>true</Include><Pagination>"
                f"<EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination></ActiveList>"
                + (f"<SoldList><Include>true</Include><DurationInDays>{sold_days}</DurationInDays>"
                   "<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>1</PageNumber></Pagination>"
                   "</SoldList>" if page == 1 else "")
                + "<DetailLevel>ReturnAll</DetailLevel>"))
            al = root.find(f"{ns}ActiveList")
            items = list(al.iter(f"{ns}Item")) if al is not None else []
            for it in items:
                active.append({
                    "id": t(it, "ItemID"), "title": t(it, "Title"), "sku": t(it, "SKU"),
                    "price": money(it, "SellingStatus/CurrentPrice") or money(it, "BuyItNowPrice"),
                    "start": t(it, "ListingDetails/StartTime"), "end": t(it, "ListingDetails/EndTime"),
                    "url": t(it, "ListingDetails/ViewItemURL"),
                    "image": t(it, "PictureDetails/GalleryURL"), "watchers": int(t(it, "WatchCount", "0") or 0),
                    "qty": int(t(it, "QuantityAvailable", "0") or t(it, "Quantity", "0") or 0)})
            if page == 1:
                sl = root.find(f"{ns}SoldList")
                if sl is not None:
                    for tr in sl.iter(f"{ns}Transaction"):
                        it = tr.find(f"{ns}Item")
                        if it is None:
                            continue
                        price = (money(tr, "TotalTransactionPrice") or money(tr, "TotalPrice")
                                 or money(tr, "TransactionPrice") or money(it, "SellingStatus/CurrentPrice"))
                        sold.append({
                            "id": t(it, "ItemID"), "title": t(it, "Title"), "sku": t(it, "SKU"), "price": price,
                            "date": t(tr, "CreatedDate") or t(it, "ListingDetails/EndTime"),
                            "paid": bool(t(tr, "PaidTime")), "shipped": bool(t(tr, "ShippedTime")),
                            "buyer": t(tr, "Buyer/UserID"), "url": t(it, "ListingDetails/ViewItemURL"),
                            "image": t(it, "PictureDetails/GalleryURL"),
                            "txn": t(tr, "TransactionID"), "order": t(tr, "OrderLineItemID"),
                            "tracking": t(tr, "ShippingDetails/ShipmentTrackingDetails/ShipmentTrackingNumber"),
                            "qty": int(t(tr, "QuantityPurchased", "1") or 1)})
            pages = int(t(al, "PaginationResult/TotalNumberOfPages", "1") or 1) if al is not None else 1
            if page >= pages:
                break
        active.sort(key=lambda a: a["start"], reverse=True)
        sold.sort(key=lambda a: a["date"], reverse=True)
        try:                                       # each listing's store categories, for showing and filtering
            cats = self.listing_store_categories([a["id"] for a in active])
            for a in active:
                a["store_cat"], a["store_cat2"] = cats.get(a["id"], ("", ""))
        except EbayError:
            pass
        return {"active": active, "sold": sold, "fetched": time.time()}

    def listing_store_categories(self, ids=None, max_pages: int = 10) -> dict:
        """{item id: (store category id, second store category id)} for every active listing.
        My eBay Selling leaves these out, so they come from the seller's list, asked twice (listings
        ending in the next 119 days, and listings started in the last 119), and any listing still
        missing is read on its own, so none is left without its categories."""
        import datetime as _dt
        from concurrent.futures import ThreadPoolExecutor
        ns = self.TRADING_NS
        now = _dt.datetime.now(_dt.timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%S.000Z"
        windows = (f"<EndTimeFrom>{now.strftime(fmt)}</EndTimeFrom>"
                   f"<EndTimeTo>{(now + _dt.timedelta(days=119)).strftime(fmt)}</EndTimeTo>",
                   f"<StartTimeFrom>{(now - _dt.timedelta(days=119)).strftime(fmt)}</StartTimeFrom>"
                   f"<StartTimeTo>{now.strftime(fmt)}</StartTimeTo>")
        out = {}

        def norm(c):
            c = (c or "").strip()
            return "" if c in ("", "0") else c
        for win in windows:
            for page in range(1, max_pages + 1):
                try:
                    root = self.trading("GetSellerList", (
                        f"{win}<DetailLevel>ReturnAll</DetailLevel>"
                        f"<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>"
                        "<OutputSelector>ItemArray.Item.ItemID</OutputSelector>"
                        "<OutputSelector>ItemArray.Item.Storefront</OutputSelector>"
                        "<OutputSelector>PaginationResult</OutputSelector>"))
                except EbayError:
                    break
                for it in root.iter(f"{ns}Item"):
                    iid = (it.findtext(f"{ns}ItemID") or "").strip()
                    sf = it.find(f"{ns}Storefront")
                    if iid and sf is not None:
                        out[iid] = (norm(sf.findtext(f"{ns}StoreCategoryID")), norm(sf.findtext(f"{ns}StoreCategory2ID")))
                pages = int(root.findtext(f"{ns}PaginationResult/{ns}TotalNumberOfPages") or 1)
                if page >= pages:
                    break
        missing = [i for i in (ids or []) if i not in out][:400]
        if missing:
            def one(iid):
                try:
                    a, b = self.listing_store_categories_one(iid)
                    return iid, (a[0], b[0])
                except EbayError:
                    return iid, None
            with ThreadPoolExecutor(6) as ex:
                for iid, v in ex.map(one, missing):
                    if v is not None:
                        out[iid] = v
        return out

    def set_listing_store_categories(self, item_id: str, sku: str, cat, cat2) -> None:
        """Both store categories of one live listing, each (id, '/Path') or ('', ''), or None to keep it."""
        if cat is None or cat2 is None:
            cur = self.listing_store_categories_one(item_id)
            cat = cat if cat is not None else cur[0]
            cat2 = cat2 if cat2 is not None else cur[1]
        self.revise_listing(item_id, sku, {"store_cat": cat, "store_cat2": cat2})

    def listing_store_categories_one(self, item_id: str):
        """((id, ''), (id2, '')) of one listing, read live."""
        ns = self.TRADING_NS
        root = self.trading("GetItem", f"<ItemID>{item_id}</ItemID><OutputSelector>Storefront</OutputSelector>")
        c1 = (root.findtext(f"{ns}Item/{ns}Storefront/{ns}StoreCategoryID") or "").strip()
        c2 = (root.findtext(f"{ns}Item/{ns}Storefront/{ns}StoreCategory2ID") or "").strip()
        return (("" if c1 in ("", "0") else c1, ""), ("" if c2 in ("", "0") else c2, ""))

    # ---------------------------------------------------------- live market prices
    def app_token(self) -> str:
        """An application token (no sign-in needed) for searching eBay's public listings."""
        if getattr(self, "_app", "") and time.time() < getattr(self, "_app_until", 0):
            return self._app
        d = self._token_request({"grant_type": "client_credentials",
                                 "scope": "https://api.ebay.com/oauth/api_scope"})
        self._app = d["access_token"]
        self._app_until = time.time() + int(d.get("expires_in", 7200)) - 120
        return self._app

    def live_listings(self, query: str, number: str = "", limit: int = 100, must=None, must_not=None) -> list[float]:
        """Prices (item plus cheapest shipping, USD) of fixed-price, ungraded listings for
        this card on eBay right now. Titles must carry the card number, and graded slabs,
        lots and proxies are dropped, so other printings do not skew the result."""
        q = urllib.parse.urlencode({"q": query, "category_ids": CATEGORY_ID, "limit": limit,
                                    "filter": "buyingOptions:{FIXED_PRICE},priceCurrency:USD,conditionIds:{4000}"})
        req = urllib.request.Request(f"{API}/buy/browse/v1/item_summary/search?{q}",
                                     headers={"Authorization": f"Bearer {self.app_token()}",
                                              "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE, "Accept": "application/json"})
        d = self._send(req, timeout=30)
        num = number.strip().lstrip("0").upper()
        bad = re.compile(r"\b(psa|bgs|cgc|sgc|graded|lot|proxy|custom|orica|fake|digital|code card)\b", re.I)
        out = []
        for it in d.get("itemSummaries", []) or []:
            title = it.get("title", "")
            if bad.search(title):
                continue
            low = " " + re.sub(r"[^a-z0-9']+", " ", title.lower()) + " "
            if must and not any(re.search(w, low) for w in must):
                continue                     # another rarity or version of the same code
            if must_not and any(re.search(w, low) for w in must_not):
                continue
            if num and not re.search(rf"(?<![0-9A-Z]){re.escape(num)}(?![0-9])", title.upper().replace("#", " ").replace("/", " / ").replace(" 0", " ")) \
                    and num not in re.sub(r"\b0+(\d)", r"\1", title.upper()):
                continue
            try:
                price = float(it["price"]["value"])
            except (KeyError, TypeError, ValueError):
                continue
            ship = 0.0
            for so in it.get("shippingOptions") or []:
                try:
                    ship = float(so["shippingCost"]["value"])
                    break
                except (KeyError, TypeError, ValueError):
                    pass
            out.append(round(price + ship, 2))
        return sorted(out)

    # ---------------------------------------------------------- account setup
    def policies(self) -> dict:
        """{'fulfillment': [(id, name)], 'return': [...], 'payment': [...]}"""
        out = {}
        for kind, key in (("fulfillment", "fulfillmentPolicies"), ("return", "returnPolicies"),
                          ("payment", "paymentPolicies")):
            try:
                d = self.call("GET", f"/sell/account/v1/{kind}_policy?marketplace_id={MARKETPLACE}")
            except EbayError as e:
                if "20403" in {str(i) for i in e.ids()} or "not opted in" in str(e).lower():
                    raise EbayError("Your eBay account is not set up for business policies yet. "
                                    "In Seller Hub, open Account > Business policies and create a "
                                    "shipping, return and payment policy, then press Refresh.")
                raise
            out[kind] = [(p[f"{kind}PolicyId"], p.get("name", "")) for p in d.get(key, [])]
        return out

    def ensure_location(self, postal_code: str, country: str = "US") -> str:
        """Where the cards ship from. Created once; a later ZIP change updates it."""
        body = {"location": {"address": {"postalCode": postal_code.strip(), "country": country}},
                "locationTypes": ["WAREHOUSE"], "name": "CardCrop", "merchantLocationStatus": "ENABLED"}
        # the lookup itself can fail with eBay's generic 500; then just try to create it
        try:
            self.call("GET", f"/sell/inventory/v1/location/{LOCATION_KEY}")
            exists = True
        except EbayError as e:
            if e.status != 404 and e.status < 500:
                raise
            exists = False
        if exists:
            self.call("POST", f"/sell/inventory/v1/location/{LOCATION_KEY}/update_location_details",
                      {"location": body["location"]})
            return LOCATION_KEY
        try:
            self.call("POST", f"/sell/inventory/v1/location/{LOCATION_KEY}", body)
        except EbayError as e:
            if "already exist" not in str(e).lower() and e.status != 409:
                raise
            self.call("POST", f"/sell/inventory/v1/location/{LOCATION_KEY}/update_location_details",
                      {"location": body["location"]})
        return LOCATION_KEY

    # ---------------------------------------------------------- photos
    def upload_image(self, path: str) -> str:
        """One photo to eBay's picture hosting; returns its eBay image URL."""
        data, fname = _jpeg_for_ebay(path)
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{fname}\"\r\n"
                f"Content-Type: image/jpeg\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{MEDIA}/commerce/media/v1_beta/image/create_image_from_file", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.access_token()}",
                     "Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"})
        d = self._send(req, timeout=180, retries=4)
        url = d.get("imageUrl")
        if not url and d.get("_location"):          # some responses carry only the image's address
            img = self.call("GET", urllib.parse.urlparse(d["_location"]).path, base=MEDIA)
            url = img.get("imageUrl")
        if not url:
            raise EbayError(f"eBay accepted {os.path.basename(path)} but returned no picture address")
        return url

    # ---------------------------------------------------------- listing
    def put_item(self, sku: str, title: str, description: str, aspects: dict, image_urls: list,
                 condition: str, quantity: int = 1, package: dict | None = None):
        body = {
            "availability": {"shipToLocationAvailability": {"quantity": int(quantity)}},
            "condition": CONDITION_ENUM,
            "conditionDescriptors": [{"name": CARD_CONDITION_DESCRIPTOR, "values": [condition]}],
            "product": {"title": _safe(title)[:80], "description": description,
                        "aspects": {k: [_safe(v)] for k, v in aspects.items() if v and _safe(v)},
                        "imageUrls": image_urls[:MAX_PHOTOS]},
        }
        if package:   # calculated shipping needs these, or publishing fails with error 25020
            body["packageWeightAndSize"] = {
                "weight": {"value": float(package["oz"]), "unit": "OUNCE"},
                "dimensions": {"length": float(package["l"]), "width": float(package["w"]),
                               "height": float(package["h"]), "unit": "INCH"}}
        self.call("PUT", f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku)}", body)

    def offer_for(self, sku: str) -> dict | None:
        try:
            d = self.call("GET", f"/sell/inventory/v1/offer?sku={urllib.parse.quote(sku)}"
                                 f"&marketplace_id={MARKETPLACE}")
        except EbayError as e:
            # no offer yet comes back as 404, as error 25713 'offer not available', or for some
            # accounts as eBay's generic 500; creating the offer then settles it either way
            if e.status == 404 or e.status >= 500 or "25713" in {str(i) for i in e.ids()}:
                return None
            raise
        offers = d.get("offers") or []
        return offers[0] if offers else None

    def store_categories(self) -> list:
        """Your eBay Store's categories and subcategories as [(id, '/Parent/Child')], in store order."""
        ns = self.TRADING_NS
        root = self.trading("GetStore", "<CategoryStructureOnly>true</CategoryStructureOnly>")
        out = []

        def walk(el, path):
            for c in el.findall(f"{ns}CustomCategory") + el.findall(f"{ns}ChildCategory"):
                name = (c.findtext(f"{ns}Name") or "").strip()
                cid = (c.findtext(f"{ns}CategoryID") or "").strip()
                if not name:
                    continue
                p = f"{path}/{name}"
                out.append((cid, p))
                walk(c, p)
        cats = root.find(f"{ns}Store/{ns}CustomCategories")
        if cats is None:
            raise EbayError("No eBay Store categories found. Store categories need an eBay Store subscription; "
                            "add them in Seller Hub > Store > Store categories.")
        walk(cats, "")
        return out

    def set_store_category(self, sku: str, path: str, path2: str = None) -> None:
        """Moves a CardCrop listing (live or unpublished) to a store category, and a second one if given;
        '' takes it out. path2=None keeps whatever second category it has."""
        off = self.offer_for(sku)
        if not off:
            return
        full = self.get_offer(off["offerId"])
        body = {k: v for k, v in full.items() if k not in ("offerId", "status", "listing")}
        have = list(full.get("storeCategoryNames") or [])
        second = (have[1] if len(have) > 1 else "") if path2 is None else path2
        names = [p for p in (path, second) if p]
        if names:
            body["storeCategoryNames"] = names
        else:
            body.pop("storeCategoryNames", None)
        self.call("PUT", f"/sell/inventory/v1/offer/{off['offerId']}", body)

    def upsert_offer(self, sku: str, price: float, description: str, policies: dict,
                     quantity: int = 1, known_offer_id: str = "", store_category: str = "",
                     store_category2: str = "") -> str:
        """Creates the listing as an unpublished offer, or updates the one already there."""
        body = {
            "sku": sku, "marketplaceId": MARKETPLACE, "format": "FIXED_PRICE",
            "availableQuantity": int(quantity), "categoryId": CATEGORY_ID,
            "listingDescription": description,
            "listingPolicies": {"fulfillmentPolicyId": policies["fulfillment"],
                                "returnPolicyId": policies["return"],
                                "paymentPolicyId": policies["payment"]},
            "pricingSummary": {"price": {"value": f"{float(price):.2f}", "currency": "USD"}},
            "merchantLocationKey": LOCATION_KEY,
        }
        cats = [p for p in (store_category, store_category2) if p]   # full paths, '/Pokemon/Singles'
        if cats:
            body["storeCategoryNames"] = cats
        existing = self.offer_for(sku)
        if existing:
            oid = existing["offerId"]
            self.call("PUT", f"/sell/inventory/v1/offer/{oid}", body)
            return oid
        if known_offer_id:                 # CardCrop's own record, for when eBay's lookup fails
            try:
                self.call("PUT", f"/sell/inventory/v1/offer/{known_offer_id}", body)
                return known_offer_id
            except EbayError as e:
                if e.status != 404 and "25713" not in {str(i) for i in e.ids()}:
                    raise
        try:
            return self.call("POST", "/sell/inventory/v1/offer", body)["offerId"]
        except EbayError as e:
            # 25002: an offer for this SKU already exists; eBay names it in the parameters
            oid = next((p.get("value") for x in e.errors for p in (x.get("parameters") or [])
                        if p.get("name") == "offerId"), None)
            if not oid:
                raise
            self.call("PUT", f"/sell/inventory/v1/offer/{oid}", body)
            return oid

    def set_price(self, sku: str, price: float) -> None:
        """Changes the price of a CardCrop listing, live or unpublished, and nothing else."""
        off = self.offer_for(sku)
        if not off:
            raise EbayError("This card has no eBay listing yet")
        body = {"requests": [{"sku": sku, "offers": [{"offerId": off["offerId"], "availableQuantity":
                                                       int(off.get("availableQuantity") or 1),
                                                       "price": {"value": f"{float(price):.2f}", "currency": "USD"}}]}]}
        d = self.call("POST", "/sell/inventory/v1/bulk_update_price_quantity", body)
        for r in d.get("responses") or []:
            if int(r.get("statusCode") or 200) >= 400:
                msgs = "; ".join(e.get("message", "") for e in r.get("errors") or [])
                raise EbayError(f"eBay did not take the new price: {msgs or r.get('statusCode')}")

    def revise_price(self, item_id: str, price: float) -> None:
        """Price change for a listing made outside CardCrop (Seller Hub, the app, other tools)."""
        self.trading("ReviseInventoryStatus", f"<InventoryStatus><ItemID>{item_id}</ItemID>"
                                              f"<StartPrice>{float(price):.2f}</StartPrice></InventoryStatus>")

    # ---------------------------------------------------------- editing a live listing
    def listing_details(self, item_id: str) -> dict:
        """Everything the listing editor shows, from the live listing."""
        ns = self.TRADING_NS
        sel = "".join(f"<OutputSelector>{x}</OutputSelector>" for x in (
            "Title", "SKU", "Quantity", "SellingStatus", "StartPrice", "ConditionID", "ConditionDisplayName",
            "ConditionDescriptors", "BestOfferDetails", "ListingDetails", "PictureDetails", "ViewItemURL",
            "WatchCount", "HitCount", "SellerProfiles", "Storefront", "ShippingDetails"))
        it = self.trading("GetItem", f"<ItemID>{item_id}</ItemID><IncludeWatchCount>true</IncludeWatchCount>{sel}"
                          ).find(f"{ns}Item")
        if it is None:
            raise EbayError("eBay did not return this listing")

        def t(path, d=""):
            v = it.find("/".join(ns + p for p in path.split("/")))
            return v.text if v is not None and v.text is not None else d

        def num(path):
            try:
                return float(t(path, "0") or 0)
            except ValueError:
                return 0.0
        cond = ""
        if t("ConditionID") != "2750":
            for dsc in it.iter(f"{ns}ConditionDescriptor"):
                if (dsc.findtext(f"{ns}Name") or "") == "40001":
                    cond = self.CONDITION_CODES.get(dsc.findtext(f"{ns}Value") or "", "")
        qty, sold = int(num("Quantity")), int(num("SellingStatus/QuantitySold"))
        ship = t("SellerProfiles/SellerShippingProfile/ShippingProfileID")
        # local pickup as eBay shows it: a Pickup service on the listing itself, or the policy's switch
        services = [(s_.findtext(f"{ns}ShippingService") or "") for s_ in it.iter(f"{ns}ShippingServiceOptions")]
        pickup = any(_is_pickup(c) for c in services) or None
        ship_summary = ""
        if ship:
            try:
                pol = self.fulfillment_policy(ship)
                pickup = bool(pickup) or policy_has_pickup(pol)
                ship_summary = policy_summary(pol)
            except EbayError:
                pass
        store_cat = t("Storefront/StoreCategoryID")
        store_cat2 = t("Storefront/StoreCategory2ID")
        return {"ship_policy": ship, "pickup": pickup, "store_cat": "" if store_cat in ("", "0") else store_cat,
                "store_cat2": "" if store_cat2 in ("", "0") else store_cat2,
                "ship_policy_name": t("SellerProfiles/SellerShippingProfile/ShippingProfileName"),
                "ship_summary": ship_summary,
                "id": item_id, "title": t("Title"), "sku": t("SKU"),
                "price": num("SellingStatus/CurrentPrice") or num("StartPrice"),
                "available": max(0, qty - sold), "sold": sold, "condition": cond,
                "graded": t("ConditionID") == "2750", "condition_name": t("ConditionDisplayName"),
                "best_offer": t("BestOfferDetails/BestOfferEnabled") == "true",
                "auto_accept": num("ListingDetails/BestOfferAutoAcceptPrice"),
                "auto_decline": num("ListingDetails/MinimumBestOfferPrice"),
                "pictures": [e.text for e in it.iter(f"{ns}PictureURL") if e.text],
                "url": t("ListingDetails/ViewItemURL"), "watchers": int(num("WatchCount")),
                "views": int(num("HitCount"))}

    # ---------- local pickup: a setting of the shipping (fulfillment) policy, so a listing gets it by
    # moving to a copy of its policy with local pickup on, made once and reused
    PICKUP_SUFFIX = " + local pickup"

    def fulfillment_policy(self, pid: str) -> dict:
        return self.call("GET", f"/sell/account/v1/fulfillment_policy/{pid}")

    def fulfillment_policies(self) -> list:
        """Your shipping policies: [{id, name, pickup, summary}], as set up in Seller Hub."""
        d = self.call("GET", f"/sell/account/v1/fulfillment_policy?marketplace_id={MARKETPLACE}")
        return [{"id": p["fulfillmentPolicyId"], "name": p.get("name", ""), "pickup": policy_has_pickup(p),
                 "summary": policy_summary(p)} for p in d.get("fulfillmentPolicies", [])]

    def set_shipping_policy(self, item_id: str, sku: str, pid: str) -> None:
        """Moves a live listing to another of your shipping policies."""
        off = None
        if sku:
            try:
                off = self.offer_for(sku)
            except EbayError:
                off = None
        if off:
            full = self.get_offer(off["offerId"])
            body = {k: v for k, v in full.items() if k not in ("offerId", "status", "listing")}
            body.setdefault("listingPolicies", {})["fulfillmentPolicyId"] = pid
            self.call("PUT", f"/sell/inventory/v1/offer/{off['offerId']}", body)
            return
        self.trading("ReviseFixedPriceItem", f"<Item><ItemID>{item_id}</ItemID><SellerProfiles>"
                     f"<SellerShippingProfile><ShippingProfileID>{pid}</ShippingProfileID>"
                     "</SellerShippingProfile></SellerProfiles></Item>")

    def pickup_twin(self, pid: str, on: bool) -> str:
        """The shipping policy that matches pid in every way except local pickup set to on: an existing
        one when there is one, else a copy made now. Returns its id (pid itself if it already matches)."""
        cur = self.fulfillment_policy(pid)
        if bool(cur.get("localPickup")) == on:
            return pid
        name = cur.get("name", "") or "Shipping"
        want = (name[:64 - len(self.PICKUP_SUFFIX)] + self.PICKUP_SUFFIX) if on else \
            (name[:-len(self.PICKUP_SUFFIX)] if name.endswith(self.PICKUP_SUFFIX) else name)
        keys = ("shippingOptions", "handlingTime", "shipToLocations", "globalShipping", "freightShipping",
                "categoryTypes")

        def same(p):
            return all(p.get(k) == cur.get(k) for k in keys)
        d = self.call("GET", f"/sell/account/v1/fulfillment_policy?marketplace_id={MARKETPLACE}")
        pols = d.get("fulfillmentPolicies", [])
        for p in pols:                                   # the twin made before, or one of yours
            if bool(p.get("localPickup")) == on and p.get("name") == want:
                return p["fulfillmentPolicyId"]
        for p in pols:
            if bool(p.get("localPickup")) == on and same(p):
                return p["fulfillmentPolicyId"]
        if not on:
            raise EbayError(f"There is no shipping policy like {name} without local pickup. Pick another "
                            "shipping policy for this listing in Seller Hub.")
        body = {k: v for k, v in cur.items() if k not in ("fulfillmentPolicyId", "warnings") and not k.startswith("_")}
        body["name"] = want
        body["localPickup"] = True
        body.setdefault("marketplaceId", MARKETPLACE)
        # eBay reads a policy with no ship-to region as pickup only, and then refuses its shipping services
        # (LOCAL_PICKUP_ONLY_ERROR): ship to the US, as the policy did, with pickup as an extra
        if not (body.get("shipToLocations") or {}).get("regionIncluded"):
            body["shipToLocations"] = {"regionIncluded": [{"regionName": "US"}]}
        # pickup is the localPickup switch, never a shipping service of its own
        for opt in body.get("shippingOptions") or []:
            opt["shippingServices"] = [sv for sv in opt.get("shippingServices") or []
                                       if (sv.get("shippingServiceCode") or "").lower() not in ("pickup", "localpickup")]
        try:
            r = self.call("POST", "/sell/account/v1/fulfillment_policy", body)
        except EbayError as e:
            if "LOCAL_PICKUP" in str(e):
                raise EbayError(f"eBay would not make a copy of {name} with local pickup. In Seller Hub, make a "
                                f"shipping policy like it with local pickup on, named “{want}”, and CardCrop will "
                                "use it from then on.") from e
            raise
        return r["fulfillmentPolicyId"]

    def set_local_pickup(self, item_id: str, sku: str, on: bool, ship_policy: str = "") -> None:
        off = None
        if sku:
            try:
                off = self.offer_for(sku)
            except EbayError:
                off = None
        if off:
            full = self.get_offer(off["offerId"])
            cur = (full.get("listingPolicies") or {}).get("fulfillmentPolicyId") or ship_policy
            if not cur:
                raise EbayError("This listing has no shipping policy to add local pickup to.")
            new = self.pickup_twin(cur, on)
            if new != cur:
                body = {k: v for k, v in full.items() if k not in ("offerId", "status", "listing")}
                body.setdefault("listingPolicies", {})["fulfillmentPolicyId"] = new
                self.call("PUT", f"/sell/inventory/v1/offer/{off['offerId']}", body)
            return
        if not ship_policy:
            raise EbayError("This listing does not use a shipping policy, so local pickup has to be changed in "
                            "Seller Hub.")
        new = self.pickup_twin(ship_policy, on)
        if new != ship_policy:
            self.trading("ReviseFixedPriceItem", f"<Item><ItemID>{item_id}</ItemID><SellerProfiles>"
                         f"<SellerShippingProfile><ShippingProfileID>{new}</ShippingProfileID>"
                         "</SellerShippingProfile></SellerProfiles></Item>")

    def revise_listing(self, item_id: str, sku: str, ch: dict) -> None:
        """Applies the editor's changes to a live listing. ch may hold title, price, available,
        condition (NM/LP/MP/HP/DMG), best_offer, auto_accept, auto_decline. CardCrop's listings
        change through their inventory record and offer; every other listing through the Trading API."""
        import listing as _listing
        if "ship_policy_set" in ch:
            self.set_shipping_policy(item_id, sku, ch["ship_policy_set"])
            ch = {k: v for k, v in ch.items() if k != "ship_policy_set"}
            if not ch:
                return
        if "pickup" in ch:
            self.set_local_pickup(item_id, sku, bool(ch["pickup"]), ch.get("ship_policy", ""))
            ch = {k: v for k, v in ch.items() if k not in ("pickup", "ship_policy")}
            if not ch:
                return
        if "title" in ch:                           # eBay refuses ♀, ★, ™ and the like in a title
            ch = dict(ch, title=_safe(ch["title"])[:80])
        if "store_cat" in ch or "store_cat2" in ch:   # (id, '/Path/To') or ('', '') for none, each
            cid, path = ch.get("store_cat") or ("", "")
            cid2, path2 = ch.get("store_cat2") or ("", "")
            done = False
            if sku:
                try:
                    if self.offer_for(sku):
                        self.set_store_category(sku, path, path2)
                        done = True
                except EbayError:
                    done = False
            if not done:
                self.trading("ReviseFixedPriceItem", f"<Item><ItemID>{item_id}</ItemID><Storefront>"
                             f"<StoreCategoryID>{cid or 1}</StoreCategoryID>"
                             f"<StoreCategory2ID>{cid2 or 0}</StoreCategory2ID></Storefront></Item>")
            ch = {k: v for k, v in ch.items() if k not in ("store_cat", "store_cat2")}
            if not ch:
                return
        off = None
        if sku:
            try:
                off = self.offer_for(sku)
            except EbayError:
                off = None
        if off:
            q = urllib.parse.quote(sku)
            if "title" in ch or "condition" in ch or "available" in ch:
                item = self.call("GET", f"/sell/inventory/v1/inventory_item/{q}")
                body = _put_body(item)
                if "title" in ch:
                    body.setdefault("product", {})["title"] = ch["title"]
                if "condition" in ch and ch["condition"] in _listing.CONDITIONS:
                    body["conditionDescriptors"] = [{"name": "40001",
                                                     "values": [_listing.CONDITIONS[ch["condition"]][2]]}]
                if "available" in ch:
                    body.setdefault("availability", {}).setdefault("shipToLocationAvailability", {})[
                        "quantity"] = int(ch["available"])
                self.call("PUT", f"/sell/inventory/v1/inventory_item/{q}", body)
            if "price" in ch or "available" in ch:
                o = {"offerId": off["offerId"],
                     "availableQuantity": int(ch.get("available", off.get("availableQuantity") or 1))}
                if "price" in ch:
                    o["price"] = {"value": f"{float(ch['price']):.2f}", "currency": "USD"}
                d = self.call("POST", "/sell/inventory/v1/bulk_update_price_quantity",
                              {"requests": [{"sku": sku, "offers": [o]}]})
                for r in d.get("responses") or []:
                    if int(r.get("statusCode") or 200) >= 400:
                        raise EbayError("eBay did not take the change: " + "; ".join(
                            e.get("message", "") for e in r.get("errors") or []))
            if {"best_offer", "auto_accept", "auto_decline"} & set(ch):
                full = self.get_offer(off["offerId"])
                body = {k: v for k, v in full.items() if k not in ("offerId", "status", "listing")}
                pol = body.setdefault("listingPolicies", {})
                bo = {"bestOfferEnabled": bool(ch.get("best_offer", True))}
                if bo["bestOfferEnabled"] and ch.get("auto_accept"):
                    bo["autoAcceptPrice"] = {"value": f"{float(ch['auto_accept']):.2f}", "currency": "USD"}
                if bo["bestOfferEnabled"] and ch.get("auto_decline"):
                    bo["autoDeclinePrice"] = {"value": f"{float(ch['auto_decline']):.2f}", "currency": "USD"}
                pol["bestOfferTerms"] = bo
                self.call("PUT", f"/sell/inventory/v1/offer/{off['offerId']}", body)
            return
        # listed anywhere else: price and quantity together, then the rest in one revise
        if "price" in ch or "available" in ch:
            inner = f"<ItemID>{item_id}</ItemID>"
            if "price" in ch:
                inner += f"<StartPrice>{float(ch['price']):.2f}</StartPrice>"
            if "available" in ch:
                inner += f"<Quantity>{int(ch['available'])}</Quantity>"
            self.trading("ReviseInventoryStatus", f"<InventoryStatus>{inner}</InventoryStatus>")
        parts = ""
        if "title" in ch:
            parts += f"<Title>{xml_escape(ch['title'][:80])}</Title>"
        if "condition" in ch and ch["condition"] in _listing.CONDITIONS:
            parts += ("<ConditionID>4000</ConditionID><ConditionDescriptors><ConditionDescriptor><Name>40001</Name>"
                      f"<Value>{_listing.CONDITIONS[ch['condition']][2]}</Value></ConditionDescriptor>"
                      "</ConditionDescriptors>")
        if {"best_offer", "auto_accept", "auto_decline"} & set(ch):
            on = bool(ch.get("best_offer", True))
            parts += f"<BestOfferDetails><BestOfferEnabled>{'true' if on else 'false'}</BestOfferEnabled></BestOfferDetails>"
            if on and (ch.get("auto_accept") or ch.get("auto_decline")):
                parts += "<ListingDetails>"
                if ch.get("auto_accept"):
                    parts += f"<BestOfferAutoAcceptPrice>{float(ch['auto_accept']):.2f}</BestOfferAutoAcceptPrice>"
                if ch.get("auto_decline"):
                    parts += f"<MinimumBestOfferPrice>{float(ch['auto_decline']):.2f}</MinimumBestOfferPrice>"
                parts += "</ListingDetails>"
        if parts:
            self.trading("ReviseFixedPriceItem", f"<Item><ItemID>{item_id}</ItemID>{parts}</Item>")

    def end_listing(self, item_id: str, sku: str) -> None:
        """Takes a listing down: CardCrop's by withdrawing its offer (it can be published again
        from List), others by ending the listing."""
        off = None
        if sku:
            try:
                off = self.offer_for(sku)
            except EbayError:
                off = None
        if off and off.get("status") == "PUBLISHED":
            self.call("POST", f"/sell/inventory/v1/offer/{off['offerId']}/withdraw")
        else:
            self.trading("EndFixedPriceItem", f"<ItemID>{item_id}</ItemID><EndingReason>NotAvailable</EndingReason>")

    def change_price(self, item_id: str, sku: str, price: float) -> None:
        """Any listing's price, however it was made: CardCrop's through its offer (eBay will not let
        the Trading API revise those), every other listing through a revise of the listing."""
        off = None
        if sku:
            try:
                off = self.offer_for(sku)
            except EbayError:
                off = None
        if off:
            self.set_price(sku, price)
        elif item_id:
            self.revise_price(item_id, price)
        else:
            raise EbayError("This card has no eBay listing yet")

    def get_offer(self, offer_id: str) -> dict:
        return self.call("GET", f"/sell/inventory/v1/offer/{offer_id}")

    def _clean_item(self, offer_id: str) -> bool:
        """Rewrites an unpublished listing's title and item specifics without the symbols eBay refuses.
        True when something changed."""
        sku = self.get_offer(offer_id).get("sku", "")
        if not sku:
            return False
        item = self.call("GET", f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku)}")
        prod = dict(item.get("product") or {})
        title = _safe(prod.get("title", ""))[:80]
        aspects = {k: [_safe(x) for x in v if _safe(x)] for k, v in (prod.get("aspects") or {}).items()}
        if title == prod.get("title") and aspects == prod.get("aspects"):
            return False
        prod.update(title=title, aspects={k: v for k, v in aspects.items() if v})
        body = _put_body(item)
        body["product"] = prod
        self.call("PUT", f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku)}", body)
        return True

    def publish(self, offer_id: str) -> str:
        """Puts an offer live. eBay's servers sometimes answer 'System error, try again later'
        (error 25002 with HTTP 500); that is retried, but only after checking the offer did
        not in fact go live, so a listing is never published twice."""
        last = None
        cleaned = False
        for attempt in range(4):
            try:
                return self.call("POST", f"/sell/inventory/v1/offer/{offer_id}/publish")["listingId"]
            except EbayError as e:
                if "25019" in {str(i) for i in e.ids()} and not cleaned:
                    # a title or item specific with a symbol eBay refuses (♀, ★, ™): written out, then again
                    cleaned = True
                    if self._clean_item(offer_id):
                        continue
                transient = (e.status or 0) >= 500 or e.status == 429 or "25002" in {str(i) for i in e.ids()} \
                    and "try again" in str(e).lower()
                if not transient or attempt == 3:
                    raise
                last = e
            time.sleep((3, 8, 20)[attempt])
            try:
                off = self.get_offer(offer_id)
                if off.get("status") == "PUBLISHED":
                    lid = (off.get("listing") or {}).get("listingId")
                    if lid:
                        return lid
            except EbayError:
                pass
            _log([f"retrying publish of offer {offer_id} after {last} (attempt {attempt + 2})"])
        raise last

    def delete_offer(self, offer_id: str):
        self.call("DELETE", f"/sell/inventory/v1/offer/{offer_id}")

    def delete_item(self, sku: str):
        """Removes an inventory item and its offers. Only for one that was never published:
        on a live one this would end the listing."""
        self.call("DELETE", f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku, safe='')}")


def forget_record(out_dir: str, sku: str):
    allr = load_records(out_dir)
    if allr.pop(sku, None) is not None:
        with open(record_path(out_dir), "w", encoding="utf-8") as f:
            json.dump(allr, f, ensure_ascii=False, indent=2)


def submit_drafts_file(client: "Client", csv_path: str, progress=None, timeout: float = 600) -> dict:
    """Hands a filled Create new drafts file to eBay's Feed API (feed type FX_LISTING),
    exactly what Seller Hub's Upload template button does, then waits for eBay to
    process it. Returns {'status', 'ok', 'failed', 'task_id', 'errors'}."""
    say = progress or (lambda m: None)
    say("Sending the drafts file to eBay…")
    hdr = {"X-EBAY-C-MARKETPLACE-ID": MARKETPLACE}
    r = client.call("POST", "/sell/feed/v1/task", {"schemaVersion": "1.0", "feedType": "FX_LISTING"}, headers=hdr)
    loc = r.get("_location", "")
    task_id = loc.rstrip("/").rsplit("/", 1)[-1] if loc else r.get("taskId", "")
    if not task_id:
        raise EbayError("eBay did not return a task for the drafts file")
    with open(csv_path, "rb") as f:
        data = f.read()
    name = os.path.basename(csv_path)
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("fileName", name), ("name", "file"), ("type", "form-data")):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                 f"Content-Type: text/csv\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"{API}/sell/feed/v1/task/{task_id}/upload_file", data=b"".join(parts), method="POST",
        headers={"Authorization": f"Bearer {client.access_token()}", "Accept": "application/json",
                 "Content-Type": f"multipart/form-data; boundary={boundary}", **hdr})
    client._send(req, timeout=180)
    say("eBay is processing the drafts…")
    t0, status, d = time.time(), "", {}
    while time.time() - t0 < timeout:
        d = client.call("GET", f"/sell/feed/v1/task/{task_id}", headers=hdr)
        status = d.get("status", "")
        if status in ("COMPLETED", "COMPLETED_WITH_ERROR", "FAILED"):
            break
        time.sleep(4)
    summary = d.get("uploadSummary") or {}
    out = {"status": status or "TIMED_OUT", "task_id": task_id,
           "ok": int(summary.get("successCount", 0) or 0), "failed": int(summary.get("failureCount", 0) or 0),
           "errors": ""}
    if status in ("COMPLETED_WITH_ERROR", "FAILED") or out["failed"]:
        out["errors"] = _feed_errors(client, task_id, hdr)
    return out


def _feed_errors(client, task_id, hdr) -> str:
    """eBay's result file for a task: a CSV (often zipped) with a reason per failed row."""
    try:
        req = urllib.request.Request(f"{API}/sell/feed/v1/task/{task_id}/download_result_file",
                                     headers={"Authorization": f"Bearer {client.access_token()}", **hdr})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except Exception as e:  # noqa: BLE001
        return f"(could not fetch eBay's result file: {e})"
    if raw[:2] == b"PK":
        import zipfile
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            raw = b"\n".join(z.read(n) for n in z.namelist())
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    txt = raw.decode("utf-8", "replace")
    _log([f"Feed task {task_id} result:", txt[:6000]])
    return txt[:3000]


def _jpeg_for_ebay(path: str) -> tuple[bytes, str]:
    """eBay limits file size and dimensions, and 16-bit PNGs of a 26 MP card are far
    over; a high-quality JPEG at 4000 px is indistinguishable on eBay."""
    import cv2
    import numpy as np
    from engine import imread, to8
    img = imread(path)
    h, w = img.shape[:2]
    k = min(1.0, UPLOAD_LONG_EDGE / max(h, w))
    if k < 1:
        from engine import to_float
        f = cv2.resize(to_float(img), None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        if k < 0.75:
            # output sharpening for the size it is seen at: a downsized photo loses edge contrast, and
            # a light, fine unsharp mask at the final size puts it back (print sharpening does the same)
            blur = cv2.GaussianBlur(f, (0, 0), 0.65)
            f = np.clip(f + (f - blur) * 0.6, 0, 1)
        img = to8(f)
    else:
        img = to8(img)
    q = 95
    while True:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q,
                                             cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444])
        if not ok:
            raise EbayError(f"Could not prepare {os.path.basename(path)} for upload")
        if len(buf) <= 11_500_000 or q <= 70:
            break
        q -= 7
    return buf.tobytes(), os.path.splitext(os.path.basename(path))[0] + ".jpg"


def listing_photos(folder: str) -> list[str]:
    """A card folder's photos in listing order (CardCrop numbers them 01 hero, 02 front...),
    leaving out the Instagram slides and text files."""
    exts = (".png", ".jpg", ".jpeg", ".tif", ".tiff")
    files = [f for f in os.listdir(folder) if f.lower().endswith(exts) and not f.startswith(".")]
    return [os.path.join(folder, f) for f in sorted(files)][:MAX_PHOTOS]


# ------------------------------------------------------------------ local record of uploads
def record_path(out_dir: str) -> str:
    return os.path.join(out_dir, "ebay_uploads.json")


def load_records(out_dir: str) -> dict:
    try:
        with open(record_path(out_dir), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_record(out_dir: str, sku: str, rec: dict, replace: bool = False):
    allr = load_records(out_dir)
    allr[sku] = dict(rec) if replace else {**allr.get(sku, {}), **rec}
    os.makedirs(out_dir, exist_ok=True)
    with open(record_path(out_dir), "w", encoding="utf-8") as f:
        json.dump(allr, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ price suggestion
def _round_price(v: float) -> float:
    """Shop-style pricing: 14.62 becomes 13.99, small prices keep their cents."""
    import math
    if v >= 3:                      # 16.99 stays 16.99; 17.40 becomes 16.99
        return max(0.99, math.floor(v + 0.011) - 0.01)
    return round(v, 2)


def suggest_price(client, db, info: dict, own=None, pc_token: str = "") -> dict:
    """Fetched live, every time. Two kinds of evidence:

    what the card SOLD for: your own sales of this exact card (own, from the sales ledger), then
    PriceCharting's ungraded value when you have a token, then TCGplayer's market price, all three
    worked out from completed sales;
    what it is LISTED for: eBay's current fixed-price, ungraded asks for the same number.

    The suggestion starts from the best sold figure. When eBay has three or more comparable
    listings and their lower quarter is under it, it meets that lower quarter so yours is not the
    dear one, unless that is under 70% of the sold figure (then those asks are more likely wrong
    printings or bait than the going rate). With no sold figure it falls back to eBay alone."""
    import prices as _prices
    import sales as _sales
    out = {"suggested": None, "basis": "", "ebay": None, "tcgplayer": None, "cardmarket": None,
           "own": _sales.summary(list(own or [])), "pricecharting": None, "error": ""}
    name, number = info.get("name_en") or info.get("name", ""), str(info.get("number", ""))
    total = str(info.get("set_total", ""))
    query = f"{name} {number}/{total}" if total else f"{name} {number}"
    if str(info.get("id", "")).startswith("manual:"):
        # a card in no database: search the way it was described; sellers often leave the number out
        query = " ".join(x for x in (name, info.get("set_name", ""), info.get("rarity", "")) if x)
        number = ""
    if info.get("language") == "ja":
        query += " Japanese"
    must, must_not = version_words(db, info)
    if client is not None and client.app_id and client.cert_id:
        try:
            got = client.live_listings(query, number, must=must, must_not=must_not)
            if got:
                n = len(got)
                out["ebay"] = {"count": n, "low": got[0], "median": got[n // 2],
                               "q1": got[max(0, (n - 1) // 4)], "query": query}
        except Exception as e:  # noqa: BLE001
            out["error"] = f"eBay search failed: {e}"
    try:
        m = db.market(info["id"], info.get("language", "en")) if info.get("id") else {}
        out["tcgplayer"], out["cardmarket"] = m.get("tcgplayer"), m.get("cardmarket")
    except Exception as e:  # noqa: BLE001
        out["error"] = (out["error"] + "; " if out["error"] else "") + f"price database failed: {e}"
    if pc_token:
        try:
            out["pricecharting"] = _prices.pricecharting(pc_token, info)
        except Exception as e:  # noqa: BLE001
            out["error"] = (out["error"] + "; " if out["error"] else "") + f"PriceCharting failed: {e}"
    sold, sold_basis = None, ""
    o, pc, t = out["own"], out["pricecharting"], out["tcgplayer"]
    if o and o["count"] >= 2:
        sold, sold_basis = o["median"], f"your last {o['count']} sales of this card"
    elif o:
        sold, sold_basis = o["last"], "what it last sold for in your store"
    elif pc and pc.get("loose"):
        sold, sold_basis = pc["loose"], "PriceCharting ungraded (from sold listings)"
    elif t and t.get("market"):
        sold, sold_basis = t["market"], "TCGplayer market (from recent sales)"
    out["sold_ref"] = sold
    e = out["ebay"]
    if sold:
        if e and e["count"] >= 3 and 0.7 * sold <= e["q1"] < sold:
            out["suggested"] = _round_price(e["q1"])
            out["basis"] = f"{sold_basis} ${sold:.2f}, met to the lower quarter of {e['count']} eBay listings"
        else:
            out["suggested"], out["basis"] = _round_price(sold), sold_basis
    elif e and e["count"] >= 3:
        out["suggested"], out["basis"] = _round_price(e["q1"]), f"lower quarter of {e['count']} eBay listings"
    elif e:
        out["suggested"], out["basis"] = _round_price(e["low"]), f"lowest of {e['count']} eBay listing(s)"
    return out


# One Piece versions, as sellers write them in titles (patterns run on lower-case words)
_OP_WORDS = {"Alt Art": [r" alt art", r" alternate", r" parallel", r" aa "], "Manga": [r" manga"],
             "SP": [r" sp ", r" special card"], "Wanted Poster": [r" wanted"], "Gold": [r" gold"],
             "Treasure Rare": [r" treasure", r" tr "], "Super Alt Art": [r" super alt", r" red super",
                                                                         r" super parallel"]}


def version_words(db, info: dict) -> tuple[list, list]:
    """Title words that a comparable listing must have, and words it must not have, so prices for a
    QCSR are not mixed with the Ultra Rare of the same code, or a Manga with the regular print."""
    game = info.get("game") or "pokemon"
    if game == "onepiece":
        own = [v for v in _OP_WORDS if v in (info.get("variant") or "")]
        must = [w for v in own for w in _OP_WORDS[v]]
        # a manga or SP card is often also called alt art; only the regular print excludes that
        keep_alt = bool(own)
        must_not = [w for v, ws in _OP_WORDS.items() if v not in own and not (keep_alt and v == "Alt Art")
                    for w in ws]
        if "Gold" not in own and "SP" in own:
            must_not += _OP_WORDS["Gold"]
        return must, must_not
    if game == "yugioh":
        import identify as _identify
        r = (info.get("rarity") or "").lower()
        siblings = set()
        try:
            siblings = {x.rarity.lower() for x in db.ygo_search(info.get("number", ""))}
        except Exception:  # noqa: BLE001
            pass
        siblings.discard(r)
        if not siblings:                     # only one printing has this code: the code says it all
            return [], []
        own = _identify.YGO_WORDS.get(r, [])
        must = [rf" {re.escape(w)}" for w in own] if r not in ("common", "rare", "super rare", "short print") else []
        must_not = []
        for s in siblings:
            for w in _identify.YGO_WORDS.get(s, []):
                if w not in r and not any(w in o or o in w for o in own):
                    must_not.append(rf" {re.escape(w)}")
        return must, must_not
    return [], []


def price_summary(r: dict) -> str:
    bits = []
    if r.get("suggested"):
        bits.append(f"<b>Suggested ${r['suggested']:.2f}</b> ({r['basis']})")
    e = r.get("ebay")
    if e:
        bits.append(f"eBay now: {e['count']} listed, low ${e['low']:.2f}, median ${e['median']:.2f}")
    o = r.get("own")
    if o:
        bits.append(f"Your sales: {o['count']}, median ${o['median']:.2f}, last ${o['last']:.2f}")
    pc = r.get("pricecharting")
    if pc:
        bits.append(f"PriceCharting ungraded ${pc['loose']:.2f}")
    t = r.get("tcgplayer")
    if t:
        bits.append(f"TCGplayer ${t['market']:.2f} ({t.get('updated', '')})")
    c = r.get("cardmarket")
    if c:
        bits.append(f"Cardmarket €{c['trend']:.2f}")
    if not bits:
        bits.append("No price data found for this card")
    if r.get("error"):
        bits.append(r["error"])
    return "  ·  ".join(bits)


def guess_carrier(tracking: str) -> str:
    """The carrier a tracking number belongs to, from its shape."""
    t = tracking.replace(" ", "").upper()
    if t.startswith("1Z") and len(t) == 18:
        return "UPS"
    if t.isdigit() and len(t) in (20, 22, 26, 30, 34) or (len(t) == 13 and t[:2].isalpha() and t.endswith("US")):
        return "USPS"
    if t.isdigit() and len(t) in (12, 15):
        return "FedEx"
    if t.isdigit() and len(t) == 10:
        return "DHL"
    return "USPS"


def market_of(r) -> float | None:
    """The card's market price from a price check: TCGplayer's market price where there is one, else the
    median eBay asking price, else the suggestion."""
    r = r or {}
    t, e = r.get("tcgplayer") or {}, r.get("ebay") or {}
    for v in (t.get("market"), e.get("median"), r.get("suggested")):
        try:
            if v and float(v) > 0:
                return round(float(v), 2)
        except (TypeError, ValueError):
            continue
    return None


def price_shortcut(kind: str, current: float, market: float | None) -> float | None:
    """The price quick buttons: the market and 10% or 25% over it, or the price rounded up to the dollar
    (the market's, when no price is set yet)."""
    import math
    if kind in ("m0", "m10", "m25"):
        if not market:
            return None
        return round(market * {"m0": 1.0, "m10": 1.10, "m25": 1.25}[kind] + 1e-9, 2)
    if kind == "ceil":
        base = current if current and current > 0 else (market or 0)
        if not base:
            return None
        return float(math.ceil(round(base, 2) - 1e-9)) if abs(base - round(base)) > 0.004 else float(round(base))
    return None

