"""Your own sales, kept for good.

eBay only hands back the last 60 days of sales, so every Store refresh is merged into a ledger
on disk (sales.json beside the other CardCrop data). Pricing reads it for what this exact card
sold for in your store, and Store and Reports read it for what sold, when and for how much,
however long ago."""
from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime

import identify


def ledger_path() -> str:
    return os.path.join(identify._cache_dir(), "sales.json")


def load() -> dict:
    try:
        with open(ledger_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _key(s: dict) -> str:
    return f"{s.get('id', '')}|{s.get('date', '')}|{s.get('buyer', '')}"


def merge(sold: list) -> int:
    """Adds sales not seen before; returns how many were new. Written all or nothing."""
    led = load()
    new = 0
    for s in sold or []:
        k = _key(s)
        if not s.get("id") or k in led:
            if k in led:                         # paid and shipped change after the sale
                led[k].update({x: s[x] for x in ("paid", "shipped") if x in s})
            continue
        led[k] = {x: s.get(x) for x in ("id", "title", "sku", "price", "date", "buyer", "qty", "paid",
                                        "shipped", "image", "url")}
        new += 1
    p = ledger_path()
    try:
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(led, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass
    return new


def _when(s: dict) -> float:
    try:
        return datetime.fromisoformat(str(s.get("date", "")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def entries(days: int | None = None) -> list:
    """Every sale, newest first; only the last `days` days when given."""
    cut = time.time() - days * 86400 if days else 0
    out = [s for s in load().values() if _when(s) >= cut]
    out.sort(key=_when, reverse=True)
    return out


def unit_prices(sku: str, days: int = 180) -> list:
    """What one copy of this card sold for in your store (item plus postage as the buyer paid),
    newest first."""
    if not sku:
        return []
    out = []
    for s in entries(days):
        if (s.get("sku") or "") == sku:
            q = max(1, int(s.get("qty") or 1))
            try:
                out.append(round(float(s.get("price") or 0) / q, 2))
            except (TypeError, ValueError):
                continue
    return [p for p in out if p > 0]


def summary(prices: list) -> dict | None:
    if not prices:
        return None
    return {"count": len(prices), "median": round(statistics.median(prices), 2), "last": prices[0],
            "low": min(prices), "high": max(prices)}


def since(days: int) -> dict:
    """Totals for the Store and Reports pages: sales, copies and money over the last `days` days."""
    es = entries(days)
    return {"sales": len(es), "copies": sum(max(1, int(s.get("qty") or 1)) for s in es),
            "total": round(sum(float(s.get("price") or 0) for s in es), 2)}
