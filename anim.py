"""Card animations built from blocks, edited on a timeline or as a node graph: both are views of the
same Sequence, so a change in one shows in the other.

A sequence has cards (one track each) and blocks. A block does one thing over its own stretch of time:
an action on the cards it reaches (flip, spin, sway, hop, move, an entrance or an outro), a layout that
gathers them (stack, row, fan, circle), an animation of the whole set (flip through the stack, lift off,
a wave of turns, round the circle, spread and gather), or a camera move (push in, pull back, orbit,
tilt, pull focus).

Links make the graph. A block's inputs are cards and other blocks: the cards it acts on are every card
that reaches it, and it starts when the last of its input blocks ends, plus its own delay. So card ->
Flip -> Stack flips the card and then stacks it. On the timeline, sliding a block changes its delay.

Every pose is the card's layout (where the latest layout block put it) plus what its actions add, so
blocks only ever add to where a card is: nothing jumps when one ends and the next begins. The camera
frames the layout, not the actions, so it reframes smoothly when the cards are gathered or spread, and
does not chase a card that has been thrown out of shot.
"""

from __future__ import annotations

import json
import math

import card3d as C

ease = C.ease_in_out

# kind: (label, family, default seconds, params {name: (default, lo, hi, label)})
KINDS = {
    # actions on each card they reach
    "flip": ("Flip", "action", 1.0, {"turns": (0.5, -3.0, 3.0, "Turns")}),
    "flip_v": ("Flip over the top", "action", 1.0, {"turns": (0.5, -3.0, 3.0, "Turns")}),
    "spin": ("Spin", "action", 1.6, {"turns": (1.0, -5.0, 5.0, "Turns")}),
    "sway": ("Sway", "action", 2.0, {"angle": (24.0, 0.0, 60.0, "Angle")}),
    "hop": ("Hop", "action", 0.7, {"height": (0.35, 0.0, 2.0, "Height")}),
    "move": ("Move", "action", 1.0, {"x": (0.0, -6.0, 6.0, "Across"), "y": (0.0, -6.0, 6.0, "Up"),
                                     "z": (0.0, -6.0, 6.0, "Toward you")}),
    "tilt": ("Tilt", "action", 0.8, {"yaw": (20.0, -180.0, 180.0, "Turn"), "pitch": (0.0, -90.0, 90.0, "Tilt"),
                                     "roll": (0.0, -180.0, 180.0, "Roll")}),
    "enter": ("Entrance", "action", C.ENTRANCE_SECONDS, {"style": ("drop", None, None, "Style")}),
    "exit": ("Outro", "action", C.ENTRANCE_SECONDS, {"style": ("drop", None, None, "Style")}),
    "stagger": ("Each in turn", "action", 2.0, {"of": ("flip", None, None, "Move"),
                                               "overlap": (0.5, 0.0, 0.95, "Overlap")}),
    # holders: the card goes into a sleeve or a top loader, or comes out
    "sleeve_in": ("Sleeve it", "holder", 3.0, {}),
    "sleeve_load": ("Sleeve it, then top load", "holder", 6.0, {}),
    "unload": ("Out of the top loader and sleeve", "holder", 6.0, {}),
    "unsleeve": ("Out of the sleeve", "holder", 3.0, {}),
    # layouts: gather the cards they reach
    "stack": ("Stack", "layout", 1.0, {}),
    "row": ("Row", "layout", 1.0, {"gap": (1.0, 0.6, 2.5, "Spacing")}),
    "fan": ("Fan", "layout", 1.0, {"spread": (12.0, 2.0, 30.0, "Spread")}),
    "circle": ("Circle", "layout", 1.2, {}),
    # animations of the set, each a loop that ends where it began
    "flip_through": ("Flip through the stack", "group", 5.0, {}),
    "lift_off": ("Lift off the stack", "group", 6.0, {}),
    "wave": ("Wave of turns", "group", 3.0, {}),
    "carousel": ("Round the circle", "group", 8.0, {}),
    "spread": ("Spread and gather", "group", 5.0, {}),
    # the camera
    "push": ("Push in", "camera", 2.0, {"amount": (0.5, -0.8, 3.0, "Amount")}),
    "pull": ("Pull back", "camera", 2.0, {"amount": (0.4, 0.0, 0.9, "Amount")}),
    "orbit": ("Orbit", "camera", 3.0, {"angle": (30.0, -180.0, 180.0, "Turn")}),
    "cam_tilt": ("Camera tilt", "camera", 2.0, {"angle": (15.0, -60.0, 60.0, "Tilt")}),
    "focus": ("Pull focus", "camera", 1.6, {}),
}
FAMILIES = [("action", "Card moves"), ("holder", "Sleeves"), ("layout", "Arrange"), ("group", "Animate the set"),
            ("camera", "Camera")]
