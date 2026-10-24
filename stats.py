"""Tracking: what has gone through CardCrop, read back from the output folder itself.

Every exported card leaves a folder with its photos and a saved listing, and every
eBay upload leaves a record, so the history needs no separate log: it is rebuilt
from those files whenever the Tracking page opens, and it covers cards exported
before tracking existed."""
from __future__ import annotations

import datetime as dt
import json
import os
import re

PHOTO_RE = re.compile(r"_(\d{2})_(front|back)(?:_[A-Z]{2})?(?:_(NM|LP|MP|HP|DMG))?\.\w+$")
MAIN_PHOTO_RE = re.compile(r"_(0[23])_(front|back)(?:_(NM|LP|MP|HP|DMG))?\.\w+$")

PRICE_BUCKETS = [("< $1", 0, 1), ("$1–5", 1, 5), ("$5–10", 5, 10), ("$10–25", 10, 25),
                 ("$25–50", 25, 50), ("$50–100", 50, 100), ("$100+", 100, 10 ** 9)]
CONDITIONS = ["NM", "LP", "MP", "HP", "DMG"]

# Pokémon eras from the set code (TCGdex ids, English and Japanese)
_ERAS = [
    (r"^(base|gym|neo|lc|si|ecard|bsp|wp|pmcg|vs|web)", "WotC"),
    (r"^(ex|pop|np)", "EX"),
    (r"^(dp|pl|hgss|col|ru|dpp|hsp|lv|pt|l\d|dpt)", "DP to HGSS"),
    (r"^(bw|bwp|bw\d|ebb|lgs)", "Black & White"),
    (r"^(xy|g1|xyp|cp\d|ma|xy\d)", "XY"),
    (r"^(sm|smp|det|sma|sm\d)", "Sun & Moon"),
    (r"^(swsh|s\d|sp\d|swshp|cel|pgo|s-p|sc\d)", "Sword & Shield"),
    (r"^(sv|svp|svhm|sm\d?k)", "Scarlet & Violet"),
    (r"^(me|m\d|mep|mc)", "Mega Evolution"),
]


def era_of(info: dict) -> str:
    game = (info or {}).get("game") or "pokemon"
    if game == "yugioh":
        return "Yu-Gi-Oh!"
    if game == "onepiece":
        return "One Piece"
    sid = ((info or {}).get("set_id") or "").lower()
    for pat, name in _ERAS:
        if re.match(pat, sid):
            return name
    y = str((info or {}).get("year") or "")
    if y.isdigit():
        y = int(y)
        for lo, name in ((2023, "Scarlet & Violet"), (2020, "Sword & Shield"), (2017, "Sun & Moon"),
                         (2014, "XY"), (2011, "Black & White"), (2007, "DP to HGSS"), (2003, "EX"),
                         (1996, "WotC")):
            if y >= lo:
                return name
    return "Other" if sid or y else "Unidentified"


def _day(ts: float) -> str:
    return dt.date.fromtimestamp(ts).isoformat()


