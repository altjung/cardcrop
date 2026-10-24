"""Small chimes for the moments that matter: a card captured, exported, listed.

The sounds are made here, not shipped: soft bell tones (a few sine partials with a quick attack and a
long ring) written once as WAV files into CardCrop's cache, then played without waiting. On a Mac they
play through afplay, which every Mac has; elsewhere through Qt Multimedia when it is there, or not at all.
"""
from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
import wave

RATE = 44100

# each chime: (start in seconds, frequency in Hz, loudness) per note
CHIMES = {
    # captured: one light, high ding, like a camera's confirm
    "capture": [(0.0, 1567.98, 0.55)],                                     # G6
    # exported: two notes rising, done and saved
    "export": [(0.0, 1046.50, 0.5), (0.11, 1567.98, 0.55)],               # C6, G6
    # listed: a little sparkle, up an arpeggio
    "listed": [(0.0, 1046.50, 0.42), (0.09, 1318.51, 0.45), (0.18, 1567.98, 0.48),
               (0.27, 2093.00, 0.5)],                                      # C6 E6 G6 C7
}
# a bell's partials: frequency multiple, loudness, how fast it dies away
PARTIALS = [(1.0, 1.0, 4.5), (2.0, 0.32, 7.0), (3.01, 0.12, 10.0), (4.17, 0.05, 14.0)]


def _render(notes, seconds=1.1) -> bytes:
    n = int(RATE * seconds)
    buf = [0.0] * n
    for start, f, amp in notes:
        s0 = int(start * RATE)
        for i in range(n - s0):
            t = i / RATE
            attack = min(1.0, t / 0.004)                    # a soft strike, no click
            v = 0.0
            for mult, a, decay in PARTIALS:
                v += a * math.exp(-decay * t) * math.sin(2 * math.pi * f * mult * t)
            buf[s0 + i] += amp * attack * v
    peak = max(1e-6, max(abs(x) for x in buf))
    k = 0.42 / peak                                         # quiet: a chime, not an alert
    fade = int(0.05 * RATE)
    for i in range(fade):                                   # end on silence
        buf[n - 1 - i] *= i / fade
    return b"".join(struct.pack("<h", int(max(-1.0, min(1.0, x * k)) * 32767)) for x in buf)


def _path(kind: str) -> str:
    import identify
    d = os.path.join(identify._cache_dir(), "sounds")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{kind}_v1.wav")
    if not os.path.exists(p):
        with wave.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(_render(CHIMES[kind]))
    return p


_effects = {}


def play(kind: str, volume: float = 0.7) -> None:
    """Plays a chime without waiting. Never raises: a missing sound is never worth an error."""
    if kind not in CHIMES:
        return
    try:
        p = _path(kind)
        if sys.platform == "darwin":
            subprocess.Popen(["afplay", "-v", f"{volume:.2f}", p], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QSoundEffect
        e = _effects.get(kind)
        if e is None:
            e = QSoundEffect()
            e.setSource(QUrl.fromLocalFile(p))
            _effects[kind] = e
        e.setVolume(volume)
        e.play()
    except Exception:  # noqa: BLE001
        pass
