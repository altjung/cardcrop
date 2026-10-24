"""Card identification: read the collector number off a flattened card, then
look the card up in TCGdex (https://tcgdex.dev), a free card database with
English and Japanese data and no API key.

Everything network-related lives here so the rest of the app stays offline
and fast; lookups run in a background thread from the GUI.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import cv2
import numpy as np

API = "https://api.tcgdex.net/v2"
UA = {"User-Agent": "CardCrop/1.0 (desktop card photo tool)"}
LANGS = {"en": "English", "ja": "Japanese", "zh-tw": "Chinese (Traditional)", "zh-cn": "Chinese (Simplified)",
         "ko": "Korean"}
# the word a listing uses for a card's language (English needs none)
LANG_WORD = {"ja": "Japanese", "zh-tw": "Chinese", "zh-cn": "Chinese", "ko": "Korean"}


def card_language(text: str) -> str:
    """The language printed on a card, from what OCR read off it: kana is Japanese, Hangul Korean,
    Chinese characters with no kana Chinese ('zh'), anything else English."""
    t = str(text or "")
    kana = len(re.findall(r"[\u3040-\u30ff]", t))
    hangul = len(re.findall(r"[\uac00-\ud7af]", t))
    han = len(re.findall(r"[\u4e00-\u9fff]", t))
    if kana >= 1:
        return "ja"
    if hangul >= 2:
        return "ko"
    if han >= 2:
        return "zh"
    return "en"


def read_language(card) -> str:
    """Which language the card is printed in: OCR of the name across the top, where every card
    spells its name in its own language."""
    from engine import to8
    img = to8(card)
    h, w = img.shape[:2]
    band = img[int(h * 0.025):int(h * 0.13), int(w * 0.03):int(w * 0.8)]
    k = max(1.0, 140 / max(1, band.shape[0]))
    band = cv2.resize(band, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    try:
        result, _ = _engine()(band)
    except Exception:  # noqa: BLE001
        return "en"
    return card_language(" ".join(str(t) for _b, t, _s in (result or [])))


def lang_order(card_lang: str, chosen: str = "en") -> list:
    """The databases to look in, the card's own language first, then the one you chose, then English."""
    first = ["zh-tw", "zh-cn"] if card_lang == "zh" else [card_lang] if card_lang in LANGS else []
    return list(dict.fromkeys(first + [chosen if chosen in LANGS else "en", "en"]))
GAMES = {"pokemon": "Pokémon", "yugioh": "Yu-Gi-Oh!", "onepiece": "One Piece"}
YGO_API = "https://db.ygoprodeck.com/api/v7"
OP_API = "https://optcgapi.com/api"
# One Piece: OP01-001, ST10-005, EB01-012, PRB01-001, P-001
OP_CODE = re.compile(r"(?<![A-Z0-9])((?:OP|ST|EB|PRB)\d{2}|P)-(\d{3})(?!\d)", re.I)
# Yu-Gi-Oh!: LOB-EN001, RA01-EN054, MP24-EN123 (region letters required to tell it from other codes)
YGO_CODE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{2,5})-(EN|E|JP|JA|DE|FR|IT|SP|PT|KR|AE)(\d{3})(?!\d)", re.I)
YGO_CODE_LOOSE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{2,5})-([A-Z]{0,2})(\d{3})(?!\d)", re.I)
OP_RARITY = {"L": "Leader", "C": "Common", "UC": "Uncommon", "R": "Rare", "SR": "Super Rare",
             "SEC": "Secret Rare", "SP": "Special", "P": "Promo", "PR": "Promo", "TR": "Treasure Rare",
             "DON": "DON!!", "DON!!": "DON!!"}
# the rarity mark One Piece prints after the card code, as OCR reads it
OP_RARITY_MARK = re.compile(r"(?<![A-Z])(SEC|SR|UC|TR|SP|PR|L|C|R|P)(?![A-Z])")
# One Piece versions of one card code, as the database names them, and how sellers write them
OP_VARIANTS = {"alternate art": "Alt Art", "super alternate art": "Super Alt Art", "parallel": "Parallel",
               "manga": "Manga", "sp": "SP", "spr": "SPR", "wanted poster": "Wanted Poster", "gold": "Gold",
               "tr": "Treasure Rare", "full art": "Full Art", "jolly roger foil": "Jolly Roger Foil",
               "pirate foil": "Pirate Foil", "textured foil": "Textured Foil", "box topper": "Box Topper",
               "dash pack": "Dash Pack", "reprint": "Reprint", "pandaman art": "Pandaman Art", "gem": "Gem",
               "navy": "Navy"}
# Yu-Gi-Oh! rarities: YGOPRODeck's spelling -> the clean name, and the short form sellers put in titles
YGO_RARITY_FIX = {"platinum secret rare": "Platinum Secret Rare", "starfoil": "Starfoil Rare",
                  "extra secret": "Extra Secret Rare", "cr": "Collector's Rare"}
YGO_NOT_RARITY = {"new", "2", "3", "reprint", "new artwork", "european & oceanian debut", "european debut",
                  "oceanian debut", "force-smw"}
YGO_SHORT = {"quarter century secret rare": "QCSR", "starlight rare": "Starlight Rare",
             "collector's rare": "Collector's Rare", "prismatic secret rare": "Prismatic Secret Rare",
             "platinum secret rare": "Platinum Secret Rare", "ultimate rare": "Ultimate Rare",
             "ghost rare": "Ghost Rare", "ghost/gold rare": "Ghost Gold Rare", "gold rare": "Gold Rare",
             "premium gold rare": "Premium Gold Rare", "gold secret rare": "Gold Secret Rare",
             "secret rare": "Secret Rare", "ultra rare": "Ultra Rare", "super rare": "Super Rare",
             "rare": "Rare", "short print": "Short Print", "super short print": "SSP",
             "ultra rare (pharaoh's rare)": "Pharaoh's Rare", "starfoil rare": "Starfoil",
             "shatterfoil rare": "Shatterfoil", "mosaic rare": "Mosaic Rare", "platinum rare": "Platinum Rare",
             "duel terminal normal parallel rare": "DT Parallel", "duel terminal rare parallel rare": "DT Rare",
             "duel terminal super parallel rare": "DT Super", "duel terminal ultra parallel rare": "DT Ultra",
             "duel terminal normal rare parallel rare": "DT Rare", "ultra parallel rare": "Ultra Parallel",
             "super parallel rare": "Super Parallel", "normal parallel rare": "Parallel Rare",
             "grand master rare": "Grand Master Rare", "extra secret rare": "Extra Secret Rare",
             "ultra secret rare": "Ultra Secret Rare", "10000 secret rare": "10000 Secret Rare", "common": ""}
# words that tell one Yu-Gi-Oh! rarity from another in a listing title
YGO_WORDS = {"quarter century secret rare": ["quarter century", "qcsr", "qcr", "25th"],
             "starlight rare": ["starlight"], "collector's rare": ["collector", "collectors rare"],
             "prismatic secret rare": ["prismatic"], "platinum secret rare": ["platinum"],
             "ultimate rare": ["ultimate"], "ghost rare": ["ghost"], "gold rare": ["gold rare"],
             "premium gold rare": ["premium gold"], "secret rare": ["secret"], "ultra rare": ["ultra"],
             "super rare": ["super rare"], "starfoil rare": ["starfoil"], "shatterfoil rare": ["shatterfoil"],
             "mosaic rare": ["mosaic"], "grand master rare": ["grand master"]}