def collect(out_dir: str, prices: dict | None = None, records: dict | None = None) -> list[dict]:
    """One entry per card folder: when it was shot, how many photos, game, language,
    era, grade, price and eBay state."""
    prices, records = prices or {}, records or {}
    cards = []
    try:
        entries = [e for e in os.scandir(out_dir) if e.is_dir()]
    except OSError:
        return []
    for e in entries:
        try:
            files = os.listdir(e.path)
        except OSError:
            continue
        photos = [f for f in files if PHOTO_RE.search(f)]
        mains = [f for f in files if MAIN_PHOTO_RE.search(f)]
        lj = next((f for f in files if f.endswith("_listing.json")), None)
        if not mains and not lj:
            continue
        L = {}
        if lj:
            try:
                with open(os.path.join(e.path, lj), encoding="utf-8") as fh:
                    L = json.load(fh)
            except (OSError, ValueError):
                L = {}
        times = []
        for f in mains or [lj]:
            try:
                times.append(os.path.getmtime(os.path.join(e.path, f)))
            except OSError:
                pass
        if not times:
            continue
        photo_days = {}
        for f in mains:
            try:
                d = _day(os.path.getmtime(os.path.join(e.path, f)))
            except OSError:
                continue
            photo_days[d] = photo_days.get(d, 0) + 1
        info = L.get("info") or {}
        cond = L.get("condition") or ""
        if not cond:
            m = next((MAIN_PHOTO_RE.search(f) for f in mains if MAIN_PHOTO_RE.search(f).group(3)), None)
            cond = m.group(3) if m else ""
        name = e.name
        sku = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:50] or "card"
        rec = records.get(sku) or {}
        price = L.get("price") or prices.get(name) or rec.get("price") or 0
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = 0.0
        status = ("live" if rec.get("status") == "published" else "unpublished" if rec.get("offer_id")
                  else "draft" if rec.get("drafted") else "")
        cards.append({
            "name": name, "day": _day(min(times)), "photo_days": photo_days, "photos": len(photos),
            "game": info.get("game") or "pokemon", "lang": info.get("language") or ("en" if info else ""),
            "era": era_of(info) if info else "Unidentified", "cond": cond, "price": price,
            "status": status, "rarity": info.get("rarity") or "", "identified": bool(info),
            "published_day": (rec.get("published") or "")[:10],
        })
    return cards


def summarize(cards: list[dict], days: int | None = None, today: dt.date | None = None) -> dict:
    """Counts for the Tracking page; days limits the distributions to the last N days."""
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days - 1)).isoformat() if days else ""
    sel = [c for c in cards if not since or c["day"] >= since]
    per_day_cards, per_day_photos = {}, {}
    for c in cards:
        per_day_cards[c["day"]] = per_day_cards.get(c["day"], 0) + 1
        for d, n in c["photo_days"].items():
            per_day_photos[d] = per_day_photos.get(d, 0) + n
    t = today.isoformat()
    week = (today - dt.timedelta(days=6)).isoformat()
    streak = 0
    d = today
    while per_day_cards.get(d.isoformat()):
        streak += 1
        d -= dt.timedelta(days=1)

    def count(key, order=None):
        out = {}
        for c in sel:
            k = c[key] or "Not set"
            out[k] = out.get(k, 0) + 1
        if order:
            return [(k, out.get(k, 0)) for k in order] + [(k, v) for k, v in out.items() if k not in order]
        return sorted(out.items(), key=lambda kv: -kv[1])

    buckets = [(label, sum(1 for c in sel if c["price"] > 0 and lo <= c["price"] < hi)) for label, lo, hi
               in PRICE_BUCKETS]
    priced = [c["price"] for c in sel if c["price"] > 0]
    langs = {"English": sum(1 for c in sel if c["lang"] == "en"),
             "Japanese": sum(1 for c in sel if c["lang"] == "ja")}
    games = {"Pokémon": sum(1 for c in sel if c["game"] == "pokemon" and c["identified"]),
             "Yu-Gi-Oh!": sum(1 for c in sel if c["game"] == "yugioh"),
             "One Piece": sum(1 for c in sel if c["game"] == "onepiece")}
    status = {k: sum(1 for c in sel if c["status"] == k) for k in ("live", "unpublished", "draft")}
    best = max(per_day_cards.values()) if per_day_cards else 0
    return {
        "cards": len(sel), "all_cards": len(cards),
        "today_cards": per_day_cards.get(t, 0), "today_photos": per_day_photos.get(t, 0),
        "week_cards": sum(n for d_, n in per_day_cards.items() if d_ >= week),
        "streak": streak, "best_day": best,
        "per_day_cards": per_day_cards, "per_day_photos": per_day_photos,
        "conditions": count("cond", CONDITIONS + ["Not set"]),
        "eras": count("era"), "langs": langs, "games": games, "buckets": buckets,
        "value": sum(priced), "avg": (sum(priced) / len(priced)) if priced else 0.0,
        "median": sorted(priced)[len(priced) // 2] if priced else 0.0,
        "status": status,
        "live_value": sum(c["price"] for c in sel if c["status"] == "live"),
    }