COLOURS = {"action": "#D6F24B", "holder": "#6FE3C1", "layout": "#7CC4FF", "group": "#C9A2FF", "camera": "#FFB36B",
           "card": "#E6E6E8"}
SLEEVE_FNS = {"sleeve_in": C.mv_sleeve, "sleeve_load": C.mv_sleeve_load, "unload": C.mv_unload,
              "unsleeve": C.mv_unsleeve}
GROUP_FNS = {"flip_through": C.grp_stack, "lift_off": C.grp_lift, "wave": C.grp_wave, "carousel": C.grp_carousel,
             "spread": C.grp_spread}
STAGGER_OF = ["flip", "flip_v", "spin", "hop", "sway"]


def _blank_pose():
    return dict(x=0.0, y=0.0, z=0.0, yaw=0.0, pitch=0.0, roll=0.0, scale=1.0)


class Sequence:
    """Cards, blocks and links: the whole animation, as plain data that saves to JSON."""

    def __init__(self):
        self.cards = []          # [{"name": card name}]: one track each, card:<index> in links
        self.blocks = []         # [{"id", "kind", "inputs": [...], "delay", "dur", "params", "x", "y"}]
        self.card_pos = {}       # node positions of the card nodes: card:<i> -> (x, y)
        self.loop = True
        self._n = 0

    # ---------- saving
    def to_json(self):
        return json.dumps(dict(cards=self.cards, blocks=self.blocks, card_pos=self.card_pos, loop=self.loop,
                               n=self._n))

    @classmethod
    def from_json(cls, text):
        s = cls()
        try:
            d = json.loads(text or "{}")
        except ValueError:
            return s
        s.cards = [c for c in d.get("cards", []) if isinstance(c, dict) and c.get("name")]
        s.blocks = [b for b in d.get("blocks", []) if b.get("kind") in KINDS]
        s.card_pos = {k: tuple(v) for k, v in d.get("card_pos", {}).items()}
        s.loop = bool(d.get("loop", True))
        s._n = int(d.get("n", len(s.blocks)))
        s._tidy()
        return s

    def copy(self):
        return Sequence.from_json(self.to_json())

    # ---------- editing
    def add_card(self, name):
        self.cards.append(dict(name=name))
        i = len(self.cards) - 1
        self.card_pos.setdefault(f"card:{i}", (40.0, 40.0 + 90.0 * i))
        return f"card:{i}"

    def remove_card(self, i):
        """Take a card out; links to it go, and later cards' links move down one."""
        del self.cards[i]
        ren = {}
        for j in range(i + 1, len(self.cards) + 1):
            ren[f"card:{j}"] = f"card:{j - 1}"
        for b in self.blocks:
            b["inputs"] = [ren.get(x, x) for x in b["inputs"] if x != f"card:{i}"]
        self.card_pos = {ren.get(k, k): v for k, v in self.card_pos.items() if k != f"card:{i}"}

    def free_spot(self, x, y, w=200.0, h=64.0):
        """The nearest place at or below (x, y) where a new node does not cover another."""
        taken = [(b["x"], b["y"]) for b in self.blocks] + list(self.card_pos.values())
        while any(abs(tx - x) < w + 20 and abs(ty - y) < h + 16 for tx, ty in taken):
            y += h + 26
        return x, y

    def add_block(self, kind, inputs=(), delay=0.0, pos=None):
        self._n += 1
        lab, fam, dur, params = KINDS[kind]
        b = dict(id=f"b{self._n}", kind=kind, inputs=list(inputs), delay=float(delay), dur=float(dur),
                 params={k: v[0] for k, v in params.items()}, x=0.0, y=0.0)
        if pos is None:
            pos = (260.0 + 40.0 * (len(self.blocks) % 6), 40.0 + 60.0 * (len(self.blocks) % 8))
        b["x"], b["y"] = self.free_spot(*pos)
        self.blocks.append(b)
        return b

    def block(self, bid):
        return next((b for b in self.blocks if b["id"] == bid), None)

    def remove_block(self, bid):
        """Take a block out; whatever followed it now follows what it followed, so chains stay whole."""
        b = self.block(bid)
        if b is None:
            return
        for o in self.blocks:
            if bid in o["inputs"]:
                o["inputs"] = [x for x in o["inputs"] if x != bid] + [x for x in b["inputs"] if x not in o["inputs"]]
        self.blocks = [o for o in self.blocks if o["id"] != bid]

    def can_link(self, src, dst):
        """src -> dst unless it would make a loop (dst already leads to src) or it is already there."""
        d = self.block(dst)
        if d is None or src == dst or src in d["inputs"]:
            return False
        if src.startswith("card:"):
            return True
        return dst not in self._upstream(src) | {src}

    def link(self, src, dst):
        if self.can_link(src, dst):
            self.block(dst)["inputs"].append(src)
            return True
        return False

    def unlink(self, src, dst):
        d = self.block(dst)
        if d is not None and src in d["inputs"]:
            d["inputs"].remove(src)

    def _upstream(self, bid, seen=None):
        seen = set() if seen is None else seen
        b = self.block(bid)
        for x in (b["inputs"] if b else []):
            if x not in seen and not x.startswith("card:"):
                seen.add(x)
                self._upstream(x, seen)
        return seen

    def _tidy(self):
        ids = {b["id"] for b in self.blocks}
        n = len(self.cards)
        for b in self.blocks:
            b["inputs"] = [x for x in b["inputs"] if x in ids or (x.startswith("card:") and int(x[5:]) < n)]
            lab, fam, dur, params = KINDS[b["kind"]]
            for k, v in params.items():
                b["params"].setdefault(k, v[0])

    # ---------- timing
    def targets(self, bid, memo=None):
        """The cards a block acts on: every card that reaches it, in card order."""
        memo = {} if memo is None else memo
        if bid in memo:
            return memo[bid]
        memo[bid] = []
        b = self.block(bid)
        out = set()
        for x in (b["inputs"] if b else []):
            if x.startswith("card:"):
                out.add(int(x[5:]))
            else:
                out |= set(self.targets(x, memo))
        if b is not None and b.get("only") is not None:       # separated: just these cards
            out &= set(b["only"])
        memo[bid] = sorted(out)
        return memo[bid]

    def set_of(self, bid, memo=None):
        """The cards an arrangement or a set animation lays out together: the ones it reached before it
        was separated, so a separated card still knows its place in the stack."""
        b = self.block(bid)
        tg = self.targets(bid, memo)
        grp = [i for i in (b.get("group") or []) if i < len(self.cards)]
        return grp if grp and all(i in grp for i in tg) else tg

    # ---------- separating, copying
    def separate(self, bid, card=None):
        """Give one card (or every card) its own copy of a block, so each can be slid, stretched or set on
        its own. Arrangements keep each card's place in the set. Returns the new blocks' ids."""
        b = self.block(bid)
        if b is None:
            return []
        tg = self.targets(bid)
        if len(tg) < 2:
            return []
        group = self.set_of(bid)
        cards = [card] if card is not None else tg[1:]
        new = []
        for k, i in enumerate(cards):
            if i not in tg:
                continue
            nb = self.clone(bid, dx=0.0, dy=(k + 1) * 80.0)
            nb["only"] = [i]
            nb["group"] = list(group)
            new.append(nb["id"])
        rest = [i for i in tg if i not in cards]
        b["only"], b["group"] = rest, list(group)
        for o in self.blocks:                                  # what followed it follows the copies too
            if bid in o["inputs"]:
                o["inputs"] += [x for x in new if x not in o["inputs"]]
        return new

    def clone(self, bid, dx=30.0, dy=30.0, inputs=None):
        b = self.block(bid)
        self._n += 1
        nb = json.loads(json.dumps(b))
        nb["id"] = f"b{self._n}"
        if inputs is not None:
            nb["inputs"] = list(inputs)
        nb["x"], nb["y"] = self.free_spot(b["x"] + dx, b["y"] + dy)
        self.blocks.append(nb)
        return nb

    def paste(self, data, inputs=None, delay=None, pos=None):
        """A copied block back in: on its old inputs while they still exist, or on the ones given."""
        self._n += 1
        nb = json.loads(data) if isinstance(data, str) else json.loads(json.dumps(data))
        if nb.get("kind") not in KINDS:
            return None
        nb["id"] = f"b{self._n}"
        ids = {b["id"] for b in self.blocks}
        keep = [x for x in nb.get("inputs", []) if x in ids or (x.startswith("card:") and int(x[5:]) < len(self.cards))]
        nb["inputs"] = list(inputs) if inputs is not None else keep
        if nb.get("only") is not None:
            nb["only"] = [i for i in nb["only"] if i < len(self.cards)] or None
        if delay is not None:
            nb["delay"] = max(0.0, float(delay))
        x, y = pos if pos is not None else (nb.get("x", 260.0) + 30.0, nb.get("y", 40.0) + 30.0)
        nb["x"], nb["y"] = self.free_spot(x, y)
        self.blocks.append(nb)
        return nb

    def times(self):
        """Each block's (start, end) in seconds: it starts when its last input block ends, plus its delay."""
        out = {}

        def start(bid, stack=()):
            if bid in out:
                return out[bid][0]
            b = self.block(bid)
            if b is None or bid in stack:
                return 0.0
            s = 0.0
            for x in b["inputs"]:
                if not x.startswith("card:"):
                    st = start(x, stack + (bid,))
                    s = max(s, st + self.block(x)["dur"])
            s += max(0.0, b["delay"])
            out[bid] = (s, s + max(0.05, b["dur"]))
            return s
        for b in self.blocks:
            start(b["id"])
        return out

    def length(self):
        t = self.times()
        return max([3.0] + [e for _s, e in t.values()]) + 0.3

    def follows_from(self, bid):
        """When a block's start is decided by its inputs (before its own delay)."""
        b = self.block(bid)
        t = self.times()
        return max([0.0] + [t[x][1] for x in b["inputs"] if x in t])

    # ---------- evaluation
    def evaluate(self, t):
        """Every card's pose at time t (x, y, z in cells, angles in degrees, scale), each card's layout
        position (for framing), and the camera (zoom, yaw, pitch, focus, dof_min)."""
        n = len(self.cards)
        times = self.times()
        memo = {}
        order = sorted(self.blocks, key=lambda b: (times[b["id"]][0], b["id"]))
        lay = [dict(x=0.0, y=0.0, z=0.0, yaw=0.0, roll=0.0) for _ in range(n)]
        # cards start in a row, unless a layout comes first: then they start there already
        row = _layout("row", n, list(range(n)), {"gap": 1.0})
        for i in range(n):
            lay[i].update(row[i])
        first = {}
        for b in order:
            if KINDS[b["kind"]][1] == "layout":
                for i in self.targets(b["id"], memo):
                    first.setdefault(i, b)
        for i, b in first.items():
            st = self.set_of(b["id"], memo)
            lay[i].update(_layout(b["kind"], n, st, b["params"])[st.index(i)])
        add = [_blank_pose() for _ in range(n)]
        sleeves = {}
        cam = dict(zoom=1.0, yaw=0.0, pitch=0.0, focus=0.0, dof_min=0.0)
        for b in order:
            s, e = times[b["id"]]
            kind, fam = b["kind"], KINDS[b["kind"]][1]
            tg = self.targets(b["id"], memo)
            p = (t - s) / max(1e-6, e - s)
            if fam == "camera":
                if p <= 0:
                    continue
                _camera(kind, min(1.0, p), b["params"], cam)
                continue
            if not tg:
                continue
            if fam == "layout":
                if p <= 0:
                    continue
                k = ease(min(1.0, p))
                st = self.set_of(b["id"], memo)
                dest = _layout(kind, n, st, b["params"])
                for i in tg:
                    d = dest[st.index(i)]
                    for key in ("x", "y", "z", "yaw", "roll"):
                        lay[i][key] += (d[key] - lay[i][key]) * k
                continue
            if fam == "holder":
                for i in tg:
                    sleeves.setdefault(i, []).append((s, e, kind))
                continue
            if fam == "group":
                if p <= 0 or p >= 1:
                    continue
                fn = GROUP_FNS[kind]
                st = self.set_of(b["id"], memo)
                m = len(st)
                for i in tg:
                    j = st.index(i)
                    a0, a = fn(0.0, j, m), fn(p, j, m)
                    for key in ("x", "y", "z", "yaw", "pitch", "roll"):
                        add[i][key] += a.get(key, 0.0) - a0.get(key, 0.0)
                continue
            # actions
            for j, i in enumerate(tg):
                if kind == "stagger":
                    m = len(tg)
                    ov = float(b["params"].get("overlap", 0.5))
                    each = 1.0 / (m - (m - 1) * ov) if m > 1 else 1.0
                    q = (p - j * each * (1 - ov)) / each
                    _action(b["params"].get("of", "flip"), q, KINDS[b["params"].get("of", "flip")][3] and
                            {k: v[0] for k, v in KINDS[b["params"].get("of", "flip")][3].items()}, add[i])
                else:
                    _action(kind, p, b["params"], add[i])
        poses = []
        for i in range(n):
            a = add[i]
            poses.append(dict(x=lay[i]["x"] + a["x"], y=lay[i]["y"] + a["y"], z=lay[i]["z"] + a["z"],
                              yaw=lay[i]["yaw"] + a["yaw"], pitch=a["pitch"], roll=lay[i]["roll"] + a["roll"],
                              scale=a["scale"]))
            if i in sleeves:                      # this card's holders, from its sleeving blocks
                poses[-1]["rig"] = _sleeve_rig(sleeves[i], t)
        return poses, [dict(x=l["x"], y=l["y"], z=l["z"]) for l in lay], cam