def ygo_rarity(r: str) -> str:
    """YGOPRODeck's rarity, cleaned: typos fixed, and notes that are not rarities left out."""
    k = (r or "").strip().lower()
    if k in YGO_NOT_RARITY:
        return ""
    return YGO_RARITY_FIX.get(k, (r or "").strip())


def rarity_short(info) -> str:
    """The rarity as sellers put it in a title, for any game ('' when it adds nothing)."""
    d = info if isinstance(info, dict) else info.__dict__
    r, g = (d.get("rarity") or "").strip(), d.get("game") or "pokemon"
    if g == "yugioh":
        return YGO_SHORT.get(r.lower(), r)
    if g == "onepiece":
        base = {"secret rare": "SEC", "super rare": "SR", "treasure rare": "TR", "leader": "Leader",
                "promo": "Promo", "special": "SP"}.get(r.lower(), "")
        return " ".join(x for x in (base, d.get("variant") or "") if x)
    return r


def detect_game(text: str) -> str:
    """A set code in the text says which game it is; otherwise Pokémon."""
    t = (text or "").upper()
    if OP_CODE.search(t):
        return "onepiece"
    if YGO_CODE.search(t):
        return "yugioh"
    return ""


# ------------------------------------------------------------------ OCR
_ocr = None
_ocr_lock = threading.Lock()


def _engine():
    global _ocr
    with _ocr_lock:
        if _ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR()
        return _ocr


# "4/102", "025/198", "TG05/TG30", "SV049/SV122", with OCR-typical spacing
NUM_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{0,3}\d{1,3})\s*/\s*([A-Z]{0,3}\d{2,3})(?!\d)")
SET_CODE_RE = re.compile(r"\b([A-Z]{2,4}\d?)\s+(EN|JP|JA)\b")


@dataclass
class Reading:
    number: str = ""          # as printed, e.g. "025"
    total: str = ""           # as printed, e.g. "198"
    set_code: str = ""        # e.g. "SVI" on modern cards, when legible
    raw: str = ""             # everything OCR saw in the strips, for display
    alts: list = field(default_factory=list)   # other (number, total) readings, next most likely first

    @property
    def found(self) -> bool:
        return bool(self.number and self.total)

    def text(self) -> str:
        return f"{self.number}/{self.total}" if self.found else ""


def read_ygo_line(card: np.ndarray) -> tuple[str, str]:
    """Yu-Gi-Oh! prints its set code (LOB-EN005) just under the art on the right, and on
    1st Edition and Limited Edition cards those words on the left of the same line.
    Returns (code, edition); edition is '' when nothing is printed there or it could not be read."""
    from engine import to8
    img = to8(card)
    h, w = img.shape[:2]
    band = img[int(h * 0.69):int(h * 0.80), int(w * 0.03):w - int(w * 0.03)]
    ed_re = re.compile(r"[1IL]S?T\W*ED[I1L]T[I1L]?[O0]N|LIMITED\W*EDITION")
    texts, code, edition = [], "", ""
    for target in (150, 230, 110):
        k = max(1.0, target / max(1, band.shape[0]))
        line = cv2.resize(band, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        lab = cv2.cvtColor(line, cv2.COLOR_BGR2LAB)
        lab[..., 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 16)).apply(lab[..., 0])
        line = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        for variant in (line, 255 - line):
            result, _ = _engine()(variant)
            texts += [str(t) for _, t, _ in (result or [])]
            toks = {re.sub(r"[^A-Z0-9]", "", t.upper()) for t in texts}
            if not edition and any(re.fullmatch(r"ED[I1L]T[I1L]?[O0]N", x) for x in toks):
                # OCR often returns "1st" and "Edition" as separate words, in either order
                if toks & {"1ST", "IST", "LST"}:
                    edition = "1st Edition"
                elif "LIMITED" in toks:
                    edition = "Limited Edition"
            for t in texts:
                u = t.upper()
                if not edition:
                    m = ed_re.search(re.sub(r"\s+", "", u))
                    if m:
                        edition = "Limited Edition" if m.group(0).startswith("LIM") else "1st Edition"
                if not code:
                    # OCR runs words together ("1stEditionMP22-EN257"): take the edition words out first
                    u = ed_re.sub(" ", re.sub(r"\s+", "", u))
                    m = re.search(r"(?<![A-Z0-9])([A-Z0-9]{2,5})-([A-Z]{2})([0-9O]{3})(?![0-9])", u)
                    if m:                       # OCR reads 0 as O in the number
                        code = f"{m.group(1)}-{m.group(2)}{m.group(3).replace('O', '0')}"
            if code and edition:
                return code, edition
        if code:                       # a code with no edition words: none printed, most likely
            return code, edition
    return code, edition


def read_ygo_code(card: np.ndarray) -> str:
    return read_ygo_line(card)[0]


_OP_OCR = re.compile(r"(?<![0-9])(PR[B8][0-9O]{2}|[O0]P[0-9O]{2}|[S5][T7][0-9O]{2}|E[B8][0-9O]{2}|P)-([0-9O]{3})(?![0-9])")


def op_code_from_ocr(raw: str) -> tuple[str, str]:
    """A One Piece code and its rarity mark from OCR text, which reads OP as 0P and runs the
    mark on ('0P05-119SEC'). Returns ('OP05-119', 'SEC'), or ('', '')."""
    t = re.sub(r"\s+", "", (raw or "").upper())
    m = _OP_OCR.search(t)
    if not m:
        return "", ""
    pre = m.group(1)
    head = re.sub(r"^[O0]P", "OP", re.sub(r"^[S5][T7]", "ST", re.sub(r"^E[B8]", "EB", re.sub(r"^PR[B8]", "PRB", pre))))
    head = head[:len(head) - 2] + head[-2:].replace("O", "0") if head != "P" else head
    code = f"{head}-{m.group(2).replace('O', '0')}"
    mk = OP_RARITY_MARK.match(t[m.end():m.end() + 4])
    return code, (mk.group(1) if mk else "")


def op_rarity_mark(raw: str, code: str) -> str:
    """The rarity printed just after a One Piece code ('OP05-119 SEC'), as a database code."""
    t = re.sub(r"\s+", " ", (raw or "").upper())
    i = t.replace(" ", "").find(code.replace(" ", "").upper()) if code else -1
    if i < 0:
        return ""
    flat = t.replace(" ", "")
    m = OP_RARITY_MARK.match(flat[i + len(code):i + len(code) + 4])
    return m.group(1) if m else ""


