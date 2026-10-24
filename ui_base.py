"""CardCrop look: theme tokens, the style sheet, type sizes, fonts and the drawn icons.

set_theme and set_ui_pt rebind T, BG, STYLE, BASE_PT and the rest here, so other parts read
them as ui_base.X (imported as TH) rather than copying them at import."""
from __future__ import annotations

import cv2
import engine
import math
import numpy as np
import os
import sys
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QPushButton

# ------------------------------------------------------------------ look
# Islands on a pale ground (or a near-black one), pills for controls, Geist for words,
# Geist Mono for file names and figures, Doto for the few numbers worth a glance.
THEMES = {
    "light": dict(ground="#E4E4E1", island="#F6F6F4", island2="#FFFFFF", pill="#EAEAE7", hover="#DEDEDA",
                  text="#111112", muted="#66666C", faint="#A1A1A6", ink="#111112", ink_text="#F6F6F4",
                  line="#E0E0DC", need="#C2610C", ok="#16924F", warn="#C2410C", back="#9A9A9F"),
    "dark": dict(ground="#0A0A0B", island="#161618", island2="#232327", pill="#1F1F22", hover="#2A2A2E",
                 text="#EDEDEF", muted="#9D9DA5", faint="#55555C", ink="#F2F2EF", ink_text="#111112",
                 line="#26262A", need="#F5A524", ok="#38E07B", warn="#FF6B4A", back="#3A3A40"),
}
T = dict(THEMES["light"])
THEME = "light"
LIME = "#D6F24B"           # the one thing to do next
HANDLE = "#FFD400"         # handles and the card outline: yellow reads on any mat
CANVAS = "#18181A"         # the photo always sits on graphite, whatever the theme
HUD_TEXT = "#E6E6E8"
STATUS = {"ready": "#2BB673", "need": "#F08C1B", "live": "#3B82F6", "draft": "#8B5CF6",
          "unpub": "#3B82F6", "idle": "#A1A1A6", "error": "#E5484D",
          "sold": "#16924F"}
ACCENT = HANDLE
BG, PANEL, TEXT, MUTED = T["ground"], T["island"], T["text"], T["muted"]
OK, WARN = T["ok"], T["warn"]
BASE_PT = 12
DEFAULT_PT = 12
ICON_PX = 30          # icon buttons: square, small
SANS, MONO, DOTS = "Geist", "Geist Mono", "Doto"

TIPS_CORNERS = ("Corners: drag each corner · wheel zooms · drag empty space to pan · "
                "click a corner, then arrows nudge (Shift = 10 px)")
TIPS_SHAPE = ("Card shape: drag a corner to resize · Cmd resizes from the centre · "
              "drag just outside a corner to rotate · drag inside to move · M for free corners")


def load_fonts():
    """Registers the bundled typefaces; falls back to the system font if missing."""
    from PySide6.QtGui import QFontDatabase
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for f in ("Geist.ttf", "GeistMono.ttf", "Doto.ttf"):
        p = os.path.join(base, "fonts", f)
        if os.path.exists(p):
            QFontDatabase.addApplicationFont(p)


def _check_svg(color):
    """The tick inside a checked box, drawn as a small SVG once per colour (Qt style sheets take
    an image, not a path)."""
    import os
    try:
        base = os.path.expanduser("~/Library/Application Support/CardCrop")
        if not os.path.isdir(os.path.dirname(base)):
            base = os.path.expanduser("~/.cardcrop")
        os.makedirs(base, exist_ok=True)
        p = os.path.join(base, f"check_{color.strip('#')}.svg")
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f:
                f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16">'
                        f'<path d="M6.5 12.5l3.5 3.5 7.5-8" fill="none" stroke="{color}" stroke-width="2.6" '
                        'stroke-linecap="round" stroke-linejoin="round"/></svg>')
        return p.replace("\\", "/")
    except OSError:
        return ""


