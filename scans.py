"""Price checks kept for good: every card photographed on the phone's Check tab, with what it was read as,
the candidates, the card you picked and what it was worth that day.

Stored beside CardCrop's other lasting data in ~/Library/Application Support/CardCrop/scans (index.json and
one small JPEG per check), never inside the app, so building CardCrop again, updating it or moving the
app leaves every check where it was."""
from __future__ import annotations

import json
import os
import threading
import time

import identify

KEEP = 5000
_lock = threading.Lock()


def folder() -> str:
    d = os.path.join(identify._cache_dir(), "scans")
    os.makedirs(d, exist_ok=True)
    return d


def _index_path() -> str:
    return os.path.join(folder(), "index.json")


def _load() -> list:
    try:
        with open(_index_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(rows: list) -> None:
    tmp = _index_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    os.replace(tmp, _index_path())          # never a half-written index, even if the Mac sleeps mid-save


def add(sid: str, jpeg: bytes, results: list, read: str = "") -> dict:
    """A new check: its straightened picture and every candidate (as CardInfo dicts, so it can be
    priced again later without the photo being read again)."""
    rec = {"id": sid, "at": time.time(), "read": read, "results": [r.to_dict() for r in results],
           "pick": 0 if results else None, "price": None}
    if jpeg:
        with open(os.path.join(folder(), f"{sid}.jpg"), "wb") as f:
            f.write(jpeg)
    with _lock:
        rows = _load()
        rows.insert(0, rec)
        for old in rows[KEEP:]:
            _drop_file(old["id"])
        _save(rows[:KEEP])
    return rec


def update(sid: str, **ch) -> dict | None:
    with _lock:
        rows = _load()
        for r in rows:
            if r["id"] == sid:
                r.update(ch)
                _save(rows)
                return r
    return None


def get(sid: str) -> dict | None:
    return next((r for r in _load() if r["id"] == sid), None)


def results(rec: dict) -> list:
    out = []
    for d in rec.get("results") or []:
        try:
            out.append(identify.CardInfo(**d))
        except TypeError:
            continue
    return out


def image(sid: str) -> bytes:
    try:
        with open(os.path.join(folder(), f"{sid}.jpg"), "rb") as f:
            return f.read()
    except OSError:
        return b""


def delete(sid: str) -> None:
    with _lock:
        rows = [r for r in _load() if r["id"] != sid]
        _save(rows)
    _drop_file(sid)


def _drop_file(sid: str) -> None:
    try:
        os.remove(os.path.join(folder(), f"{sid}.jpg"))
    except OSError:
        pass


def summary(rec: dict) -> dict:
    """What a list of checks shows: the picked card's name, the price and when."""
    res = rec.get("results") or []
    pick = rec.get("pick")
    card = res[pick] if isinstance(pick, int) and 0 <= pick < len(res) else None
    name = ""
    if card:
        name = card.get("name_en") or card.get("name") or ""
        num = card.get("number", "")
        if num:
            name += f" {num}" + (f"/{card['set_total']}" if card.get("set_total") and "/" not in num else "")
    p = rec.get("price") or {}
    return {"id": rec["id"], "at": rec["at"], "name": name or (rec.get("read") or "Not identified"),
            "set": (card or {}).get("set_name_en") or (card or {}).get("set_name", ""),
            "price": p.get("suggested"), "basis": p.get("basis", "")}


def page(n: int = 0, size: int = 20, q: str = "") -> dict:
    rows = _load()
    q = q.strip().lower()
    items = [summary(r) for r in rows]
    if q:
        items = [x for x in items if q in (x["name"] + " " + x["set"]).lower()]
    pages = max(1, -(-len(items) // size))
    n = max(0, min(pages - 1, n))
    return {"page": n, "pages": pages, "total": len(items), "rows": items[n * size:(n + 1) * size]}