def _sleeve_rig(blocks, t):
    """Which holders a card is in at time t, and where they are (centre in mm above the card's): before its
    first sleeving block, as that block begins; during one, as it plays; after, as the last one ended."""
    blocks = sorted(blocks)
    started = [b for b in blocks if t >= b[0]]
    if not started:
        s, e, kind = blocks[0]
        return [tuple(h) for h in SLEEVE_FNS[kind](0.0)["rig"]["holders"]]
    s, e, kind = started[-1]
    q = min(1.0, (t - s) / max(1e-6, e - s))
    return [tuple(h) for h in SLEEVE_FNS[kind](q)["rig"]["holders"]]


def _layout(kind, n, tg, params):
    """Where a layout puts each of the cards it reaches (in order): x, y, z in cells, yaw and roll."""
    m = len(tg)
    out = []
    for j in range(m):
        if kind == "stack":
            out.append(dict(x=0.0, y=0.0, z=-C.STACK_GAP * j, yaw=0.0, roll=0.0))
        elif kind == "row":
            cols, rows = C._grid(m)
            g = float(params.get("gap", 1.0))
            c, r = j % cols, j // cols
            out.append(dict(x=(c - (cols - 1) / 2) * g, y=((rows - 1) / 2 - r) * g, z=0.0, yaw=0.0, roll=0.0))
        elif kind == "fan":
            sp = math.radians(float(params.get("spread", 12.0)))
            a = (j - (m - 1) / 2) * sp
            R = 1.45
            out.append(dict(x=R * math.sin(a), y=R * math.cos(a) - R, z=j * C.STACK_GAP, yaw=0.0, roll=-math.degrees(a)))
        elif kind == "circle":
            r = max(0.95, m * 0.86 / (2 * math.pi))
            a = 2 * math.pi * j / max(1, m)
            out.append(dict(x=r * math.sin(a), y=0.0, z=r * math.cos(a) - r, yaw=math.degrees(a), roll=0.0))
        else:
            out.append(dict(x=0.0, y=0.0, z=0.0, yaw=0.0, roll=0.0))
    return out