def _card_feats(img: np.ndarray):
    """A small fingerprint of a card picture: its colour layout and its outlines."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        img = img[..., :3]
    c = cv2.resize(img, (100, 140), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(c, cv2.COLOR_BGR2LAB).astype(np.float32)
    small = cv2.resize(lab, (10, 14), interpolation=cv2.INTER_AREA)
    small -= small.reshape(-1, 3).mean(0)
    small /= small.reshape(-1, 3).std(0) + 1e-6
    g = cv2.GaussianBlur(lab[..., 0], (0, 0), 1.2)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = cv2.resize(np.sqrt(gx * gx + gy * gy), (50, 70), interpolation=cv2.INTER_AREA)
    mag = (mag - mag.mean()) / (mag.std() + 1e-6)
    return small.ravel(), mag.ravel()


def image_match(photo: np.ndarray, picture: np.ndarray) -> float:
    """How alike a photographed card and a database picture are, -1..1 (about 0.8+ for the same art)."""
    a, b = _card_feats(photo), _card_feats(picture)
    col = float(np.dot(a[0], b[0]) / len(a[0]))
    edge = float(np.dot(a[1], b[1]) / len(a[1]))
    return 0.45 * col + 0.55 * edge


def _clean(t: str) -> str:
    # common OCR confusions in collector numbers
    t = t.replace("O", "0").replace("o", "0") if re.search(r"\d", t) else t
    return t.replace("\\", "/").replace("|", "/").replace("l/", "1/")


_TOTALS = None
PROMO_PREFIX = ("TG", "GG", "SV", "SWSH", "SM", "XY", "BW", "DP", "HGSS", "RC", "SH", "H", "SL", "PR")


def plausible_totals() -> set:
    """Every printed set total there is (from the set lists kept on this Mac), to tell a real
    collector number from OCR noise without asking the database."""
    global _TOTALS
    if _TOTALS is None:
        out = set()
        for lang in LANGS:
            try:
                with open(os.path.join(_cache_dir(), f"sets_{lang}.json")) as f:
                    for st in json.load(f):
                        v = str((st.get("cardCount") or {}).get("official") or "")
                        if v.isdigit():
                            out.add(int(v))
            except (OSError, ValueError):
                pass
        _TOTALS = out
    return _TOTALS


def _candidates(text: str) -> list:
    """(score, number, total) for every collector number the OCR text could hold, best first: an exact
    slash, a slash misread as 7, 1, l or I, stray letters or digits stuck to the front."""
    totals = plausible_totals()
    out = {}

    def add(n, t, score):
        n, t = n.strip(), t.strip()
        if not n or not t:
            return
        pn = re.match(r"([A-Z]*)(\d+)$", n)
        pt = re.match(r"([A-Z]*)(\d+)$", t)
        if not pn or not pt:
            return
        # letters in front: kept only for the gallery and promo numbering that really prints them
        if pn.group(1) and not (pn.group(1) in PROMO_PREFIX and pn.group(1) == pt.group(1)):
            n = pn.group(2)
        if pt.group(1) and not (pt.group(1) in PROMO_PREFIX and pn.group(1) == pt.group(1)):
            t = pt.group(2)
        nd, td = int(re.sub(r"\D", "", n) or 0), int(re.sub(r"\D", "", t) or 0)
        if td == 0:
            return
        if t.isdigit() and n.isdigit() and nd > td + 150 and len(n) > 1:
            add(n[1:], t, score - 0.5)                       # a stray digit stuck to the front
            return
        s_ = score
        if t.isdigit() and totals:
            s_ += 2.0 if td in totals else -1.5
        if n.isdigit() and t.isdigit():
            s_ += 1.0 if nd <= td else (0.3 if nd <= td + 150 else -2.0)
        key = (n.lstrip("0") or "0", t.lstrip("0") or "0")
        if key not in out or out[key][0] < s_:
            out[key] = (s_, n, t)
    up = text.upper()
    for m in NUM_RE.finditer(up):
        add(m.group(1), m.group(2), 1.0)
    # the slash read as a 7, 1, l or I: 99/114 seen as 9971147
    for m in re.finditer(r"(?<![A-Z0-9])(\d{1,3})[71LI|](\d{2,3})(?:\d|[^0-9]|$)", up):
        add(m.group(1), m.group(2), -0.5)
    return sorted(out.values(), reverse=True)


def _ocr_texts(img) -> list:
    result, _ = _engine()(img)
    return [_clean(str(text)) for _box, text, _score in (result or [])]


def _prep(strip, target_h):
    k = max(1.0, target_h / strip.shape[0])
    strip = cv2.resize(strip, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    lab = cv2.cvtColor(strip, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def read_number(card: np.ndarray) -> Reading:
    """OCR the collector number off an upright, flattened card (no margin). Older sets print it bottom
    right, modern ones bottom left: the whole bottom strip is read first, then each corner on its own,
    larger, light-on-dark too, then the card turned round in case it was the wrong way up. Every
    reading is checked against the set totals that exist, so OCR noise is not taken for a number."""
    from engine import to8
    img = to8(card)
    texts = []
    best = None

    def look(strip, target_h):
        nonlocal best
        for variant in (strip, 255 - strip):
            texts.extend(_ocr_texts(_prep(strip if variant is strip else variant, target_h)))
            cands = _candidates(" ".join(texts))
            if cands and cands[0][0] >= 2.5:              # a real total and a sane number
                best = cands
                return True
        cands = _candidates(" ".join(texts))
        if cands and (best is None or cands[0][0] > best[0][0]):
            best = cands
        return False

    for im in (img, cv2.rotate(img, cv2.ROTATE_180)):
        h, w = im.shape[:2]
        strip = im[int(h * 0.88):h - int(h * 0.005), int(w * 0.02):w - int(w * 0.02)]
        if look(strip, 160):
            break
        # each corner of the strip on its own, bigger: the number is small and sits at one end
        lo, hi = int(h * 0.86), h - int(h * 0.004)
        if look(im[lo:hi, int(w * 0.02):int(w * 0.48)], 220) or look(im[lo:hi, int(w * 0.52):w - int(w * 0.02)], 220):
            break
        if best and best[0][0] >= 1.5:
            break
    joined = " ".join(texts)
    if best:
        _s, n, t = best[0]
        sc = SET_CODE_RE.search(joined)
        r = Reading(n, t, sc.group(1) if sc else "", joined)
        r.alts = [(n_, t_) for _s, n_, t_ in best[1:4]]
        return r
    return Reading(raw=joined)


# ------------------------------------------------------------------ database
@dataclass
class CardInfo:
    id: str
    name: str
    number: str
    set_name: str = ""
    set_id: str = ""
    set_total: str = ""
    rarity: str = ""
    category: str = ""
    year: str = ""
    language: str = "en"
    image: str = ""            # base URL; append /low.png or /high.png
    name_en: str = ""          # Japanese cards: the English name, for titles and searching
    set_name_en: str = ""      # Japanese cards: the set code, since the set name is in Japanese
    game: str = "pokemon"      # pokemon, yugioh or onepiece
    variant: str = ""          # One Piece: Alt Art, Manga, SP, Wanted Poster... (one code, many versions)
    edition: str = ""          # Yu-Gi-Oh!: 1st Edition or Limited Edition, when it is printed on the card
    match: float = 0.0         # how closely the photo matches this card's picture, when compared
    maker: str = ""            # cards you enter yourself: who made it (Bandai for Carddass, say)

    def label(self) -> str:
        name = f"{self.name_en}  ({self.name})" if self.name_en and self.name_en != self.name else self.name
        set_name = f"{self.set_name_en}  {self.set_name}" if self.set_name_en else self.set_name
        bits = [name, f"{self.number}/{self.set_total}" if self.set_total else self.number,
                set_name, self.rarity, self.variant, self.edition, LANG_WORD.get(self.language, "")]
        return "  ·  ".join(b for b in bits if b)

    @property
    def manual(self) -> bool:
        return self.id.startswith("manual:")

    def slug(self) -> str:
        if self.manual:                      # charizard-carddass-part-3-6
            s = "-".join(x for x in (self.name_en or self.name, self.set_id, self.number) if x)
            if self.language != "en":
                s += f"-{self.language}"
            s = re.sub(r"[^\w.\- ]+", "", s, flags=re.UNICODE).strip().replace(" ", "-")
            return re.sub(r"-{2,}", "-", s).lower()
        if self.game != "pokemon":           # the printed code already names set and number
            # one code can be several cards: a QCSR and an Ultra Rare, a Manga and the regular print
            tail = self.variant if self.game == "onepiece" else (
                "" if self.rarity.lower() in ("", "common", "rare", "super rare", "ultra rare")
                else YGO_SHORT.get(self.rarity.lower(), self.rarity))
            s = re.sub(r"[^\w.\- ]+", "", f"{self.name_en or self.name}-{self.number}" + (f"-{tail}" if tail else ""),
                       flags=re.UNICODE)
            return re.sub(r"-{2,}", "-", s.strip().replace(" ", "-")).lower()
        s = f"{self.name_en or self.name}-{self.set_id}-{self.number}"
        if self.language != "en":
            s += f"-{self.language}"
        s = re.sub(r"[^\w.\- ]+", "", s, flags=re.UNICODE).strip().replace(" ", "-")
        return re.sub(r"-{2,}", "-", s).lower()

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def manual_card(name: str, set_name: str = "", number: str = "", year: str = "", rarity: str = "",
                language: str = "en", game: str = "pokemon", maker: str = "", category: str = "") -> CardInfo:
    """A card that is in no database (Carddass, Topsun, a promo nobody lists), entered by hand."""
    name = name.strip()
    if name and name == name.lower():         # typed in a hurry: charizard -> Charizard
        name = name.title()
    set_id = re.sub(r"[^a-z0-9]+", "-", set_name.lower()).strip("-")[:28]
    sid = re.sub(r"[^a-z0-9]+", "-", f"{name} {set_id} {number} {rarity} {language}".lower()).strip("-")
    return CardInfo(id=f"manual:{sid}", name=name.strip(), number=number.strip(), set_name=set_name.strip(),
                    set_id=set_id, rarity=rarity.strip(), year=str(year).strip(), language=language,
                    game=game, maker=maker.strip(), category=category.strip())


def _cache_dir() -> str:
    base = os.path.expanduser("~/Library/Application Support/CardCrop")
    if not os.path.isdir(os.path.dirname(base)):
        base = os.path.expanduser("~/.cardcrop")
    os.makedirs(base, exist_ok=True)
    return base


def _get(url: str, timeout: float = 12.0):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Database:
    """Thin TCGdex client with a local cache of set totals."""

    def __init__(self, getter=_get):
        self._get = getter
        self._sets: dict[str, dict] = {}
        self._card_cache: dict[str, CardInfo] = {}

    # sets list changes a few times a year, so cache it for a week
    def sets(self, lang: str) -> dict:
        if lang in self._sets:
            return self._sets[lang]
        path = os.path.join(_cache_dir(), f"sets_{lang}.json")
        data = None
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
            try:
                with open(path) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = None
        if data is None:
            data = self._get(f"{API}/{lang}/sets")
            try:
                with open(path, "w") as f:
                    json.dump(data, f)
            except OSError:
                pass
        self._sets[lang] = {s["id"]: s for s in data}
        return self._sets[lang]

    def card(self, card_id: str, lang: str) -> CardInfo:
        key = f"{lang}:{card_id}"
        if key in self._card_cache:
            return self._card_cache[key]
        d = self._get(f"{API}/{lang}/cards/{urllib.parse.quote(card_id)}")
        st = d.get("set") or {}
        cc = st.get("cardCount") or {}
        year = ""
        sets = self._sets.get(lang, {})
        rel = (sets.get(st.get("id"), {}) or {}).get("releaseDate") or d.get("releaseDate") or ""
        if rel:
            year = str(rel)[:4]
        info = CardInfo(
            id=d.get("id", card_id), name=d.get("name", ""), number=str(d.get("localId", "")),
            set_name=st.get("name", ""), set_id=st.get("id", ""),
            # promos print only their number (BW81, SWSH020), never "of" a set total
            set_total="" if "promo" in (st.get("name") or "").lower() else str(cc.get("official") or ""),
            rarity="" if str(d.get("rarity")) in ("None", "") else d.get("rarity"),
            category=d.get("category") or "", year=year, language=lang, image=d.get("image") or "")
        if lang != "en":
            # an English name to list it by: from its Pokédex number, any language; cards that carry
            # one teach the species name, so ones that do not (many Chinese and Japanese cards) still get it
            dex = d.get("dexId") or []
            info.name_en = self.english_name(info.name, dex)
            if info.name_en and len(dex) == 1:
                native = info.name
                for _ in range(2):
                    native = self._JA_STRIP.sub("", native)
                    native = next((native[len(p):] for p, _e in self._ZH_PREFIX if native.startswith(p)), native)
                    native = re.sub(r"\s*(ex|EX|GX|VMAX|VSTAR|V-UNION|V|BREAK|LV\.X|☆|δ)$", "", native).strip()
                if native and not native.isascii() and len(native) >= 2:
                    self._learn_ja(native, self.species(dex[0]))
            if not info.name_en:
                info.name_en = self._en_from_ja(info.name)
            if info.set_name and not info.set_name.isascii():
                info.set_name_en = info.set_id
        self._card_cache[key] = info
        return info

    # ---------------------------------------------------------- Japanese cards, in English
    _JA_PREFIX = [("メガ", "Mega"), ("かがやく", "Radiant"), ("ひかる", "Shining"), ("ダーク", "Dark"),
                  ("ロケット団の", "Team Rocket's"), ("ヒスイ", "Hisuian"), ("ガラル", "Galarian"),
                  ("アローラ", "Alolan"), ("パルデア", "Paldean"), ("テラスタル", "Tera")]
    _ZH_PREFIX = [("超級", "Mega"), ("超级", "Mega"), ("光輝", "Radiant"), ("光辉", "Radiant"), ("閃耀", "Shining"),
                  ("火箭隊的", "Team Rocket's"), ("火箭队的", "Team Rocket's"), ("洗翠", "Hisuian"), ("伽勒爾", "Galarian"),
                  ("伽勒尔", "Galarian"), ("阿羅拉", "Alolan"), ("阿罗拉", "Alolan"), ("帕底亞", "Paldean"),
                  ("帕底亚", "Paldean"), ("메가", "Mega"), ("빛나는", "Radiant")]
    _SUFFIX = re.compile(r"(ex|EX|GX|VMAX|VSTAR|V-UNION|V|BREAK|LV\.X|☆|δ|prime|LEGEND)$")
    _EN_STRIP = re.compile(r"^(Dark|Light|Shining|Radiant|Team Rocket's|Mega|M|Alolan|Galarian|Hisuian|"
                           r"Paldean|[A-Z][a-z]+'s)\s+|\s+(ex|EX|GX|V|VMAX|VSTAR|V-UNION|BREAK|LV\.X|δ|Star|☆|"
                           r"Prime|LEGEND|& .*)$")

    def species(self, dex: int) -> str:
        """English species name for a national Pokédex number, cached on disk."""
        if not hasattr(self, "_species"):
            self._species_path = os.path.join(_cache_dir(), "species_en.json")
            try:
                with open(self._species_path) as f:
                    self._species = json.load(f)
            except (OSError, ValueError):
                self._species = {}
        k = str(dex)
        if k in self._species:
            return self._species[k]
        q = urllib.parse.urlencode({"dexId": f"eq:{dex}", "pagination:itemsPerPage": 60})
        names = {}
        for r in self._get(f"{API}/en/cards?{q}") or []:
            n = r.get("name", "")
            for _ in range(3):
                n = self._EN_STRIP.sub("", n).strip()
            if n:
                names[n] = names.get(n, 0) + 1
        name = max(names, key=names.get) if names else ""
        self._species[k] = name
        try:
            with open(self._species_path, "w") as f:
                json.dump(self._species, f)
        except OSError:
            pass
        return name

    def english_name(self, ja_name: str, dex_ids: list) -> str:
        """ミュウex -> Mew ex, かがやくゲッコウガ -> Radiant Greninja. Pokémon only: trainer
        and energy cards keep their printed name, with the number to identify them."""
        if not dex_ids:
            return ""
        try:
            species = " & ".join(s for s in (self.species(d) for d in dex_ids) if s)
        except Exception:  # noqa: BLE001
            return ""
        if not species:
            return ""
        pre = next((en for jp, en in self._JA_PREFIX + self._ZH_PREFIX if ja_name.startswith(jp)), "")
        m = self._SUFFIX.search(ja_name.strip())
        return " ".join(x for x in (pre, species, m.group(1) if m else "") if x)

    _JA_STRIP = re.compile(r"^(メガ|かがやく|ひかる|ダーク|ロケット団の|ヒスイ|ガラル|アローラ|パルデア|テラスタル)|"
                           r"(ex|EX|GX|VMAX|VSTAR|V-UNION|V|BREAK|LV\.X|☆|δ)$")

    def _ja_names(self):
        if not hasattr(self, "_jamap"):
            self._jamap_path = os.path.join(_cache_dir(), "species_ja_en.json")
            try:
                with open(self._jamap_path) as f:
                    self._jamap = json.load(f)
            except (OSError, ValueError):
                self._jamap = {}
        return self._jamap

    def _learn_ja(self, ja_species: str, en_species: str):
        m = self._ja_names()
        if ja_species and en_species and m.get(ja_species) != en_species:
            m[ja_species] = en_species
            try:
                with open(self._jamap_path, "w") as f:
                    json.dump(m, f, ensure_ascii=False)
            except OSError:
                pass

    def _en_from_ja(self, ja_name: str) -> str:
        """For Japanese cards without a Pokédex number: the longest known Japanese species
        name inside the card name, learned from earlier searches."""
        m = self._ja_names()
        hit = max((k for k in m if k in ja_name), key=len, default="")
        if not hit:
            return ""
        pre = next((en for jp, en in self._JA_PREFIX + self._ZH_PREFIX if ja_name.startswith(jp)), "")
        suf = self._SUFFIX.search(ja_name.strip())
        return " ".join(x for x in (pre, m[hit], suf.group(1) if suf else "") if x)

    def _dex_for(self, name: str) -> list[int]:
        """Pokédex numbers for an English name, from the English cards that carry it."""
        words = [w for w in name.lower().split() if w]
        key = max(words, key=len)
        hits = [r for r in self._resumes("en", name=key)
                if all(w in r.get("name", "").lower() for w in words)]
        hits.sort(key=lambda r: len(r.get("name", "")))
        dex = []
        for r in hits[:4]:
            try:
                d = self._get(f"{API}/en/cards/{urllib.parse.quote(r['id'])}")
            except Exception:  # noqa: BLE001
                continue
            for n in d.get("dexId") or []:
                if n not in dex:
                    dex.append(n)
            if dex:
                break
        return dex

    _FORM_WORDS = {"ex", "gx", "v", "vmax", "vstar", "v-union", "break", "lv.x", "prime", "legend",
                   "mega", "radiant", "shining", "dark", "alolan", "galarian", "hisuian", "paldean"}

    def search_japanese(self, words: list[str], number: str = "", total: str = "", limit: int = 24, lang: str = "ja"):
        """Cards in another language found by their English name: 'umbreon ex 92' finds ブラッキーex,
        or the Chinese card in the Chinese database."""
        species = [w for w in words if w.lower() not in self._FORM_WORDS]
        forms = [w.lower() for w in words if w.lower() in self._FORM_WORDS]
        if not species:
            return []
        dex = self._dex_for(" ".join(species))
        hits = []
        for n in dex:
            hits += self._resumes(lang, dexId=f"eq:{n}")
        # many Japanese cards carry no Pokédex number, so also search by the Japanese name
        # those that do have it are printed with (ルギア for Lugia), and remember the pair
        counts = {}
        for r in hits:
            nm = r.get("name", "")
            if nm and not re.search(r"[A-Za-z]{3,}", nm) and "の" not in nm and "&" not in nm:
                for _ in range(2):
                    nm = self._JA_STRIP.sub("", nm)
                counts[nm] = counts.get(nm, 0) + 1
        ja_species = max(counts, key=counts.get) if counts else ""
        if lang != "ja":
            ja_species = ""                        # learning names by kana is for Japanese only
        if ja_species and dex:
            self._learn_ja(ja_species, self.species(dex[0]))
            seen = {r["id"] for r in hits}
            hits += [r for r in self._resumes("ja", name=ja_species) if r["id"] not in seen]
        suffix = next((f for f in forms if f not in ("mega", "radiant", "shining", "dark", "alolan",
                                                      "galarian", "hisuian", "paldean")), "")
        out = []
        for r in hits:
            nm = r.get("name", "")
            if number and not self._num_eq(r.get("localId", ""), number):
                continue
            if suffix and not nm.lower().endswith(suffix):
                continue
            if suffix == "v" and re.search(r"(vmax|vstar)$", nm.lower()):
                continue
            out.append(r)
        self.sets(lang)
        with ThreadPoolExecutor(6) as ex:
            cards = [c for c in ex.map(lambda r: self._safe_card(r["id"], lang), out[:limit * 2]) if c]
        if total:
            pinned = [c for c in cards if c.set_total.lstrip("0") == total.lstrip("0")]
            cards = pinned or cards
        return cards[:limit]

    def by_number(self, number: str, total: str, lang: str = "en", limit: int = 12) -> list[CardInfo]:
        """Every card whose printed number and set total match.

        Primary route: the sets whose printed total equals the one on the card
        (usually one to three of them), then each set's card at that number,
        fetched by id. This does not depend on the API's list filters.
        """
        sets = self.sets(lang)
        num = number.strip().upper()
        tot = total.strip().upper()
        want = tot.lstrip("0") if tot.isdigit() else tot
        forms = [num]
        if num.isdigit():
            forms = list(dict.fromkeys([num, num.lstrip("0") or "0", num.zfill(2), num.zfill(3)]))
        if tot.isdigit():
            cand = [sid for sid, st in sets.items()
                    if str((st.get("cardCount") or {}).get("official") or "") == want]
        else:
            # gallery and promo numbering like TG05/TG30: no numeric total to match on
            cand = []
        ids = [f"{sid}-{f}" for sid in cand for f in forms]
        with ThreadPoolExecutor(8) as ex:
            found = [c for c in ex.map(lambda i: self._safe_card(i, lang), ids) if c]
        seen, out = set(), []
        for c in found:
            if c.id not in seen:
                seen.add(c.id)
                out.append(c)
        if out:
            return out[:limit]
        # fallback: the API's own filter, matched exactly on our side
        resumes = []
        for f in forms:
            q = urllib.parse.urlencode({"localId": f})
            try:
                resumes += self._get(f"{API}/{lang}/cards?{q}") or []
            except Exception:  # noqa: BLE001
                pass
        keep = []
        for r in resumes:
            if str(r.get("localId", "")).upper().lstrip("0") != num.lstrip("0"):
                continue
            sid = r["id"].rsplit("-", 1)[0]
            st = sets.get(sid)
            off = str((st or {}).get("cardCount", {}).get("official") or "")
            if off == want or (not tot.isdigit() and tot[:2] == num[:2]):
                keep.append(r["id"])
        keep = list(dict.fromkeys(keep))[:limit]
        with ThreadPoolExecutor(6) as ex:
            return [c for c in ex.map(lambda i: self._safe_card(i, lang), keep) if c]

    # TCG Pocket is digital-only and shares the database, so it never belongs in a paper listing
    _POCKET = re.compile(r"^(A\d+[a-z]?|B\d+[a-z]?|P-[AB])-", re.I)

    def _resumes(self, lang: str, **filters) -> list[dict]:
        q = urllib.parse.urlencode({**filters, "pagination:itemsPerPage": 250, "pagination:page": 1})
        out = self._get(f"{API}/{lang}/cards?{q}") or []
        return [r for r in out if not self._POCKET.match(r.get("id", ""))]

    @staticmethod
    def _num_eq(a: str, b: str) -> bool:
        a, b = str(a).strip().upper(), str(b).strip().upper()
        return a == b or (a.lstrip("0") or "0") == (b.lstrip("0") or "0")

    def by_name(self, name: str, lang: str = "en", limit: int = 24, number: str = "") -> list[CardInfo]:
        """Cards whose name contains every word typed, in any order, optionally at
        one collector number. Exact names rank first, then names starting with
        what was typed."""
        words = [w for w in re.split(r"\s+", name.strip().lower()) if w]
        if not words:
            return []
        # ask the API for the longest word (the most selective), filter the rest here
        key = max(words, key=len)
        filt = {"name": key}
        if number:
            filt["localId"] = number.lstrip("0") or number
        resumes = self._resumes(lang, **filt)
        if number and not resumes:          # the API matched the number too strictly
            resumes = self._resumes(lang, name=key)
        low = name.strip().lower()
        hits = [r for r in resumes
                if all(w in r.get("name", "").lower() for w in words)
                and (not number or self._num_eq(r.get("localId", ""), number))]
        def rank(r):
            n = r.get("name", "").lower()
            whole = all(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", n) for w in words)
            return (n != low, not whole, not n.startswith(low), len(n))
        hits.sort(key=rank)          # 'mew' puts Mew ex ahead of Mewtwo
        self.sets(lang)
        with ThreadPoolExecutor(6) as ex:
            return [c for c in ex.map(lambda r: self._safe_card(r["id"], lang), hits[:limit]) if c]

    def by_local_number(self, number: str, lang: str = "en", limit: int = 24) -> list[CardInfo]:
        """Only a number, no total and no name: every card printed at that number."""
        hits = [r for r in self._resumes(lang, localId=number.lstrip("0") or number)
                if self._num_eq(r.get("localId", ""), number)]
        self.sets(lang)
        with ThreadPoolExecutor(6) as ex:
            return [c for c in ex.map(lambda r: self._safe_card(r["id"], lang), hits[:limit]) if c]

    LOOSE_NUM = re.compile(r"^#?([A-Z]{0,4}\d{1,3}[A-Z]?)$", re.I)

    def search(self, query: str, lang: str = "en", game: str = "pokemon") -> list[CardInfo]:
        """Forgiving search. Any of these work:
        '185/195'  'lugia 185/195'  'lugia 185'  '185 lugia'  'lugia v'  'lugia'  '185'.
        With a full number and total the set is pinned exactly; a name and a bare
        number search every set; a name alone matches every word in any order."""
        query = query.strip()
        if not query:
            return []
        game = detect_game(query) or game
        if game == "yugioh":
            return self.ygo_search(query)
        if game == "onepiece":
            return self.op_search(query)
        if lang != "en" and re.search(r"[A-Za-z]{3,}", NUM_RE.sub("", query)):
            # typed in English: go through the Pokédex number to the cards in that language
            m = NUM_RE.search(query.upper())
            rest = NUM_RE.sub("", query) if m else query
            number, total, words = (m.group(1), m.group(2), []) if m else ("", "", [])
            for tok in rest.split():
                mm = self.LOOSE_NUM.match(tok)
                if mm and not number and re.search(r"\d", tok):
                    number = mm.group(1)
                else:
                    words.append(tok)
            found = self.search_japanese(words, number, total, lang=lang)
            if found or not number:
                return found
            return self.by_number(number, total, lang) if total else []
        m = NUM_RE.search(query.upper())
        if m:
            found = self.by_number(m.group(1), m.group(2), lang)
            rest = NUM_RE.sub("", query.upper()).strip().lower()
            words = [w for w in rest.split() if w]
            if words:
                narrowed = [c for c in found if all(w in c.name.lower() for w in words)]
                if narrowed:
                    return narrowed
                # the name does not fit that set: the total was probably misread or
                # mistyped, so trust the name and the number and search every set
                return self.by_name(" ".join(words), lang, number=m.group(1)) or found
            return found
        words, number = [], ""
        for tok in query.split():
            mm = self.LOOSE_NUM.match(tok)
            if mm and not number and re.search(r"\d", tok):
                number = mm.group(1)
            else:
                words.append(tok)
        name = " ".join(words)
        if name:
            found = self.by_name(name, lang, number=number)
            if found or not number:
                return found
            # the name was slightly off: keep the number, loosen the name to any one word
            for w in sorted(words, key=len, reverse=True):
                found = self.by_name(w, lang, number=number)
                if found:
                    return found
            return []
        return self.by_local_number(number, lang)

    # what CardCrop and most sellers append to a card's file name
    _SLUG_TAIL = re.compile(r"(_\d{2}_(front|back).*|_IG_\d+|[ _.-]+(edit(ed)?|final|copy|v\d+|\d{1,2})$)",
                            re.I)

    def from_slug(self, stem: str):
        """A file already named for its card, like 'thundurus-ex-bwp-bw81' or
        'lugia-v-swsh12-185-ja': read the set and number straight from the name
        and fetch that exact card. Returns a CardInfo, or None if the name is not
        in that form (then the photo is identified the usual way)."""
        s = stem.strip().lower()
        for _ in range(3):
            s = self._SLUG_TAIL.sub("", s).strip(" _-")
        g = detect_game(s)
        if g:                       # roronoa-zoro-op01-001, dark-magician-lob-en005
            m = (OP_CODE if g == "onepiece" else YGO_CODE).search(s.upper())
            words = s[:m.start()].replace("-", " ").replace("_", " ").strip() if m else ""
            try:
                found = self.search(f"{words} {m.group(0)}".strip(), "en", g)
            except Exception:  # noqa: BLE001
                return None
            exact = [f for f in found if f.slug() == s]
            return exact[0] if exact else (found[0] if found else None)
        lang = "en"
        for code in ("zh-tw", "zh-cn", "ja", "ko"):
            if s.endswith("-" + code):
                lang, s = code, s[:-len(code) - 1]
                break
        toks = [t for t in re.split(r"[-_ ]+", s) if t]
        if len(toks) < 3:
            return None
        sets = {k.lower(): k for k in self.sets(lang)}
        for k in range(len(toks) - 2, 0, -1):          # the set code sits just before the number
            sid = sets.get(toks[k])
            if not sid:
                continue
            num = "-".join(toks[k + 1:])
            forms = [num.upper(), num]
            if num.isdigit():
                forms += [num.lstrip("0") or "0", num.zfill(2), num.zfill(3)]
            for form in dict.fromkeys(forms):
                card = self._safe_card(f"{sid}-{form}", lang)
                if card:
                    return card
            # right set, odd number: fall back to the name and number across every set
            found = self.by_name(" ".join(toks[:k]), lang, number=num)
            return found[0] if len(found) == 1 else None
        return None

    def _safe_card(self, cid, lang):
        try:
            return self.card(cid, lang)
        except Exception:  # noqa: BLE001
            return None

    def market(self, card_id: str, lang: str = "en") -> dict:
        """TCGplayer and Cardmarket prices for one card, fetched fresh (never cached)."""
        if card_id.startswith(("ygo:", "op:")):
            return self._other_market(card_id)
        if card_id.startswith("manual:"):          # in no database: eBay is the only price there is
            return {}
        d = self._get(f"{API}/{lang}/cards/{urllib.parse.quote(card_id)}")
        p = d.get("pricing") or {}
        out = {}
        tp = p.get("tcgplayer") or {}
        for variant in ("holofoil", "normal", "reverse-holofoil", "1st-edition-holofoil", "1st-edition",
                        "unlimited-holofoil", "unlimited"):
            v = tp.get(variant)
            if isinstance(v, dict) and v.get("marketPrice"):
                out["tcgplayer"] = {"market": v["marketPrice"], "low": v.get("lowPrice"),
                                    "variant": variant, "updated": str(tp.get("updated", ""))[:10]}
                break
        cm = p.get("cardmarket") or {}
        if cm.get("trend") or cm.get("avg"):
            out["cardmarket"] = {"trend": cm.get("trend") or cm.get("avg"), "low": cm.get("low"),
                                 "updated": str(cm.get("updated", ""))[:10]}
            for k in ("avg1", "avg7", "avg30"):          # sold averages over 1, 7 and 30 days
                try:
                    if cm.get(k):
                        out["cardmarket"][k] = float(cm[k])
                except (TypeError, ValueError):
                    pass
        return out

    def image_bytes(self, info: CardInfo, quality: str = "low") -> bytes | None:
        if not info.image:
            return None
        if re.search(r"\.(jpe?g|png|webp)$", info.image, re.I):
            return self._cached_image(info.image)
        try:
            req = urllib.request.Request(f"{info.image}/{quality}.png", headers=UA)
            with urllib.request.urlopen(req, timeout=12) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            return None

    def _cached_image(self, url: str) -> bytes | None:
        """Yu-Gi-Oh! and One Piece pictures are fetched once and kept, as their hosts ask."""
        import hashlib
        d = os.path.join(_cache_dir(), "images")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, hashlib.sha1(url.encode()).hexdigest() + os.path.splitext(url)[1][:5])
        if os.path.exists(p):
            with open(p, "rb") as f:
                return f.read()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
                data = r.read()
            with open(p, "wb") as f:
                f.write(data)
            return data
        except Exception:  # noqa: BLE001
            return None

    # ---------------------------------------------------------- Yu-Gi-Oh! (YGOPRODeck)
    def _mkt(self) -> dict:
        if not hasattr(self, "_market_cache"):
            self._market_cache = {}
        return self._market_cache

    @staticmethod
    def _price(v) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    def _ygo_infos(self, card: dict, only_code: str = "") -> list[CardInfo]:
        imgs = card.get("card_images") or [{}]
        image = imgs[0].get("image_url_small") or imgs[0].get("image_url") or ""
        tcg = self._price(((card.get("card_prices") or [{}])[0]).get("tcgplayer_price"))
        out = []
        for st in card.get("card_sets") or [{}]:
            code = (st.get("set_code") or "").upper()
            if only_code and code != only_code:
                continue
            raw_rarity = st.get("set_rarity") or ""
            rarity = ygo_rarity(raw_rarity)
            cid = f"ygo:{card.get('id')}:{code}:{st.get('set_rarity_code') or raw_rarity}"
            out.append(CardInfo(id=cid, name=card.get("name", ""), number=code, set_name=st.get("set_name", ""),
                                set_id=code.split("-")[0] if code else "", rarity=rarity,
                                category=card.get("type", ""), language="en", image=image, game="yugioh"))
            price = self._price(st.get("set_price")) or tcg
            if price:
                self._mkt()[cid] = {"tcgplayer": {"market": price, "low": None, "variant": rarity,
                                                  "updated": "YGOPRODeck"}}
        return out

    def ygo_search(self, query: str, limit: int = 40) -> list[CardInfo]:
        """'dark magician', 'LOB-EN005', or both. A set code pins the exact printing."""
        q = query.strip()
        m = YGO_CODE_LOOSE.search(q.upper())
        code = m.group(0).upper() if m and re.search(r"\d{3}$", m.group(0)) else ""
        words = (q[:m.start()] + q[m.end():]).strip() if code else q
        try:
            if code:
                s = None
                pre, _, post = code.partition("-")
                # OCR mixes up O and 0 in set codes too (RAO1 for RA01): try the other readings
                import itertools
                spots = [i for i, ch in enumerate(pre) if ch in "O0"][:3]
                tries = []
                for combo in itertools.product("O0", repeat=len(spots)):
                    p = list(pre)
                    for i, ch in zip(spots, combo):
                        p[i] = ch
                    tries.append("".join(p) + "-" + post)
                tries = [code] + [t for t in tries if t != code]
                for t in tries:
                    try:
                        s = self._get(f"{YGO_API}/cardsetsinfo.php?" + urllib.parse.urlencode({"setcode": t}))
                    except urllib.error.HTTPError as e:
                        if e.code != 400:
                            raise
                        s = None
                    if s and s.get("id"):
                        code = t
                        break
                if s and s.get("id"):
                    d = self._get(f"{YGO_API}/cardinfo.php?" + urllib.parse.urlencode({"id": s["id"]}))
                    return self._dedupe([i for c in (d.get("data") or []) for i in self._ygo_infos(c, code)])[:limit]
            if not words:
                return []
            d = self._get(f"{YGO_API}/cardinfo.php?" + urllib.parse.urlencode({"fname": words, "num": 20,
                                                                               "offset": 0}))
        except urllib.error.HTTPError as e:
            if e.code == 400:             # YGOPRODeck answers 400 for "no card matching"
                return []
            raise
        cards = d.get("data") or []
        low = words.lower()
        cards.sort(key=lambda c: (c.get("name", "").lower() != low, not c.get("name", "").lower().startswith(low)))
        return self._dedupe([i for c in cards for i in self._ygo_infos(c)])[:limit]

    @staticmethod
    def _dedupe(infos):
        seen, out = set(), []
        for i in infos:
            k = (i.name, i.number, i.rarity, i.variant)
            if k not in seen:
                seen.add(k)
                out.append(i)
        return out

    # ---------------------------------------------------------- One Piece (OPTCG API)
    def _op_cards(self) -> list[dict]:
        if getattr(self, "_op", None) is not None:
            return self._op
        path = os.path.join(_cache_dir(), "onepiece_cards_v2.json")
        data = None
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
            try:
                with open(path) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = None
        if data is None:
            data = []
            for ep in ("allSetCards", "allSTCards", "allPromos", "allDonCards"):
                try:
                    part = self._get(f"{OP_API}/{ep}/", timeout=40)
                    for p in part if isinstance(part, list) else []:
                        if ep == "allDonCards":
                            p.setdefault("card_set_id", "DON")
                            p.setdefault("set_name", "DON!! Cards")
                    if isinstance(part, list):
                        data += part
                except Exception:  # noqa: BLE001
                    continue
            if not data and os.path.exists(path):        # offline: an old list beats none
                with open(path) as f:
                    data = json.load(f)
            elif data:
                try:
                    with open(path, "w") as f:
                        json.dump(data, f)
                except OSError:
                    pass
        self._op = data
        return data

    def _op_info(self, c: dict) -> CardInfo:
        raw = c.get("card_name", "")
        bits = [v.strip() for v in re.findall(r"\(([^)]*)\)", raw)]
        # (119) and (OP05-119) only repeat the code; promos name their event in brackets too
        bits = [v for v in bits if not re.fullmatch(r"\d{3}|[A-Z]{1,3}\d{0,2}-\d{3}", v, re.I)
                and not re.search(r"premium card collection|tournament|event|pack vol|celebration", v, re.I)]
        vs = []
        for v in bits:
            n = OP_VARIANTS.get(v.lower(), v)
            if n not in vs:
                vs.append(n)
        if "Alt Art" in vs and "Super Alt Art" in vs:
            vs.remove("Alt Art")
        if "Parallel" in vs and len(vs) > 1:      # "(Parallel) (Manga) (Alternate Art)" is the manga card
            vs.remove("Parallel")
        if "Manga" in vs and "Alt Art" in vs:
            vs.remove("Alt Art")
        variant = " ".join(vs)
        name = re.sub(r"\s*\([^)]*\)", "", raw).strip()
        code = (c.get("card_set_id") or "").upper()
        rarity = OP_RARITY.get((c.get("rarity") or "").upper(), c.get("rarity") or "")
        img_id = (c.get("card_image_id") or code).lower()
        cid = "op:" + code + ":" + img_id
        info = CardInfo(id=cid, name=name, number=code, set_name=c.get("set_name", ""),
                        set_id=(c.get("set_id") or "").upper(), rarity=rarity, category=c.get("card_type", ""),
                        language="en", image=c.get("card_image") or "", game="onepiece", variant=variant)
        price = self._price(c.get("market_price")) or self._price(c.get("inventory_price"))
        if price:
            m = {"tcgplayer": {"market": price, "low": self._price(c.get("inventory_price")),
                               "variant": " ".join(x for x in (rarity, variant) if x),
                               "updated": str(c.get("date_scraped") or "")}}
            self._mkt()[cid] = m
            # ids saved by CardCrop before 2.19 named the version by its words
            old = "op:" + code + ":" + re.sub(r"\W+", "-", " ".join(bits)).strip("-").lower()
            self._mkt().setdefault(old, m)
        return info

    def op_search(self, query: str, limit: int = 40) -> list[CardInfo]:
        """'zoro', 'OP01-001', or 'zoro op01'. Parallel and other versions come after the regular one."""
        q = query.strip()
        m = OP_CODE.search(q.upper())
        code = f"{m.group(1).upper()}-{m.group(2)}" if m else ""
        rest = (q[:m.start()] + q[m.end():]) if m else q
        words = [w for w in re.split(r"\s+", rest.lower()) if w]
        set_hint = next((w.upper() for w in words if re.fullmatch(r"(op|st|eb|prb)\d{2}", w)), "")
        words = [w for w in words if w.upper() != set_hint]
        # with a code, a rarity mark (SEC, SR, L...) narrows it; version words (manga, sp, parallel) too
        mark = ""
        if code:
            for w in list(words):
                if w.upper() in OP_RARITY and w.upper() not in ("SP",):
                    mark = w.upper()
                    words.remove(w)
        vwords = [w for w in words if w in {"manga", "sp", "parallel", "alt", "wanted", "gold", "spr", "tr"}]
        words = [w for w in words if w not in vwords] if code else words
        hits = []
        for c in self._op_cards():
            cid = (c.get("card_set_id") or "").upper()
            if code and cid != code:
                continue
            if set_hint and not cid.startswith(set_hint + "-"):
                continue
            n = (c.get("card_name") or "").lower()
            if not all(w in n for w in words):
                continue
            hits.append(c)
        if mark:                                    # a misread mark must not empty the list
            marked = [c for c in hits if OP_RARITY.get((c.get("rarity") or "").upper()) == OP_RARITY.get(mark)]
            hits = marked or hits
        if vwords:                                  # prefer the versions named, keep the rest after
            hits.sort(key=lambda c: -sum(v in (c.get("card_name") or "").lower() for v in vwords))
        if not code and not words and not set_hint:
            return []
        seen, out = set(), []
        if not vwords:
            hits.sort(key=lambda c: ("(" in re.sub(r"\(\d{3}\)", "", c.get("card_name", "")),
                                     c.get("card_set_id", ""), c.get("card_name", "")))
        for c in hits:
            info = self._op_info(c)
            if info.id in seen:
                continue
            seen.add(info.id)
            out.append(info)
            if len(out) >= limit:
                break
        return out

    def rank_by_image(self, photo: np.ndarray, infos: list, limit: int = 16) -> list:
        """Orders candidates by how closely their database picture matches the photo, so the
        alternate art, manga or parallel version actually photographed comes first. Each gets
        its score in .match; candidates past the limit, or with no picture, keep their order after."""
        head, tail = infos[:limit], infos[limit:]
        if len(head) < 2 or photo is None:
            return infos

        def score(i):
            try:
                data = self.image_bytes(i, "low")
                pic = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
                return image_match(photo, pic) if pic is not None else -2.0
            except Exception:  # noqa: BLE001
                return -2.0
        from engine import to8
        photo = to8(photo)
        with ThreadPoolExecutor(6) as ex:
            scores = list(ex.map(score, head))
        for i, sc in zip(head, scores):
            i.match = round(sc, 3)
        order = sorted(range(len(head)), key=lambda k: -scores[k])
        return [head[k] for k in order] + tail

    @staticmethod
    def sure_match(infos: list) -> bool:
        """True when the photo picks out one picture clearly: a strong match well ahead of the next
        different picture. Printings that share a picture (one code in two rarities) never count."""
        if not infos or infos[0].match < 0.55:
            return False
        nxt = next((i for i in infos[1:] if i.image != infos[0].image), None)
        same_pic = [i for i in infos[1:] if i.image == infos[0].image]
        return not same_pic and (nxt is None or infos[0].match - nxt.match >= 0.12)

    def _other_market(self, card_id: str) -> dict:
        got = self._mkt().get(card_id)
        if got is None:
            try:
                if card_id.startswith("op:"):
                    self.op_search(card_id.split(":")[1], limit=60)
                else:
                    self.ygo_search(card_id.split(":")[2])
            except Exception:  # noqa: BLE001
                pass
            got = self._mkt().get(card_id, {})
        return dict(got)
