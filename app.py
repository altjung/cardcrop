"""CardCrop: flatten trading card photos and cut corner close-ups for eBay.

Run:  python app.py  [files or folders ...]

The window (Main) is built here and its behaviour is split by job into mixins: main_shoot,
main_queue, main_session, main_ebay, main_reports and main_export. The parts it is made of
are in the ui_*.py files beside it:
ui_base (theme, type, icons), ui_widgets (shared controls and charts), ui_tasks (background
work), ui_editor (the corner editor), ui_live (live view), ui_dialogs, ui_store, ui_list,
ui_market, ui_reports and ui_viewer3d.

Checks: python tests/run.py (every check runs offscreen with a private home folder).
"""
from __future__ import annotations

APP_VERSION = "3.14.0"  # see CHANGELOG.md

import cv2
import ebay
import engine
import identify
import json
import listing
import numpy as np
import os
import re
import sys
import tether
import traceback
from PySide6.QtCore import QItemSelectionModel, QRectF, QSettings, QThreadPool, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit, QListWidget, QMainWindow, QMenu, QPushButton, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget
from engine import FORMATS, Job, Settings

from main_shoot import ShootMixin
from main_queue import QueueMixin
from main_session import SessionMixin
from main_pipeline import PipelineMixin
from main_ebay import EbayMixin
from main_reports import ReportsMixin
from main_export import ExportMixin
from ui_base import DEFAULT_PT, HUD_TEXT, LIME, TIPS_CORNERS, _ICONS, _icon_color, icon_button, load_fonts, make_icon, set_theme, set_ui_pt
from ui_editor import Editor
from ui_list import ListPage
from ui_live import GRIDS, GRID_WIDTHS, LiveView
from ui_market import MarketPage
from ui_reports import ReportsPage, TrackingPage
from ui_store import StorePage, _StageShim
from ui_viewer3d import SHOW_3D, Viewer3D
from ui_widgets import AutoLabel, ImageLabel, Island, Notice, PageStack, PillFilter, PriceBox, TileDelegate, _logo_pixmap, dot_label, hud, labeled_slider
import ui_base as TH
import ui_motion as motion
from ui_marks import BorderGlow, PipelineHud