def make_style(pt):
    t = T
    return f"""
* {{ color: {t['text']}; font-family: '{SANS}'; font-size: {pt}pt; }}
QMainWindow, QWidget#root {{ background: {t['ground']}; }}
QDialog {{ background: {t['island']}; }}
QFrame#island {{ background: {t['island']}; border-radius: 22px; }}
QFrame#panel {{ background: {t['island']}; border-radius: 22px; }}
QFrame#canvas {{ background: {CANVAS}; border-radius: 22px; }}
QFrame#card2 {{ background: {t['island2']}; border-radius: 16px; }}
QFrame#row {{ background: transparent; border-radius: 16px; }}
QFrame#row[sel="true"] {{ background: {t['island2']}; }}
QFrame#row:hover {{ background: {t['pill']}; }}
QLabel#h {{ font-size: {pt + 2}pt; font-weight: 600; }}
QLabel#display {{ font-size: {pt + 13}pt; font-weight: 500; }}
QLabel#title2 {{ font-size: {pt + 26}pt; font-weight: 500; }}
QLabel#muted {{ color: {t['muted']}; }}
QLabel#small {{ color: {t['muted']}; font-size: {pt - 1}pt; }}
QLabel#mono {{ font-family: '{MONO}'; color: {t['muted']}; font-size: {pt - 1}pt; }}
QLabel#monotext {{ font-family: '{MONO}'; }}
QLabel#dot {{ font-family: '{DOTS}'; font-weight: 800; font-size: {pt + 20}pt; }}
QLabel#dotneed {{ font-family: '{DOTS}'; font-weight: 800; font-size: {pt + 20}pt; color: {t['need']}; }}
QLabel#dotbig {{ font-family: '{DOTS}'; font-weight: 800; font-size: {pt + 28}pt; }}
QLabel#dotneedbig {{ font-family: '{DOTS}'; font-weight: 800; font-size: {pt + 28}pt; color: {t['need']}; }}
QLabel#tag {{ background: {LIME}; color: #111; border-radius: 9px; padding: 2px 8px; font-size: {pt - 2}pt;
             font-weight: 700; }}
QPushButton {{ background: {t['pill']}; border: none; border-radius: 15px; padding: 7px 14px; font-weight: 500; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:checked {{ background: {t['ink']}; color: {t['ink_text']}; font-weight: 600; }}
QPushButton:disabled {{ color: {t['faint']}; }}
QPushButton#primary {{ background: {t['ink']}; color: {t['ink_text']}; border-radius: 25px; padding: 14px 20px;
                      font-size: {pt + 2}pt; font-weight: 500; }}
QPushButton#primary:disabled {{ background: {t['pill']}; color: {t['faint']}; }}
QPushButton#accent {{ background: {LIME}; color: #111; font-weight: 600; }}
QPushButton#accent:disabled {{ background: {t['pill']}; color: {t['faint']}; }}
QPushButton#chip {{ background: {t['pill']}; color: {t['text']}; border-radius: 13px; padding: 5px 11px;
    font-size: {pt - 1}pt; }}
QPushButton#chip:hover {{ background: {t['line']}; }}
QPushButton#chip:disabled {{ color: {t['muted']}; }}
QPushButton#ghost {{ background: transparent; color: {t['muted']}; }}
QPushButton#ghost:hover {{ background: {t['pill']}; color: {t['text']}; }}
QPushButton#icon {{ background: transparent; padding: 0; border-radius: 12px; }}
QPushButton#icon:hover {{ background: {t['pill']}; }}
QPushButton#icon:checked {{ background: {t['pill']}; }}
QPushButton#seg {{ background: transparent; color: {t['muted']}; border-radius: 12px; padding: 7px 10px; }}
QPushButton#seg:checked {{ background: {t['island2']}; color: {t['text']}; }}
QPushButton#cond {{ border-radius: 16px; padding: 8px 0; font-weight: 600; }}
QPushButton#cond:disabled {{ color: {t['muted']}; }}
QPushButton#cond:checked:disabled {{ background: {t['ink']}; color: {t['ink_text']}; }}
QPushButton#stage {{ background: transparent; color: {t['muted']}; border-radius: 16px; padding: 8px 0 6px;
                    font-size: {pt - 1}pt; }}
QPushButton#stage:checked {{ background: {t['pill']}; color: {t['text']}; font-weight: 600; }}
QToolButton#stage {{ background: transparent; color: {t['muted']}; border: none; border-radius: 16px;
                    padding: 6px 0 4px; font-size: {pt - 1}pt; }}
QToolButton#stage:hover {{ background: {t['pill']}; }}
QToolButton#stage:checked {{ background: transparent; color: {t['text']}; font-weight: 600; }}
QLabel#dotmuted {{ font-family: '{DOTS}'; font-weight: 800; font-size: {pt + 10}pt; color: {t['muted']}; }}
QFrame#hline {{ background: {t['line']}; border: none; }}
QFrame#segbox {{ background: {t['pill']}; border-radius: 15px; }}
QFrame#hud {{ background: rgba(24,24,26,205); border: 1px solid rgba(255,255,255,22); border-radius: 18px; }}
QFrame#hud QLabel {{ color: {HUD_TEXT}; }}
QFrame#hud QLabel#mono {{ color: #A6A6AD; }}
QFrame#hud QToolButton#tray {{ background: transparent; color: #8E8E95; border: none; border-radius: 12px;
    padding: 6px 2px 4px; font-size: {max(7, pt - 4)}pt; font-weight: 500; }}
QFrame#hud QToolButton#tray:hover {{ background: rgba(255,255,255,24); color: {HUD_TEXT}; }}
QFrame#hud QToolButton#tray:pressed {{ background: rgba(255,255,255,40); }}
QFrame#hud QToolButton#tray:checked {{ background: {LIME}; color: #111; }}
QFrame#hud QToolButton#tray::menu-indicator {{ image: none; width: 0; }}
QFrame#hud QPushButton {{ background: transparent; color: {HUD_TEXT}; border-radius: 12px; padding: 6px 10px; }}
QFrame#hud QPushButton:hover {{ background: rgba(255,255,255,28); }}
QFrame#hud QPushButton:checked {{ background: {HANDLE}; color: #111; }}
QFrame#hud QPushButton#hudprimary {{ background: {LIME}; color: #111; font-weight: 600; padding: 6px 16px; }}
QFrame#hud QPushButton#hudprimary:hover {{ background: #E2FA6A; }}
QFrame#hud QComboBox {{ background: rgba(255,255,255,20); color: {HUD_TEXT}; }}
QFrame#hud QComboBox QAbstractItemView {{ background: #1E1E22; color: {HUD_TEXT}; border: 1px solid #3A3A40;
                                         selection-background-color: rgba(255,255,255,34);
                                         selection-color: {HUD_TEXT}; outline: 0; padding: 4px; }}
QFrame#hud QCheckBox {{ color: {HUD_TEXT}; }}
QFrame#hud QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; background: rgba(255,255,255,40); border: 1px solid rgba(255,255,255,60); }}
QFrame#hud QCheckBox::indicator:checked {{ background: {HANDLE}; border-color: {HANDLE}; }}
QLabel#hudchip {{ background: {LIME}; color: #111; border-radius: 11px; padding: 3px 10px;
                 font-family: '{MONO}'; font-size: {pt - 1}pt; font-weight: 600; }}
QFrame#toast {{ background: {t['ink']}; border-radius: 18px; }}
QFrame#toast QLabel {{ color: {t['ink_text']}; }}
QFrame#toast QPushButton {{ background: {t['ink_text']}; color: {t['ink']}; border-radius: 15px; padding: 6px 14px; }}
QFrame#toast QPushButton#icon {{ background: transparent; }}
QFrame#actionbar {{ background: #111112; border-radius: 28px; }}
QFrame#actionbar QLabel {{ color: #F2F2EF; }}
QFrame#actionbar QLabel#mono {{ color: #B5B5BB; }}
QFrame#actionbar QPushButton {{ background: #26262A; color: #F2F2EF; border-radius: 21px; padding: 0 20px; }}
QFrame#actionbar QPushButton:hover {{ background: #303035; }}
QFrame#actionbar QPushButton#accent {{ background: {LIME}; color: #111; font-weight: 600; }}
QFrame#actionbar QPushButton:disabled {{ color: #66666C; }}
QFrame#actionbar QPushButton#accent:disabled {{ background: #3A3A3F; color: #8A8A90; }}
QLineEdit {{ background: {t['pill']}; border: 1px solid transparent; border-radius: 13px; padding: 6px 12px;
            selection-background-color: {LIME}; selection-color: #111; }}
QLineEdit:focus {{ background: {t['island2']}; border: 1px solid {t['ink']}; }}
QLineEdit#bare {{ background: transparent; border: 1px solid transparent; padding: 4px 0; }}
QLineEdit#bare:focus {{ background: transparent; border: 1px solid transparent; border-bottom: 1px solid {t['ink']}; }}
QLineEdit#slug {{ font-family: '{MONO}'; font-size: {pt - 1}pt; }}
QComboBox {{ background: {t['pill']}; border: none; border-radius: 13px; padding: 6px 12px; }}
QComboBox:hover {{ background: {t['hover']}; }}
QComboBox:disabled {{ color: {t['faint']}; }}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox QAbstractItemView {{ background: {t['island2']}; border: 1px solid {t['line']}; outline: 0;
                              selection-background-color: {t['pill']}; selection-color: {t['text']}; padding: 4px; }}
QComboBox#tile {{ background: transparent; padding: 0; font-family: '{DOTS}'; font-weight: 800;
                 font-size: {pt + 14}pt; }}
QComboBox#tile::drop-down {{ width: 0; }}
QAbstractSpinBox {{ background: {t['pill']}; border: 1px solid transparent; border-radius: 13px; padding: 6px 0;
                   selection-background-color: {LIME}; selection-color: #111; }}
QAbstractSpinBox:focus {{ border: 1px solid {t['ink']}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow {{ image: none; width: 0; height: 0; }}
QAbstractSpinBox QLineEdit, QAbstractSpinBox QLineEdit:focus {{ background: transparent; border: none; padding: 0 12px; }}
QDoubleSpinBox#bigprice QLineEdit, QDoubleSpinBox#bigprice QLineEdit:focus {{ padding: 0; }}
QDoubleSpinBox#bigprice {{ background: transparent; border: none; padding: 0; font-family: '{DOTS}';
                          font-weight: 800; font-size: {pt + 30}pt; }}
QDoubleSpinBox#bigprice QLineEdit {{ selection-background-color: {LIME}; selection-color: #111; }}
QDoubleSpinBox#rowprice {{ font-family: '{MONO}'; font-weight: 500; }}
QSlider {{ min-height: 20px; }}
QProgressBar {{ background: {t['pill']}; border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: {t['ink']}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: {t['pill']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['ink']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t['island2']}; border: 2px solid {t['ink']}; width: 12px;
                             margin: -6px 0; border-radius: 8px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; background: {t['pill']};
                       border: 1px solid {t['line']}; }}
QCheckBox::indicator:checked {{ background: {t['ink']}; border-color: {t['ink']}; image: url("{_check_svg(t['ink_text'])}"); }}
QCheckBox::indicator:hover {{ border-color: {t['muted']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle {{ background: {t['line']}; border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {t['faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0;
    background: transparent; }}
QToolTip {{ background: {t['ink']}; color: {t['ink_text']}; border: none; padding: 3px 7px; border-radius: 6px;
            font-size: {max(9, pt - 3)}pt; }}
QMenu {{ background: {t['island2']}; border: 1px solid {t['line']}; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 8px; }}
QMenu::item:selected {{ background: {t['pill']}; }}
QMenu::separator {{ height: 1px; background: {t['line']}; margin: 5px 8px; }}
QListWidget {{ background: {t['island']}; border: none; border-radius: 16px; padding: 4px; outline: 0; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 10px; }}
QListWidget::item:selected {{ background: {t['pill']}; color: {t['text']}; }}
QListWidget#film {{ background: transparent; padding: 0; }}
QListWidget#film::item, QListWidget#film::item:selected {{ background: transparent; padding: 0; }}
QTableWidget {{ background: {t['island2']}; gridline-color: {t['line']}; border: none; border-radius: 14px; }}
QHeaderView::section {{ background: {t['island2']}; color: {t['muted']}; border: none; padding: 8px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {t['muted']}; padding: 6px 10px; }}
QTabBar::tab:selected {{ color: {t['text']}; }}
QStatusBar {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
"""


