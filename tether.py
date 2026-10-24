"""Live tethering to a Sony camera through crbridge (see tether/crbridge.cpp).

The bridge is a separate process speaking one JSON object per line, so a
camera or SDK fault can never take CardCrop down with it.
"""
from __future__ import annotations

import base64
import json
import os
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtGui import QImage

BRIDGE_DIR = os.path.expanduser("~/Library/Application Support/CardCrop/tether")
RAW_EXTS = (".arw", ".srf", ".sr2", ".dng")


def bridge_path() -> str | None:
    for p in (os.environ.get("CARDCROP_BRIDGE"), os.path.join(BRIDGE_DIR, "crbridge")):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def captures_dir() -> str:
    import datetime
    d = os.path.join(os.path.expanduser("~/Pictures/CardCrop Captures"), datetime.date.today().isoformat())
    os.makedirs(d, exist_ok=True)
    return d


# ------------------------------------------------------------------ value formatting
RANGE_BIT, SIGN_BIT = 0x4000, 0x1000

MODES = {1: "M", 2: "P", 3: "A", 4: "S", 0x8000: "Auto", 0x8001: "Auto+"}
WB = {0x0000: "Auto", 0x0011: "Daylight", 0x0012: "Shade", 0x0013: "Cloudy", 0x0014: "Tungsten",
      0x0020: "Fluorescent", 0x0021: "Fluor. warm", 0x0022: "Fluor. cool", 0x0023: "Fluor. day white",
      0x0024: "Fluor. daylight", 0x0030: "Flash", 0x0100: "Kelvin", 0x0101: "Custom 1",
      0x0102: "Custom 2", 0x0103: "Custom 3", 0x0104: "Custom"}
FOCUS = {1: "MF", 2: "AF-S", 3: "AF-C", 4: "AF-A", 5: "AF-D", 6: "DMF", 7: "PF"}
AREA = {1: "Wide", 2: "Zone", 3: "Center", 4: "Spot S", 5: "Spot M", 6: "Spot L", 7: "Expand spot",
        8: "Spot", 0x11: "Track wide", 0x12: "Track zone", 0x13: "Track center", 0x14: "Track spot S",
        0x15: "Track spot M", 0x16: "Track spot L", 0x17: "Track expand", 0x18: "Track spot",
        0x19: "Spot XS", 0x1A: "Spot XL"}
FILETYPE = {1: "JPEG", 2: "RAW", 3: "RAW+JPEG", 4: "RAW+HEIF", 5: "HEIF"}
QUALITY = {1: "Light", 2: "Standard", 3: "Fine", 4: "Extra fine"}
DEST = {1: "Mac only", 2: "Card only", 3: "Mac + card"}


def _signed(v: int, ptype: int) -> int:
    width = {1: 8, 2: 16, 3: 32, 4: 64}.get(ptype & 0xF, 64)
    v &= (1 << width) - 1
    return v - (1 << width) if v >= 1 << (width - 1) else v


def fmt(key: str, v: int, ptype: int = 0) -> str:
    if key == "fnumber":
        return "--" if v >= 0xFFFD else f"f/{v / 100:g}"
    if key == "shutter":
        if v == 0:
            return "Bulb"
        if v == 0xFFFFFFFF:
            return "--"
        num, den = v >> 16, v & 0xFFFF
        if den == 0:
            return "--"
        if num >= den:
            return f'{num / den:g}"'
        return f"1/{den / num:g}" if num else "--"
    if key == "iso":
        base, mode = v & 0xFFFFFF, (v >> 24) & 0xF
        txt = "ISO Auto" if base == 0xFFFFFF else f"ISO {base}"
        return txt + (" MFNR" if mode in (1, 2) else "")
    if key == "ev":
        return f"{_signed(v, 2) / 1000:+.1f} EV".replace("+0.0", "±0.0")
    if key == "kelvin":
        return f"{v} K" if v else "--"
    if key == "battery":
        return f"Battery {v}%"
    table = {"mode": MODES, "wb": WB, "focus": FOCUS, "area": AREA, "filetype": FILETYPE,
             "quality": QUALITY, "dest": DEST}.get(key)
    if table is not None:
        return table.get(v, f"0x{v:X}")
    return str(v)


def options(prop: dict) -> list[int]:
    """The selectable raw values for a property, expanding min/max/step ranges."""
    vals, ptype = list(prop.get("values") or []), int(prop.get("type", 0))
    if ptype & RANGE_BIT and len(vals) >= 3:
        lo, hi, step = vals[0], vals[1], max(1, vals[2])
        if prop["key"] == "kelvin":
            step = max(step, 100)
        n = (hi - lo) // step + 1
        if n > 400:                         # keep the menu usable
            step = (hi - lo) // 399
        return list(range(lo, hi + 1, step))
    if prop["key"] == "ev":
        vals = sorted(vals, key=lambda x: _signed(x, ptype))
    return vals


