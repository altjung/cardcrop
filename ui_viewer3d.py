"""CardCrop 3D stage: the card in a sleeve and top loader, animation and video export."""
from __future__ import annotations

import engine
import identify
import json
import math
import os
import time
from PySide6.QtCore import QThreadPool, QTimer, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QProgressDialog, QPushButton, QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget
import ui_base as TH
import ui_motion as motion

SHOW_3D = True
SHOW_LAYERS = True


class Viewer3D(QWidget):
    """The card in 3D: drag to turn it any way, presets for the moves you want on camera,
    and an MP4 of a full turn (or of whatever you do) for Instagram or a listing."""

    MOTIONS = [("loop", "Steady loop"), ("eased", "Eased, pausing on the front"), ("showcase", "Sway, then a full turn"),
               ("corners", "Corner tour, front"), ("corners_both", "Corner tour, both sides"),
               ("edges", "Edge tour, front"), ("pan", "Pan top to bottom"), ("reel", "Reel: sway, turn, corner tour"),
               ("sleeve_in", "Sleeve it"), ("sleeve_load", "Sleeve it, then top load"),
               ("unload", "Out of the top loader and sleeve"), ("unsleeve", "Out of the sleeve")]
    TOUR_SECS = {"corners": 9, "corners_both": 16, "edges": 9, "pan": 6, "reel": 15, "sleeve_in": 4, "sleeve_load": 8,
                 "unload": 8, "unsleeve": 4}      # long enough to read each stop
    CAMERAS = [("", "Still camera"), ("push_slow", "Slow push in"), ("push_fast", "Fast push in"),
               ("pull_back", "Pull back reveal"), ("breathe", "Breathe in and out")]
    SIZES = [((1080, 1080), "Square 1080"), ((1080, 1350), "Portrait 1080 × 1350"),
             ((1080, 1920), "Story 1080 × 1920"), ((1920, 1080), "Wide 1920 × 1080"),
             ((2160, 2160), "Square 4K 2160"), ((2160, 3840), "Story 4K 2160 × 3840"),
             ((3840, 2160), "Wide 4K 3840 × 2160")]
    BGS = [("#18181A", "Dark"), ("#F2F2EF", "Light"), ("#FFFFFF", "White"), ("#D6F24B", "Lime")]

    def __init__(self, m):
        super().__init__()
        import card3d
        self.m, self.name, self.cfg = m, "", m.cfg
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.isl = Island("canvas")
        il = QVBoxLayout(self.isl)
        il.setContentsMargins(0, 0, 0, 0)
        self.view = card3d.CardView(None, None)
        self.view.on_space = lambda: self.b_spin.toggle()
        self.view.mode = str(self.cfg.value("3d_mode", "whole"))
        self.view.holo = float(self.cfg.value("3d_holo", 0.6))
        self.view.on_change = self._angles
        il.addWidget(self.view)
        import animui
        top_ = QWidget()
        h_ = QHBoxLayout(top_)
        h_.setContentsMargins(0, 0, 0, 0)
        h_.setSpacing(10)
        h_.addWidget(self.isl, 1)
        self.anim_ed = animui.AnimEditor(self.view, self.say)
        self.anim_ed.hide()
        self.anim_ed.changed.connect(self._anim_changed)
        self.anim_ed.closed.connect(self.close_animate)
        self.anim_ed.export.connect(self.export_animation)
        self.anim_ed.blender.connect(self.export_blender)
        self.anim_ed.cards_wanted.connect(self.animate_cards)
        self.view.on_seq_time = self.anim_ed.on_time
        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(10)
        self.split.addWidget(top_)
        self.split.addWidget(self.anim_ed)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        v.addWidget(self.split)

        # top left: which card, and where it is pointing
        self.pick = QComboBox()
        self.pick.setMinimumWidth(240)
        self.pick.setMaxVisibleItems(24)
        self.pick.setToolTip("The card to hold: this batch first, then cards exported earlier")
        self.pick.activated.connect(lambda _i: self.load(self.pick.currentData() or ""))
        self.lbl_ang = QLabel("", objectName="mono")
        self.b_group = QPushButton("Several cards…")
        self.b_group.setToolTip("Show several cards together and animate them: flip through a stack, round a "
                                "circle, fan out, a wave of turns, spread and gather. Export makes the video")
        self.b_group.clicked.connect(self.pick_group)
        self.b_anim = QPushButton("Animate…")
        self.b_anim.setToolTip("Build your own animation of one card or several, on a timeline or as nodes: "
                               "flips, spins, stacks, fans, entrances and camera moves, each a block you place")
        self.b_anim.clicked.connect(self.open_animate)
        self.isl.float_widget(hud(self.pick, self.lbl_ang, self.b_group, self.b_anim, margins=(6, 4, 8, 4),
                                  spacing=12), "tl")
        # while a group shows: what it is, its animation, and the way back to one card
        self.grp_lbl = QLabel("")
        self.grp_combo = QComboBox()
        for k, (label, _fn) in card3d.GROUP_PRESETS.items():
            self.grp_combo.addItem(label, k)
        self.grp_combo.activated.connect(lambda i: self._group_preset(self.grp_combo.itemData(i)))
        b_edit = QPushButton("Change cards…")
        b_edit.clicked.connect(self.pick_group)
        b_one = QPushButton("Back to one card")
        b_one.clicked.connect(lambda: self.exit_group())
        # your camera on the group: turn round it, look down or up, move in or out. 0° and 0° is each
        # animation's own framing, and every group and every animation starts there
        self.grp_sl, self.grp_box = {}, {}
        cam_bits = []
        for key, label, lo, hi, suf, tip in (("yaw", "Turn", -90, 90, "°", "Turn the camera round the group"),
                                             ("pitch", "Tilt", -45, 60, "°", "Look down on the group, or up at it"),
                                             ("zoom", "Distance", 50, 200, "%", "Move in close, or step back")):
            l_ = QLabel(label)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi)
            sl.setFixedWidth(90)
            sl.setToolTip(tip)
            sl.setStyleSheet(
                "QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,40); border-radius: 2px; }"
                f"QSlider::sub-page:horizontal {{ background: {LIME}; border-radius: 2px; }}"
                "QSlider::handle:horizontal { background: #F2F2EF; border: none; width: 14px; height: 14px;"
                " margin: -5px 0; border-radius: 7px; }")
            box = QSpinBox()
            box.setRange(lo, hi)
            box.setSuffix(suf)
            box.setFixedWidth(70)
            box.setAlignment(Qt.AlignCenter)
            box.setToolTip(tip + "; type a number and press Return")
            box.setStyleSheet(f"QSpinBox {{ background: rgba(255,255,255,20); color: {HUD_TEXT}; border-radius: 8px; }}"
                              "QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }")
            start = 100 if key == "zoom" else 0
            sl.setValue(start)
            box.setValue(start)
            sl.valueChanged.connect(lambda v, k=key: self._group_cam_set(k, v, src="slider"))
            box.valueChanged.connect(lambda v, k=key: self._group_cam_set(k, v, src="box"))
            self.grp_sl[key], self.grp_box[key] = sl, box
            cam_bits += [l_, sl, box]
        b_cam0 = QPushButton("0°, 0°")
        b_cam0.setToolTip("Back to the animation's own camera: Turn 0°, Tilt 0°, Distance 100%")
        b_cam0.clicked.connect(self._group_cam_reset)
        self.grp_bar = hud(self.grp_lbl, self.grp_combo, "|", *cam_bits, b_cam0, "|", b_edit, b_one,
                           margins=(12, 4, 6, 4), spacing=6)
        self.isl.float_widget(self.grp_bar, "t", my=64)
        self.grp_bar.hide()
        self.group_names = []
        self.empty = QLabel("Name a card in Edit (or export one) and it shows up here to turn in 3D.")
        self.empty.setStyleSheet(f"color:{HUD_TEXT}; font-size:{TH.BASE_PT + 2}pt;")
        self.isl.float_widget(self.empty, "c")
        self.empty.hide()

        # top right: export, and the inspector
        try:
            saved = json.loads(str(self.cfg.value("3d_fx", "{}")) or "{}")
        except ValueError:
            saved = {}
        self.view.fx.update({k: v for k, v in saved.items() if k in self.view.FX_DEFAULT})
        try:
            saved_l = json.loads(str(self.cfg.value("3d_light", "{}")) or "{}")
        except ValueError:
            saved_l = {}
        self.view.light.update({k: v for k, v in saved_l.items() if k in self.view.LIGHT_DEFAULT})
        try:
            saved_y = json.loads(str(self.cfg.value("3d_layers", "{}")) or "{}")
        except ValueError:
            saved_y = {}
        self.view.lay.update({k: v for k, v in saved_y.items() if k in self.view.LAYER_DEFAULT})
        if not SHOW_LAYERS:
            self.view.lay["on"] = False             # layered cards are shelved
        self.view.set_background(str(self.cfg.value("3d_bg", "#18181A")))
        self.view.set_bg_shader(str(self.cfg.value("3d_bg_fx", "") or ""))
        self.fx_panel = self._fx_panel()
        h_.addWidget(self.fx_panel)
        self.set_mode(self.view.mode)
        self._apply_bg_photo(quiet=True)
        self._apply_holder()
        self.view.on_holder = self._holder_from_view

        self.b_rec = icon_button("rec", "Record what you do here as an MP4 (click again to stop)", 36, role="hud",
                                 text=" Record")
        self.b_rec.clicked.connect(self.toggle_rec)
        self.b_exp = QPushButton("Export")
        self.b_exp.setObjectName("hudprimary")
        self.b_exp.setFixedHeight(36)
        self.b_exp.setToolTip("Save a video of the card turning, a still, or the card as a 3D model")
        exp_menu = QMenu(self.b_exp)
        exp_menu.addAction("Video of a 360° turn…", self.export_mp4)
        exp_menu.addAction("Reel for Instagram and TikTok…", self.export_reel)
        exp_menu.addAction("Video of several cards…", self.export_group_video)
        exp_menu.addAction("3D model for Blender and Cinema 4D…", self.export_obj)
        self.b_exp.setMenu(exp_menu)
        self.b_obj = self.b_exp                       # kept for older callers
        self.b_fx = QPushButton("Inspector")
        self.b_fx.setCheckable(True)
        self.b_fx.setFixedHeight(36)
        self.b_fx.setToolTip("Material, layers, light, camera and scene, in the panel on the right")
        self.b_fx.setChecked(str(self.cfg.value("3d_inspector", "1")) == "1")
        self.b_fx.toggled.connect(self._show_fx)
        self._show_fx(self.b_fx.isChecked())
        self.isl.float_widget(hud(self.b_rec, "|", self.b_fx, self.b_exp, margins=(6, 5, 6, 5), spacing=4), "tr")

        # bottom: the moves as a tray of line icons with a word under each, as on the phone
        T_ICONS = {
            "front": '<rect x="6" y="3" width="12" height="18" rx="2"/><path d="M9 7h6M9 10h4"/>',
            "back": '<rect x="6" y="3" width="12" height="18" rx="2"/><circle cx="12" cy="12" r="3"/>',
            "flip": '<path d="M12 3v18"/><path d="M8 7L3 12l5 5V7zM16 7l5 5-5 5V7z"/>',
            "spin": '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v4h-4"/>',
            "sway": '<path d="M3 12c3-5 6-5 9 0s6 5 9 0"/>',
            "turntable": '<ellipse cx="12" cy="16" rx="8" ry="3"/><path d="M12 4v9M9 7l3-3 3 3"/>',
            "entrance": '<path d="M3 12h11M10 8l4 4-4 4"/><path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4"/>',
            "outro": '<path d="M10 12h11M17 8l4 4-4 4"/><path d="M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4"/>',
            "camera": '<path d="M4 8h3l2-2h6l2 2h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
            "reset": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="1.5"/>',
        }

        def tray(key, label, tip, fn=None, menu=None, checkable=False):
            import weakref
            from PySide6.QtCore import QSize
            from PySide6.QtWidgets import QToolButton
            b = QToolButton(objectName="tray")
            b.setText(label.upper())
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            name = "svg:" + T_ICONS[key]
            b.setIcon(make_icon(name, 40, TH.HUD_TEXT))
            TH._ICONS.append((weakref.ref(b), name, "hud"))
            b.setIconSize(QSize(20, 20))
            b.setFixedSize(60, 54)
            f = b.font()
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
            b.setFont(f)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b._icon = name
            if fn is not None:
                b.clicked.connect(lambda _=False, f_=fn: f_())     # never hand a move the button's checked flag
            if menu is not None:
                b.setMenu(menu)
                b.setPopupMode(QToolButton.InstantPopup)
            if checkable:
                b.setCheckable(True)
                # on the lime of the checked state the icon goes dark, as the phone's does
                b.toggled.connect(lambda on, b_=b, n=name: b_.setIcon(make_icon(n, 40, "#111111" if on else TH.HUD_TEXT)))
            return b
        face = [tray("front", "Front", "Face-on front", self.view.show_front),
                tray("back", "Back", "Face-on back", self.view.show_back),
                tray("flip", "Flip", "Half a turn to the other side  (F)", self.view.flip)]
        turns = [tray("spin", "Spin", "One full eased turn", self.view.spin360),
                 tray("sway", "Sway", "Tilt either side so the foil sweeps across", self.view.sway)]
        self.b_spin = tray("turntable", "Turn", "Turntable: keep turning; off eases it to a stop  (Space)",
                           checkable=True)
        self.b_spin.toggled.connect(lambda on: self.view.set_spin(on))
        turns.append(self.b_spin)
        ent_menu = QMenu(self)
        for k, (label, _fn) in card3d.ENTRANCES.items():
            ent_menu.addAction(label, lambda k_=k: self.play_entrance(k_))
        self.b_ent = tray("entrance", "Enter", "Bring the card in: drop, rise, slide, flip, tumble, spiral, pop or "
                          "toss. The one you pick last also opens your exported videos", menu=ent_menu)
        out_menu = QMenu(self)
        for k, (label, _fn) in card3d.OUTROS.items():
            out_menu.addAction(label, lambda k_=k: self.view.play_outro(k_))
        self.b_out = tray("outro", "Exit", "Send the card out of frame: drop out, lift off, slide out, flip, tumble, "
                          "spiral, pop or toss away. It comes back a moment later", menu=out_menu)
        b_home = tray("reset", "Centre", "Face-on at 0° and 0°  (double-click)", self.view.reset)
        cam_menu = QMenu(self)
        for k, (label, _fn, _secs, _own) in card3d.CAMERA_MOVES.items():
            if k in (card3d.TOUR_MOVES[0], card3d.SLEEVE_MOVES[0]):
                cam_menu.addSeparator()
            cam_menu.addAction(label, lambda k_=k: self.view.play_camera(k_))
        cam_menu.addSeparator()
        cam_menu.addAction("Pull focus", self.view.pull_focus)
        self.b_cam = tray("camera", "Camera", "Camera moves: push in, pull back, breathe, and close tours of the "
                          "corners and edges for condition. The same moves are in Export", menu=cam_menu)
        self.isl.float_widget(hud(*face, "|", *turns, "|", self.b_ent, self.b_out, self.b_cam, "|", b_home,
                                  margins=(6, 4, 6, 4), spacing=0), "b", my=20)

        self.notice = Notice(self.isl)
        self.isl.float_widget(self.notice, "bl", my=80)
        self.notice.hide()
        self._angles(self.view.yaw, self.view.pitch)

    # ---------- the stage
    def _choices(self):
        """The card on screen now, the cards in this batch, then card folders already exported (newest first)."""
        import stats
        names = list(self.m._card_names())
        for n in reversed(list(getattr(self, "_shown", {}))):        # cards shown from elsewhere (a listing)
            if n not in names:
                names.insert(0, n)
        try:
            dirs = sorted((e for e in os.scandir(self.m.out_dir) if e.is_dir()), key=lambda e: -e.stat().st_mtime)
        except OSError:
            dirs = []
        seen = {engine.safe_name(n) for n in names}
        older = []
        for e in dirs[:300]:
            if e.name in seen:
                continue
            try:
                if any(stats.MAIN_PHOTO_RE.search(f) for f in os.listdir(e.path)):
                    older.append(e.name)
            except OSError:
                pass
        return names, older

    def enter(self, name=""):
        names, older = self._choices()
        self.pick.blockSignals(True)
        self.pick.clear()
        for n in names:
            self.pick.addItem(n, n)
        if names and older:
            self.pick.insertSeparator(self.pick.count())
        for n in older:
            self.pick.addItem(n, n)
        self.pick.blockSignals(False)
        want = name or self.name or (names[0] if names else (older[0] if older else ""))
        i = self.pick.findData(want)
        if i >= 0:
            self.pick.setCurrentIndex(i)
        self.empty.setVisible(not (names or older) and not self.name)
        self.isl._place()
        if want and (want != self.name or i < 0 or not self.view.has_card()):
            self.load(want)
        self.view.setFocus()

    def load(self, name):
        if self.view.rec is not None:
            self.toggle_rec()
        front, back = self.m._card_sides(name)
        if front is None and back is not None:
            front, back = back, None
        self.name = name
        if front is None:
            self.say("No straightened photo of this card yet: set its corners in Edit first.", "info")
            return
        self.exit_group(quiet=True)
        self.empty.hide()
        self.view.set_images(front, back)
        self.view.reset()
        self._apply_holder()
        self._layers_refresh()

    def show_images(self, name, front, back):
        """A card from elsewhere (a live listing's photos), shown without touching the batch."""
        if front is None and back is not None:
            front, back = back, None
        self.name = name
        # remembered, so the card picker, Animate and Several cards know it as the card on screen
        if not hasattr(self, "_shown"):
            self._shown = {}
        self._shown[name] = (front, back)
        self.pick.blockSignals(True)
        if self.pick.findData(name) < 0:
            self.pick.insertItem(0, name, name)
        self.pick.setCurrentIndex(self.pick.findData(name))
        self.pick.blockSignals(False)
        self.exit_group(quiet=True)
        self.empty.hide()
        self.view.set_images(front, back)
        self.view.reset()
        self._apply_holder()
        if self.view.lay.get("on"):                  # a video is about to be made: build now
            self.layers_now()

    # ---------- layers (frame, background, subject)
    def _manual_folder(self):
        """Your own PNG layers for the shown card: a folder you picked for it, or a "layers" folder
        inside its export folder."""
        import layers
        try:
            known = json.loads(str(self.cfg.value("layer_folders", "{}")) or "{}")
        except ValueError:
            known = {}
        d = known.get(self.name or "")
        if d and os.path.isdir(d) and layers.find_pngs(d):
            return d
        if self.name:
            d = os.path.join(self.m.out_dir, engine.safe_name(self.name), "layers")
            if os.path.isdir(d) and layers.find_pngs(d):
                return d
        return ""

    def _use_manual(self, folder, quiet=False):
        import layers
        try:
            data = layers.from_pngs(folder, self._fit_for(), order=self._order_for(), depths=self._depth_for())
        except Exception as e:  # noqa: BLE001
            self.say(f"Those layers could not be used: {e}", "error")
            return False
        self.view.set_layers(data)
        self._arr_folder = folder
        self._arr_show(data)
        if not quiet:
            roles = ", ".join(r for r in ("subject", "frame", "backdrop") if r in data["files"])
            self.say(f"Using your PNG layers ({roles}).", "ok", secs=4)
        return True

    # ---------- arranging your own PNGs
    def _fits(self):
        try:
            return json.loads(str(self.cfg.value("layer_fit", "{}")) or "{}")
        except ValueError:
            return {}

    def _fit_for(self):
        return {r: tuple(v) for r, v in self._fits().get(self.name or "", {}).items()}

    def _depths(self):
        try:
            return json.loads(str(self.cfg.value("layer_depth", "{}")) or "{}")
        except ValueError:
            return {}

    def _depth_for(self):
        return {r: float(v) for r, v in self._depths().get(self.name or "", {}).items()}

    def _order_for(self):
        try:
            return json.loads(str(self.cfg.value("layer_order", "{}")) or "{}").get(self.name or "")
        except ValueError:
            return None

    @staticmethod
    def _size_of(v):          # slider -100..100 -> 0.33x..3x, even steps either way
        return 3.0 ** (v / 100.0)

    def _arr_show(self, data):
        if getattr(self, "arr_box", None) is None:
            return
        files = data.get("files", {})
        self._arr_defdepth = {x["name"]: float(x["depth"]) for x in data.get("stack", [])}
        roles = [r for r in ("subject", "backdrop") if r in files] + list(data.get("frame_names", []))
        self.arr_box.setVisible(bool(roles))
        if roles and self.arr_role not in roles:
            self.arr_role = roles[0]
        self.arr_combo.blockSignals(True)
        self.arr_combo.clear()
        for r in roles:
            self.arr_combo.addItem(r.title() if r in ("subject", "backdrop") else f"Frame · {r}", r)
        self.arr_combo.setCurrentIndex(max(0, self.arr_combo.findData(self.arr_role)))
        self.arr_combo.blockSignals(False)
        self._arr_load()
        if getattr(self, "fx_panel", None) is not None:
            self._fx_page(self.fx_stack.currentIndex())

    def _arr_pick(self, role):
        if role:
            self.arr_role = role
        self._arr_load()

    def _arr_load(self):
        sc, dx, dy = self._fit_for().get(self.arr_role, (1.0, 0.0, 0.0))
        dep = self._depth_for().get(self.arr_role, getattr(self, "_arr_defdepth", {}).get(self.arr_role, 0.0))
        vals = {"size": int(round(100 * math.log(max(sc, 1e-3)) / math.log(3.0))),
                "x": int(round(dx * 100 / 0.6)), "y": int(round(-dy * 100 / 0.6)),
                "depth": int(round(dep * 100))}
        # the backdrop's depth is the Depth slider above: it sets how far back the whole window goes
        for w_ in getattr(self, "arr_depth_row", ()):
            w_.setEnabled(self.arr_role != "backdrop")
        for k, (sl, val) in self.arr_sl.items():
            sl.blockSignals(True)
            sl.setValue(max(-100, min(100, vals[k])))
            sl.blockSignals(False)
        self._arr_labels()

    def _arr_labels(self):
        v = {k: sl.value() for k, (sl, _l) in self.arr_sl.items()}
        self.arr_sl["size"][1].setText(f"{self._size_of(v['size']) * 100:.0f}%")
        self.arr_sl["x"][1].setText(f"{v['x'] * 0.6:+.0f}%")
        self.arr_sl["y"][1].setText(f"{v['y'] * 0.6:+.0f}%")
        dv = v["depth"]
        self.arr_sl["depth"][1].setText("Surface" if dv == 0 else (f"Back {dv}" if dv > 0 else f"Front {-dv}"))

    def _arr_changed(self):
        self._arr_labels()
        v = {k: sl.value() for k, (sl, _l) in self.arr_sl.items()}
        allf = self._fits()
        mine = allf.setdefault(self.name or "", {})
        mine[self.arr_role] = [self._size_of(v["size"]), v["x"] * 0.6 / 100, -v["y"] * 0.6 / 100]
        self.cfg.setValue("layer_fit", json.dumps(allf))
        if self.arr_role != "backdrop":
            alld = self._depths()
            cur = self._depth_for().get(self.arr_role, getattr(self, "_arr_defdepth", {}).get(self.arr_role, 0.0))
            if abs(cur - v["depth"] / 100) > 1e-6:
                alld.setdefault(self.name or "", {})[self.arr_role] = v["depth"] / 100
                self.cfg.setValue("layer_depth", json.dumps(alld))
        self._arr_timer.start()

    def _arr_reset(self):
        allf = self._fits()
        allf.get(self.name or "", {}).pop(self.arr_role, None)
        self.cfg.setValue("layer_fit", json.dumps(allf))
        alld = self._depths()
        alld.get(self.name or "", {}).pop(self.arr_role, None)
        self.cfg.setValue("layer_depth", json.dumps(alld))
        self._arr_load()
        self._arr_apply()

    def arrange_dialog(self):
        folder = getattr(self, "_arr_folder", "")
        if not folder:
            return
        d = ArrangeDialog(self, folder, {r: list(v) for r, v in self._fit_for().items()}, self._order_for())
        if d.exec() != QDialog.Accepted:
            return
        allf = self._fits()
        allf[self.name or ""] = {r: [float(x) for x in v] for r, v in d.fit.items()}
        self.cfg.setValue("layer_fit", json.dumps(allf))
        try:
            allo = json.loads(str(self.cfg.value("layer_order", "{}")) or "{}")
        except ValueError:
            allo = {}
        allo[self.name or ""] = d.order
        self.cfg.setValue("layer_order", json.dumps(allo))
        self._arr_load()
        self._arr_apply()

    def _arr_apply(self):
        folder = getattr(self, "_arr_folder", "")
        if folder:
            self._use_manual(folder, quiet=True)

    def pick_layer_folder(self):
        import layers
        d = QFileDialog.getExistingDirectory(self, "A folder with subject.png, frame.png and backdrop.png",
                                             self._folder())
        if not d:
            return
        found = layers.find_pngs(d)
        if not found:
            self.say("No PNG in that folder is named subject, frame or backdrop (foreground, border and "
                     "background work too).", "error", secs=8)
            return
        try:
            known = json.loads(str(self.cfg.value("layer_folders", "{}")) or "{}")
        except ValueError:
            known = {}
        if self.name:
            known[self.name] = d
            self.cfg.setValue("layer_folders", json.dumps(known))
        if self._use_manual(d):
            self._lay_set("on", True)

    def use_auto_layers(self):
        try:
            known = json.loads(str(self.cfg.value("layer_folders", "{}")) or "{}")
        except ValueError:
            known = {}
        known.pop(self.name or "", None)
        self.cfg.setValue("layer_folders", json.dumps(known))
        self._arr_folder = ""
        self.arr_box.hide()
        self.view.set_layers(None)
        self._layers_refresh()

    def _layers_refresh(self):
        """Splits the shown card into layers in the background when layers are on: your own PNGs
        when the card has them, else the automatic split."""
        if not self.view.lay.get("on") or self.view.front_np is None:
            return
        manual = self._manual_folder()
        if manual:
            self._use_manual(manual)
            return
        import layers
        if not layers.available():
            return
        if not layers.have_model():                  # turned on before, but a model is new or missing
            if not getattr(self, "_asking_models", False):
                self._asking_models = True
                try:
                    self._layers_toggle(True)
                finally:
                    self._asking_models = False
            return
        self.say("Separating the subject from the background…", "info", secs=3)
        t = CallTask(layers.build, self.view.front_np, float(self.view.lay["frame"]))
        want = id(self.view.front_np)
        t.then(lambda data, err: (self.say(f"Layers could not be made: {err}", "error") if err else
                                  self.view.set_layers(data) if id(self.view.front_np) == want else None))
        QThreadPool.globalInstance().start(t)

    def layers_now(self):
        manual = self._manual_folder()
        if manual:
            self._use_manual(manual)
            return
        import layers
        if self.view.front_np is None or not (layers.available() and layers.have_model()):
            return
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.view.set_layers(layers.build(self.view.front_np, float(self.view.lay["frame"])))
        except Exception as e:  # noqa: BLE001
            self.say(f"Layers could not be made: {e}", "error")
        finally:
            QApplication.restoreOverrideCursor()

    def _layers_toggle(self, on):
        import layers
        if on and self._manual_folder():           # your own PNGs need no model
            self._lay_set("on", True)
            self._layers_refresh()
            return
        if on and not layers.available():
            self.say("Layers need onnxruntime, which this build does not have. Rebuild CardCrop to add it.", "error")
            self._lay_chk.setChecked(False)
            return
        if on and not layers.have_model():
            if QMessageBox.question(self, "Download the layer model",
                                    "Splitting a card into frame, background and subject uses two models, one "
                                    "trained on anime-style art and one on objects in general, like Photoshop's "
                                    "Select Subject. They download once (about 350 MB) and then run on this Mac "
                                    "with no internet. Download them now?") != QMessageBox.Yes:
                self._lay_chk.setChecked(False)
                self._lay_set("on", False)
                return
            prog = QProgressDialog("Downloading the layer models…", "Cancel", 0, 100, self)
            prog.setWindowModality(Qt.WindowModal)
            prog.setMinimumDuration(0)

            def step(done, total):
                prog.setValue(int(done * 100 / max(1, total)))
                QApplication.processEvents()
                return not prog.wasCanceled()
            try:
                layers.download_model(step)
            except Exception as e:  # noqa: BLE001
                prog.close()
                self.say(f"The models did not download: {e}", "error")
                self._lay_chk.setChecked(False)
                self._lay_set("on", False)
                return
            prog.close()
        self._lay_set("on", on)
        if on and not self.view.layers:
            self._layers_refresh()

    def _lay_set(self, key, value):
        self.view.lay[key] = value
        self.cfg.setValue("3d_layers", json.dumps(self.view.lay))
        self._fx_sync()
        self.view.update()

    def play_entrance(self, k):
        self.cfg.setValue("3d_entrance", k)
        self.view.play_entrance(k)

    def render_saved(self, path, progress=None):
        """A 360° turn with the last export settings (entrance, motion, length, size, background),
        for a listing: always H.264, since eBay takes MP4 up to 150 MB and plays H.264 everywhere."""
        w, h = self._video_size()
        q = str(self.cfg.value("3d_quality", "standard"))
        q = q if q in ("standard", "high") else "high"
        return self.view.export_turntable(path, w, h, float(int(self.cfg.value("3d_secs", 6))),
                                          int(self.cfg.value("3d_fps", 30)),
                                          str(self.cfg.value("3d_motion", "loop")), self._video_bg(), progress,
                                          entrance=str(self.cfg.value("3d_video_entrance", "")),
                                          outro=str(self.cfg.value("3d_video_outro", "")), quality=q,
                                          camera=str(self.cfg.value("3d_camera", "")),
                                          motion_blur=str(self.cfg.value("3d_mblur", "0")) == "1",
                                          focus_pull=str(self.cfg.value("3d_focuspull", "0")) == "1")

    def leave(self):
        if self.view.rec is not None:
            self.toggle_rec()
        self.view.stop()
        if self.b_spin.isChecked():
            self.b_spin.blockSignals(True)
            self.b_spin.setChecked(False)
            self.b_spin.blockSignals(False)
            self.b_spin.setIcon(make_icon(self.b_spin._icon, 40, HUD_TEXT))

    def say(self, text, kind="info", **k):
        self.notice.show_msg(text, kind, **k)
        self.isl._place()

    def _angle_box(self, lo, hi, tip):
        b = QSpinBox()
        b.setRange(lo, hi)
        b.setSuffix("°")
        b.setWrapping(lo == -180)
        b.setToolTip(tip + "; type a number and press Return")
        b.setFixedWidth(66)
        b.setAlignment(Qt.AlignCenter)
        b.setStyleSheet(f"QSpinBox {{ background: rgba(255,255,255,20); color: {HUD_TEXT}; }}"
                        "QSpinBox QLineEdit { padding: 0 6px; }")
        return b

    def _angles(self, yaw, pitch):
        y = int(round((yaw + 180) % 360 - 180))
        p = int(round((pitch + 180) % 360 - 180))
        self.lbl_ang.setText(f"{y:+d}°  {p:+d}°")
        for b_, val in ((self.turn, y), (self.tilt, max(-90, min(90, p)))):
            if not b_.hasFocus():
                b_.blockSignals(True)
                b_.setValue(val)
                b_.blockSignals(False)

    def _go_angle(self):
        self.view.angle(self.turn.value(), self.tilt.value())

    FX_SLIDERS = (("dispersion", "Dispersion", 0.1, 4.0, "How far the rainbow spreads: low is one soft colour, "
                                                         "high is many tight bands of colour"),
                  ("scale", "Scale", 4.0, 90.0, "Band, ring, ray or shard size: low is broad, high is fine"),
                  ("saturation", "Saturation", 0.0, 1.0, "From silver foil to full colour"),
                  ("response", "Response", 0.0, 2.0, "How much the foil shifts as the card tilts"),
                  ("sparkle", "Sparkle", 0.0, 1.5, "Glints scattered over the foil"))
    FX_PATTERNS = (("linear", "Linear", "Diagonal bands, the classic sheen"),
                   ("radial", "Radial", "Rings radiating out from a centre that follows the light"),
                   ("sunburst", "Sunburst", "Rays out from a centre, like a starlight or cosmos foil"),
                   ("ice", "Ice", "Cracked-ice shards, each catching its own colour"),
                   ("glitter", "Glitter", "A fine field of flecks that flicker as it turns"))

    # ---------- the inspector: one docked panel, a tab per part of the shot
    INSPECTOR_W = 380

    def _section(self, text, first=False):
        l = QLabel(text.upper(), objectName="insection")
        l.setContentsMargins(0, 0 if first else 14, 0, 0)
        return l

    def _ins_slider(self, label, tip, lo_hi=(0, 200), on_change=None, val_w=72):
        """A labelled slider in the inspector's style: the name and its value on one line, the full-width
        slider under them. Returns (layout, slider, value label, name label)."""
        box = QVBoxLayout()
        box.setSpacing(4)
        top = QHBoxLayout()
        name = QLabel(label, objectName="insname")
        name.setToolTip(tip)
        val = QLabel("", objectName="insval")
        val.setMinimumWidth(val_w)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(val)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(*lo_hi)
        sl.setToolTip(tip)
        sl.setObjectName("insslider")
        if on_change is not None:
            sl.valueChanged.connect(on_change)
        box.addLayout(top)
        box.addWidget(sl)
        return box, sl, val, name

    def _chip(self, label, tip="", checkable=True):
        from PySide6.QtGui import QFontMetrics
        b = QPushButton(label, objectName="inschip")
        b.setCheckable(checkable)
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        # tall enough for its text at the panel's size, so a grid of them never squeezes the words
        f = QFont(b.font())
        f.setPointSize(TH.BASE_PT + 1)
        b.setMinimumHeight(QFontMetrics(f).height() + 22)
        b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        return b

    def _chips(self, buttons, cols):
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(6)
        for i, b in enumerate(buttons):
            g.addWidget(b, i // cols, i % cols)
        return g

    def _fx_panel(self):
        from PySide6.QtWidgets import QScrollArea
        pages = {k: QVBoxLayout() for k in ("material", "layers", "light", "camera", "scene")}

        # MATERIAL: the finish, then the foil's pattern
        p = pages["material"]
        p.addWidget(self._section("Finish", first=True))
        self.holo_btns = {}
        for key, label, tip in (("off", "Plain", "No foil"), ("whole", "Holo", "Foil over the whole face"),
                                ("art", "Art", "Foil in the art window only, like a classic holo"),
                                ("reverse", "Reverse", "Foil everywhere but the art, like a reverse holo")):
            b = self._chip(label, tip)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            self.holo_btns[key] = b
        p.addLayout(self._chips(list(self.holo_btns.values()), 4))
        row, self.sl, self._holo_val, _n = self._ins_slider("Strength", "How strong the foil is", (0, 100),
                                                             self._holo)
        self.sl.setValue(int(self.view.holo * 100))
        self._holo_val.setText(f"{self.sl.value()}%")
        p.addLayout(row)
        p.addWidget(self._section("Pattern"))
        self.fx_btns = {}
        for key, label, tip in self.FX_PATTERNS:
            b = self._chip(label, tip)
            b.clicked.connect(lambda _=False, k=key: self._fx_set("pattern", k))
            self.fx_btns[key] = b
        p.addLayout(self._chips(list(self.fx_btns.values()), 3))
        self.fx_sl = {}
        for key, label, lo, hi, tip in self.FX_SLIDERS:
            row, sl, val, _n = self._ins_slider(label, tip, (0, 200),
                                                lambda v, k=key, a=lo, b=hi: self._fx_set(k, a + (b - a) * v / 200.0))
            p.addLayout(row)
            self.fx_sl[key] = (sl, val, lo, hi)

        # LAYERS: where they come from, their foil and light, how deep they sit, and your PNGs
        p = pages["layers"]
        p.addWidget(self._section("Source", first=True))
        self._lay_chk = QCheckBox("Split into frame, backdrop and subject")
        self._lay_chk.setToolTip("An AI model finds the subject; the frame stays on the surface, the background "
                                 "sits deep behind it and the subject floats in front, each lit and foiled on its "
                                 "own. Best on full-art and illustration cards")
        self._lay_chk.toggled.connect(self._layers_toggle)
        p.addWidget(self._lay_chk)
        b_png = self._chip("Use my PNGs…", "Your own layers for this card: a folder with subject.png, frame.png and "
                                           "backdrop.png (transparent where each layer is empty). A folder named "
                                           "layers inside the card's export folder is used on its own", False)
        b_png.clicked.connect(self.pick_layer_folder)
        b_auto = self._chip("Automatic", "Back to the AI split for this card", False)
        b_auto.clicked.connect(self.use_auto_layers)
        p.addLayout(self._chips([b_png, b_auto], 2))
        p.addWidget(self._section("Foil on"))
        self.lay_foil = {}
        for key, label in (("frame_foil", "Frame"), ("bg_foil", "Backdrop"), ("fg_foil", "Subject")):
            b = self._chip(label, f"Foil on the {label.lower()}, on or off")
            b.toggled.connect(lambda on, k=key: self._lay_set(k, 1.0 if on else 0.0))
            self.lay_foil[key] = b
        p.addLayout(self._chips(list(self.lay_foil.values()), 3))
        p.addWidget(self._section("Depth and light"))
        self.lay_sl = {}
        lay_rows = (("depth", "Depth", 0.0, 1.6, "How far apart the layers sit: more depth, more parallax as the "
                                                 "card turns"),
                    ("frame", "Frame width", 0.02, 0.09, "How wide the printed border is (automatic split only)"),
                    ("fg_light", "Subject light", 0.7, 1.6, "Light on the subject"),
                    ("bg_light", "Backdrop light", 0.4, 1.3, "Light on the background art"))
        for key, label, lo, hi, tip in lay_rows:
            row, sl, val, _n = self._ins_slider(label, tip, (0, 200),
                                                lambda v, k=key, a=lo, b=hi: self._lay_set(k, a + (b - a) * v / 200.0))
            p.addLayout(row)
            self.lay_sl[key] = (sl, val, lo, hi)
        b_dof = self._chip("Backdrop blur", "Only the backdrop goes soft, so the layers read as farther apart. "
                                            "For a lens blur over the whole card, use Depth of field under Camera")
        b_dof.toggled.connect(lambda on: self._lay_set("dof_on", 1.0 if on else 0.0))
        self.lay_foil["dof_on"] = b_dof
        p.addLayout(self._chips([b_dof], 2))
        row, sl, val, _n = self._ins_slider("Backdrop blur amount", "How soft the backdrop is with Backdrop blur on",
                                            (0, 200), lambda v: self._lay_set("dof", v / 200.0))
        p.addLayout(row)
        self.lay_sl["dof"] = (sl, val, 0.0, 1.0)
        # your own PNGs: size, place and stack each layer
        self.arr_box = QWidget()
        av_ = QVBoxLayout(self.arr_box)
        av_.setContentsMargins(0, 0, 0, 0)
        av_.setSpacing(10)
        av_.addWidget(self._section("Arrange your PNGs"))
        self.arr_role = "subject"
        self.arr_combo = QComboBox()
        self.arr_combo.setToolTip("The layer the sliders move: the subject, the backdrop or any frame file")
        self.arr_combo.activated.connect(lambda i: self._arr_pick(self.arr_combo.itemData(i)))
        av_.addWidget(self.arr_combo)
        b_drag = self._chip("Arrange and order…", "Open the card flat: drag each layer into place, and set which "
                                                  "layer sits on top (the subject in front of the frame for a "
                                                  "pop-out card)", False)
        b_drag.clicked.connect(self.arrange_dialog)
        b_ar = self._chip("Reset layer", "Back to the automatic fit for this layer", False)
        b_ar.clicked.connect(self._arr_reset)
        av_.addLayout(self._chips([b_drag, b_ar], 2))
        self.arr_sl = {}
        for key, label, tip in (("size", "Size", "Bigger or smaller than the automatic fit"),
                                ("x", "Left / right", "Move it across the art window"),
                                ("y", "Up / down", "Move it up or down the art window"),
                                ("depth", "Parallax", "How deep this layer sits, so it slides at its own speed as "
                                                      "the card turns: toward Back it drifts with the backdrop, "
                                                      "toward Front it floats over the card and slides the other "
                                                      "way. The middle stays on the card's surface")):
            row, sl, val, name = self._ins_slider(label, tip, (-100, 100), lambda _v: self._arr_changed())
            av_.addLayout(row)
            self.arr_sl[key] = (sl, val)
            if key == "depth":
                self.arr_depth_row = (name, sl, val)
        p.addWidget(self.arr_box)
        self.arr_box.hide()
        self._arr_timer = QTimer(self, singleShot=True, interval=140)
        self._arr_timer.timeout.connect(self._arr_apply)

        # LIGHT: the setup, then how it falls
        p = pages["light"]
        p.addWidget(self._section("Setup", first=True))
        self.light_btns = {}
        for key, label, tip in (
                ("studio", "Studio", "A key light high on the left, soft fill, a cool rim: lit like a product shot"),
                ("softbox", "Softbox", "One big even light from the front, low contrast"),
                ("dramatic", "Dramatic", "A hard key from the side, the far side in shadow, a strong rim"),
                ("sunset", "Sunset", "A warm low key with a violet fill"),
                ("classic", "Classic", "The original flat light with a sliding glare")):
            b = self._chip(label, tip)
            b.clicked.connect(lambda _=False, k=key: self._light_set("mode", k))
            self.light_btns[key] = b
        p.addLayout(self._chips(list(self.light_btns.values()), 3))
        p.addWidget(self._section("Response"))
        self.light_sl = {}
        light_rows = {"gloss": ("Gloss", 0.0, 1.0, "Matte to high gloss: sharper highlights and a brighter "
                                                    "reflection sliding across"),
                      "exposure": ("Exposure", 0.5, 1.8, "Overall brightness"),
                      "shadow": ("Shadow", 0.0, 1.0, "The soft shadow the card throws on the backdrop"),
                      "dof": ("Focus falloff", 0.0, 1.0, "How fast the card goes soft away from the point of "
                                                         "focus, with Depth of field on"),
                      "env": ("Reflection", 0.0, 1.0, "How much of the room shows in the card and in its sleeve, top loader or slab"),
                      "focus": ("Focus point", -0.3, 0.3, "Where the lens focuses: the middle is the card's "
                                                          "centre, left nearer the camera, right farther behind"),
                      "bloom": ("Bloom", 0.0, 1.0, "A soft glow round the brightest parts, the foil's flashes "
                                                   "above all"),
                      "vignette": ("Vignette", 0.0, 1.0, "The corners of the frame fall a little darker"),
                      "grain": ("Grain", 0.0, 1.0, "Fine film grain, so gradients never band and the frame "
                                                   "feels shot, not drawn"),
                      "drift": ("Light drift", 0.0, 1.0, "The lights drift slowly round the card, so highlights "
                                                         "and the foil keep moving even when the card is still. "
                                                         "In videos the drift comes back to where it began, so "
                                                         "loops stay seamless"),
                      "floor": ("Floor reflection", 0.0, 1.0, "How strong the card's reflection in the floor is")}

        def light_row(page, key):
            label, lo, hi, tip = light_rows[key]
            row, sl, val, _n = self._ins_slider(label, tip, (0, 200),
                                                lambda v, k=key, a=lo, b=hi: self._light_set(k, a + (b - a) * v / 200.0))
            page.addLayout(row)
            self.light_sl[key] = (sl, val, lo, hi)
        for k in ("gloss", "exposure", "shadow"):
            light_row(p, k)
        p.addWidget(self._section("Reflections"))
        self.light_env = self._chip("Room reflections", "The laminate and foil reflect a real room: a photo studio, "
                                                        "or your backdrop photo when you use one, so the card "
                                                        "picks up its colours as it turns")
        self.light_env.toggled.connect(lambda on: self._light_set("env_on", 1.0 if on else 0.0))
        p.addLayout(self._chips([self.light_env], 2))
        light_row(p, "env")
        p.addWidget(self._section("Movement"))
        light_row(p, "drift")

        # CAMERA: the lens, how the card settles, and exact angles
        p = pages["camera"]
        p.addWidget(self._section("Lens", first=True))
        self.light_dof = self._chip("Depth of field", "A lens focused on the middle of the card: as it turns, the "
                                                      "near and far edges go soft, the whole card and its layers "
                                                      "alike. In exports too")
        self.light_dof.toggled.connect(lambda on: self._light_set("dof_on", 1.0 if on else 0.0))
        p.addLayout(self._chips([self.light_dof], 2))
        light_row(p, "dof")
        light_row(p, "focus")
        b_pull = self._chip("Pull focus", "Watch it once: the lens starts focused behind the card and pulls onto "
                                          "it. Export can open a video this way", False)
        b_pull.clicked.connect(self.view.pull_focus)
        p.addLayout(self._chips([b_pull], 2))
        p.addWidget(self._section("Film"))
        for k in ("bloom", "vignette", "grain"):
            light_row(p, k)
        p.addWidget(self._section("Handling"))
        self.b_snap = self._chip("Snap to face", "Let go and the card settles face-on, front or back, level and "
                                                 "centred")
        self.view.snap = str(self.cfg.value("3d_snap", "1")) == "1"
        self.b_snap.setChecked(self.view.snap)

        def _snap(on):
            self.view.snap = on
            self.cfg.setValue("3d_snap", "1" if on else "0")
            if on and not self.view.busy():
                self.view.snap_center()
        self.b_snap.toggled.connect(_snap)
        p.addLayout(self._chips([self.b_snap], 2))
        p.addWidget(self._section("Angle"))
        self.turn = self._angle_box(-180, 180, "Turn: degrees round, 0 is the front, 180 the back")
        self.tilt = self._angle_box(-90, 90, "Tilt: degrees forward or back")
        for b_ in (self.turn, self.tilt):
            b_.editingFinished.connect(self._go_angle)
        ag = QGridLayout()
        ag.setHorizontalSpacing(10)
        ag.setVerticalSpacing(6)
        for c, (txt, box) in enumerate((("Turn", self.turn), ("Tilt", self.tilt))):
            ag.addWidget(QLabel(txt, objectName="insname"), 0, c)
            box.setMinimumWidth(100)
            box.setMaximumWidth(10000)
            box.setStyleSheet("")
            ag.addWidget(box, 1, c)
        p.addLayout(ag)
        quick = []
        for deg in (15, 30, 45):
            b = self._chip(f"{deg}°", f"Turn to {deg}° with a slight tilt", False)
            b.clicked.connect(lambda _=False, d=deg: self.view.angle(d, 6))
            quick.append(b)
        p.addLayout(self._chips(quick, 3))

        # SCENE: what is behind the card, in the view and in everything you export
        p = pages["scene"]
        p.addWidget(self._section("Background", first=True))
        self.bg_btns = {}
        for hx, label in self.BGS + [("#0B0B0C", "Black"), ("#8C8A84", "Stone")]:
            b = self._chip(label, f"A plain {label.lower()} background, in the view and in videos")
            b.clicked.connect(lambda _=False, h=hx: self._set_bg(h))
            self.bg_btns[hx] = b
        b_custom = self._chip("Custom…", "Any colour you like", False)
        b_custom.clicked.connect(self._pick_bg)
        p.addLayout(self._chips(list(self.bg_btns.values()) + [b_custom], 3))
        p.addWidget(self._section("Holder"))
        self.holder_btns = {}
        for key, label, tip in (("", "None", "The card on its own"),
                                ("sleeve", "Sleeve", "A clear fitted sleeve, cut close to the card"),
                                ("sleeve_tl", "Top loader", "In a fitted sleeve inside a 3 × 4 in top loader, the "
                                                            "way most cards ship"),
                                ("slab", "Slab", "A graded-style slab at real size with a label of the card's "
                                                 "details: year, game and set, name, number, and its condition "
                                                 "if you like. No number grade, no grading company's marks")):
            b = self._chip(label, tip)
            b.clicked.connect(lambda _=False, k=key: self._set_holder(k))
            self.holder_btns[key] = b
        p.addLayout(self._chips(list(self.holder_btns.values()), 2))
        self.slab_box = QWidget()
        sb = QGridLayout(self.slab_box)
        sb.setContentsMargins(0, 4, 0, 0)
        sb.setHorizontalSpacing(8)
        sb.setVerticalSpacing(6)
        self.slab_edits = {}
        for r_, (key, label, hint) in enumerate((("top", "Year and set", ""), ("name", "Name", ""),
                                                 ("number", "Number", ""), ("condition", "Condition", ""))):
            sb.addWidget(QLabel(label, objectName="insname"), r_, 0)
            e = QLineEdit()
            e.setProperty("hint", hint)
            e.setPlaceholderText(hint)
            e.editingFinished.connect(self._slab_edited)
            sb.addWidget(e, r_, 1)
            self.slab_edits[key] = e
        self.slab_cond = QCheckBox("Show the condition on the label")
        self.slab_cond.setToolTip("Your condition for the card (Near Mint, Lightly Played...) on the right of "
                                  "the label; off leaves just the card's details")
        self.slab_cond.toggled.connect(lambda on: (self.cfg.setValue("3d_slab_cond", "1" if on else "0"),
                                                   self._apply_holder()))
        sb.addWidget(self.slab_cond, 4, 0, 1, 2)
        note = QLabel("Blank fields use what CardCrop knows of the card.", objectName="insval")
        note.setWordWrap(True)
        sb.addWidget(note, 5, 0, 1, 2)
        p.addWidget(self.slab_box)
        self.slab_box.hide()
        p.addWidget(self._section("Floor"))
        self.light_floor = self._chip("Glossy floor", "The card stands just above a glossy surface and is "
                                                      "reflected in it, with a soft contact shadow, like a "
                                                      "tabletop product shot")
        self.light_floor.toggled.connect(lambda on: self._light_set("floor_on", 1.0 if on else 0.0))
        p.addLayout(self._chips([self.light_floor], 2))
        light_row(p, "floor")
        p.addWidget(self._section("Backdrop photo"))
        b_bgp = self._chip("Choose photo…", "Use a photo of your own behind the card, blurred and darkened, in the "
                                            "view and in videos and stills. Best at least 2160 px on its short "
                                            "side, in the shape of your video", False)
        b_bgp.clicked.connect(self.pick_bg_photo)
        self.b_bgp_clear = self._chip("Clear", "Back to the plain background colour", False)
        self.b_bgp_clear.clicked.connect(lambda: self.set_bg_photo(""))
        p.addLayout(self._chips([b_bgp, self.b_bgp_clear], 2))
        self.bgp_name = QLabel("", objectName="insval")
        self.bgp_name.setWordWrap(True)
        p.addWidget(self.bgp_name)
        self.bgp_sl = {}
        for key, label, default, tip in (("blur", "Photo blur", 0.5, "How soft the photo is: a hint of the scene "
                                                                      "up to pure colour and light"),
                                         ("dim", "Photo dim", 0.45, "How dark the photo is, so the card stands "
                                                                    "out against it")):
            row, sl, val, _n = self._ins_slider(label, tip, (0, 100))
            sl.setValue(int(round(float(self.cfg.value(f"3d_bgp_{key}", default)) * 100)))
            val.setText(f"{sl.value()}%")
            sl.valueChanged.connect(lambda v, k=key, lb=val: (lb.setText(f"{v}%"),
                                                              self.cfg.setValue(f"3d_bgp_{k}", v / 100),
                                                              self._bgp_timer.start()))
            p.addLayout(row)
            self.bgp_sl[key] = sl
        self._bgp_timer = QTimer(self, singleShot=True, interval=120)
        self._bgp_timer.timeout.connect(self._apply_bg_photo)

        # the panel: a title, tabs, the page (scrolling when it is taller than the window), a footer
        panel = QFrame(objectName="inspector")
        panel.setFixedWidth(self.INSPECTOR_W)
        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(22, 20, 22, 10)
        title = QLabel("Inspector", objectName="institle")
        head.addWidget(title)
        head.addStretch(1)
        col.addLayout(head)
        tabs = QHBoxLayout()
        tabs.setContentsMargins(16, 0, 16, 0)
        tabs.setSpacing(0)
        self.fx_stack = QStackedWidget()
        self.fx_tabs = {}
        self._page_keys = []
        for i, (key, label) in enumerate((("material", "Material"), ("layers", "Layers"), ("light", "Light"),
                                          ("camera", "Camera"), ("scene", "Scene"))):
            lay = pages[key]
            lay.setContentsMargins(22, 18, 22, 24)
            lay.setSpacing(12)
            lay.addStretch(1)
            pw = QWidget(objectName="inspage")
            pw.setLayout(lay)
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setWidget(pw)
            sc.setObjectName("insscroll")
            self.fx_stack.addWidget(sc)
            b = QPushButton(label, objectName="instab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i_=i: self._fx_page(i_))
            tabs.addWidget(b, 1)
            self.fx_tabs[i] = b
            self._page_keys.append(key)
            b.setVisible(key != "layers" or SHOW_LAYERS)
        col.addLayout(tabs)
        rule = QFrame(objectName="insrule")
        rule.setFixedHeight(1)
        col.addWidget(rule)
        col.addWidget(self.fx_stack, 1)
        rule2 = QFrame(objectName="insrule")
        rule2.setFixedHeight(1)
        col.addWidget(rule2)
        foot = QHBoxLayout()
        foot.setContentsMargins(22, 12, 22, 16)
        b_reset = self._chip("Reset look", "Back to the linear foil, studio light and no depth of field", False)
        b_reset.clicked.connect(self._fx_reset)
        foot.addStretch(1)
        foot.addWidget(b_reset)
        col.addLayout(foot)
        panel.setStyleSheet(inspector_style())
        pg = int(self.cfg.value("3d_inspector_page", 0) or 0)
        pg = pg if 0 <= pg < len(self._page_keys) else 0
        self._fx_page(0 if self._page_keys[pg] == "layers" and not SHOW_LAYERS else pg)
        self._sync_bg()
        self._fx_sync()
        return panel

    def _fx_page(self, i):
        self.fx_stack.setCurrentIndex(i)
        for k, b in self.fx_tabs.items():
            b.setChecked(k == i)
        self.cfg.setValue("3d_inspector_page", i)

    def _set_bg(self, hx):
        self.cfg.setValue("3d_bg", hx)
        self.view.set_background(hx)
        if str(self.cfg.value("3d_bgp_path", "") or ""):
            self.set_bg_photo("")                     # a colour picked means the colour, not the photo
        self._sync_bg()

    def _pick_bg(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(str(self.cfg.value("3d_bg", "#18181A"))), self, "Background colour")
        if c.isValid():
            self._set_bg(c.name().upper())

    def _sync_bg(self):
        cur = str(self.cfg.value("3d_bg", "#18181A")).upper()
        photo = bool(str(self.cfg.value("3d_bgp_path", "") or ""))
        for hx, b in getattr(self, "bg_btns", {}).items():
            b.setChecked(hx.upper() == cur and not photo)

    # ---------- backdrop photo
    def pick_bg_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "A photo for behind the card", os.path.dirname(str(self.cfg.value("3d_bgp_path", "")) or "")
            or os.path.expanduser("~/Pictures"), "Images (*.jpg *.jpeg *.png *.heic *.tif *.tiff *.webp *.bmp)")
        if path:
            self.set_bg_photo(path)

    def set_bg_photo(self, path):
        self.cfg.setValue("3d_bgp_path", path)
        self._apply_bg_photo(announce=bool(path))

    def _apply_bg_photo(self, announce=False, quiet=False):
        import card3d
        path = str(self.cfg.value("3d_bgp_path", "") or "")
        img = None
        if path:
            if not os.path.isfile(path):
                quiet or self.say("The backdrop photo was moved or deleted, so the plain colour is back.", "info")
                self.cfg.setValue("3d_bgp_path", "")
                path = ""
            else:
                img = card3d.prepare_backdrop_photo(path, float(self.cfg.value("3d_bgp_blur", 0.5)),
                                                    float(self.cfg.value("3d_bgp_dim", 0.45)))
                if img is None:
                    self.say("That photo could not be read.", "error")
                    self.cfg.setValue("3d_bgp_path", "")
                    path = ""
                elif announce:
                    import cv2
                    src = cv2.imread(path)
                    short = min(src.shape[:2]) if src is not None else 0
                    if short and short < 1080:
                        self.say(f"That photo is {short} px on its short side; it works blurred, but 1080 px "
                                 "or more keeps it smooth, and 2160 for 4K videos.", "info", secs=7)
        self.view.set_backdrop_photo(img)
        self.view.set_env(card3d.prepare_env(path) if img is not None else None)
        self._sync_bg()
        if getattr(self, "bgp_name", None) is not None:
            self.bgp_name.setText(os.path.basename(path) if path else "No photo, the colour above is used")
            self.b_bgp_clear.setEnabled(bool(path))
            for sl in self.bgp_sl.values():
                sl.setEnabled(bool(path))

    def _light_set(self, key, value):
        self.view.light[key] = value
        self.cfg.setValue("3d_light", json.dumps(self.view.light))
        self._fx_sync()
        self.view.update()

    def _fx_sync(self):
        ly = self.view.lay
        if getattr(self, "_lay_chk", None) is not None:
            self._lay_chk.blockSignals(True)
            self._lay_chk.setChecked(bool(ly.get("on")))
            self._lay_chk.blockSignals(False)
            for k, b in self.lay_foil.items():
                b.blockSignals(True)
                b.setChecked(float(ly[k]) > 0.5)
                b.blockSignals(False)
            for k, (sl, val, lo, hi) in self.lay_sl.items():
                sl.blockSignals(True)
                sl.setValue(int(round((float(ly[k]) - lo) / (hi - lo) * 200)))
                sl.blockSignals(False)
                val.setText(f"{float(ly[k]):.2f}")
        lt = self.view.light
        for k, b in getattr(self, "light_btns", {}).items():
            b.setChecked(k == lt["mode"])
        for key, attr in (("dof_on", "light_dof"), ("env_on", "light_env"), ("floor_on", "light_floor")):
            b = getattr(self, attr, None)
            if b is not None:
                b.blockSignals(True)
                b.setChecked(float(lt.get(key, 0)) > 0.5)
                b.blockSignals(False)
        for k, (sl, val, lo, hi) in getattr(self, "light_sl", {}).items():
            sl.blockSignals(True)
            sl.setValue(int(round((float(lt[k]) - lo) / (hi - lo) * 200)))
            sl.blockSignals(False)
            val.setText(f"{float(lt[k]):.2f}")
        fx = self.view.fx
        for k, b in self.fx_btns.items():
            b.setChecked(k == fx["pattern"])
        for k, (sl, val, lo, hi) in self.fx_sl.items():
            sl.blockSignals(True)
            sl.setValue(int(round((float(fx[k]) - lo) / (hi - lo) * 200)))
            sl.blockSignals(False)
            val.setText(f"{float(fx[k]):.0f}" if k == "scale" else f"{float(fx[k]):.2f}")

    def _fx_set(self, key, value):
        self.view.fx[key] = value
        if key == "pattern" and self.view.mode == "off":
            self.set_mode("whole")                 # picking a pattern means you want to see it
        self.cfg.setValue("3d_fx", json.dumps(self.view.fx))
        self._fx_sync()
        self.view.update()

    def _fx_reset(self):
        import card3d
        self.view.fx = dict(card3d.CardView.FX_DEFAULT)
        self.view.light = dict(card3d.CardView.LIGHT_DEFAULT)
        self.cfg.setValue("3d_fx", json.dumps(self.view.fx))
        self.cfg.setValue("3d_light", json.dumps(self.view.light))
        self._fx_sync()
        self.view.update()

    def _show_fx(self, on):
        self.fx_panel.setVisible(on)
        self.cfg.setValue("3d_inspector", "1" if on else "0")
        self.isl._place()

    def set_mode(self, mode):
        self.view.mode = mode
        for k, b in self.holo_btns.items():
            b.setChecked(k == mode)
        self.sl.setEnabled(mode != "off")
        self.cfg.setValue("3d_mode", mode)
        self.view.update()

    def _holo(self, v):
        if getattr(self, "_holo_val", None) is not None:
            self._holo_val.setText(f"{v}%")
        self.view.holo = v / 100
        self.cfg.setValue("3d_holo", v / 100)

    def _folder(self):
        f = os.path.join(self.m.out_dir, engine.safe_name(self.name)) if self.name else self.m.out_dir
        try:
            os.makedirs(f, exist_ok=True)
        except OSError:
            f = self.m.out_dir
        return f

    def _stem(self):
        return engine.safe_name(self.name) if self.name else "card"

    def _video_size(self):
        i = int(self.cfg.value("3d_size", 0))
        return self.SIZES[i if 0 <= i < len(self.SIZES) else 0][0]

    def _video_bg(self):
        b = str(self.cfg.value("3d_bg", "#18181A"))
        return tuple(int(b[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def export_obj(self):
        if not self.view.has_card():
            self.say("Pick a card first.", "info")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save the 3D card",
                                              os.path.join(self._folder(), f"{self._stem()}.obj"),
                                              "Wavefront OBJ (*.obj)")
        if not path:
            return
        if not path.lower().endswith(".obj"):
            path += ".obj"
        try:
            files = self.view.export_obj(path)
        except Exception as e:  # noqa: BLE001
            self.say(f"The model could not be saved: {e}", "error")
            return
        self.say(f"Saved {os.path.basename(path)} with its material and two textures, at real size in metres. "
                 "In Blender: File > Import > Wavefront (.obj).", "ok", secs=8)
        subprocess_reveal(files[0])

    def export_mp4(self):
        if self.view.seq is not None and self.view.group:
            return self.export_animation()
        if self.view.group:
            return self.export_group_video()
        d = QDialog(self)
        d.setWindowTitle("Export a 360° turn")
        f = QFormLayout(d)
        f.setContentsMargins(20, 18, 20, 16)
        f.setSpacing(10)
        motion = QComboBox()
        for k, label in self.MOTIONS:
            motion.addItem(label, k)
        motion.setCurrentIndex(max(0, motion.findData(str(self.cfg.value("3d_motion", "loop")))))
        import card3d
        ent = QComboBox()
        ent.addItem("None", "")
        for k, (label, _fn) in card3d.ENTRANCES.items():
            ent.addItem(label, k)
        ent.setCurrentIndex(max(0, ent.findData(str(self.cfg.value("3d_video_entrance", "")))))
        ent.setToolTip("How the card arrives at the start of the video (about 1.6 s); the motion plays after it")
        outro = QComboBox()
        outro.addItem("None", "")
        for k, (label, _fn) in card3d.OUTROS.items():
            outro.addItem(label, k)
        outro.setCurrentIndex(max(0, outro.findData(str(self.cfg.value("3d_video_outro", "")))))
        outro.setToolTip("How the card leaves at the end of the video (about 1.6 s). Leave it at None for a "
                         "video that loops without a cut")
        secs = QSpinBox()
        secs.setRange(2, 30)
        secs.setSuffix(" s")
        secs.setValue(int(self.cfg.value("3d_secs", 6)))
        size = QComboBox()
        for wh, label in self.SIZES:
            size.addItem(label, wh)
        size.setCurrentIndex(int(self.cfg.value("3d_size", 0)))
        quality = QComboBox()
        have = card3d.available_encoders()
        for k, qd in card3d.QUALITIES.items():
            if not have or qd["codec"] in have:
                quality.addItem(qd["label"], k)
        quality.setCurrentIndex(max(0, quality.findData(str(self.cfg.value("3d_quality", "standard")))))
        quality.setToolTip("Every option is tagged Rec. 709 so colours play back as rendered. HEVC and ProRes "
                           "render in 16-bit, so gradients and shadows do not band; ProRes is for editing apps, "
                           "4444 keeps the background transparent")
        fps = QComboBox()
        fps.addItem("30 fps", 30)
        fps.addItem("60 fps (smoother turns, twice the frames)", 60)
        fps.addItem("120 fps (four times the frames)", 120)
        fps.setCurrentIndex(max(0, fps.findData(int(self.cfg.value("3d_fps", 30)))))
        bg = QComboBox()
        cur_bg = str(self.cfg.value("3d_bg", "#18181A"))
        for hx, label in self.BGS + [("#0B0B0C", "Black"), ("#8C8A84", "Stone")]:
            bg.addItem(label, hx)
        if bg.findData(cur_bg) < 0:
            bg.addItem(f"Custom {cur_bg}", cur_bg)
        bgp = str(self.cfg.value("3d_bgp_path", "") or "")
        if bgp:                                      # the backdrop photo on screen is what the video shows
            bg.insertItem(0, f"Backdrop photo · {os.path.basename(bgp)[:28]}", "photo")
            bg.setCurrentIndex(0)
        else:
            bg.setCurrentIndex(max(0, bg.findData(cur_bg)))
        f.addRow("Entrance", ent)
        f.addRow("Outro", outro)
        f.addRow("Motion", motion)
        camera = QComboBox()
        for k, label in self.CAMERAS:
            camera.addItem(label, k)
        camera.setCurrentIndex(max(0, camera.findData(str(self.cfg.value("3d_camera", "")))))
        camera.setToolTip("A camera move over the motion: a slow or fast push in, a pull back, or a slow "
                          "breath in and out. The tours move the camera themselves")
        f.addRow("Camera", camera)
        mblur = QCheckBox("Motion blur, like a film camera's shutter (renders 8 times slower)")
        mblur.setChecked(str(self.cfg.value("3d_mblur", "0")) == "1")
        f.addRow("", mblur)
        fpull = QCheckBox("Pull focus onto the card at the start")
        fpull.setChecked(str(self.cfg.value("3d_focuspull", "0")) == "1")
        f.addRow("", fpull)

        def _motion_changed(_i=0):
            k = motion.currentData()
            camera.setEnabled(k not in self.TOUR_SECS)
            if k in self.TOUR_SECS and secs.value() < self.TOUR_SECS[k]:
                secs.setValue(self.TOUR_SECS[k])
        motion.currentIndexChanged.connect(_motion_changed)
        _motion_changed()
        f.addRow("Length", secs)
        f.addRow("Size", size)
        f.addRow("Quality", quality)
        f.addRow("Frame rate", fps)
        f.addRow("Background", bg)
        bgfx = QComboBox()
        bgfx.addItem("Still", "")
        for k, (label, _src) in card3d.FX_BG.items():
            bgfx.addItem(f"{label} (moving, tinted by the background)", k)
        bgfx.setCurrentIndex(max(0, bgfx.findData(str(self.cfg.value("3d_bg_fx", "") or ""))))
        bgfx.setToolTip("An animated backdrop behind the card, drawn on the graphics card for every frame")
        bgfx.currentIndexChanged.connect(lambda _i: self.view.set_bg_shader(bgfx.currentData()))
        f.addRow("Backdrop", bgfx)
        reveal = QComboBox()
        reveal.addItem("None", "")
        for k, (label, secs_) in card3d.FX_REVEAL.items():
            reveal.addItem(f"{label} ({secs_:.1f}s)", k)
        reveal.setCurrentIndex(max(0, reveal.findData(str(self.cfg.value("3d_reveal", "") or ""))))
        reveal.setToolTip("Drawn over the first moments of the video: rings that open onto the card, a band "
                          "of foil colour crossing the frame, or crosshairs and brackets that lock on")
        f.addRow("Reveal", reveal)
        if self.view.bg_photo is not None:
            bg.setEnabled(False)
            bg.setToolTip("Your backdrop photo is used instead; clear it under Look…, Lighting for a colour")
            f.addRow(QLabel("Using your backdrop photo (not with ProRes 4444, which stays transparent).",
                            objectName="small"))
        note = QLabel("Your foil and lighting are used. Listing videos are always H.264 (eBay's limit is 150 MB).",
                      objectName="small")
        note.setWordWrap(True)
        f.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Export…")
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        f.addRow(bb)
        if d.exec() != QDialog.Accepted:
            return
        self.cfg.setValue("3d_motion", motion.currentData())
        self.cfg.setValue("3d_camera", camera.currentData())
        self.cfg.setValue("3d_mblur", "1" if mblur.isChecked() else "0")
        self.cfg.setValue("3d_focuspull", "1" if fpull.isChecked() else "0")
        self.cfg.setValue("3d_bg_fx", bgfx.currentData())
        self.cfg.setValue("3d_reveal", reveal.currentData())
        self.cfg.setValue("3d_video_entrance", ent.currentData())
        self.cfg.setValue("3d_video_outro", outro.currentData())
        self.cfg.setValue("3d_secs", secs.value())
        self.cfg.setValue("3d_size", size.currentIndex())
        if bg.currentData() != "photo":
            self._set_bg(bg.currentData())
        self.cfg.setValue("3d_quality", quality.currentData())
        self.cfg.setValue("3d_fps", fps.currentData())
        ext = card3d.QUALITIES[quality.currentData()]["ext"]
        kind = "QuickTime movie (*.mov)" if ext == ".mov" else "MP4 video (*.mp4)"
        path, _ = QFileDialog.getSaveFileName(self, "Save the video",
                                              os.path.join(self._folder(), f"{self._stem()}_360{ext}"), kind)
        if not path:
            return
        if not path.lower().endswith(ext):
            path = os.path.splitext(path)[0] + ext
        w, h = size.currentData()
        prog = QProgressDialog("Rendering the turn…", "Cancel", 0, 100, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        self.view.stop()

        def step(i, n):
            prog.setMaximum(n)
            prog.setValue(i)
            prog.setLabelText(f"Rendering frame {i} of {n}")
            QApplication.processEvents()
            return not prog.wasCanceled()

        self.view.reveal_fx = {"kind": reveal.currentData()} if reveal.currentData() else None
        try:
            ok = self.view.export_turntable(path, w, h, float(secs.value()), fps.currentData(), motion.currentData(),
                                            self._video_bg(), step, entrance=ent.currentData(),
                                            outro=outro.currentData(), quality=quality.currentData(),
                                            camera=camera.currentData(), motion_blur=mblur.isChecked(),
                                            focus_pull=fpull.isChecked())
        except Exception as e:  # noqa: BLE001
            prog.close()
            self.say(f"The video could not be made: {e}", "error")
            return
        finally:
            self.view.reveal_fx = None
        prog.close()
        if not ok:
            try:
                os.remove(path)
            except OSError:
                pass
            self.say("Export cancelled", "info")
            return
        self.say(f"Saved {os.path.basename(path)}", "ok",
                             action=("Show", lambda p_=path: subprocess_reveal(p_)))

    def export_reel(self):
        """One click to a vertical video ready to post: 1080 × 1920, about 17 seconds, the card arriving,
        a sway and a full turn, then close on each corner, focus pulled at the start, your look and holder."""
        import card3d
        if self.view.group:
            return self.export_group_video(1080, 1920, "the reel")
        if not self.view.has_card():
            self.say("Pick a card first.", "info")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save the reel",
                                              os.path.join(self._folder(), f"{self._stem()}_reel.mp4"),
                                              "MP4 video (*.mp4)")
        if not path:
            return
        if not path.lower().endswith(".mp4"):
            path += ".mp4"
        ent = str(self.cfg.value("3d_video_entrance", "")) or "pop"
        ent = ent if ent in card3d.ENTRANCES else "pop"
        mblur = str(self.cfg.value("3d_mblur", "0")) == "1"
        prog = QProgressDialog("Rendering the reel…", "Cancel", 0, 100, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        self.view.stop()

        def step(i, n):
            prog.setMaximum(n)
            prog.setValue(i)
            prog.setLabelText(f"Rendering frame {i} of {n}")
            QApplication.processEvents()
            return not prog.wasCanceled()
        rv = str(self.cfg.value("3d_reveal", "") or "")
        self.view.reveal_fx = {"kind": rv} if rv in card3d.FX_REVEAL else None
        try:
            ok = self.view.export_turntable(path, 1080, 1920, 15.0 + card3d.ENTRANCE_SECONDS, 30, "reel",
                                            self._video_bg(), step, entrance=ent, quality="standard",
                                            motion_blur=mblur, focus_pull=True)
        except Exception as e:  # noqa: BLE001
            prog.close()
            self.say(f"The reel could not be made: {e}", "error")
            return
        finally:
            self.view.reveal_fx = None
        prog.close()
        if not ok:
            try:
                os.remove(path)
            except OSError:
                pass
            self.say("Export cancelled", "info")
            return
        self.say(f"Saved {os.path.basename(path)}, 1080 × 1920, ready to post", "ok",
                 action=("Show", lambda p_=path: subprocess_reveal(p_)))

    # ---------- holders: fitted sleeve, top loader, graded slab
    def _slab_texts(self):
        try:
            return json.loads(str(self.cfg.value("slab_text", "{}")) or "{}")
        except ValueError:
            return {}

    def _card_title(self):
        n = (self.name or "").replace("_", " ").replace("-", " ").strip()
        return " ".join(w if any(c.isdigit() for c in w) else w.capitalize() for w in n.split())

    def _slab_defaults(self, name=None):
        """The label from what CardCrop knows of the card: its identification and the condition you set."""
        import listing
        name = self.name if name is None else name
        keep, self.name = self.name, name
        title = self._card_title()
        self.name = keep
        out = dict(top="", name=title, number="", condition="")
        same = [x for x in getattr(self.m, "jobs", []) if x.card_name.strip() == (name or "")]
        info = next((x.card_info for x in same if x.card_info), None)
        if info:
            try:
                ci = identify.CardInfo(**info)
                game = {"pokemon": "Pokemon", "yugioh": "Yu-Gi-Oh!", "onepiece": "One Piece"}.get(ci.game, "")
                if identify.LANG_WORD.get(ci.language):
                    game = f"{game} {identify.LANG_WORD[ci.language]}".strip()
                out["top"] = " ".join(x for x in (ci.year, game, ci.set_name_en or ci.set_name) if x)
                out["name"] = ci.name_en or ci.name or out["name"]
                num = f"#{ci.number}" if ci.number else ""
                out["number"] = " ".join(x for x in (num, ci.variant, ci.edition,
                                                       ci.rarity if "holo" in ci.rarity.lower() else "") if x)
            except TypeError:
                pass
        code = next((x.condition for x in same if x.condition), "")
        if code in listing.CONDITIONS:
            out["condition"] = listing.CONDITIONS[code][0]
        return out

    def _apply_holder(self):
        name = str(self.cfg.value("3d_holder", "") or "")
        if name == "toploader":                       # the loader on its own is gone: sleeved and loaded
            name = "sleeve_tl"
            self.cfg.setValue("3d_holder", name)
        mine = {k: v for k, v in self._slab_texts().get(self.name or "", {}).items() if v}
        dflt = self._slab_defaults()
        show_cond = str(self.cfg.value("3d_slab_cond", "1")) == "1"
        shown = dict(dflt, **mine)
        if not show_cond:
            shown["condition"] = ""
        self.view.set_holder(name, shown)
        for k, b in getattr(self, "holder_btns", {}).items():
            b.setChecked(k == name)
        if getattr(self, "slab_box", None) is not None:
            self.slab_box.setVisible(name == "slab")
            for k, e in self.slab_edits.items():
                e.blockSignals(True)
                e.setText(mine.get(k, ""))
                e.setPlaceholderText(dflt.get(k, "") or {"top": "Year, game and set", "name": "Card name",
                                                        "number": "Number and variety",
                                                        "condition": "Near Mint"}[k])
                e.blockSignals(False)
            self.slab_cond.blockSignals(True)
            self.slab_cond.setChecked(show_cond)
            self.slab_cond.blockSignals(False)

    def _slab_shown(self, name):
        mine = {k: v for k, v in self._slab_texts().get(name or "", {}).items() if v}
        shown = dict(self._slab_defaults(name), **mine)
        if str(self.cfg.value("3d_slab_cond", "1")) != "1":
            shown["condition"] = ""
        return shown

    def _holder_from_view(self, name):
        """A sleeving move finished: the card is now in that holder."""
        self.cfg.setValue("3d_holder", name)
        for k, b in getattr(self, "holder_btns", {}).items():
            b.setChecked(k == name)
        if getattr(self, "slab_box", None) is not None:
            self.slab_box.setVisible(name == "slab")

    def _set_holder(self, name):
        cur = self.view.holder or ""
        if self.view._cam_anim is not None and self.view._cam_anim.get("end_holder") is not None:
            cur = self.view._cam_anim["end_holder"]           # mid-move: start from where it was going
        self.cfg.setValue("3d_holder", name)
        if name != cur and motion.enabled() and not self.view.group:
            self.view.holder = cur
            if name == "slab":                                # its label is ready before the front half arrives
                shown = self._slab_shown(self.name)
                if shown != self.view.slab_text:
                    self.view.slab_text = dict(shown)
                    self.view._label_dirty = True
            if self.view.play_holder(name):                   # sleeve it, load it, slab it, or take it out
                for k, b in self.holder_btns.items():
                    b.setChecked(k == name)
                if getattr(self, "slab_box", None) is not None:
                    self.slab_box.setVisible(name == "slab")
                return
        self._apply_holder()
        if self.view.group:
            self._show_group(self.group_names, self.view.group_preset)      # new labels for every card

    # ---------- several cards together
    def pick_group(self):
        names, older = self._choices()
        try:
            chosen = json.loads(str(self.cfg.value("3d_group", "[]")) or "[]")
        except ValueError:
            chosen = []
        d = GroupDialog(self, names, older, self.group_names or chosen,
                        self.view.group_preset if self.view.group else str(self.cfg.value("3d_group_preset", "stack")))
        if d.exec() != QDialog.Accepted:
            return
        self.cfg.setValue("3d_group", json.dumps(d.order))
        self.cfg.setValue("3d_group_preset", d.preset.currentData())
        self._show_group(d.order, d.preset.currentData())

    def _show_group(self, names, preset):
        cards = []
        for n in names:
            front, back = self.m._card_sides(n)
            if front is None and back is not None:
                front, back = back, None
            if front is None:
                continue
            cards.append(dict(name=n, front=front, back=back, label=self._slab_shown(n)))
        if len(cards) < 2:
            self.say("At least two of those cards need a straightened photo to show together.", "info")
            return
        if self.view.rec is not None:
            self.toggle_rec()
        self.view.stop()
        self.view.set_group(cards, preset)
        self.view.yaw = self.view.pitch = 0.0
        self._group_cam_reset()
        self.group_names = [c["name"] for c in cards]
        self.empty.hide()
        self.grp_lbl.setText(f"{len(cards)} cards")
        self.grp_combo.setCurrentIndex(max(0, self.grp_combo.findData(preset)))
        self.grp_bar.show()
        self.isl._place()

    def _group_cam_set(self, key, v, src="slider"):
        """A camera number changed, by slider or typed: keep the two in step and use it."""
        other = self.grp_box[key] if src == "slider" else self.grp_sl[key]
        other.blockSignals(True)
        other.setValue(int(v))
        other.blockSignals(False)
        self.view.group_cam[key] = v / 100.0 if key == "zoom" else float(v)
        self.view.update()

    def _group_cam_reset(self):
        for k in self.grp_sl:
            v = 100 if k == "zoom" else 0
            for w_ in (self.grp_sl[k], self.grp_box[k]):
                w_.blockSignals(True)
                w_.setValue(v)
                w_.blockSignals(False)
        self.view.group_cam = dict(yaw=0.0, pitch=0.0, zoom=1.0)
        self.view.update()

    def _group_preset(self, preset):
        self.view.set_group_preset(preset)
        self.view.yaw = self.view.pitch = 0.0
        self._group_cam_reset()
        self.cfg.setValue("3d_group_preset", preset)

    def exit_group(self, quiet=False):
        if getattr(self, "anim_ed", None) is not None and self.anim_ed.isVisible():
            self.close_animate(reload=False)
        if not self.view.group:
            return
        self.view.set_group(None)
        self.group_names = []
        self.grp_bar.hide()
        self.view.yaw = self.view.pitch = 0.0
        if not quiet and self.name:
            self.load(self.name)

    # ---------- your own animation: timeline and nodes
    def _anim_cards(self, names):
        out = []
        for n in names:
            front, back = self.m._card_sides(n)
            if front is None and back is not None:
                front, back = back, None
            if front is not None:
                out.append(dict(name=n, front=front, back=back, label=self._slab_shown(n)))
        return out

    def open_animate(self):
        import anim
        seq = anim.Sequence.from_json(str(self.cfg.value("3d_sequence", "") or ""))
        names = [c["name"] for c in seq.cards]
        # Animate starts from the card on screen: the saved animation only if that card is in it
        if not names or len(self._anim_cards(names)) != len(names) or (self.name and self.name not in names):
            chosen = [self.name] if self.name else []
            pick = self._pick_anim_cards(chosen)
            if pick is None:
                return
            seq = anim.starter(pick)
        self._start_animate(seq)

    def _pick_anim_cards(self, chosen):
        names, older = self._choices()
        d = GroupDialog(self, names, older, chosen, "stack", least=1, title="Cards to animate",
                        ok_text="Animate these", show_preset=False)
        if d.exec() != QDialog.Accepted:
            return None
        return list(d.order)

    def _start_animate(self, seq):
        cards = self._anim_cards([c["name"] for c in seq.cards])
        if not cards:
            self.say("Those cards need a straightened photo to animate.", "info")
            return
        if self.view.rec is not None:
            self.toggle_rec()
        self.view.stop()
        self.grp_bar.hide()
        self.view.seq = seq
        self.view.set_group(cards)
        self.view.yaw = self.view.pitch = 0.0
        self._group_cam_reset()
        self.group_names = [c["name"] for c in cards]
        self.empty.hide()
        self.anim_ed.set_sequence(seq)
        self.anim_ed.show()
        h = self.split.height()
        self.split.setSizes([int(h * 0.58), int(h * 0.42)])
        self.view.seek_seq(0.0)
        self.cfg.setValue("3d_sequence", seq.to_json())

    def animate_cards(self):
        """Change the cards: new ones get a track and a node of their own, ones taken out go with their links."""
        seq = self.anim_ed.seq
        pick = self._pick_anim_cards([c["name"] for c in seq.cards])
        if pick is None:
            return
        self.anim_ed.begin_edit()
        for i in reversed(range(len(seq.cards))):
            if seq.cards[i]["name"] not in pick:
                seq.remove_card(i)
        have = [c["name"] for c in seq.cards]
        for n in pick:
            if n not in have:
                seq.add_card(n)
        self.anim_ed.edited()                               # tracks keep the order they were added in

    def _anim_changed(self):
        seq = self.anim_ed.seq
        self.cfg.setValue("3d_sequence", seq.to_json())
        names = [c["name"] for c in seq.cards]
        if names != self.group_names:                        # cards added or taken out (or undone)
            cards = self._anim_cards(names)
            self.view.seq = seq
            if cards:
                self.view.set_group(cards)
            self.group_names = names
        self.view.update()

    def close_animate(self, reload=True):
        if self.view.seq_playing:
            self.view.play_seq(False)
        self.anim_ed.hide()
        self.view.seq = None
        self.view.set_group(None)
        self.group_names = []
        if reload and self.name:
            self.load(self.name)

    def export_blender(self):
        """The animation (or the cards on screen) as a glTF file for Blender: real-size cards with their
        faces, holders, the camera and every keyframe."""
        import gltf_export
        names = self.group_names if self.view.group else ["card"]
        stem = "_".join(engine.safe_name(n)[:16] for n in names[:3]) or "cards"
        path, _ = QFileDialog.getSaveFileName(self, "Save for Blender",
                                              os.path.join(self.m.out_dir, f"{stem}_scene.glb"),
                                              "glTF binary (*.glb)")
        if not path:
            return
        if not path.lower().endswith(".glb"):
            path += ".glb"
        if self.view.seq_playing:
            self.anim_ed.toggle_play()
        w, h = self._video_size()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            gltf_export.export(self.view, path, w, h, int(self.cfg.value("3d_fps", 30)),
                               progress=lambda i, n: QApplication.processEvents())
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            self.say(f"The Blender file could not be made: {e}", "error")
            return
        QApplication.restoreOverrideCursor()
        self.say(f"Saved {os.path.basename(path)}: in Blender, File > Import > glTF 2.0", "ok",
                 action=("Show", lambda p_=path: subprocess_reveal(p_)))

    def export_animation(self):
        if self.view.seq is None or not self.view.group:
            return
        stem = "_".join(engine.safe_name(n)[:16] for n in self.group_names[:3]) or "cards"
        path, _ = QFileDialog.getSaveFileName(self, "Save the animation",
                                              os.path.join(self.m.out_dir, f"{stem}_animation.mp4"),
                                              "MP4 video (*.mp4)")
        if not path:
            return
        if not path.lower().endswith(".mp4"):
            path += ".mp4"
        w, h = self._video_size()
        q = str(self.cfg.value("3d_quality", "standard"))
        q = q if q in ("standard", "high", "hevc10") else "standard"
        if self.view.seq_playing:
            self.anim_ed.toggle_play()
        prog = QProgressDialog("Rendering the animation…", "Cancel", 0, 100, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)

        def step(i, n):
            prog.setMaximum(n)
            prog.setValue(i)
            prog.setLabelText(f"Rendering frame {i} of {n}")
            QApplication.processEvents()
            return not prog.wasCanceled()
        try:
            ok = self.view.export_sequence(path, w, h, int(self.cfg.value("3d_fps", 30)), self._video_bg(), step,
                                           quality=q, motion_blur=str(self.cfg.value("3d_mblur", "0")) == "1")
        except Exception as e:  # noqa: BLE001
            prog.close()
            self.say(f"The video could not be made: {e}", "error")
            return
        prog.close()
        if not ok:
            try:
                os.remove(path)
            except OSError:
                pass
            self.say("Export cancelled", "info")
            return
        self.say(f"Saved {os.path.basename(path)}", "ok", action=("Show", lambda p_=path: subprocess_reveal(p_)))

    def export_group_video(self, w=None, h=None, label="several cards"):
        """The group's animation as a video, in whole loops so it repeats without a seam."""
        if not self.view.group:
            self.say("Show several cards first: Several cards… at the top left.", "info")
            return
        stem = "_".join(engine.safe_name(n)[:16] for n in self.group_names[:3]) or "cards"
        path, _ = QFileDialog.getSaveFileName(self, "Save the video",
                                              os.path.join(self.m.out_dir, f"{stem}_{self.view.group_preset}.mp4"),
                                              "MP4 video (*.mp4)")
        if not path:
            return
        if not path.lower().endswith(".mp4"):
            path += ".mp4"
        if w is None:
            w, h = self._video_size()
        q = str(self.cfg.value("3d_quality", "standard"))
        q = q if q in ("standard", "high", "hevc10") else "standard"
        loop = self.view.group_seconds()
        want = float(int(self.cfg.value("3d_secs", 6)))
        loops = max(1, round(want / loop))
        prog = QProgressDialog(f"Rendering {label}…", "Cancel", 0, 100, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)

        def step(i, n):
            prog.setMaximum(n)
            prog.setValue(i)
            prog.setLabelText(f"Rendering frame {i} of {n}")
            QApplication.processEvents()
            return not prog.wasCanceled()
        try:
            ok = self.view.export_group(path, w, h, None, int(self.cfg.value("3d_fps", 30)), self._video_bg(), step,
                                        quality=q, motion_blur=str(self.cfg.value("3d_mblur", "0")) == "1",
                                        loops=loops)
        except Exception as e:  # noqa: BLE001
            prog.close()
            self.say(f"The video could not be made: {e}", "error")
            return
        prog.close()
        if not ok:
            try:
                os.remove(path)
            except OSError:
                pass
            self.say("Export cancelled", "info")
            return
        self.say(f"Saved {os.path.basename(path)}", "ok", action=("Show", lambda p_=path: subprocess_reveal(p_)))

    def _slab_edited(self):
        allt = self._slab_texts()
        allt[self.name or ""] = {k: e.text().strip() for k, e in self.slab_edits.items()}
        self.cfg.setValue("slab_text", json.dumps(allt))
        self._apply_holder()

    def toggle_rec(self):
        if self.view.rec is None:
            w, h = self._video_size()
            path = os.path.join(self._folder(), f"{self._stem()}_3d_{time.strftime('%H%M%S')}.mp4")
            try:
                self.view.start_recording(path, w, h, 30, self._video_bg())
            except Exception as e:  # noqa: BLE001
                self.say(f"Recording could not start: {e}", "error")
                return
            self.b_rec.setIcon(make_icon("stop", 40, "#E5484D"))
            self.b_rec.setText(" Stop")
            self.say(f"Recording at {w} × {h}. Drag, use the moves, then Stop.", "warn", secs=4)
        else:
            path, secs = self.view.stop_recording()
            self.b_rec.setIcon(make_icon("rec", 40, HUD_TEXT))
            self.b_rec.setText(" Record")
            if path:
                self.say(f"Saved {os.path.basename(path)}, {secs:.1f} s", "ok",
                                     action=("Show", lambda p_=path: subprocess_reveal(p_)))


# names from the other parts, bound once every part has loaded
from ui_base import HUD_TEXT, LIME, icon_button, make_icon, subprocess_reveal  # noqa: E402
from ui_dialogs import ArrangeDialog, GroupDialog  # noqa: E402
from ui_tasks import CallTask  # noqa: E402
from ui_widgets import Island, Notice, hud, inspector_style  # noqa: E402