STYLE = make_style(BASE_PT)
UI_PT_RANGE = (9, 20)
_ICONS = []     # (weakref to button, icon name, colour role) so icons follow the theme


def _icon_color(role):
    return {"text": T["text"], "ink": T["ink_text"], "muted": T["muted"], "hud": HUD_TEXT}.get(role, role)


def _apply_app_style():
    app = QApplication.instance()
    if app is not None:
        app.setFont(QFont(SANS, BASE_PT))
        app.setStyleSheet(STYLE)


def set_ui_pt(pt):
    """Changes the type size everywhere: the app style, its default font, and the
    module values that dialogs and painted labels read when they are built."""
    global BASE_PT, STYLE
    BASE_PT = max(UI_PT_RANGE[0], min(UI_PT_RANGE[1], int(pt)))
    STYLE = make_style(BASE_PT)
    _apply_app_style()
    return BASE_PT


def set_theme(name):
    """Light or dark: swaps the tokens, the style and every themed icon."""
    global T, THEME, BG, PANEL, TEXT, MUTED, OK, WARN, STYLE
    THEME = name if name in THEMES else "light"
    T = dict(THEMES[THEME])
    BG, PANEL, TEXT, MUTED = T["ground"], T["island"], T["text"], T["muted"]
    OK, WARN = T["ok"], T["warn"]
    STYLE = make_style(BASE_PT)
    _apply_app_style()
    alive = []
    for ref, name_, role in _ICONS:
        b = ref()
        if b is None:
            continue
        try:
            b.setIcon(make_icon(name_, 40, _icon_color(role)))
        except RuntimeError:
            continue
        alive.append((ref, name_, role))
    _ICONS[:] = alive
    return THEME