# ------------------------------------------------------------------ client
class Tether(QObject):
    status = Signal(str)          # human-readable progress or problems
    connected = Signal(str)       # model name
    disconnected = Signal()
    props = Signal(dict)          # key -> property dict (only the ones that changed)
    frame = Signal(QImage)
    focus = Signal(str)           # focused / failed / idle
    shot = Signal()
    file = Signal(str)            # a capture to load (RAW preferred when both arrive)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc: QProcess | None = None
        self.buf = b""
        self.is_connected = False
        self.model = ""
        self.state: dict[str, dict] = {}
        self.prefer_raw = True
        self._pending: dict[str, list[str]] = {}    # stem -> paths arriving for one shot
        self._flush = QTimer(self, singleShot=True, interval=1500)
        self._flush.timeout.connect(self._release_files)

    # ---------------------------------------------------------- process
    def available(self) -> bool:
        return bridge_path() is not None

    def start(self) -> bool:
        if self.proc is not None:
            return True
        path = bridge_path()
        if not path:
            self.status.emit("Camera bridge not installed: run tether/build_tether.sh once (see README)")
            return False
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(os.path.dirname(path))
        self.proc.setProcessChannelMode(QProcess.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.readyReadStandardError.connect(self._stderr)
        self.proc.finished.connect(self._ended)
        self.proc.start(path, [])
        if not self.proc.waitForStarted(5000):
            self.status.emit("The camera bridge would not start; re-run tether/build_tether.sh")
            self.proc = None
            return False
        return True

    def send(self, **cmd):
        if self.proc is None:
            return
        self.proc.write((json.dumps(cmd) + "\n").encode())

    def connect_camera(self):
        if self.start():
            self.send(cmd="connect", path=captures_dir())

    def disconnect_camera(self):
        self.send(cmd="disconnect")

    def stop(self):
        if self.proc is None:
            return
        self.send(cmd="quit")
        if not self.proc.waitForFinished(10000):     # the bridge waits for in-flight shots
            self.proc.kill()
        self.proc = None

    # ---------------------------------------------------------- commands
    def live(self, on: bool):
        self.send(cmd="lv", on=bool(on))

    def set(self, key: str, value: int):
        self.send(cmd="set", prop=key, value=int(value))

    def autofocus(self):
        self.send(cmd="af")

    def shoot(self, af: bool = True):
        self.send(cmd="shoot", af=bool(af))

    # ---------------------------------------------------------- events
    def _stderr(self):
        data = bytes(self.proc.readAllStandardError()).decode("utf-8", "replace").strip()
        if data:
            print("[crbridge]", data, file=sys.stderr)

    def _read(self):
        self.buf += bytes(self.proc.readAllStandardOutput())
        *lines, self.buf = self.buf.split(b"\n")
        last_frame = None
        for raw in lines:
            if not raw.strip():
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if ev.get("ev") == "frame":
                last_frame = ev            # only the newest frame is worth drawing
                continue
            self._handle(ev)
        if last_frame is not None:
            img = QImage.fromData(base64.b64decode(last_frame["jpg"]), "JPG")
            if not img.isNull():
                self.frame.emit(img)

    def _handle(self, ev: dict):
        kind = ev.get("ev")
        if kind == "status":
            self.status.emit(ev.get("msg", ""))
        elif kind == "error":
            self.status.emit(ev.get("msg", "Camera error"))
        elif kind == "connected":
            self.is_connected, self.model = True, ev.get("model", "camera")
            self.connected.emit(self.model)
        elif kind == "disconnected":
            self.is_connected = False
            self.disconnected.emit()
        elif kind == "props":
            changed = {p["key"]: p for p in ev.get("props", [])}
            self.state.update(changed)
            self.props.emit(changed)
        elif kind == "focus":
            self.focus.emit(ev.get("state", "idle"))
        elif kind == "shot":
            self.shot.emit()
        elif kind == "file":
            path = ev.get("path", "")
            if path:
                stem = os.path.splitext(path)[0]
                self._pending.setdefault(stem, []).append(path)
                self._flush.start()           # wait briefly for the RAW/JPEG sibling

    def _release_files(self):
        for stem, paths in self._pending.items():
            raws = [p for p in paths if p.lower().endswith(RAW_EXTS)]
            others = [p for p in paths if p not in raws]
            pick = (raws or others) if self.prefer_raw else (others or raws)
            if pick:
                self.file.emit(pick[0])
        self._pending.clear()

    def _ended(self, *_):
        was = self.is_connected
        self.is_connected = False
        self.proc = None
        if was:
            self.disconnected.emit()
            self.status.emit("Camera bridge stopped")
