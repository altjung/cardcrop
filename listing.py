"""Listing drafts: eBay title, item specifics and description for a card,
plus filling eBay's own "Create drafts" bulk template.

eBay's bulk templates change columns over time, so rather than hard-coding a
header we read the template the seller downloads from Seller Hub > Reports >
Upload > Get template (Create drafts, category Pokémon Individual Cards) and
fill whichever columns we recognise. Photos are added when each draft is
finished in Seller Hub, which the drafts template explicitly allows.
"""
from __future__ import annotations

import csv
import html
import json
import os
import re

TITLE_MAX = 80
CATEGORY_ID = "183454"      # eBay US: CCG Individual Cards

RARITY_SHORT = {
    "rare holo": "Holo Rare", "holo rare": "Holo Rare",
    "special illustration rare": "SIR", "illustration rare": "IR",
    "double rare": "Double Rare", "ultra rare": "Ultra Rare", "hyper rare": "Hyper Rare",
    "secret rare": "Secret Rare", "rare holo v": "Holo Rare", "rare holo vmax": "Holo Rare",
    "amazing rare": "Amazing Rare", "radiant rare": "Radiant", "shiny rare": "Shiny Rare",
    "rare": "Rare", "promo": "Promo",
}
# Seller grading shorthand -> (description wording, eBay "Card Condition" value, its eBay value ID).
# eBay's ungraded trading card condition (Condition ID 4000) has four grades, so
# Damaged maps to its lowest one and the description says Damaged outright.
CONDITIONS = {
    # value IDs for Pokémon (category 183454), from eBay's trading card descriptor table;
    # other card categories use 400011-400013 instead, which 183454 rejects
    "NM": ("Near Mint", "Near Mint or Better", "400010"),
    "LP": ("Lightly Played", "Lightly Played (Excellent)", "400015"),
    "MP": ("Moderately Played", "Moderately Played (Very Good)", "400016"),
    "HP": ("Heavily Played", "Heavily Played (Poor)", "400017"),
    "DMG": ("Damaged", "Heavily Played (Poor)", "400017"),
}
UNGRADED_CONDITION_ID = "4000"

SUFFIXES = r"\s+(ex|EX|GX|V|VMAX|VSTAR|V-UNION|LV\.X|BREAK|Prime|LEGEND|δ|Star|☆)$"