def to_qimage(img: np.ndarray) -> QImage:
    img = engine.to8(img)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def subprocess_reveal(path):
    """Select a file in Finder (or open its folder elsewhere)."""
    import subprocess
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ editor
def _rotate_cursor():
    """A curved double arrow, like Figma's rotate cursor, drawn so it reads on any photo."""
    from PySide6.QtGui import QCursor
    pm = QPixmap(36, 36)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.arcMoveTo(QRectF(7, 7, 22, 22), 200)
    path.arcTo(QRectF(7, 7, 22, 22), 200, -220)
    for pen in (QPen(QColor("#000"), 5, Qt.SolidLine, Qt.RoundCap), QPen(QColor("#FFF"), 2.2, Qt.SolidLine, Qt.RoundCap)):
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    ends = [path.pointAtPercent(0), path.pointAtPercent(1)]
    tangents = [path.angleAtPercent(0) + 180, path.angleAtPercent(1)]
    for pt, ang in zip(ends, tangents):
        r = math.radians(ang)
        tip = QPointF(pt.x() + 5 * math.cos(r), pt.y() - 5 * math.sin(r))
        l = QPointF(pt.x() + 5 * math.cos(r + 2.4), pt.y() - 5 * math.sin(r + 2.4))
        rr = QPointF(pt.x() + 5 * math.cos(r - 2.4), pt.y() - 5 * math.sin(r - 2.4))
        for pen, brush in ((QPen(QColor("#000"), 3), QColor("#000")), (QPen(QColor("#FFF"), 1), QColor("#FFF"))):
            p.setPen(pen)
            p.setBrush(brush)
            p.drawPolygon(QPolygonF([tip, l, rr]))
    p.end()
    return QCursor(pm, 18, 18)