def _action(kind, p, params, a):
    """Add what an action does by fraction p of its time (held at its end after, nothing before)."""
    if kind == "enter":
        fn = C.ENTRANCES.get(params.get("style", "drop"), C.ENTRANCES["drop"])[1]
        pz = fn(min(1.0, max(0.0, p)))                  # before it begins the card waits out of shot
        _pose_add(a, pz)
        return
    if p <= 0:
        return
    q = min(1.0, p)
    e = ease(q)
    if kind == "exit":
        fn = C.OUTROS.get(params.get("style", "drop"), C.OUTROS["drop"])[1]
        _pose_add(a, fn(q))
    elif kind == "flip":
        a["yaw"] += 360.0 * float(params.get("turns", 0.5)) * C.ease_out_back(q) if q < 1 else \
            360.0 * float(params.get("turns", 0.5))
        a["z"] += 0.15 * math.sin(math.pi * q)
    elif kind == "flip_v":
        a["pitch"] += 360.0 * float(params.get("turns", 0.5)) * e
        a["z"] += 0.15 * math.sin(math.pi * q)
    elif kind == "spin":
        a["yaw"] += 360.0 * float(params.get("turns", 1.0)) * e
    elif kind == "sway":
        ang = float(params.get("angle", 24.0))
        a["yaw"] += ang * math.sin(2 * math.pi * q) * math.sin(math.pi * q)
        a["pitch"] += ang * 0.3 * math.sin(4 * math.pi * q) * math.sin(math.pi * q)
    elif kind == "hop":
        a["y"] += float(params.get("height", 0.35)) * math.sin(math.pi * q)
    elif kind == "move":
        for k in ("x", "y", "z"):
            a[k] += float(params.get(k, 0.0)) * e
    elif kind == "tilt":
        for k in ("yaw", "pitch", "roll"):
            a[k] += float(params.get(k, 0.0)) * e