# eBay US listings are written in English: anything in Japanese script is translated
# where CardCrop knows the English, and otherwise left out rather than printed
_CJK = re.compile(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")
_CATEGORY_EN = {"ポケモン": "Pokémon", "トレーナーズ": "Trainer", "エネルギー": "Energy",
                "pokemon": "Pokémon", "trainer": "Trainer", "energy": "Energy"}
_RARITY_EN = {"コモン": "Common", "アンコモン": "Uncommon", "レア": "Rare", "ダブルレア": "Double Rare",
              "スーパーレア": "Super Rare", "ウルトラレア": "Ultra Rare", "アートレア": "Art Rare",
              "スペシャルアートレア": "Special Art Rare", "ハイパーレア": "Hyper Rare",
              "シークレットレア": "Secret Rare", "プロモ": "Promo", "キャラクターレア": "Character Rare"}


GAME_WORDS = {   # title words, eBay "Game" and "Manufacturer" for each game
    "pokemon": (("Pokemon", 2), ("TCG", 4), ("Card", 3), "Pokémon TCG", "The Pokémon Company"),
    "yugioh": (("Yu-Gi-Oh!", 1), ("TCG", 4), ("Card", 3), "Yu-Gi-Oh! TCG", "Konami"),
    "onepiece": (("One Piece", 1), ("TCG", 4), ("Card", 3), "One Piece Card Game", "Bandai"),
    "other": (("Trading Card", 2), ("", 9), ("", 9), "", ""),
}


def game_of(info: dict) -> str:
    g = (info or {}).get("game") or "pokemon"
    return g if g in GAME_WORDS else "pokemon"


def has_cjk(t) -> bool:
    return bool(_CJK.search(str(t or "")))


# symbols eBay refuses in titles and item specifics (error 25019: superscript, subscript, ™, ♥, ½, ★),
# spelled out the way sellers write them
_EBAY_WORDS = {"♀": " F", "♂": " M", "★": " Star", "☆": " Star", "◇": " Prism Star", "♢": " Prism Star",
               "½": " 1/2", "¼": " 1/4", "¾": " 3/4", "™": "", "®": "", "©": "", "℠": "",
               "♥": "", "♡": "", "❤": "", "♦": "", "♠": "", "♣": "", "•": " ", "·": " ", "…": "...",
               "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}


def ebay_safe(t) -> str:
    """Text eBay accepts in a title: the gender signs as F and M, a star as Star, fractions written out,
    superscripts and subscripts as plain characters, and other pictographs dropped. Letters with accents
    (Poké) and Greek letters (δ for delta species) stay, since eBay takes those."""
    import unicodedata
    out = []
    for ch in str(t or ""):
        if ch in _EBAY_WORDS:
            out.append(_EBAY_WORDS[ch])
            continue
        cat = unicodedata.category(ch)
        if ch.isascii() or cat.startswith("L") and unicodedata.decomposition(ch)[:7] not in ("<super>", "<sub> "):
            out.append(ch)
            continue
        plain = unicodedata.normalize("NFKC", ch)          # ¹ to 1, ᴱ to E, ＭＡＸ to MAX
        if plain != ch and all(c.isascii() for c in plain):
            out.append(plain)
        elif cat[0] in "LN":
            out.append(ch)
        elif cat[0] == "Z":
            out.append(" ")
        # any other symbol (So, Sm, Sk) is left out
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()


def en(t) -> str:
    """English only: Japanese characters are dropped, and with them any brackets left empty, and only
    characters eBay takes in a title are kept."""
    t = ebay_safe(_CJK.sub(" ", str(t or "")))
    t = re.sub(r"\(\s*\)|\[\s*\]|「\s*」", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ·-–,")


def name_of(info: dict) -> str:
    n = info.get("name_en") or ""
    if n and not has_cjk(n):
        return ebay_safe(n)
    n = info.get("name") or ""
    return "" if has_cjk(n) else ebay_safe(n)


def set_of(info: dict) -> str:
    for k in ("set_name_en", "set_name"):
        v = info.get(k) or ""
        if v and not has_cjk(v):
            return v
    return (info.get("set_id") or "").upper()


def rarity_of(info: dict) -> str:
    r = info.get("rarity") or ""
    return _RARITY_EN.get(r, "" if has_cjk(r) else r)


def needs_english_name(info: dict) -> bool:
    return bool(info) and not name_of(info)


def _character(name: str, category: str) -> str:
    if category and category.lower() not in ("pokemon", "pokémon", "ポケモン"):
        return ""
    n = re.sub(r"^(Dark|Light|Shining|Radiant|Team Rocket's|Mega|M)\s+", "", name)
    n = re.sub(SUFFIXES, "", n)
    return n.split(" & ")[0].strip()


CLEAN_MIN_PRICE = 25.0     # Near Mint cards priced above this get "CLEAN" in the title


def make_title(info: dict, condition: str = "", price: float = 0.0) -> str:
    """Greedy title under 80 characters; least useful words drop first. A Near Mint
    card priced over $25 carries CLEAN, the word buyers search for at that level."""
    name = name_of(info)                  # Japanese cards list under their English name
    num = f"{info.get('number', '')}/{info.get('set_total', '')}".strip("/")
    game = game_of(info)
    r = rarity_of(info)
    if str(info.get("id", "")).startswith("manual:"):
        rar = r                              # typed by you, used as typed (Prism, Holo...)
    elif game == "pokemon":
        rar = RARITY_SHORT.get(r.lower(), "")
    else:                                    # QCSR, Starlight Rare; SEC Manga, SR Alt Art
        import identify as _identify
        rar = _identify.rarity_short({**info, "rarity": r})
    edition = info.get("edition", "") if game == "yugioh" else ""
    w1, w2, w3 = GAME_WORDS[game][:3]
    if str(info.get("id", "")).startswith("manual:"):
        w2 = ("", 9)                         # Carddass and the like are not the trading card game
        if str(info.get("number", "")).isdigit():
            num = f"No. {info['number']}"
    import identify as _id
    lang = _id.LANG_WORD.get(info.get("language", "en"), "")
    parts = [  # (text, priority: lower drops last)
        (name, 0), (num, 0), ("CLEAN" if condition == "NM" and float(price or 0) > CLEAN_MIN_PRICE else "", 1),
        # the printed code already names the set for Yu-Gi-Oh! and One Piece, so rarity outranks it there
        (set_of(info), 1 if game == "pokemon" else 2), (rar, 2 if game == "pokemon" else 1), (lang, 0),
        (edition, 1),
        (info.get("year", "") if str(info.get("id", "")).startswith("manual:") else "", 1),
        (info.get("maker", "") if str(info.get("id", "")).startswith("manual:") else "", 2),
        w1, w2, w3,
        # condition is deliberately absent: the app cannot judge it, and a
        # condition word in the title is a claim the seller has to stand behind
    ]
    parts = [(en(t), p) for t, p in parts if en(t)]
    while True:
        title = " ".join(t for t, _ in parts)
        if len(title) <= TITLE_MAX or len(parts) <= 2:
            return title[:TITLE_MAX]
        drop = max(range(len(parts)), key=lambda i: (parts[i][1], i))
        parts.pop(drop)


def specifics(info: dict, condition: str = "") -> dict:
    game = game_of(info)
    s = {
        "Game": GAME_WORDS[game][3],
        "Card Name": name_of(info),
        "Character": (_character(name_of(info), info.get("category", "")) if game == "pokemon"
                      else name_of(info) if game == "onepiece" else ""),
        "Set": set_of(info),
        "Card Number": f"{info.get('number', '')}/{info.get('set_total', '')}".strip("/"),
        "Rarity": rarity_of(info),
        "Edition": info.get("edition", "") if game == "yugioh" else "",
        "Language": {"en": "English", "ja": "Japanese", "zh-tw": "Chinese", "zh-cn": "Chinese",
                     "ko": "Korean"}.get(info.get("language", "en"), ""),
        "Card Type": _CATEGORY_EN.get((info.get("category") or "").lower(), info.get("category", "")),
        "Year Manufactured": info.get("year", ""),
        "Manufacturer": info.get("maker") or GAME_WORDS[game][4],
        "Graded": "No",
        "Card Condition": CONDITIONS[condition][1] if condition in CONDITIONS else "",
    }
    return {k: en(v) for k, v in s.items() if en(v)}


# In every description: a line from the seller at the top, the store's policies at the bottom.
WELCOME = "Welcome in! Real studio photos of the exact card you get, never TCGplayer stock."
POLICIES = (
    "Same-day handling: orders placed before 2 PM Central ship the same business day.",
    "Packed in a penny sleeve and toploader inside a protective mailer.",
    "No cancellations once an order is placed, so please buy with care.",
    "No returns. The photos are the exact card, so check them closely, corners included.",
    "Questions about a card? Message me before you buy and I will answer quickly.",
    "eBay's Money Back Guarantee still covers you if a card arrives not as described.",
)


def description_html(info: dict, centering: dict, condition: str = "", price: float = 0.0,
                     corners: bool = True) -> str:
    rows = "".join(f"<tr><td><b>{html.escape(k)}</b></td><td>{html.escape(v)}</td></tr>"
                   for k, v in specifics(info).items() if k not in ("Graded", "Manufacturer", "Card Condition"))
    if game_of(info) == "onepiece" and en(info.get("variant", "")):
        rows += f"<tr><td><b>Version</b></td><td>{html.escape(en(info['variant']))}</td></tr>"
    cent = "".join(f"<li>{html.escape(side.title())}: {html.escape(text)}</li>"
                   for side, text in centering.items() if text)
    out = [f"<h2>{html.escape(make_title(info, condition, price))}</h2>"]
    if WELCOME:
        out.append(f"<p><i>{html.escape(WELCOME)}</i></p>")
    out.append(f"<table>{rows}</table>")
    if condition in CONDITIONS:
        out.append(f"<p><b>Condition: {CONDITIONS[condition][0]} ({condition})</b>, ungraded. "
                   "Judge it by the photos as well.</p>")
    if cent:
        out.append(f"<p><b>Centering (measured from the photos)</b></p><ul>{cent}</ul>")
    out.append("<p>The photos show the exact card you will receive" +
               (", including close-ups of all four corners" if corners else ", front and back") +
               ". Please review them, as they are part of the description.</p>")
    if POLICIES:
        out.append("<p><b>Store policies</b></p><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in POLICIES) + "</ul>")
    return "\n".join(out)


def description_text(info: dict, centering: dict, condition: str = "", price: float = 0.0,
                     corners: bool = True) -> str:
    """The same description as plain text, for pasting into eBay's editor."""
    t = re.sub(r"</(p|h2|tr|li|table|ul)>", "\n", description_html(info, centering, condition, price, corners))
    t = re.sub(r"<td><b>(.*?)</b></td><td>(.*?)</td>", r"\1: \2", t)
    t = re.sub(r"<li>", "  - ", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    t = "\n".join(en(line) if has_cjk(line) else line for line in t.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def build(info: dict, sku: str, centering: dict, title_override: str = "", condition: str = "",
          price: float = 0.0, corners: bool = True) -> dict:
    return {
        "sku": sku,
        "title": en(title_override or make_title(info, condition, price))[:TITLE_MAX],
        "specifics": specifics(info, condition),
        "description_html": description_html(info, centering, condition, price, corners),
        "description_text": description_text(info, centering, condition, price, corners),
        "centering": centering,
        "condition": condition,
        "price": round(float(price or 0), 2),
        "info": info,
    }


def save(listing: dict, folder: str, name: str) -> list[str]:
    os.makedirs(folder, exist_ok=True)
    jp = os.path.join(folder, f"{name}_listing.json")
    tp = os.path.join(folder, f"{name}_listing.txt")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(listing, f, ensure_ascii=False, indent=2)
    with open(tp, "w", encoding="utf-8") as f:
        # the description already opens with the title and the card details
        f.write("TITLE\n" + listing["title"] + "\n\nDESCRIPTION\n")
        f.write(listing["description_text"] + "\n\nITEM SPECIFICS\n")
        f.write("\n".join(f"{k}: {v}" for k, v in listing["specifics"].items()) + "\n")
    return [jp, tp]


def load_all(out_dir: str) -> list[dict]:
    """Every listing saved under the output folder, oldest first."""
    found = []
    for root, _, files in os.walk(out_dir):
        for fn in files:
            if fn.endswith("_listing.json"):
                p = os.path.join(root, fn)
                try:
                    with open(p, encoding="utf-8") as f:
                        found.append((os.path.getmtime(p), json.load(f)))
                except (OSError, ValueError):
                    pass
    return [d for _, d in sorted(found, key=lambda x: x[0])]


# ------------------------------------------------------------------ eBay template
def _norm(h: str) -> str:
    h = h.strip().lstrip("*").strip()
    h = re.sub(r"^(C|CD):", "", h, flags=re.I)
    h = re.sub(r"\(.*?\)", "", h)
    return re.sub(r"\s+", " ", h).strip(" -").lower()


def fill_ebay_template(template_path: str, listings: list[dict], out_path: str) -> dict:
    """Copy the seller's eBay drafts template, adding one row per listing.

    Returns a report of which columns were filled and which were left blank,
    so nothing is silently skipped.
    """
    with open(template_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    hi = next((i for i, r in enumerate(rows) if r and re.match(r"^\*?Action", r[0].strip(), re.I)), None)
    if hi is None:
        raise ValueError("This does not look like an eBay upload template: no Action column found. "
                         "Download it from Seller Hub > Reports > Uploads > Get template, choosing Create drafts.")
    header = rows[hi]
    examples = [r for r in rows[hi + 1:] if any(c.strip() for c in r)]
    action = next((r[0] for r in examples if r and r[0].strip()), "") or "Draft"
    norm = [_norm(h) for h in header]

    filled_cols = set()
    out_rows = []
    for L in listings:
        spec = {k.lower(): v for k, v in L["specifics"].items()}
        extra = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in (L.get("extra") or {}).items()}
        row = [""] * len(header)
        for i, n in enumerate(norm):
            v = None
            squashed = re.sub(r"[^a-z0-9]", "", n)
            if i == 0:
                v = action
            elif n in ("custom label", "custom label sku", "sku"):
                v = L["sku"]
            elif n in ("category id", "category"):
                v = CATEGORY_ID
            elif n == "title":
                v = L["title"]
            elif n == "description":
                v = L["description_html"]
            elif n in ("condition id", "condition") and L.get("condition") in CONDITIONS:
                # the drafts template only takes NEW or USED; the card grade is finished in Drafts
                v = "USED" if action.strip().lower() == "draft" else UNGRADED_CONDITION_ID
            elif n == "card condition" and L.get("condition") in CONDITIONS:
                # descriptor columns (CD:) take eBay's value ID, plain columns the wording
                v = CONDITIONS[L["condition"]][2 if header[i].strip().lstrip("*").upper().startswith("CD:")
                                               else 1]
            elif n in spec:
                v = spec[n]
            elif squashed in extra:
                v = extra[squashed]
            if v:
                row[i] = v
                filled_cols.add(header[i])
        out_rows.append(row)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in rows[:hi + 1]:
            w.writerow(r)
        for r in out_rows:
            w.writerow(r)
    required_blank = [h for h in header if h.strip().startswith("*") and h not in filled_cols]
    return {"rows": len(out_rows), "filled": sorted(filled_cols), "required_left_blank": required_blank}


def draft_extras(photo_urls, price, zip_code="", policy_names=None, package=None, store_category=None,
                 store_category2=None) -> dict:
    """Columns a drafts template may carry beyond the item itself. Matching ignores case,
    spaces and punctuation, and a column the template does not have is simply skipped."""
    urls = "|".join(photo_urls)
    e = {"Item photo URL": urls, "PicURL": urls, "Photo URL": urls,
         "Price": f"{float(price):.2f}", "Start price": f"{float(price):.2f}", "StartPrice": f"{float(price):.2f}",
         "Quantity": "1", "Format": "FixedPrice", "Duration": "GTC"}
    if zip_code:
        e.update({"Postal code": zip_code, "PostalCode": zip_code, "Zip code": zip_code, "Item location postal code": zip_code})
    for kind, label in (("fulfillment", "Shipping"), ("return", "Return"), ("payment", "Payment")):
        name = (policy_names or {}).get(kind)
        if name:
            e[f"{label} profile name"] = name
            e[f"{label} policy name"] = name
    if store_category and store_category[0]:        # (id, path): the drafts file takes the number
        e.update({"Store category": store_category[0], "StoreCategory": store_category[0],
                  "Store category 1": store_category[0], "StoreCategoryID": store_category[0]})
    if store_category2 and store_category2[0]:
        e.update({"Store category 2": store_category2[0], "StoreCategory2": store_category2[0],
                  "StoreCategory2ID": store_category2[0]})
    if package:
        oz = float(package.get("oz", 0))
        e.update({"WeightMajor": str(int(oz // 16)), "WeightMinor": f"{oz % 16:g}",
                  "Package weight": f"{oz:g}", "PackageLength": f"{package['l']:g}",
                  "PackageWidth": f"{package['w']:g}", "PackageDepth": f"{package['h']:g}"})
    return e


def export_csv(listings: list[dict], out_path: str) -> None:
    """A plain spreadsheet of every listing, for your own records."""
    keys = []
    for L in listings:
        for k in L["specifics"]:
            if k not in keys:
                keys.append(k)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["SKU", "Title"] + keys + ["Centering front", "Centering back", "Description"])
        for L in listings:
            c = L.get("centering", {})
            w.writerow([L["sku"], L["title"]] + [L["specifics"].get(k, "") for k in keys]
                       + [c.get("front", ""), c.get("back", ""), L["description_text"]])