def make_icon(name, size=40, color="#FFFFFF"):
    """Line icons drawn in code, in the spirit of Imaging Edge's controls,
    so they stay crisp at any size and need no image files."""
    from PySide6.QtGui import QIcon
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2 * size / 40, 2 * size / 40)        # draw on a 40 x 40 grid
    if name.startswith("svg:"):                  # a line icon given as SVG paths on a 24 grid, as the phone draws them
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QByteArray
        p.end()
        pm.fill(Qt.transparent)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
               f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{name[4:]}</svg>')
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg.encode())).render(p)
        p.end()
        pm.setDevicePixelRatio(2.0)
        return QIcon(pm)
    pen = QPen(QColor(color), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if name == "shutter":
        p.drawRoundedRect(QRectF(6, 12, 28, 20), 4, 4)
        p.drawRect(QRectF(14, 8, 12, 4))
        p.drawEllipse(QPointF(20, 22), 6, 6)
    elif name == "af":
        p.drawEllipse(QPointF(20, 20), 15, 15)
        f = p.font(); f.setPixelSize(13); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(5, 5, 30, 30), Qt.AlignCenter, "AF")
    elif name == "live":
        p.drawRoundedRect(QRectF(5, 9, 30, 22), 3, 3)
        p.setBrush(QColor("#FF5A4A")); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(11, 15), 3, 3)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        f = p.font(); f.setPixelSize(9); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(10, 17, 24, 12), Qt.AlignCenter, "LIVE")
    elif name in ("rot_left", "rot_right"):
        left = name == "rot_left"
        path = QPainterPath()
        start = 30 if left else 150
        path.arcMoveTo(QRectF(7, 9, 26, 26), start)
        path.arcTo(QRectF(7, 9, 26, 26), start, 250 if left else -250)
        p.drawPath(path)
        tip = path.pointAtPercent(1.0)
        ang = math.radians(path.angleAtPercent(1.0))
        d = QPointF(math.cos(ang), -math.sin(ang))          # direction of travel at the tip
        n = QPointF(-d.y(), d.x())
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([tip + d * 6, tip - d * 2 + n * 5, tip - d * 2 - n * 5]))
        p.setPen(pen); p.setBrush(Qt.NoBrush)
    elif name == "magnify":
        p.drawEllipse(QPointF(17, 17), 10, 10)
        p.drawLine(QPointF(24.5, 24.5), QPointF(34, 34))
        p.drawLine(QPointF(12, 17), QPointF(22, 17)); p.drawLine(QPointF(17, 12), QPointF(17, 22))
    elif name == "grid":
        p.drawRect(QRectF(6, 6, 28, 28))
        for t in (15.33, 24.66):
            p.drawLine(QPointF(t, 6), QPointF(t, 34)); p.drawLine(QPointF(6, t), QPointF(34, t))
        thin = QPen(QColor(color), 1.3); p.setPen(thin)
        p.drawLine(QPointF(6, 6), QPointF(34, 34)); p.drawLine(QPointF(34, 6), QPointF(6, 34))
    elif name == "overlay":
        p.setPen(QPen(QColor(color), 2.6, Qt.DashLine))
        p.drawRoundedRect(QRectF(11, 5, 18, 30), 2, 2)
        p.setPen(pen)
        for x, y in ((11, 5), (29, 5), (29, 35), (11, 35)):
            p.drawEllipse(QPointF(x, y), 2.5, 2.5)
    elif name == "match":
        p.drawEllipse(QPointF(20, 20), 12, 12)
        p.drawEllipse(QPointF(20, 20), 4, 4)
        for a, b in (((20, 3), (20, 10)), ((20, 30), (20, 37)), ((3, 20), (10, 20)), ((30, 20), (37, 20))):
            p.drawLine(QPointF(*a), QPointF(*b))
    elif name == "reset":
        path = QPainterPath()
        path.arcMoveTo(QRectF(8, 8, 24, 24), 60)
        path.arcTo(QRectF(8, 8, 24, 24), 60, 300)
        p.drawPath(path)
        end = path.currentPosition()
        p.drawLine(end, end + QPointF(-7, 0)); p.drawLine(end, end + QPointF(-1, -7))
    elif name == "settings":
        for y, x in ((11, 26), (20, 14), (29, 22)):
            p.drawLine(QPointF(6, y), QPointF(34, y))
            p.setBrush(QColor(BG)); p.drawEllipse(QPointF(x, y), 3.5, 3.5); p.setBrush(Qt.NoBrush)
    elif name == "sidebar":
        p.drawRoundedRect(QRectF(5, 8, 30, 24), 3, 3)
        p.drawLine(QPointF(15, 8), QPointF(15, 32))
        for y in (14, 19, 24):
            p.drawLine(QPointF(8.5, y), QPointF(11.5, y))
    elif name == "add":
        p.drawRoundedRect(QRectF(6, 6, 28, 28), 4, 4)
        p.drawLine(QPointF(20, 12), QPointF(20, 28)); p.drawLine(QPointF(12, 20), QPointF(28, 20))
    elif name == "trash":
        p.drawLine(QPointF(7, 11), QPointF(33, 11))
        p.drawPolyline(QPolygonF([QPointF(15, 11), QPointF(16, 6), QPointF(24, 6), QPointF(25, 11)]))
        p.drawPolyline(QPolygonF([QPointF(10, 11), QPointF(12, 34), QPointF(28, 34), QPointF(30, 11)]))
        p.drawLine(QPointF(17, 17), QPointF(17, 28)); p.drawLine(QPointF(23, 17), QPointF(23, 28))
    elif name == "search":
        p.drawEllipse(QPointF(17, 17), 10, 10)
        p.drawLine(QPointF(24.5, 24.5), QPointF(34, 34))
    elif name == "detect":
        for x, y, dx, dy in ((6, 6, 1, 1), (34, 6, -1, 1), (34, 34, -1, -1), (6, 34, 1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + 8 * dx, y)); p.drawLine(QPointF(x, y), QPointF(x, y + 8 * dy))
        p.drawRoundedRect(QRectF(14, 11, 12, 18), 2, 2)
    elif name == "fit":
        p.drawRoundedRect(QRectF(12, 10, 16, 20), 2, 2)
        for a, b_ in (((6, 6), (11, 11)), ((34, 6), (29, 11)), ((34, 34), (29, 29)), ((6, 34), (11, 29))):
            p.drawLine(QPointF(*a), QPointF(*b_))
    elif name == "shape":
        p.drawRoundedRect(QRectF(11, 6, 18, 28), 3, 3)
        f = p.font(); f.setPixelSize(9); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(11, 6, 18, 28), Qt.AlignCenter, "63")
    elif name == "copy":
        p.drawRoundedRect(QRectF(14, 13, 19, 22), 3, 3)
        p.drawPolyline(QPolygonF([QPointF(9, 27), QPointF(7, 27), QPointF(7, 5), QPointF(26, 5), QPointF(26, 8)]))
    elif name == "save":
        p.drawRoundedRect(QRectF(7, 7, 26, 26), 3, 3)
        p.drawRect(QRectF(13, 7, 14, 8))
        p.drawRect(QRectF(12, 22, 16, 11))
    elif name == "more":
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        for x in (10, 20, 30):
            p.drawEllipse(QPointF(x, 20), 3, 3)
    elif name == "info":
        p.drawEllipse(QPointF(20, 20), 14, 14)
        p.drawLine(QPointF(20, 18), QPointF(20, 28))
        p.setBrush(QColor(color)); p.drawEllipse(QPointF(20, 12.5), 1.2, 1.2)
    elif name == "close":
        p.drawLine(QPointF(11, 11), QPointF(29, 29)); p.drawLine(QPointF(29, 11), QPointF(11, 29))
    elif name == "report":                   # centering: a card's four corners framed round a crosshair
        for x, y, dx, dy in ((8, 6, 1, 1), (32, 6, -1, 1), (8, 34, 1, -1), (32, 34, -1, -1)):
            p.drawPolyline(QPolygonF([QPointF(x, y + 7 * dy), QPointF(x, y), QPointF(x + 7 * dx, y)]))
        p.drawLine(QPointF(20, 14), QPointF(20, 26))
        p.drawLine(QPointF(14, 20), QPointF(26, 20))
    elif name == "trend":
        p.drawPolyline(QPolygonF([QPointF(5, 29), QPointF(14, 20), QPointF(21, 26), QPointF(34, 12)]))
        p.drawPolyline(QPolygonF([QPointF(26, 12), QPointF(34, 12), QPointF(34, 20)]))
        p.drawLine(QPointF(5, 34), QPointF(35, 34))
    elif name == "store":
        p.drawPolyline(QPolygonF([QPointF(6, 15), QPointF(9, 7), QPointF(31, 7), QPointF(34, 15)]))
        path = QPainterPath()
        path.moveTo(6, 15)
        for k in range(4):
            x = 6 + k * 7
            path.arcTo(QRectF(x, 11.5, 7, 7), 180, 180)
        p.drawPath(path)
        p.drawPolyline(QPolygonF([QPointF(8, 19), QPointF(8, 33), QPointF(32, 33), QPointF(32, 19)]))
        p.drawRect(QRectF(16, 24, 8, 9))
    elif name == "camera":
        p.drawRoundedRect(QRectF(5, 12, 30, 21), 5, 5)
        p.drawPolyline(QPolygonF([QPointF(14, 12), QPointF(16.5, 7), QPointF(23.5, 7), QPointF(26, 12)]))
        p.drawEllipse(QPointF(20, 22.5), 6, 6)
    elif name == "edit":
        p.drawPolygon(QPolygonF([QPointF(10, 7), QPointF(32, 11), QPointF(29.5, 33), QPointF(8, 32)]))
        p.setBrush(QColor(color))
        for x, y in ((10, 7), (32, 11), (29.5, 33), (8, 32)):
            p.drawEllipse(QPointF(x, y), 2.4, 2.4)
        p.setBrush(Qt.NoBrush)
    elif name == "list":
        for y in (11, 20, 29):
            p.drawRoundedRect(QRectF(6, y - 2.5, 5, 5), 1.5, 1.5)
            p.drawLine(QPointF(16, y), QPointF(34, y))
    elif name == "sun":
        p.drawEllipse(QPointF(20, 20), 6, 6)
        for k in range(8):
            a = math.radians(k * 45)
            p.drawLine(QPointF(20 + 10 * math.cos(a), 20 + 10 * math.sin(a)),
                       QPointF(20 + 14 * math.cos(a), 20 + 14 * math.sin(a)))
    elif name == "moon":
        path = QPainterPath()
        path.addEllipse(QPointF(20, 20), 13, 13)
        cut = QPainterPath()
        cut.addEllipse(QPointF(27, 14), 11, 11)
        p.drawPath(path.subtracted(cut))
    elif name == "back":
        p.drawPolyline(QPolygonF([QPointF(24, 9), QPointF(13, 20), QPointF(24, 31)]))
    elif name == "next":
        p.drawLine(QPointF(8, 20), QPointF(32, 20))
        p.drawPolyline(QPolygonF([QPointF(22, 10), QPointF(32, 20), QPointF(22, 30)]))
    elif name == "upload":
        p.drawLine(QPointF(20, 28), QPointF(20, 8))
        p.drawPolyline(QPolygonF([QPointF(12, 15), QPointF(20, 7), QPointF(28, 15)]))
        p.drawLine(QPointF(8, 33), QPointF(32, 33))
    elif name == "cube":
        top = [QPointF(20, 5), QPointF(33, 12.5), QPointF(20, 20), QPointF(7, 12.5)]
        p.drawPolygon(QPolygonF(top))
        p.drawPolyline(QPolygonF([QPointF(7, 12.5), QPointF(7, 27.5), QPointF(20, 35), QPointF(33, 27.5),
                                  QPointF(33, 12.5)]))
        p.drawLine(QPointF(20, 20), QPointF(20, 35))
    elif name == "rec":
        p.drawEllipse(QPointF(20, 20), 14, 14)
        p.setBrush(QColor("#E5484D")); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(20, 20), 8, 8)
    elif name == "stop":
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(11, 11, 18, 18), 3, 3)
    elif name == "film":
        p.drawRoundedRect(QRectF(6, 9, 28, 22), 4, 4)
        p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(17, 14.5), QPointF(25, 20), QPointF(17, 25.5)]))
    elif name == "plug":
        p.drawRoundedRect(QRectF(10, 14, 20, 14), 3, 3)
        p.drawLine(QPointF(15, 8), QPointF(15, 14)); p.drawLine(QPointF(25, 8), QPointF(25, 14))
        p.drawLine(QPointF(20, 28), QPointF(20, 35))
    p.end()
    pm.setDevicePixelRatio(2.0)
    return QIcon(pm)


def icon_button(name, tip, size=None, primary=False, text="", role=None):
    """A small square icon button (or icon plus a short word when text is given);
    the shortcut and the full meaning live in the tooltip. Its icon follows the theme."""
    import weakref
    from PySide6.QtCore import QSize
    size = size or ICON_PX
    role = role or ("ink" if primary else "text")
    b = QPushButton(text)
    b.setIcon(make_icon(name, 40, _icon_color(role)))
    _ICONS.append((weakref.ref(b), name, role))
    b.setIconSize(QSize(int(size * .6), int(size * .6)))
    if primary:
        b.setObjectName("primary")
    elif not text:
        b.setObjectName("icon")
    if text:
        b.setFixedHeight(size)
    else:
        b.setFixedSize(size, size)
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


SIGNS = [(-1, -1), (1, -1), (1, 1), (-1, 1)]   # TL, TR, BR, BL in card axes