class Main(ShootMixin, QueueMixin, PipelineMixin, SessionMixin, EbayMixin, ReportsMixin, ExportMixin, QMainWindow):
    PREVIEW_MAX = 1800   # long edge of the proxy used for live previews

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CardCrop")
        self._pills = PillFilter(self)
        QApplication.instance().installEventFilter(self._pills)
        self.cfg = getattr(self, "cfg", None) or QSettings("CardCrop", "CardCrop")
        motion.set_motion(str(self.cfg.value("motion", "true")).lower() in ("true", "1"))
        self._press = motion.PressFilter(self)          # a ripple from every button you press
        QApplication.instance().installEventFilter(self._press)
        scr = QApplication.primaryScreen()
        avail = scr.availableGeometry() if scr else None
        if avail is not None:      # start inside the screen, whatever its size
            self.resize(min(2000, avail.width() - 40), min(1177, avail.height() - 40))
        else:
            self.resize(2000, 1177)
        geom = QSettings("CardCrop", "CardCrop").value("window_geom")
        if geom is not None:       # the size and place you left it at, through closes and rebuilds
            try:
                self.restoreGeometry(geom)
            except Exception:  # noqa: BLE001
                pass
        self.cfg = QSettings("CardCrop", "CardCrop")
        self.settings = Settings(
            lens_k1=float(self.cfg.value("lens_k1", 0.0)),
            lens_profile=str(self.cfg.value("lens_profile", "")),
            lens_raw_only=self.cfg.value("lens_raw_only", "true") in (True, "true"),
            lens_fit=str(self.cfg.value("lens_fit", "") or ""),
            flatten=self.cfg.value("flatten", "true") in (True, "true"),
            corner_frac=float(self.cfg.value("corner_frac", 0.30)),
            lock_ratio=self.cfg.value("lock_ratio", "true") in (True, "true"),
            out_format=str(self.cfg.value("out_format", "png")),
            margin_px=int(self.cfg.value("margin_px", 20)),
            corner_px=int(self.cfg.value("corner_px", 1600)),
            auto_portrait=self.cfg.value("auto_portrait", "true") in (True, "true"),
            hero=self.cfg.value("hero", "true") in (True, "true"),
            grade=False,                     # condition reports are made on request, never at export
            hero_bg=str(self.cfg.value("hero_bg", "light")),
            # Back in hero (3.8.8) unticked meant the front alone
            hero_sides=str(self.cfg.value("hero_sides", "both" if self.cfg.value("hero_back", "true") in (True, "true")
                                          else "front")),
            ig=self.cfg.value("ig", "true") in (True, "true"),
            corners=self.cfg.value("corners", "true") in (True, "true"),
            detail=float(self.cfg.value("detail", 0.5)),
        )
        ebay.UPLOAD_LONG_EDGE = int(self.cfg.value("ebay_px", 1600))
        try:
            c = json.loads(str(self.cfg.value("ig_crop", "")) or "null")
            if c and len(c) == 3:
                self.settings.ig_crop = tuple(float(x) for x in c)
        except ValueError:
            pass
        self.spots = {}
        for i in range(1, 5):
            try:
                v = json.loads(str(self.cfg.value(f"spot_{i}", "")) or "null")
                if v:
                    self.spots[i] = np.array(v, np.float32)
            except ValueError:
                pass
        self.last_quad = None          # corners of the last card you confirmed
        self.last_size = None
        self.next_name, self.next_side = "", "front"
        self.next_info = None
        self.db = identify.Database()
        self.tether = tether.Tether(self)
        self.tether.status.connect(self._cam_status)
        self.tether.connected.connect(self._cam_connected)
        self.tether.disconnected.connect(self._cam_disconnected)
        self.tether.props.connect(self._cam_props)
        self.tether.frame.connect(self._cam_frame)
        self.tether.focus.connect(self._cam_focus)
        self.tether.shot.connect(lambda: self.statusBar().showMessage("Shot taken, transferring…"))
        self.tether.file.connect(self._cam_file)
        self.title_overrides = {}       # card name -> edited title
        self.measure_timer = QTimer(self, singleShot=True, interval=150)
        self.measure_timer.timeout.connect(self.measure_current)
        for k in engine.EDIT_KEYS:
            setattr(self.settings, k, float(self.cfg.value(k, 0.0)))
        self.out_dir = str(self.cfg.value("out_dir", os.path.join(os.path.expanduser("~"), "CardCrop Output")))
        self.jobs: list[Job] = []
        self.cur: Job | None = None
        self.proxy = None          # (small image, scale) for fast previews
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max(1, min(3, (os.cpu_count() or 2) - 1)))
        self._build()
        self.setAcceptDrops(True)
        self.preview_timer = QTimer(self, singleShot=True, interval=40)
        self.preview_timer.timeout.connect(self.update_preview)

    # --- layout
    def _build(self):
        from PySide6.QtWidgets import QScrollArea
        from PySide6.QtCore import QSize
        root = QWidget(objectName="root")
        self.root = root
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)
        self.statusBar().hide()                 # messages show in a pill on the canvas instead
        self.stage = "edit"
        self.stack = _StageShim(self)
        self._batch_state = {}
        self._sugg_cache = {}
        self._sugg_pending = set()
        self.sum_timer = QTimer(self, singleShot=True, interval=120)
        self.sum_timer.timeout.connect(self._update_summary)

        def scrolled(w):
            sa = QScrollArea()
            sa.setWidget(w)
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            return sa

        def act(keys, fn):
            a = QAction(self)
            if isinstance(keys, (list, tuple)):
                a.setShortcuts([QKeySequence(k) for k in keys])
            else:
                a.setShortcut(QKeySequence(keys))
            a.triggered.connect(fn)
            self.addAction(a)
            return a

        def isl(kind="island", m=(20, 18, 20, 18), spacing=12, vertical=True):
            f = Island(kind)
            v = QVBoxLayout(f) if vertical else QHBoxLayout(f)
            v.setContentsMargins(*m)
            v.setSpacing(spacing)
            return f, v

        def row(*ws, spacing=8):
            h = QHBoxLayout()
            h.setSpacing(spacing)
            for w in ws:
                if w is None:
                    h.addStretch(1)
                elif isinstance(w, QLayout):
                    h.addLayout(w)
                else:
                    h.addWidget(w)
            return h

        # ================================================================ rail
        rail, rv = isl(m=(10, 18, 10, 16), spacing=6)
        rail.setFixedWidth(84)
        logo = QLabel(objectName="logo")
        logo.setPixmap(_logo_pixmap(34))
        logo.setFixedSize(34, 34)
        rv.addWidget(logo, 0, Qt.AlignHCenter)
        rv.addSpacing(20)
        self.stage_btns = {}
        for key, label, icon, tip in (("shoot", "Shoot", "camera", "Shoot with the camera  (L)"),
                                      ("edit", "Edit", "edit", "Crop and identify  (E)"),
                                      ("view3d", "3D", "cube", "The card in 3D, and 360° videos  (D)"),
                                      ("list", "List", "list", "Price and list the batch  (Cmd+L)"),
                                      ("store", "Store", "store", "Your eBay sales and listings  (Cmd+Y)"),
                                      ("market", "Market", "trend", "Price movers and alerts for your cards  (Shift+Cmd+M)"),
                                      ("reports", "Reports", "report", "Centering for grading, and condition reports"),
                                      ("ship", "Ship", "svg:<path d='M3 7h11v9H3z'/><path d='M14 10h4l3 3v3h-7'/>"
                                       "<circle cx='7' cy='17.5' r='1.8'/><circle cx='17' cy='17.5' r='1.8'/>",
                                       "Shipments: tracking for your sales and your own numbers  (Shift+Cmd+S)")):
            b = QToolButton(objectName="stage")
            b.setText(label)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIcon(make_icon(icon, 40, _icon_color("text")))
            import weakref
            _ICONS.append((weakref.ref(b), icon, "text"))
            b.setIconSize(QSize(22, 22))
            b.setFixedSize(64, 58)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            rv.addWidget(b, 0, Qt.AlignHCenter)
            self.stage_btns[key] = b
        rv.addStretch(1)
        b_cmd = icon_button("search", "Commands  (Cmd+K)", 44)
        b_cmd.setObjectName("")
        b_cmd.clicked.connect(self.open_palette)
        rv.addWidget(b_cmd, 0, Qt.AlignHCenter)
        b_set = QToolButton(objectName="stage")
        b_set.setText("Settings")
        b_set.setToolTip("Tracking, output, eBay and app settings  (Cmd+,)")
        b_set.setCheckable(True)
        b_set.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b_set.setIcon(make_icon("settings", 40, _icon_color("text")))
        import weakref as _wr
        _ICONS.append((_wr.ref(b_set), "settings", "text"))
        b_set.setIconSize(QSize(22, 22))
        b_set.setFixedSize(64, 58)
        b_set.setCursor(Qt.PointingHandCursor)
        b_set.clicked.connect(lambda: self.go("settings"))
        rv.addWidget(b_set, 0, Qt.AlignHCenter)
        self.stage_btns["settings"] = b_set
        self.theme_btn = icon_button("moon" if TH.THEME == "light" else "sun", "Light or dark", 44)
        self.theme_btn.clicked.connect(self.toggle_theme)
        rv.addWidget(self.theme_btn, 0, Qt.AlignHCenter)
        # on a short screen the rail drops its labels, and past that it scrolls, so it never
        # makes the window taller than the screen
        self.rail, self._rail_logo_gap = rail, rv
        self._rail_btns = list(self.stage_btns.values())
        rail_sa = QScrollArea()
        rail_sa.setWidgetResizable(True)
        rail_sa.setFrameShape(QFrame.NoFrame)
        rail_sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rail_sa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rail_sa.setFixedWidth(84)
        rail_sa.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
        rail_sa.setWidget(rail)
        self.rail_sa = rail_sa
        self.rail_pill = motion.RailPill(rail)           # the marker that glides to the current stage
        self._rail_full = rail.minimumSizeHint().height()
        self._rail_compact = False
        lay.addWidget(rail_sa)

        self.stages = PageStack()
        lay.addWidget(self.stages, 1)

        # ================================================================ EDIT
        edit = QWidget()
        eh = QHBoxLayout(edit)
        eh.setContentsMargins(0, 0, 0, 0)
        eh.setSpacing(12)
        center = QVBoxLayout()
        center.setSpacing(12)
        self.canvas_isl = Island("canvas")
        cl = QVBoxLayout(self.canvas_isl)
        cl.setContentsMargins(6, 6, 6, 6)
        self.editor = Editor()
        self.editor.field_idx = int(self.cfg.value("loupe_field", 1)) % len(Editor.FIELDS)
        self.editor.about_to_change.connect(self.push_undo)
        self.editor.changed.connect(self.on_edit)
        self.editor.committed.connect(self.on_commit)
        cl.addWidget(self.editor)

        self.title = QLabel("Drop card photos to start", objectName="monotext")
        self.conf_lbl = QLabel("")
        self.cent_lbl = QLabel("Centering –", objectName="hudchip")
        b_cc = icon_button("copy", "Copy the centering", 26, role="hud")
        b_cc.clicked.connect(self.copy_centering)
        self.hud_file = self.canvas_isl.float_widget(hud(self.title, margins=(14, 7, 14, 7)), "tl")
        self.hud_conf = self.canvas_isl.float_widget(hud(self.conf_lbl, self.cent_lbl, b_cc, margins=(14, 4, 4, 4)),
                                                     "tr")
        tools = []
        for text, fn, key, ic in (("Auto-detect", self.redetect, "R", "detect"),
                                  ("Rotate 90°", self.rotate, "T", "rot_right"),
                                  ("Fit view", self.editor.fit, "F", "fit")) + (
                                  (("See the card in 3D", lambda: self.open_3d(), "D", "cube"),) if SHOW_3D else ()):
            b = icon_button(ic, f"{text}  ({key})", 40, role="hud")
            b.clicked.connect(fn)
            tools.append(b)
            act(key, fn)
        tools.append("|")
        self.mode_corners = icon_button("edit", "Free corners: fix perspective  (M)", 40, role="hud")
        self.mode_shape = icon_button("shape", "Locked 63 × 88 card shape  (M)", 40, role="hud")
        for b, mode in ((self.mode_corners, "corners"), (self.mode_shape, "shape")):
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, md=mode: self._pick_mode(md))
            tools.append(b)
        self.mode_btn = self.mode_shape
        b = icon_button("match", "Snap to the card shape  (C)", 40, role="hud")
        b.clicked.connect(self.card_shape)
        act("C", self.card_shape)
        tools.append(b)
        b = icon_button("magnify", "Loupe size  (Z)", 40, role="hud")
        b.clicked.connect(self.cycle_loupe)
        tools.append(b)
        tools.append("|")
        self.spot_btns = []
        for i in range(1, 5):
            b = QPushButton(str(i))
            b.setFixedSize(40, 30)
            b.setToolTip(f"Spot {i}: press {i} to jump, Cmd+{i} or Shift+click to save these corners")
            b.clicked.connect(lambda _=False, i=i: self.spot_clicked(i))
            tools.append(b)
            self.spot_btns.append(b)
            for seq, fn in ((str(i), self.apply_spot), (f"Ctrl+{i}", self.save_spot)):
                act(seq, lambda _=False, i=i, fn=fn: fn(i))
        self.tools_row = self.canvas_isl.float_widget(hud(*tools, vertical=True, margins=(6, 8, 6, 8), spacing=2),
                                                      "l")

        # result picture-in-picture
        pip = QFrame(objectName="hud")
        pv = QVBoxLayout(pip)
        pv.setContentsMargins(12, 10, 12, 12)
        pv.setSpacing(8)
        self.out_dims = QLabel("", objectName="mono")
        pv.addLayout(row(QLabel("Result"), None, self.out_dims))
        pr = QHBoxLayout()
        pr.setSpacing(8)
        self.card_lbl = ImageLabel(130)
        self.card_lbl.setFixedSize(96, 132)
        pr.addWidget(self.card_lbl)
        cg = QGridLayout()
        cg.setSpacing(6)
        self.corner_lbls = []
        for k, name in enumerate(["Top left", "Top right", "Bottom left", "Bottom right"]):
            il = ImageLabel(56)
            il.setFixedSize(62, 62)
            il.setToolTip(name)
            cg.addWidget(il, k // 2, k % 2)
            self.corner_lbls.append(il)
        pr.addLayout(cg)
        pv.addLayout(pr)
        for lbl in self.corner_lbls:
            lbl.setVisible(self.settings.corners)
        self.pip = self.canvas_isl.float_widget(pip, "br")
        eh_ = QLabel("Drop card photos or a folder here")
        eh_.setStyleSheet(f"color:{HUD_TEXT}; font-size:{TH.BASE_PT + 6}pt; font-weight:500;")
        eh2 = QLabel("JPG, PNG, TIFF, HEIC, Sony ARW and other RAW · or connect the camera in Shoot")
        eh2.setStyleSheet("color:#8A8A90;")
        self.empty_hint = QFrame()
        ehv = QVBoxLayout(self.empty_hint)
        ehv.setSpacing(6)
        ehv.addWidget(eh_, 0, Qt.AlignHCenter)
        ehv.addWidget(eh2, 0, Qt.AlignHCenter)
        self.canvas_isl.float_widget(self.empty_hint, "c")
        self.status_lbl = QLabel("")
        self.status_lbl.setMaximumWidth(460)
        self.hud_status = self.canvas_isl.float_widget(hud(self.status_lbl, margins=(14, 7, 14, 7)), "bl")
        self.hud_status.hide()
        self.tips = QLabel(TIPS_CORNERS)
        self.tips.hide()
        center.addWidget(self.canvas_isl, 1)

        # filmstrip
        film, fv = isl(m=(8, 8, 12, 8), spacing=8, vertical=False)
        film.setFixedHeight(TileDelegate.H + 22)
        self.listw = QListWidget(objectName="film")
        self.listw.setFlow(QListWidget.LeftToRight)
        self.listw.setWrapping(False)
        self.listw.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.listw.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.listw.setItemDelegate(TileDelegate(self.listw))
        self.strip_pulse = motion.StripPulse(self.listw.viewport())
        self.strip_pulse.keep = lambda: any(x.quad is None and not x.error or getattr(x, "id_bg", False)
                                            for x in self.jobs)
        self.listw.setMouseTracking(True)
        self.listw.setUniformItemSizes(True)
        self.listw.currentRowChanged.connect(self.select)
        self.listw.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.listw.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listw.customContextMenuRequested.connect(self._film_menu)
        for key in ("Backspace", "Delete", "Ctrl+Backspace"):
            sc = QShortcut(QKeySequence(key), self.listw)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(self.remove_selected)
        fv.addWidget(self.listw, 1)
        self.film_empty = QLabel("Your photos line up here", objectName="muted")
        fv.addWidget(self.film_empty, 1)
        side_tools = QVBoxLayout()
        side_tools.setSpacing(6)
        b_add = icon_button("add", "Add photos…")
        b_add.clicked.connect(self.add_dialog)
        b_clear = icon_button("trash", "Clear the list (your files stay). Select photos and press Delete to "
                                       "remove just those; Cmd+Z brings them back")
        b_clear.clicked.connect(self.clear_jobs)
        side_tools.addLayout(row(b_add, b_clear, spacing=4))
        self.c_carousel_mode = QPushButton("Carousel only")
        self.c_carousel_mode.setCheckable(True)
        self.c_carousel_mode.setToolTip("Every photo writes only its Instagram slides, with no eBay files. Your "
                                        "crop, rotation and tone edits are used; with the tone sliders at zero, "
                                        "an already edited photo is left as it is")
        self.c_carousel_mode.setChecked(self.cfg.value("carousel_mode", "false") in (True, "true"))
        self.c_carousel_mode.toggled.connect(self.set_carousel_mode)
        side_tools.addWidget(self.c_carousel_mode)
        fv.addLayout(side_tools)
        self.left_panel = film
        center.addWidget(film)
        eh.addLayout(center, 1)

        # right column: the card, or one settings section at a time
        self.rcol = QStackedWidget()
        self.rcol.setFixedWidth(348)
        eh.addWidget(self.rcol)
        p0 = QWidget()
        c0 = QVBoxLayout(p0)
        c0.setContentsMargins(0, 0, 0, 0)
        c0.setSpacing(12)
        st, sv = isl(m=(20, 14, 16, 14), spacing=8, vertical=False)
        self.stat_lbls = {}
        for key, cap in (("ready", "ready"), ("need", "need you"), ("live", "on eBay")):
            box = QVBoxLayout()
            box.setSpacing(0)
            n = QLabel("00", objectName="dotneed" if key == "need" else "dot")
            box.addWidget(n)
            box.addWidget(QLabel(cap, objectName="small"))
            sv.addLayout(box, 1)
            self.stat_lbls[key] = n
        self.b_next_warn = QPushButton("Next ⚠")
        self.b_next_warn.setToolTip("Jump to the next photo that needs something before it can be listed")
        self.b_next_warn.clicked.connect(self.next_attention)
        self.b_next_warn.hide()
        sv.addWidget(self.b_next_warn, 0, Qt.AlignVCenter)
        self.batch_lbl = QLabel("")
        self.batch_lbl.hide()
        c0.addWidget(st)

        ci, cv = isl(spacing=12)
        self.strip_id = QLabel("No card", objectName="display")
        self.strip_id.setWordWrap(True)
        self.card_meta = QLabel("", objectName="small")
        self.card_meta.setWordWrap(True)
        idv = QVBoxLayout()
        idv.setSpacing(4)
        idv.addWidget(self.strip_id)
        idv.addWidget(self.card_meta)
        # the identified card's language, editable without identifying it again
        self.b_lang = QPushButton("English ▾", objectName="seg")
        self.b_lang.setToolTip("The language this card is printed in: it goes in the title and item specifics")
        lm = QMenu(self.b_lang)
        for k_, lab_ in identify.LANGS.items():
            lm.addAction(lab_, lambda k__=k_: self.set_card_language(k__))
        self.b_lang.setMenu(lm)
        self.b_lang.hide()
        idv.addWidget(self.b_lang, 0, Qt.AlignLeft)
        self.card_num = QLabel("", objectName="dot")
        self.card_num.setStyleSheet(f"font-size:{TH.BASE_PT + 8}pt;")
        cv.addLayout(row(idv, None, self.card_num))
        self.card_lbl_info = AutoLabel("", objectName="small")
        self.card_lbl_info.setWordWrap(True)
        cv.addWidget(self.card_lbl_info)
        self.card_lbl_info.hide()
        self.b_en = QPushButton("Add the English name", objectName="accent")
        self.b_en.setToolTip("CardCrop found no English name for this Japanese card; eBay listings stay English")
        self.b_en.clicked.connect(self.set_english_name)
        self.b_en.hide()
        cv.addWidget(self.b_en)
        self.name_edit = QLineEdit(objectName="slug")
        self.name_edit.setPlaceholderText("card-name-number  (Enter exports)")
        self.name_edit.setToolTip("The folder and file name for this card; Enter exports")
        self.name_edit.textEdited.connect(self.on_name)
        self.name_edit.returnPressed.connect(self.export_current)
        self.id_btn = icon_button("search", "Search for the card by name or number  (I)", 32)
        self.id_btn.setObjectName("")
        self.id_btn.clicked.connect(self.open_identify)
        self.b_read = QPushButton("Identify")
        self.b_read.setFixedHeight(32)
        self.b_read.setToolTip("Read the card number and look it up again; with several photos selected in the "
                               "strip, reads them all  (Shift+I)")
        self.b_read.clicked.connect(self.identify_now)
        cv.addLayout(row(self.name_edit, self.b_read, self.id_btn, spacing=6))
        self.b_sides = QPushButton("Fronts and backs…", objectName="ghost")
        self.b_sides.setToolTip("Every photo still to export as a tile: mark fronts and backs, pair them, read again")
        self.b_sides.clicked.connect(lambda: self.sort_sides())
        seg = QFrame(objectName="segbox")
        sg = QHBoxLayout(seg)
        sg.setContentsMargins(4, 4, 4, 4)
        sg.setSpacing(4)
        self.seg_side = {}
        for side in ("front", "back"):
            b = QPushButton(side.title(), objectName="seg")
            b.setCheckable(True)
            b.setToolTip("Front or back of the card  (B)")
            b.clicked.connect(lambda _=False, sd=side: self._pick_side(sd))
            sg.addWidget(b, 1)
            self.seg_side[side] = b
        cv.addWidget(seg)
        cv.addWidget(self.b_sides, 0, Qt.AlignLeft)
        self.side_btn = QPushButton()          # kept for older code paths; the segmented pair is what shows
        self.side_btn.hide()
        self.cond_cap = QLabel("Condition", objectName="small")
        cv.addWidget(self.cond_cap)
        self.cond_row = QWidget()
        cr_ = QHBoxLayout(self.cond_row)
        cr_.setContentsMargins(0, 0, 0, 0)
        cr_.setSpacing(6)
        self.cond_btns = {}
        for i, code in enumerate(listing.CONDITIONS, 1):
            b = QPushButton(code, objectName="cond")
            b.setCheckable(True)
            b.setToolTip(f"{listing.CONDITIONS[code][0]}  (Alt+{i}); click again to clear. Set on the back.")
            b.clicked.connect(lambda _=False, c=code: self.set_condition(c))
            cr_.addWidget(b, 1)
            self.cond_btns[code] = b
            act(f"Alt+{i}", lambda _=False, c=code: self.set_condition(c))
        cv.addWidget(self.cond_row)
        self.grade_lbl = QLabel("", objectName="small")
        self.grade_lbl.setWordWrap(True)
        self.grade_lbl.setTextFormat(Qt.RichText)
        self.grade_lbl.setToolTip("What the condition report measured from the exported photos")
        self.grade_lbl.hide()
        cv.addWidget(self.grade_lbl)
        self.b_report = QPushButton("Condition report")
        self.b_report.setToolTip("Measure this card from its photos and preview the report  (Ctrl+R)")
        self.b_report.clicked.connect(lambda: self.condition_report())
        cv.addWidget(self.b_report)
        self.strip_cond = QLabel("")
        self.strip_cond.hide()
        c0.addWidget(ci)

        pi_, pv_ = isl(spacing=8)
        self.price_box = pi_
        self.b_use_price = QPushButton("Use suggested", objectName="accent")
        self.b_use_price.clicked.connect(self.use_suggested)
        self.b_use_price.setEnabled(False)
        b_ref = icon_button("reset", "Check prices again now", 28)
        b_ref.clicked.connect(lambda: self.check_price(force=True))
        lab = QLabel("Price", objectName="small")
        pv_.addLayout(row(lab, None, self.b_use_price, b_ref, spacing=6))
        dollar = QLabel("$", objectName="dotmuted")
        self.price = PriceBox(objectName="bigprice")
        self.price.setRange(0, 100000)
        self.price.setDecimals(2)
        self.price.setSingleStep(1.0)
        self.price.valueChanged.connect(self.on_price)
        self.price.setMinimumWidth(120)
        self.price.setMinimumHeight(64)
        self.price.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        pv_.addLayout(row(dollar, self.price, spacing=2))
        # quick prices: the market, 10% and 25% over it, and up to the next whole dollar
        self.price_quick = {}
        qb = []
        for kind, label, tip in (("m0", "Market", "The market price"),
                                 ("m10", "+10%", "10% over the market price"),
                                 ("m25", "+25%", "25% over the market price"),
                                 ("ceil", "Round up", "Up to the next whole dollar")):
            b = QPushButton(label, objectName="chip")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=kind: self.quick_price(k))
            qb.append(b)
            self.price_quick[kind] = b
        pv_.addLayout(row(*qb, None, spacing=6))
        self.price_info = QLabel("", objectName="mono")
        self.price_info.setWordWrap(True)
        self.price_info.setTextFormat(Qt.RichText)
        pv_.addWidget(self.price_info)
        c0.addWidget(pi_)

        ti, tv_ = isl(m=(20, 14, 14, 14), spacing=6)
        self.title_count = QLabel("", objectName="mono")
        b_ct = icon_button("copy", "Copy the title", 26)
        b_ct.clicked.connect(self.copy_title)
        b_cd = icon_button("copy", "Copy the description", 26, text="Desc")
        b_cd.setObjectName("icon")
        b_cd.clicked.connect(self.copy_desc)
        tv_.addLayout(row(QLabel("Title", objectName="small"), None, self.title_count, b_ct, b_cd, spacing=4))
        self.title_edit = QLineEdit(objectName="bare")
        self.title_edit.setPlaceholderText("Appears once the card is identified")
        self.title_edit.textEdited.connect(self.on_title)
        tv_.addWidget(self.title_edit)
        self.ebay_msg = AutoLabel("", objectName="small")
        self.ebay_msg.setWordWrap(True)
        tv_.addWidget(self.ebay_msg)
        self.ebay_msg.hide()
        self.ebay_state = QLabel("")
        self.ebay_state.hide()
        c0.addWidget(ti)

        secs = QHBoxLayout()
        secs.setSpacing(6)
        for k, name in enumerate(("Crop", "Tone", "Lens"), 1):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, k=k: self._open_section(k))
            secs.addWidget(b, 1)
        c0.addLayout(secs)
        c0.addStretch(1)
        wrap = QWidget()
        wv = QVBoxLayout(wrap)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(12)
        wv.addWidget(scrolled(p0), 1)
        self.c_auto = icon_button("upload", "Auto-upload: each finished card (identified, graded, priced, both "
                                  "sides exported) goes up to eBay unpublished as you move on; publish later "
                                  "from List", 50)
        self.c_auto.setObjectName("")
        self.c_auto.setCheckable(True)
        self.c_auto.setStyleSheet("border-radius:25px; padding:0;")
        self.c_auto.setChecked(self.cfg.value("auto_upload", "false") in (True, "true"))
        self.c_auto.toggled.connect(self.set_auto_upload)
        self.c_auto.toggled.connect(lambda _on: self._auto_icon())
        self._auto_icon()
        _ICONS[:] = [e for e in _ICONS if e[0]() is not self.c_auto]     # its colour depends on on/off
        self.b_export = QPushButton("Export and next  ↵", objectName="primary")
        self.b_export.setStyleSheet("padding:14px 10px;")
        self.b_export.setToolTip("Export this card and go to the next unfinished one  (Enter)")
        self.b_export.clicked.connect(self.export_current)
        self.listw.itemSelectionChanged.connect(self._sync_export_label)
        self.b_all = QPushButton("All")
        self.b_all.setMinimumHeight(50)
        self.b_all.setStyleSheet("border-radius:25px; padding:0 16px;")
        self.b_all.setToolTip("Export every unfinished photo with what detection found")
        self.b_all.clicked.connect(self.export_all)
        self.b_ready = QPushButton("Ready")
        self.b_ready.setMinimumHeight(50)
        self.b_ready.setStyleSheet("border-radius:25px; padding:0 16px;")
        self.b_ready.setToolTip("Export every card CardCrop is sure of, together: both sides with strong edges "
                                "and the card identified. What is left is what needs you")
        self.b_ready.clicked.connect(self.export_ready)
        self.b_ready.hide()
        wv.addLayout(row(self.b_export, self.b_ready, self.b_all, self.c_auto))
        self._glows = [BorderGlow(self.b_export), BorderGlow(self.b_ready)]   # the action that matters glows
        self.b_export.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.rcol.addWidget(wrap)

        self._settings_pages = []

        def settings_page(title, sub=""):
            f = Island()
            fv_ = QVBoxLayout(f)
            fv_.setContentsMargins(28, 24, 28, 24)
            fv_.setSpacing(12)
            if sub:
                fv_.addWidget(QLabel(sub, objectName="small"))
            body = QWidget()
            bv = QVBoxLayout(body)
            bv.setContentsMargins(0, 0, 4, 0)
            bv.setSpacing(10)
            body.setMaximumWidth(560)
            fv_.addWidget(scrolled(body), 1)
            self._settings_pages.append((title, f))
            return bv

        def section(title):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(12)
            f, fv_ = isl(spacing=12)
            back = icon_button("back", "Back to the card", 30)
            back.clicked.connect(lambda: self._open_section(0))
            h_ = QLabel(title, objectName="display")
            fv_.addLayout(row(back, h_, None))
            v.addWidget(f, 1)
            body = QWidget()
            bv = QVBoxLayout(body)
            bv.setContentsMargins(0, 0, 4, 0)
            bv.setSpacing(10)
            fv_.addWidget(scrolled(body), 1)
            self.rcol.addWidget(w)
            return bv

        # Crop
        tv = section("Crop")
        self.c_corners = QCheckBox("Export corner close-ups")
        self.c_corners.setToolTip("Untick when you only want the card itself, for example for a carousel post")
        self.c_corners.setChecked(self.settings.corners)
        self.c_corners.toggled.connect(self.on_settings)
        l1, self.s_corner = labeled_slider("Corner crop", 15, 50, int(self.settings.corner_frac * 100),
                                           lambda v: f"{v}% of width")
        self.s_corner.valueChanged.connect(self.on_settings)
        l3, self.s_margin = labeled_slider("Edge margin", 0, 80, self.settings.margin_px,
                                           lambda v: "none" if v == 0 else f"{v} px")
        self.s_margin.valueChanged.connect(self.on_settings)
        for w in (self.c_corners, l1, self.s_corner, l3, self.s_margin):
            tv.addWidget(w)
        self.c_ratio = QCheckBox("Force 63 × 88 card shape")
        self.c_ratio.setChecked(self.settings.lock_ratio)
        self.c_ratio.toggled.connect(self.on_settings)
        self.c_port = QCheckBox("Auto-rotate sideways cards upright")
        self.c_port.setChecked(self.settings.auto_portrait)
        self.c_port.toggled.connect(self.on_settings)
        self.c_flat = QCheckBox("Straighten curled cards")
        self.c_flat.setToolTip("Follows each side's own curve, so a card that curls (holos, most of all) comes out "
                               "with straight sides instead of keeping the bow the four corners cannot see")
        self.c_flat.setChecked(self.settings.flatten)
        self.c_flat.toggled.connect(self.on_settings)
        self.c_up = QCheckBox("Upscale corners to 1600 px")
        self.c_up.setChecked(self.settings.corner_px > 0)
        self.c_up.toggled.connect(self.on_settings)
        for w in (self.c_ratio, self.c_flat, self.c_port, self.c_up):
            tv.addWidget(w)
        tv.addStretch(1)

        # Tone
        av = section("Tone")
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("Every crop, tone, lens and output setting at once")
        self.preset_combo.activated.connect(self._preset_chosen)
        b_ps = icon_button("save", "Save the current settings as a preset of your own")
        b_ps.clicked.connect(self.save_preset)
        self.b_pdel = icon_button("trash", "Delete this preset of yours")
        self.b_pdel.clicked.connect(self.delete_preset)
        av.addWidget(QLabel("Preset", objectName="small"))
        pr_row = row(self.preset_combo, b_ps, self.b_pdel, spacing=4)
        pr_row.setStretch(0, 1)
        av.addLayout(pr_row)
        b_reset = QPushButton("Reset tone")
        b_reset.clicked.connect(self.reset_edits)
        signed = lambda v: "0" if v == 0 else f"{v:+d}"  # noqa: E731
        specs = [("exposure", "Exposure", -250, 250, lambda v: "0" if v == 0 else f"{v / 50:+.2f} EV"),
                 ("contrast", "Contrast", -100, 100, signed),
                 ("highlights", "Highlights", -100, 100, signed),
                 ("shadows", "Shadows", -100, 100, signed),
                 ("saturation", "Saturation", -100, 100, signed),
                 ("warmth", "Warmth", -100, 100, signed),
                 ("sharpen", "Sharpen", 0, 100, lambda v: "off" if v == 0 else str(v))]
        self.edit_sliders = {}
        for key, text, lo, hi, fmt in specs:
            lab_, sl = labeled_slider(text, lo, hi, int(round(getattr(self.settings, key) * 100)), fmt)
            sl.valueChanged.connect(lambda v, k=key: self.on_edit_slider(k, v))
            av.addWidget(lab_)
            av.addWidget(sl)
            self.edit_sliders[key] = sl
        av.addWidget(b_reset, 0, Qt.AlignLeft)
        av.addStretch(1)

        # Lens: the profile and distortion live on Shoot, beside the camera they describe; the detail
        # recovery is an export step and stays here
        lv_ = section("Lens")
        moved = QLabel("Lens profile and distortion are on the Shoot tab, with Measure from session.", objectName="muted")
        moved.setWordWrap(True)
        lv_.addWidget(moved)
        l3, self.s_detail = labeled_slider("Lens detail", 0, 100, int(round(self.settings.detail * 100)),
                                           lambda v: "off" if v == 0 else str(v))
        self.s_detail.setToolTip("Undoes the slight blur every lens and sensor adds, at export: print edges and "
                                 "lettering come back crisp, flat areas and grain are left alone. It recovers "
                                 "detail you captured; it never paints in detail that is not there")
        self.s_detail.valueChanged.connect(lambda v: (setattr(self.settings, "detail", v / 100),
                                                      self.cfg.setValue("detail", v / 100)))
        lv_.addWidget(l3)
        lv_.addWidget(self.s_detail)
        lv_.addStretch(1)

        # Output
        ov = settings_page("Output", "Format, hero photo, Instagram slides and where files go")
        self.fmt = QComboBox()
        for k, (label, _) in FORMATS.items():
            self.fmt.addItem(label, k)
        self.fmt.setCurrentIndex(max(0, list(FORMATS).index(self.settings.out_format)
                                     if self.settings.out_format in FORMATS else 0))
        self.fmt.currentIndexChanged.connect(self.on_settings)
        ov.addWidget(QLabel("Format", objectName="small"))
        ov.addWidget(self.fmt)
        # hero: on or off, then which sides and on what, side by side under it
        self.c_hero = QCheckBox("Hero first photo")
        self.c_hero.setChecked(self.settings.hero)
        self.c_hero.toggled.connect(self.on_settings)
        self.hero_sides = QComboBox()
        for k, label in engine.HERO_SIDES.items():
            self.hero_sides.addItem(label, k)
        self.hero_sides.setCurrentIndex(max(0, self.hero_sides.findData(self.settings.hero_sides)))
        self.hero_sides.currentIndexChanged.connect(self.on_settings)
        self.hero_bg = QComboBox()
        for k in engine.HERO_BGS:
            self.hero_bg.addItem(k.title() + " background", k)
        self.hero_bg.setCurrentIndex(max(0, list(engine.HERO_BGS).index(self.settings.hero_bg)
                                         if self.settings.hero_bg in engine.HERO_BGS else 0))
        self.hero_bg.currentIndexChanged.connect(self.on_settings)
        ov.addSpacing(8)
        ov.addWidget(QLabel("Hero", objectName="small"))
        ov.addWidget(self.c_hero)
        hr = row(self.hero_sides, self.hero_bg)
        hr.setStretch(0, 1)
        hr.setStretch(1, 1)
        ov.addLayout(hr)

        self.c_ig = QCheckBox("Instagram carousel for fronts")
        self.c_ig.setToolTip("Three 4:5 slides at 9374 × 11718, 300 dpi, in an instagram folder beside the photos")
        self.c_ig.setChecked(self.settings.ig)
        self.c_ig.toggled.connect(self.on_settings)
        b_ig = QPushButton("Close-up framing   P")
        b_ig.clicked.connect(self.open_ig)
        b_car = QPushButton("From edited photos…")
        b_car.setToolTip("Add finished, already edited photos: CardCrop finds the card, drops the background "
                         "and writes only the Instagram slides, with no tone changes")
        b_car.clicked.connect(self.add_carousel_photos)
        ov.addSpacing(8)
        ov.addWidget(QLabel("Instagram", objectName="small"))
        ov.addWidget(self.c_ig)
        ir = row(b_ig, b_car)
        ir.setStretch(0, 1)
        ir.setStretch(1, 1)
        ov.addLayout(ir)
        self.c_auto_id = QCheckBox("Auto-identify new fronts (needs internet)")
        self.c_auto_id.setChecked(self.cfg.value("auto_identify", "true") in (True, "true"))
        self.c_auto_id.toggled.connect(lambda v: self.cfg.setValue("auto_identify", v))
        ov.addSpacing(8)
        ov.addWidget(QLabel("Identify", objectName="small"))
        ov.addWidget(self.c_auto_id)
        ov.addSpacing(8)
        ov.addWidget(QLabel("Save to", objectName="small"))
        self.dir_lbl = QLabel(objectName="mono")
        self.dir_lbl.setWordWrap(True)
        b_dir = QPushButton("Folder…")
        b_dir.clicked.connect(self.pick_dir)
        ov.addWidget(self.dir_lbl)
        ov.addLayout(row(b_dir, None))
        self._show_dir()
        ov.addStretch(1)
        self.stages.addWidget(edit)

        # ================================================================ SHOOT
        shoot = QWidget()
        sh = QHBoxLayout(shoot)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(12)
        self.live_isl = Island("canvas")
        lv = QVBoxLayout(self.live_isl)
        lv.setContentsMargins(6, 6, 6, 6)
        self.live = LiveView()
        lv.addWidget(self.live)
        sh.addWidget(self.live_isl, 1)
        self.cam_lbl = QLabel("Camera")
        self.live_dot = dot_label("#6E6E75")
        self.live_word = QLabel("OFF")
        self.live_isl.float_widget(hud(self.live_dot, self.live_word, self.cam_lbl, margins=(14, 7, 14, 7), spacing=8),
                                   "tl")
        self.zoom_btn = QPushButton("1x")
        self.zoom_btn.setToolTip("Scroll or double-click on the live view to magnify; double-click again to reset")
        self.zoom_btn.clicked.connect(self.cycle_zoom)
        self.live_isl.float_widget(hud(self.zoom_btn, margins=(4, 4, 4, 4)), "tr")
        lb = []
        for name, step, tip in (("rot_left", -1, "Rotate view left  (Shift+T)"),
                                ("rot_right", 1, "Rotate view right  (T)")):
            b = icon_button(name, tip, 36, role="hud")
            b.clicked.connect(lambda _=False, st_=step: self.rotate_live(st_))
            lb.append(b)
        lb.append("|")
        b_m = QPushButton("Match last")
        b_m.setToolTip("Move the overlay to the last detected card  (U)")
        b_m.clicked.connect(self.match_last_shot)
        b_r = QPushButton("Reset overlay")
        b_r.clicked.connect(self.reset_guide)
        lb += [b_m, b_r]
        self.live_isl.float_widget(hud(*lb, margins=(6, 4, 6, 4), spacing=2), "br")
        self.last_thumb = QLabel()
        self.last_thumb.setFixedSize(44, 60)
        self.last_l1 = QLabel("No shots yet")
        self.last_l2 = QLabel("", objectName="mono")
        lt = QVBoxLayout()
        lt.setSpacing(2)
        lt.addWidget(self.last_l1)
        lt.addWidget(self.last_l2)
        b_rep = QPushButton("Report")
        b_rep.setToolTip("Condition report for the card in the last shot")
        b_rep.clicked.connect(self._report_last_shot)
        self.hud_last = self.live_isl.float_widget(hud(self.last_thumb, lt, b_rep, margins=(8, 8, 8, 8), spacing=12),
                                                   "bl")
        self.hud_last.hide()
        # shown while no camera is connected
        cc = QFrame(objectName="island")
        cc_v = QVBoxLayout(cc)
        cc_v.setContentsMargins(28, 24, 28, 24)
        cc_v.setSpacing(12)
        cc_v.addWidget(QLabel("Camera not connected", objectName="display"))
        msg = QLabel("Connect the a6700 by USB, turn on PC Remote, then connect.", objectName="muted")
        msg.setWordWrap(True)
        msg.setMaximumWidth(320)
        cc_v.addWidget(msg)
        self.cam_btn = QPushButton("Connect camera   K", objectName="primary")
        self.cam_btn.clicked.connect(self.toggle_camera)
        cc_v.addWidget(self.cam_btn)
        self.connect_card = self.live_isl.float_widget(cc, "c")
        self.pipe_hud = PipelineHud()                    # the lattice and thought line for background reading
        self.pipe_hud_box = self.live_isl.float_widget(hud(self.pipe_hud, margins=(6, 2, 8, 2)), "t")
        self.pipe_hud_box.hide()
        self.pipe_hud.toggled.connect(lambda _o: self.live_isl._place())

        scol = QVBoxLayout()
        scol.setSpacing(12)
        ex, exv = isl(spacing=12)
        self.cam_state = QLabel("Not connected", objectName="small")
        exv.addLayout(row(QLabel("Exposure", objectName="small"), None, self.cam_state))
        self.cam_combos = {}
        tiles = QHBoxLayout()
        tiles.setSpacing(8)

        def cam_combo(key, tile=False):
            combo = QComboBox(objectName="tile" if tile else "")
            combo.addItem("–")
            combo.setEnabled(False)
            combo.activated.connect(lambda idx, k=key: self.cam_set(k, idx))
            self.cam_combos[key] = combo
            return combo

        for key, label in (("fnumber", "Aperture"), ("shutter", "Shutter"), ("iso", "ISO")):
            t_ = QFrame(objectName="segbox")
            t_.setMinimumHeight(74)
            tl_ = QVBoxLayout(t_)
            tl_.setContentsMargins(12, 10, 8, 10)
            tl_.setSpacing(2)
            tl_.addWidget(QLabel(label, objectName="small"))
            tl_.addWidget(cam_combo(key, True))
            tiles.addWidget(t_, 1)
        exv.addLayout(tiles)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        for k, (key, label) in enumerate((("ev", "EV"), ("wb", "WB"), ("kelvin", "Kelvin"), ("focus", "Focus"),
                                          ("area", "Area"), ("filetype", "File"), ("dest", "Save to"))):
            g.addWidget(QLabel(label, objectName="small"), k, 0)
            g.addWidget(cam_combo(key), k, 1)
        g.setColumnStretch(1, 1)
        self.cam_grid = QWidget()
        self.cam_grid.setLayout(g)
        g.setContentsMargins(0, 0, 0, 0)
        exv.addWidget(self.cam_grid)
        self.cam_preset_combo = QComboBox()
        self.cam_preset_combo.setToolTip("Saved camera settings: pick one to set the camera  (Cmd+1 to Cmd+4)")
        self.cam_preset_combo.activated.connect(lambda i: self.apply_cam_preset(self.cam_preset_combo.itemData(i)))
        b_ps = QPushButton("Save…")
        b_ps.setToolTip("Save the camera's current aperture, shutter, ISO, EV, white balance and focus as a setting")
        b_ps.clicked.connect(self.save_cam_preset)
        b_pd = QPushButton("Delete")
        b_pd.clicked.connect(self.delete_cam_preset)
        pr_ = row(QLabel("Saved", objectName="small"), self.cam_preset_combo, b_ps, b_pd, spacing=6)
        pr_.setStretch(1, 1)
        exv.addLayout(pr_)
        self._fill_cam_presets()
        self.cam_set_btn = QPushButton()
        self.cam_set_btn.setCheckable(True)
        self.cam_set_btn.hide()
        scol.addWidget(ex)

        vw, vwv = isl(spacing=10)
        vwv.addWidget(QLabel("View", objectName="small"))
        self.grid_combo = QComboBox()
        self.grid_combo.addItems(GRIDS)
        self.grid_combo.setToolTip("Grid  (G cycles)")
        self.grid_combo.currentTextChanged.connect(self.set_grid)
        self.color_btn = QPushButton("")
        self.color_btn.setToolTip("Grid colour and opacity")
        self.color_btn.setFixedSize(44, 30)
        self.color_btn.clicked.connect(self.pick_grid_color)
        self.width_combo = QComboBox()
        self.width_combo.addItems(list(GRID_WIDTHS))
        self.width_combo.currentTextChanged.connect(self.set_grid_width)
        gr = row(self.grid_combo, self.width_combo, self.color_btn, spacing=6)
        gr.setStretch(0, 1)
        vwv.addLayout(gr)
        self.c_guide = QCheckBox("Card overlay  (O)")
        self.c_guide.setChecked(self.cfg.value("lv_show_guide", "true") in (True, "true"))
        self.c_guide.toggled.connect(self.set_show_guide)
        self.c_follow = QCheckBox("Follow shots")
        self.c_follow.setToolTip("After each shot, move the overlay to where the card was actually detected")
        self.c_follow.setChecked(self.cfg.value("lv_follow", "true") in (True, "true"))
        self.c_follow.toggled.connect(lambda v: self.cfg.setValue("lv_follow", v))
        vwv.addLayout(row(self.c_guide, self.c_follow, None, spacing=16))
        self.c_pair = QCheckBox("Shoot both sides, then edit")
        self.c_pair.setToolTip("Stay in live view after the front: shoot the back straight after, then crop and "
                               "identify the front and its back together")
        self.c_pair.setChecked(self.cfg.value("lv_pair", "true") in (True, "true"))
        self.c_pair.toggled.connect(lambda v: (self.cfg.setValue("lv_pair", v), setattr(self, "_pair_front", None)))
        vwv.addWidget(self.c_pair)
        self.c_batch = QCheckBox("Batch: shoot every card, edit later")
        self.c_batch.setToolTip("Stay in live view the whole time: front, back, next front, next back… Then go to "
                                "Edit (E) and crop, identify and export them in turn, or all at once")
        self.c_batch.setChecked(self.cfg.value("lv_batch", "false") in (True, "true"))
        self.c_batch.toggled.connect(lambda v: (self.cfg.setValue("lv_batch", v), self._update_next()))
        vwv.addWidget(self.c_batch)
        # which game is being shot: identifying reads the number the way that game prints it
        gseg = QFrame(objectName="segbox")
        gsl = QHBoxLayout(gseg)
        gsl.setContentsMargins(4, 4, 4, 4)
        gsl.setSpacing(4)
        self.game_btns = {}
        for k_, label_ in identify.GAMES.items():
            b_ = QPushButton(label_, objectName="seg")
            b_.setCheckable(True)
            b_.setToolTip("The game these cards are from: identifying reads the number the way it prints it")
            b_.clicked.connect(lambda _=False, k__=k_: self.set_game(k__))
            gsl.addWidget(b_)
            self.game_btns[k_] = b_
        vwv.addWidget(gseg)
        self.c_edges = QCheckBox("Live edges and centering  (V)")
        self.c_edges.setToolTip("Find the card in live view: its edges turn green when locked, with the centering")
        self.c_peak = QCheckBox("Focus peaking  (X)")
        self.c_peak.setToolTip("Sharp edges glow magenta: the more glow on the card's text and corners, the sharper")
        self.c_loupe = QCheckBox("Corner loupe  (Q)")
        self.c_loupe.setToolTip("The card's four corners magnified, top right, to check they are crisp")
        self.c_autoshot = QCheckBox("Auto-capture  (N)")
        self.c_autoshot.setToolTip("Shoots by itself when a card sits still with its edges locked; swap the card "
                               "and it shoots the next one")
        for cb, key, default in ((self.c_edges, "lv_edges", "true"), (self.c_peak, "lv_peak", "false"),
                                 (self.c_loupe, "lv_loupe", "false"), (self.c_autoshot, "lv_auto", "false")):
            cb.setChecked(self.cfg.value(key, default) in (True, "true"))
            cb.toggled.connect(lambda v, k=key: (self.cfg.setValue(k, v), self._live_flags()))
        vwv.addLayout(row(self.c_edges, None, spacing=16))
        vwv.addLayout(row(self.c_peak, self.c_loupe, None, spacing=16))
        hold = QComboBox()
        for secs in (0.5, 0.8, 1.2, 2.0):
            hold.addItem(f"after {secs:g} s still", secs)
        hold.setCurrentIndex(max(0, hold.findData(float(self.cfg.value("lv_auto_hold", 0.8)))))
        hold.currentIndexChanged.connect(lambda _i: self.cfg.setValue("lv_auto_hold", hold.currentData()))
        hold.setToolTip("How long a card has to sit still before it is shot")
        self.auto_hold = hold
        vwv.addLayout(row(self.c_autoshot, hold, None, spacing=10))
        scol.addWidget(vw)

        # Lens: a profile, a distortion measured from your own shots at the distance you shoot, and a slider
        ln, lnv = isl(spacing=10)
        self.lens_state = QLabel("", objectName="small")
        lnv.addLayout(row(QLabel("Lens", objectName="small"), None, self.lens_state))
        self.lens_combo = QComboBox()
        self.lens_combo.setToolTip("Distortion and colour-fringe correction for your lens. Lensfun's profile is measured "
                                   "at infinity focus; Measured is fitted to the straight edges of cards in your own "
                                   "shots, at the distance you shoot them. RAW only skips camera JPEGs, which the "
                                   "camera has usually corrected already")
        self._fill_lens_combo()
        self.lens_combo.currentIndexChanged.connect(self.on_lens)
        lnv.addWidget(self.lens_combo)
        self.lens_fit_lbl = QLabel("")
        self.lens_fit_lbl.setWordWrap(True)
        self.lens_fit_lbl.setStyleSheet("font-size: 14px; line-height: 1.4;")
        lnv.addWidget(self.lens_fit_lbl)
        self.b_lens_measure = QPushButton("Measure from session")
        self.b_lens_measure.setToolTip("Fits the lens's distortion to the four straight sides of the cards in this "
                                       "session's photos. Shoot a few cards at different spots in the frame, corners "
                                       "included, at your usual distance, then measure")
        self.b_lens_measure.clicked.connect(self.measure_lens)
        self.b_lens_forget = QPushButton("Forget")
        self.b_lens_forget.setToolTip("Drop the measured distortion and go back to the Lensfun profile")
        self.b_lens_forget.clicked.connect(self.forget_lens_fit)
        lnv.addLayout(row(self.b_lens_measure, self.b_lens_forget, None, spacing=6))
        l2, self.s_lens = labeled_slider("Extra distortion (manual)", -40, 40, int(self.settings.lens_k1 * 100),
                                         lambda v: "off" if v == 0 else (f"barrel {v}" if v > 0 else f"pincushion {-v}"))
        self.s_lens.sliderReleased.connect(self.on_lens)
        self.s_lens.valueChanged.connect(lambda _: None if self.s_lens.isSliderDown() else self.on_lens())
        lnv.addWidget(l2)
        lnv.addWidget(self.s_lens)
        scol.addWidget(ln)
        self._show_lens_fit()

        nx, nxv = isl(spacing=6)
        nxv.addWidget(QLabel("Next up", objectName="small"))
        self.next_lbl = QLabel("Card 1 · Front", objectName="display")
        nxv.addWidget(self.next_lbl)
        nseg = QFrame(objectName="segbox")
        ns = QHBoxLayout(nseg)
        ns.setContentsMargins(4, 4, 4, 4)
        ns.setSpacing(4)
        self.seg_next = {}
        for side in ("front", "back"):
            b = QPushButton(side.title(), objectName="seg")
            b.setCheckable(True)
            b.setToolTip("Whether the next shot is a card's front or its back")
            b.clicked.connect(lambda _=False, sd=side: self.set_next_side(sd))
            ns.addWidget(b, 1)
            self.seg_next[side] = b
        nxv.addWidget(nseg)
        scol.addWidget(nx)
        scol.addStretch(1)

        cap, capv = isl(m=(18, 18, 18, 18), spacing=12, vertical=False)
        b_af = QPushButton("AF")
        b_af.setToolTip("Autofocus  (A)")
        b_af.setFixedSize(64, 64)
        b_af.setStyleSheet("border-radius:32px; font-weight:600;")
        b_af.clicked.connect(self.cam_af)
        self.shutter_btn = QPushButton()
        self.shutter_btn.setToolTip("Focus and shoot  (Space)")
        self.shutter_btn.setFixedSize(96, 96)
        self.shutter_btn.setCursor(Qt.PointingHandCursor)
        self.shutter_btn.clicked.connect(self.cam_shoot)
        b_rev = icon_button("next", "Review the shots in Edit  (E)", 64)
        b_rev.setObjectName("")
        b_rev.setStyleSheet("border-radius:32px;")
        b_rev.clicked.connect(lambda: self.go("edit"))
        capv.addWidget(b_af)
        capv.addStretch(1)
        capv.addWidget(self.shutter_btn)
        capv.addStretch(1)
        capv.addWidget(b_rev)
        scol.addWidget(cap)
        sw = QWidget()
        sw.setLayout(scol)
        sw.setFixedWidth(348)
        scol.setContentsMargins(0, 0, 0, 0)
        sw_sa = scrolled(sw)               # a short screen scrolls the column instead of growing the window
        sw_sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sw_sa.setFixedWidth(356)
        sh.addWidget(sw_sa)
        self.cambar = QWidget()          # older code shows and hides this; the Shoot stage replaces it
        self.stages.insertWidget(0, shoot)

        # live view state
        self.live.grid = str(self.cfg.value("lv_grid", "Thirds + diagonals"))
        self.live.grid_width = str(self.cfg.value("lv_grid_width", "Thin"))
        self.live.rot = int(self.cfg.value("lv_rot", 0)) % 360
        c = QColor(str(self.cfg.value("lv_grid_color", "#C8FFFFFF")))
        if c.isValid():
            self.live.grid_color = c
        self.grid_combo.setCurrentText(self.live.grid)
        self.width_combo.setCurrentText(self.live.grid_width)
        self._swatch()
        self.live.show_guide = self.c_guide.isChecked()
        self.live.on_guide = self._guide_edited
        try:
            g_ = json.loads(str(self.cfg.value("lv_guide", "")) or "null")
            self.live.guide = np.array(g_, np.float32) if g_ else None
        except ValueError:
            self.live.guide = None
        self.live_spots = {}
        for i in range(1, 5):
            try:
                v = json.loads(str(self.cfg.value(f"lv_spot_{i}", "")) or "null")
                if v:
                    self.live_spots[i] = np.array(v, np.float32)
            except ValueError:
                pass
        self.live.on_zoom = lambda z: self.zoom_btn.setText(f"{z:.1f}x".replace(".0x", "x"))
        self._lv_busy, self._lv_last = False, 0.0
        self._auto = {"state": "wait", "since": 0.0, "prev": None, "shot_thumb": None, "gone": 0}
        self._live_flags()

        # ================================================================ LIST
        self.list_page = ListPage(self)
        self.stages.addWidget(scrolled(self.list_page))

        # ================================================================ STORE
        self.store_page = StorePage(self)
        self.stages.addWidget(scrolled(self.store_page))

        # ================================================================ SETTINGS
        sp = QWidget()
        spv = QVBoxLayout(sp)
        spv.setContentsMargins(0, 0, 0, 0)
        spv.setSpacing(12)
        head = QHBoxLayout()
        head.setContentsMargins(8, 4, 4, 0)
        head.addWidget(QLabel("Settings", objectName="title2"))
        head.addSpacing(24)
        self.set_tabs = {}
        self.set_stack = QStackedWidget()
        self.tracking = TrackingPage(self)
        pages = [("Tracking", self.tracking)] + self._settings_pages
        # eBay
        eb_w, ebv = Island(), None
        ebv = QVBoxLayout(eb_w)
        ebv.setContentsMargins(28, 24, 28, 24)
        ebv.setSpacing(12)
        ebv.addWidget(QLabel("Your eBay connection, how cards are sent, and what happens automatically",
                             objectName="small"))
        b_acc = QPushButton("eBay account, policies and package…")
        b_acc.clicked.connect(self.ebay_account)
        ebv.addLayout(row(b_acc, None))
        ebv.addWidget(QLabel("Listing route", objectName="small"))
        self.route_btns = {}
        rr = QHBoxLayout()
        for key, label in (("direct", "Upload unpublished (API)"), ("drafts", "Seller Hub drafts")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_ebay_route(k))
            rr.addWidget(b)
            self.route_btns[key] = b
        rr.addStretch(1)
        ebv.addLayout(rr)
        ebv.addWidget(QLabel("eBay Store category for new listings; each card can have its own in List",
                             objectName="small"))
        self.b_store_def = QPushButton("")
        sdm = QMenu(self.b_store_def)
        sdm.aboutToShow.connect(lambda: self.store_cat_menu(sdm, None))
        self.b_store_def.setMenu(sdm)
        ebv.addLayout(row(self.b_store_def, None))
        self._sync_store_default()
        self.c_auto2 = QCheckBox("Auto-upload finished cards as I move on (always unpublished)")
        self.c_auto2.setChecked(self.c_auto.isChecked())
        self.c_auto2.toggled.connect(self.c_auto.setChecked)
        self.c_auto.toggled.connect(self.c_auto2.setChecked)
        ebv.addWidget(self.c_auto2)
        b_rev2 = QPushButton("Review and publish…")
        b_rev2.clicked.connect(self.ebay_review)
        b_fold2 = QPushButton("Add exported folders…")
        b_fold2.clicked.connect(lambda: self.list_folders([]))
        b_csv2 = QPushButton("Drafts file for every exported card…")
        b_csv2.clicked.connect(self.fill_drafts)
        ebv.addLayout(row(b_rev2, b_fold2, b_csv2, None))
        self.tpl_lbl = QLabel("", objectName="mono")
        self.tpl_lbl.setWordWrap(True)
        b_tpl = QPushButton("Choose drafts template…")
        b_tpl.clicked.connect(self.pick_template)
        ebv.addWidget(QLabel("Seller Hub drafts template", objectName="small"))
        ebv.addWidget(self.tpl_lbl)
        ebv.addLayout(row(b_tpl, None))
        ebv.addStretch(1)
        pages.append(("eBay", eb_w))
        # App
        ap_w = Island()
        apv = QVBoxLayout(ap_w)
        apv.setContentsMargins(28, 24, 28, 24)
        apv.setSpacing(12)
        apv.addWidget(QLabel("Look and feel", objectName="small"))
        self.theme_btns = {}
        tr = QHBoxLayout()
        for key, label in (("light", "Light"), ("dark", "Dark")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: (TH.THEME != k) and self.toggle_theme())
            tr.addWidget(b)
            self.theme_btns[key] = b
        tr.addStretch(1)
        apv.addLayout(tr)
        apv.addWidget(QLabel("Text size", objectName="small"))
        sz = QHBoxLayout()
        for label, d in (("Smaller", -1), ("Default", 0), ("Larger", 1)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, d=d: self.ui_size(d))
            sz.addWidget(b)
        self.size_lbl = QLabel("", objectName="mono")
        sz.addWidget(self.size_lbl)
        sz.addStretch(1)
        apv.addLayout(sz)
        apv.addWidget(QLabel("Identification", objectName="small"))
        self.game_pick = QComboBox()
        for k, label in identify.GAMES.items():
            self.game_pick.addItem(label, k)
        g_ = str(self.cfg.value("id_game", "pokemon"))
        self.game_pick.setCurrentIndex(max(0, list(identify.GAMES).index(g_) if g_ in identify.GAMES else 0))
        self.game_pick.currentIndexChanged.connect(lambda _i: self.set_game(self.game_pick.currentData()))
        self.set_game(str(self.cfg.value("id_game", "pokemon")))
        apv.addLayout(row(QLabel("Usual game"), self.game_pick, None))
        self.c_sounds = QCheckBox("Chimes when a card is captured, exported and listed")
        self.c_sounds.setChecked(str(self.cfg.value("sounds", "true")).lower() in ("true", "1"))
        self.c_sounds.toggled.connect(lambda v: (self.cfg.setValue("sounds", "true" if v else "false"),
                                                 v and self.chime("listed")))
        apv.addWidget(self.c_sounds)
        self.c_motion = QCheckBox("Motion: pages dissolve, buttons ripple, lists ease in")
        self.c_motion.setChecked(motion.enabled())
        self.c_motion.toggled.connect(lambda v: (self.cfg.setValue("motion", "true" if v else "false"),
                                                 motion.set_motion(v)))
        apv.addWidget(self.c_motion)
        apv.addWidget(QLabel("Prices", objectName="small"))
        self.c_autoprice = QCheckBox("Fill in the suggested price for cards you have not priced")
        self.c_autoprice.setChecked(str(self.cfg.value("price_autofill", "true")).lower() in ("true", "1"))
        self.c_autoprice.toggled.connect(lambda v: self.cfg.setValue("price_autofill", "true" if v else "false"))
        apv.addWidget(self.c_autoprice)
        self.pc_token = QLineEdit(str(self.cfg.value("pc_token", "") or ""))
        self.pc_token.setEchoMode(QLineEdit.Password)
        self.pc_token.setPlaceholderText("PriceCharting API token (optional)")
        self.pc_token.setToolTip("With a PriceCharting subscription, its ungraded value (worked out from sold "
                                 "listings) joins the price suggestion. Find the token on PriceCharting's "
                                 "Subscriptions page")
        self.pc_token.editingFinished.connect(lambda: self.cfg.setValue("pc_token", self.pc_token.text().strip()))
        apv.addLayout(row(QLabel("PriceCharting"), self.pc_token, None))
        self.ebay_px = QComboBox()
        for px, label in ((1600, "1600 px, sharpened for that size (eBay's largest view)"),
                          (2400, "2400 px, sharpened"), (4000, "4000 px (eBay resizes them itself)")):
            self.ebay_px.addItem(label, px)
        self.ebay_px.setCurrentIndex(max(0, self.ebay_px.findData(int(self.cfg.value("ebay_px", 1600)))))
        self.ebay_px.setToolTip("eBay shows listing photos at up to 1600 px and zooms on those, so a photo sized "
                                "and sharpened here for 1600 looks crisper than one eBay shrinks from 4000 itself")
        self.ebay_px.currentIndexChanged.connect(lambda _i: (self.cfg.setValue("ebay_px", self.ebay_px.currentData()),
                                                             setattr(ebay, "UPLOAD_LONG_EDGE",
                                                                     int(self.ebay_px.currentData()))))
        apv.addLayout(row(QLabel("Photos to eBay"), self.ebay_px, None))
        apv.addStretch(1)
        pages.append(("Videos", self._video_settings()))
        import phone_link
        self.phone = phone_link.PhoneLink(self)
        pages.append(("Phone", phone_link.phone_pane(self, self.phone)))
        pages.append(("App", ap_w))
        if self.phone.enabled():
            QTimer.singleShot(1500, self.phone.start)
        for i, (title, w_) in enumerate(pages):
            b = QPushButton(title)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.settings_tab(i))
            head.addWidget(b)
            self.set_tabs[i] = b
            self.set_stack.addWidget(w_)
        head.addStretch(1)
        self.range_btns = {}
        for label, days in TrackingPage.RANGES:
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, d=days: self._set_range(d))
            head.addWidget(b)
            self.range_btns[days] = b
        spv.addLayout(head)
        spv.addWidget(self.set_stack, 1)
        self.stages.addWidget(scrolled(sp))

        # ================================================================ 3D
        self.viewer3d = Viewer3D(self)
        self.stages.addWidget(self.viewer3d)

        # ================================================================ MARKET
        self.market_page = MarketPage(self)
        self.stages.addWidget(scrolled(self.market_page))

        # ================================================================ REPORTS
        self.reports_page = ReportsPage(self)
        self.stages.addWidget(scrolled(self.reports_page))

        # ================================================================ SHIPMENTS
        from ui_ship import ShipPage
        self.ship_page = ShipPage(self)
        self.stages.addWidget(self.ship_page)
        self.market_dot = QLabel(self.stage_btns["market"])
        self.market_dot.setFixedSize(9, 9)
        self.market_dot.setStyleSheet(f"background:{LIME}; border-radius:4px; border: 1px solid #111;")
        self.market_dot.move(44, 6)
        self.market_dot.hide()
        self.market_timer = QTimer(self, interval=60_000)
        self.market_timer.timeout.connect(self._market_tick)
        self.market_timer.start()
        QTimer.singleShot(8000, self._market_tick)
        self.settings_tab(0)
        self._set_range(None)

        # ================================================================ floating
        self.banner = Notice(root)
        self.statusBar().messageChanged.connect(self._status)
        self.status_timer = QTimer(self, singleShot=True, interval=5000)
        self.status_timer.timeout.connect(self.hud_status.hide)
        # kept so older code paths have something to talk to
        self.back_live_btn = QPushButton()
        self.back_live_btn.hide()
        self.namer_row = QWidget()
        self.card_strip = QWidget()
        self.spots_row = QWidget()
        self.b_upload = self.b_ebay = QPushButton()
        self.b_ebay.hide()
        rm = QMenu(self)
        self.a_other = rm.addAction("", self.ebay_other)
        self.a_route = {k: rm.addAction(k) for k in ("direct", "drafts")}
        for a in self.a_route.values():
            a.setCheckable(True)

        # ================================================================ keys
        for key, fn in (("K", self.toggle_camera), ("L", self.toggle_live), ("A", self.cam_af),
                        ("Space", self.cam_shoot), ("G", self.cycle_grid), ("O", self.toggle_guide),
                        ("U", self.match_last_shot), ("Shift+T", lambda: self.rotate_live(-1)),
                        ("B", self.toggle_side), ("M", self.toggle_mode), ("Z", self.cycle_loupe),
                        ("I", self.open_identify), ("Shift+I", self.identify_now), ("P", self.open_ig), ("E", lambda: self.go("edit")),
                        ("Ctrl+L", lambda: self.go("list")), ("Ctrl+K", self.open_palette),
                        ("Ctrl+,", lambda: self.go("settings")), ("Ctrl+Y", lambda: self.go("store")),
                        ("Ctrl+Shift+M", lambda: self.go("market")), ("Ctrl+Shift+S", lambda: self.go("ship")),
                        ("Ctrl+R", lambda: self.condition_report()),
                        ("Ctrl+\\", self.toggle_left)):
            act(key, fn)
        for key, cb in (("V", lambda: self.c_edges.toggle()), ("X", lambda: self.c_peak.toggle()),
                        ("Q", lambda: self.c_loupe.toggle()), ("N", lambda: self.c_autoshot.toggle())):
            act(key, cb)
        for i in range(4):
            act(f"Ctrl+{i + 1}", lambda _=False, i=i: self.apply_cam_preset_n(i))
        act(QKeySequence.Undo, self.undo)
        act([QKeySequence(QKeySequence.Redo).toString(), "Ctrl+Shift+Z"], self.redo)
        act(["Return", "Enter"], self.export_current)
        for key, d in (("PgDown", 1), ("PgUp", -1), ("]", 1), ("[", -1)):
            act(key, lambda _=False, d=d: self.step(d))
        for keys, d in ((("Ctrl+=", "Ctrl++"), 1), (("Ctrl+-",), -1), (("Ctrl+0",), 0)):
            act(list(keys), lambda _=False, d=d: self.ui_size(d))

        self._refresh_spots()
        self._refresh_presets()
        self._route_ui()
        self._skin()
        self._show_side()
        self._update_summary()
        self.go("edit")
        self.statusBar().showMessage("Ready")
        try:
            engine.load_surface()          # the calibrated surface, if one was shot
        except Exception:  # noqa: BLE001
            pass
        self._level_badge = QLabel("")         # the mat against the camera's sensor, read with the phone
        self._level_badge.setToolTip("Surface level against the camera, measured with the phone (Surface > Level). "
                                     "The second number is the same tilt measured from the last card's edges.")
        self.statusBar().addPermanentWidget(self._level_badge)
        self.restore_session()
        self._session_timer = QTimer(self, interval=1000)    # saved every second while you work (only when it changed)
        self._session_timer.timeout.connect(self.save_session)
        self._session_timer.timeout.connect(self._refresh_level)
        self._refresh_level(force=True)
        self._session_timer.start()

    _SIDE_RE = re.compile(r"^(?P<stem>.*?)[ _.-]*(?:0[23][ _.-]+)?(?P<side>front|back)"
                          r"(?:[ _.-]+(?P<cond>NM|LP|MP|HP|DMG))?$", re.I)

    # --- stages
    def go(self, stage):
        """Shoot, Edit or List. Live view only runs while Shoot is showing."""
        order = ("shoot", "edit", "list", "store", "settings", "view3d", "market", "reports", "ship")
        if stage not in order:
            return
        if getattr(self, "stage", None) == "view3d" and stage != "view3d":
            self.viewer3d.leave()
        self.stage = stage
        prev = getattr(self, "_prev_stage", None)
        self._prev_stage = stage
        if "view3d" in (prev, stage):               # a GL page cannot be photographed: no dissolve
            self.stages.setCurrentIndex(order.index(stage))
        else:
            motion.crossfade(self.stages, order.index(stage))
        if getattr(self, "rail_pill", None) is not None:
            self.rail_pill.move_to(self.stage_btns.get(stage), animate=prev is not None)
        for k, b in self.stage_btns.items():
            b.setChecked(k == stage)
        connected = self.tether.is_connected
        if connected:
            self.tether.live(stage == "shoot")
        self.live_dot.setStyleSheet(f"background:{'#FF5A4A' if connected else '#6E6E75'}; border-radius:4px;")
        self.live_word.setText("LIVE" if connected else "OFF")
        if stage == "shoot":
            if self.live.guide is None:
                self.live.guide = self._default_guide()
            self.live.message = "Waiting for live view…" if connected else "Live view is off"
            self.connect_card.setVisible(not connected)
            self.live_isl._place()
            self._update_next()
            self.live.setFocus()
        elif stage == "edit" and self.jobs and (self.cur is None or self.cur.done):
            # coming in from a batch: the first card that needs you, else the first still to edit
            nxt = self.first_attention()
            if nxt is None:
                nxt = next((i for i, x in enumerate(self.jobs) if not x.done and not x.error), None)
            if nxt is not None:
                self.listw.setCurrentRow(nxt, QItemSelectionModel.ClearAndSelect)
        elif stage == "list":
            self.list_page.refresh()
            self.list_page.setFocus()
        elif stage == "store":
            if self.store_page.stale():
                self.store_page.refresh()
        elif stage == "reports":
            self.reports_page.refresh()
        elif stage == "market":
            self.market_dot.hide()
            self.market_page.analyze()
        elif stage == "view3d":
            self.viewer3d.enter(self.cur.card_name.strip() if self.cur is not None else "")
        elif stage == "settings":
            self._sync_settings()
            if self.set_stack.currentIndex() == 0:
                self.tracking.refresh()
        else:
            self.editor.setFocus()
        self._place_floats()

    def toggle_live(self):
        self.go("edit" if self.stage == "shoot" else "shoot")

    def _update_next(self):
        self._update_next_text()
        back = self.next_lbl.text().endswith("Back")
        for k, b in getattr(self, "seg_next", {}).items():
            b.setChecked((k == "back") == back)
        ph = getattr(self, "phone", None)
        if ph is not None and hasattr(ph, "dirty"):
            try:
                ph.dirty("status")
            except Exception:  # noqa: BLE001
                pass

    def _update_next_text(self):
        names = []
        for x in self.jobs:
            n = x.card_name.strip()
            if n and n not in names and not x.ig_only:
                names.append(n)
        if getattr(self, "c_pair", None) is not None and (self.c_pair.isChecked() or self.c_batch.isChecked()):
            # front then back for each card, counting the pairs shot but not named yet
            k = len(names) + sum(1 for x in self.jobs if getattr(x, "_new_card", False) and not x.card_name.strip())
            if getattr(self, "_pair_front", None) is not None:
                self.next_lbl.setText(f"Card {k} · Back")
            else:
                self.next_lbl.setText(f"Card {k + 1} · Front")
            self.next_lbl.setToolTip("")
            return
        if self.next_side == "back" and self.next_name:
            k = names.index(self.next_name) + 1 if self.next_name in names else len(names)
            self.next_lbl.setText(f"Card {k} · Back")
            self.next_lbl.setToolTip(self.next_name)
        else:
            self.next_lbl.setText(f"Card {len(names) + 1} · Front")
            self.next_lbl.setToolTip("")

    def _place_floats(self):
        b = self.banner
        if b.isVisible():
            b.adjustSize()
            # centred low on the photo (or above the List action bar), never over the controls
            area = {"edit": self.canvas_isl, "shoot": self.live_isl}.get(self.stage, self.stages.currentWidget())
            tl = area.mapTo(self.root, area.rect().topLeft())
            ar = QRectF(tl.x(), tl.y(), area.width(), area.height())
            w = int(min(b.sizeHint().width(), ar.width() - 48))
            h = max(b.heightForWidth(w) if b.hasHeightForWidth() else 0, b.sizeHint().height())
            lift = 104 if self.stage == "list" else (190 if self.stage == "edit" else 120)
            b.setGeometry(int(ar.x() + (ar.width() - w) / 2), int(ar.bottom() - h - lift), w, h)
            b.raise_()

    # ---------- saved camera settings
    CAM_PRESET_KEYS = ("wb", "kelvin", "fnumber", "shutter", "iso", "ev", "focus", "area")

    ROUTES = {"direct": ("Upload to eBay",
                         "Uploads the photos and creates the listing on eBay without publishing it; "
                         "put it live from Review and publish"),
              "drafts": ("Make eBay draft",
                         "Photos go up to eBay, then a drafts file puts this card in your eBay Drafts "
                         "after one Upload template click in Seller Hub")}

    # --- presets
    BUILTIN_PRESETS = {
        "eBay listing (default)": dict(corners=True, corner_frac=0.30, margin_px=20, lock_ratio=True, auto_portrait=True,
                                       corner_px=1600, out_format="png", hero=True, hero_bg="light", ig=True, grade=True,
                                       **{k: 0.0 for k in engine.EDIT_KEYS}),
        "No tone edits": {k: 0.0 for k in engine.EDIT_KEYS},
        "Already edited photos": dict(lens_profile="", lens_k1=0.0, ig=True,
                                      **{k: 0.0 for k in engine.EDIT_KEYS}),
        # under-$1 cards: the front, the back and the side-by-side hero, nothing else
        "Bulk (under $1)": dict(corners=False, corner_px=0, hero=True, hero_bg="light", ig=False, grade=False,
                                out_format="jpg", margin_px=20),
    }
    PRESET_KEYS = ("corners", "corner_frac", "margin_px", "lock_ratio", "flatten", "auto_portrait", "corner_px", "out_format",
                   "hero", "hero_sides", "hero_bg", "grade", "ig", "lens_k1", "lens_profile", "lens_raw_only") + engine.EDIT_KEYS


