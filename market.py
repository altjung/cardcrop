"""Market watch: what your cards are worth today against what you ask for them.

A scan prices every identified card in the output folder the same way the price
suggestion does (eBay's live asking prices for that exact card, TCGplayer's market
price, which TCGplayer works out from its recent sales, and Cardmarket's sold
averages) and keeps one snapshot per card per day. Day-to-day changes come from
those snapshots; until there are two days of them, Cardmarket's 1-day against
7-day sold average stands in."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time

import ebay
import identify
import stats

KEEP_DAYS = 120


def _history_path():
    return os.path.join(identify._cache_dir(), "market_history.json")


def load_history() -> dict:
    try:
        with open(_history_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_history(h: dict) -> None:
    tmp = _history_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f)
    os.replace(tmp, _history_path())


def _sku(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:50] or "card"


# ---------------------------------------------------------- listings made outside CardCrop
_NOISE = re.compile(r"\b(pok[eé]mon|tcg|card|cards|holo|reverse|rare|ultra|secret|full art|alt art|nm|lp|mp|hp|dmg|"
                    r"near mint|mint|english|promo|pop|black star|1st edition|unlimited|shadowless|foil|single|"
                    r"illustration|special|double|hyper|art)\b", re.I)
_NUM = re.compile(r"(?<![A-Za-z0-9])#?([A-Z]{0,4}\d{1,3}[a-z]?)\s*/\s*([A-Z]{0,4}\d{1,3})(?![0-9])", re.I)
_PROMO = re.compile(r"\b((?:SWSH|SM|XY|BW|DP|HGSS|SVP?|SV)\s?-?\d{2,3})\b", re.I)


def _ids_path():
    return os.path.join(identify._cache_dir(), "market_ids.json")


def _load_ids() -> dict:
    try:
        with open(_ids_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def parse_title(title: str) -> dict:
    """Name, number and set size from a listing title such as
    'Dark Ampharos 039/084 Rocket Gang Strikes Back Holo Rare Pokemon'."""
    t = re.sub(r"\s+", " ", title or "").strip()
    lang = "ja" if re.search(r"\b(japanese|japan|jpn)\b", t, re.I) else "en"
    m = _NUM.search(t)
    num = total = ""
    if m:
        num, total = m.group(1), m.group(2)
        head = t[:m.start()]
    else:
        pm = _PROMO.search(t)
        if pm:
            num = pm.group(1).replace(" ", "").replace("-", "")
            head = t[:pm.start()]
        else:
            head = t
    head = re.sub(r"\(.*?\)", " ", head)
    head = _NOISE.sub(" ", head)
    head = re.sub(r"[^\w' &.-]+", " ", head)
    words = [w for w in head.split() if not re.fullmatch(r"\d{4}", w)][:4]
    return {"name": " ".join(words), "number": num, "set_total": total, "language": lang}


def resolve(db, title: str) -> dict:
    """The card a listing title is about: the database's card when name and number agree,
    else just what the title says (eBay prices still work from that)."""
    p = parse_title(title)
    q = f"{p['name']} {p['number']}/{p['set_total']}" if p["set_total"] else f"{p['name']} {p['number']}".strip()
    try:
        found = db.search(q, p["language"]) if q else []
    except Exception:  # noqa: BLE001
        found = []
    want = p["number"].lstrip("0").upper()
    for c in found[:12]:
        if want and str(c.number).lstrip("0").upper() == want:
            d = c.to_dict()
            d["from_title"] = True
            return d
    p["from_title"] = True
    return p


def inventory(out_dir: str, store: dict | None, prices: dict, records: dict) -> list[dict]:
    """Every card you have up for sale: CardCrop's own cards from the output folder, plus every
    other active eBay listing in your store, identified from its title."""
    store = store or {}
    live = {a.get("sku"): a for a in store.get("active", []) if a.get("sku")}
    sold = {a.get("sku") for a in store.get("sold", []) if a.get("sku")}
    out = []
    try:
        entries = sorted((e for e in os.scandir(out_dir) if e.is_dir()), key=lambda e: e.name)
    except OSError:
        return []
    for e in entries:
        try:
            files = os.listdir(e.path)
        except OSError:
            continue
        lj = next((f for f in files if f.endswith("_listing.json")), None)
        if not lj:
            continue
        try:
            with open(os.path.join(e.path, lj), encoding="utf-8") as fh:
                L = json.load(fh)
        except (OSError, ValueError):
            continue
        info = L.get("info") or {}
        if not info.get("id"):
            continue
        sku = _sku(e.name)
        a, rec = live.get(sku), records.get(sku) or {}
        mine = (a or {}).get("price") or prices.get(e.name) or rec.get("price") or L.get("price") or 0
        try:
            mine = float(mine)
        except (TypeError, ValueError):
            mine = 0.0
        status = ("live" if a else "sold" if sku in sold else
                  "unpublished" if rec.get("offer_id") else "exported")
        photo = next((os.path.join(e.path, f) for f in sorted(files) if stats.MAIN_PHOTO_RE.search(f)
                      and "_front" in f), "")
        out.append({"key": e.name, "sku": sku, "info": info, "mine": mine, "status": status,
                    "title": L.get("title") or info.get("name", e.name), "photo": photo,
                    "url": (a or {}).get("url", ""), "item_id": (a or {}).get("id", ""),
                    "image": (a or {}).get("image", "")})
    mine_skus = {x["sku"] for x in out}
    ids = _load_ids()
    for a in store.get("active", []):
        if a.get("sku") and a["sku"] in mine_skus:
            continue
        iid = a.get("id") or ""
        if not iid:
            continue
        out.append({"key": f"ebay-{iid}", "sku": a.get("sku", ""), "info": ids.get(iid) or parse_title(a["title"]),
                    "needs_id": iid not in ids, "mine": float(a.get("price") or 0), "status": "live",
                    "title": a.get("title", ""), "photo": "", "url": a.get("url", ""), "item_id": iid,
                    "image": a.get("image", ""), "outside": True})
    return out


def snapshot(client, db, item: dict) -> dict:
    if item.get("needs_id"):                    # once per listing; remembered afterwards
        item["info"] = resolve(db, item.get("title", ""))
        ids = _load_ids()
        ids[item["item_id"]] = item["info"]
        tmp = _ids_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ids, f)
        os.replace(tmp, _ids_path())
        item["needs_id"] = False
    r = ebay.suggest_price(client, db, item["info"])
    snap = {"d": dt.date.today().isoformat(), "t": time.time(), "sugg": r.get("suggested"),
            "basis": r.get("basis", ""), "err": r.get("error", "")}
    t, c, e = r.get("tcgplayer") or {}, r.get("cardmarket") or {}, r.get("ebay") or {}
    if t.get("market"):
        snap["tcg"] = float(t["market"])
    if c.get("trend"):
        snap["cm"] = float(c["trend"])
    for k in ("avg1", "avg7", "avg30"):
        if c.get(k):
            snap["cm" + k[3:]] = float(c[k])
    if e:
        snap.update(e_n=e.get("count", 0), e_low=e.get("low"), e_q1=e.get("q1"), e_med=e.get("median"))
    return snap


def record(history: dict, key: str, snap: dict) -> None:
    rows = [s for s in history.get(key, []) if s.get("d") != snap["d"]] + [snap]
    rows.sort(key=lambda s: s["d"])
    cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    history[key] = [s for s in rows if s["d"] >= cutoff]


def _ref_key(latest: dict) -> str:
    """The figure changes are measured on: TCGplayer's market price (built from its sales)
    when there is one, else the lower quarter of eBay asking prices, else Cardmarket."""
    for k in ("tcg", "e_q1", "cm"):
        if latest.get(k):
            return k
    return ""


def _change(now, before):
    return (now - before) / before if now and before else None


def analyze(item: dict, rows: list[dict], threshold: float = 0.10, min_dollars: float = 0.50) -> dict:
    """Movement and advice for one card. threshold is a fraction (0.10 = 10%)."""
    out = dict(item, market=None, ref="", day=None, day_basis="", week=None, week_basis="", series=[],
               sugg=None, gap=None, alerts=[], scanned="")
    if not rows:
        return out
    latest = rows[-1]
    ref = _ref_key(latest)
    out["scanned"], out["sugg"], out["ref"] = latest["d"], latest.get("sugg"), ref
    out["basis"] = latest.get("basis", "")
    if not ref:
        return out
    now = latest[ref]
    out["market"] = now
    out["series"] = [s.get(ref) or 0.0 for s in rows[-30:]]
    earlier = [s for s in rows[:-1] if s.get(ref)]
    if earlier:
        prev = earlier[-1]
        out["day"] = _change(now, prev[ref])
        gap_days = (dt.date.fromisoformat(latest["d"]) - dt.date.fromisoformat(prev["d"])).days
        out["day_basis"] = "since yesterday's scan" if gap_days == 1 else f"since the scan {gap_days} days ago"
        wk = (dt.date.fromisoformat(latest["d"]) - dt.timedelta(days=7)).isoformat()
        older = [s for s in earlier if s["d"] <= wk]
        if older:
            out["week"], out["week_basis"] = _change(now, older[-1][ref]), "since a week ago"
    if out["day"] is None and latest.get("cm1") and latest.get("cm7"):
        out["day"], out["day_basis"] = _change(latest["cm1"], latest["cm7"]), "Cardmarket sales: 1-day vs 7-day average"
    if out["week"] is None and latest.get("cm7") and latest.get("cm30"):
        out["week"], out["week_basis"] = _change(latest["cm7"], latest["cm30"]), "Cardmarket sales: 7-day vs 30-day average"

    mine, sugg = item.get("mine") or 0.0, out["sugg"]
    if mine and sugg:
        out["gap"] = (sugg - mine) / mine
        if out["gap"] >= threshold and sugg - mine >= min_dollars:
            out["alerts"].append(("raise", f"Under market: you ask ${mine:,.2f}, the market says ${sugg:,.2f}"))
        elif out["gap"] <= -threshold and mine - sugg >= min_dollars:
            out["alerts"].append(("lower", f"Over market: you ask ${mine:,.2f}, the market says ${sugg:,.2f}"))
    d = out["day"]
    if d is not None and abs(d) >= threshold and abs(now * d) >= min_dollars:
        out["alerts"].append(("up" if d > 0 else "down",
                              f"Market {'up' if d > 0 else 'down'} {abs(d) * 100:.0f}% ({out['day_basis']})"))
    return out


def scan(client, db, items: list[dict], progress=None, cancelled=None) -> dict:
    """Price every card and store today's snapshot. Returns the updated history."""
    history = load_history()
    for i, it in enumerate(items):
        if cancelled and cancelled():
            break
        try:
            record(history, it["key"], snapshot(client, db, it))
        except Exception as e:  # noqa: BLE001
            if progress:
                progress(i + 1, len(items), f"{it['key']}: {e}")
            continue
        if progress:
            progress(i + 1, len(items), it["key"])
        if (i + 1) % 10 == 0:
            save_history(history)
    save_history(history)
    return history