def _pose_add(a, pz):
    """An entrance or outro pose (offsets in card heights, angles, scale) added to a card."""
    a["yaw"] += pz.get("yaw", 0.0)
    a["pitch"] += pz.get("pitch", 0.0)
    a["roll"] += pz.get("roll", 0.0)
    a["x"] += pz.get("ox", 0.0)
    a["y"] += pz.get("oy", 0.0)
    a["scale"] *= max(0.001, pz.get("scale", 1.0))


def _camera(kind, q, params, cam):
    e = ease(q)
    if kind == "push":
        cam["zoom"] *= 1.0 + float(params.get("amount", 0.5)) * e
    elif kind == "pull":
        cam["zoom"] *= 1.0 - float(params.get("amount", 0.4)) * e
    elif kind == "orbit":
        cam["yaw"] += float(params.get("angle", 30.0)) * e
    elif kind == "cam_tilt":
        cam["pitch"] += float(params.get("angle", 15.0)) * e
    elif kind == "focus" and q < 1.0:
        cam["focus"] += C.rack_focus(q)
        cam["dof_min"] = max(cam["dof_min"], 0.6 * (1 - q))


def starter(names):
    """A first animation for these cards, so the editor never opens empty: they arrive, gather into a
    stack, and the stack is flipped through, the camera pushing in a little."""
    s = Sequence()
    ids = [s.add_card(n) for n in names]
    if not ids:
        return s
    en = s.add_block("enter", ids, pos=(260.0, 40.0))
    st = s.add_block("stack", [en["id"]], pos=(520.0, 40.0)) if len(ids) > 1 else None
    if st is not None:
        s.add_block("flip_through", [st["id"]], pos=(780.0, 40.0))
    else:
        s.add_block("spin", [en["id"]], pos=(520.0, 40.0))
    cam = s.add_block("push", [], delay=0.5, pos=(260.0, 40.0 + 90.0 * max(1, len(ids))))
    cam["params"]["amount"] = 0.15
    return s