def _pin_qt_plugins():
    """opencv-python (the non-headless build) bundles its own Qt and, on import,
    points QT_QPA_PLATFORM_PLUGIN_PATH at it, which leaves PySide6 unable to find
    its macOS 'cocoa' plugin. Point Qt back at PySide6's own plugins."""
    from PySide6.QtCore import QLibraryInfo
    plugins = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    if os.path.isdir(plugins):
        os.environ["QT_PLUGIN_PATH"] = plugins
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(plugins, "platforms")


def selftest():
    """Used by the build script: proves the bundled engines load and work."""
    import numpy as np  # noqa: F811
    img = np.full((2095, 1500, 3), 235, np.uint8)
    cv2.putText(img, "4/102", (1180, 2030), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 4, cv2.LINE_AA)
    import rawpy  # noqa: F401
    import card3d  # noqa: F401
    try:
        import imageio_ffmpeg
        print("self-test: video encoder at", os.path.basename(imageio_ffmpeg.get_ffmpeg_exe()))
    except Exception as e:  # noqa: BLE001
        print("self-test: video encoder missing, 3D video falls back to OpenCV:", e)
    try:
        r = identify.read_number(img)
    except ImportError:
        print("self-test: RAW decoder and detection engine loaded; card number reader NOT installed "
              "(Identify will search by name only)")
        sys.exit(0)
    print(f"self-test: OCR read {r.text() or 'nothing'}; RAW decoder loaded; detection engine loaded")
    sys.exit(0 if r.text() == "4/102" else 1)


def main():
    if "--selftest" in sys.argv:
        selftest()
    _pin_qt_plugins()
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    try:                           # the Shipments page's hidden browser has to load before the app does
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        import PySide6.QtWebEngineCore  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    load_fonts()
    cfg = QSettings("CardCrop", "CardCrop")
    set_theme(str(cfg.value("theme", "light")))
    set_ui_pt(int(cfg.value("ui_pt", DEFAULT_PT)))
    w = Main()
    if QSettings("CardCrop", "CardCrop").value("window_geom") is None:
        w.showMaximized()          # first open: fill the screen; after that, the size you left it at
    else:
        w.show()
    if len(sys.argv) > 1:
        w.add_paths(sys.argv[1:])
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
