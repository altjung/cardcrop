"""The 3D view as a glTF scene for Blender (and Cinema 4D, Maya, any glTF app): every card with its photos,
its holders, the camera, and the animation baked as keyframes, at real size in metres.

The camera stands still at the origin looking down -Z, as in CardCrop, and the cards move round it, so
orbits and pushes come through as the cards' own motion. Holders that come and go (a sleeve going on) are
scaled to nothing while they are not there. Opens in Blender with File > Import > glTF 2.0.
"""

from __future__ import annotations

import json
import math
import struct

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice

import card3d as C

M_PER_UNIT = 0.088 / C.CARD_H            # a card is 88 mm tall


class _GLB:
    """Collects buffers, accessors, images, materials, meshes and nodes, and writes one .glb file."""

    def __init__(self):
        self.bin = bytearray()
        self.j = dict(asset=dict(version="2.0", generator="CardCrop"), scenes=[dict(nodes=[])], scene=0, nodes=[],
                      meshes=[], materials=[], textures=[], images=[], samplers=[dict(magFilter=9729,
                                                                                       minFilter=9987)],
                      accessors=[], bufferViews=[], buffers=[], animations=[], cameras=[],
                      extensionsUsed=["KHR_materials_transmission", "KHR_materials_ior"])

    def _view(self, data, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin += data
        v = dict(buffer=0, byteOffset=off, byteLength=len(data))
        if target:
            v["target"] = target
        self.j["bufferViews"].append(v)
        return len(self.j["bufferViews"]) - 1

    def accessor(self, arr, kind, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        if arr.dtype == np.uint32:
            ctype = 5125
        else:
            arr = arr.astype(np.float32)
            ctype = 5126
        bv = self._view(arr.tobytes(), target)
        count = arr.shape[0]
        a = dict(bufferView=bv, componentType=ctype, count=int(count), type=kind)
        if minmax:
            flat = arr.reshape(count, -1)
            a["min"] = [float(x) for x in flat.min(axis=0)]
            a["max"] = [float(x) for x in flat.max(axis=0)]
        self.j["accessors"].append(a)
        return len(self.j["accessors"]) - 1

    def image(self, png):
        bv = self._view(png)
        self.j["images"].append(dict(bufferView=bv, mimeType="image/png"))
        self.j["textures"].append(dict(source=len(self.j["images"]) - 1, sampler=0))
        return len(self.j["textures"]) - 1

    def material(self, name, colour=(1, 1, 1, 1), tex=None, rough=0.4, clear=False, double=False):
        pbr = dict(baseColorFactor=list(colour), metallicFactor=0.0, roughnessFactor=rough)
        if tex is not None:
            pbr["baseColorTexture"] = dict(index=tex)
        m = dict(name=name, pbrMetallicRoughness=pbr, doubleSided=bool(double or clear))
        if clear:                         # clear acrylic: let light through, refract like plastic
            m["extensions"] = dict(KHR_materials_transmission=dict(transmissionFactor=0.96),
                                   KHR_materials_ior=dict(ior=1.49))
        self.j["materials"].append(m)
        return len(self.j["materials"]) - 1

    def mesh(self, name, prims):
        """prims: [(positions (n,3), normals (n,3), uvs (n,2), material)] as triangle lists."""
        out = []
        for pos, nor, uv, mat in prims:
            if len(pos) == 0:
                continue
            out.append(dict(attributes=dict(POSITION=self.accessor(pos, "VEC3", 34962, minmax=True),
                                            NORMAL=self.accessor(nor, "VEC3", 34962),
                                            TEXCOORD_0=self.accessor(uv, "VEC2", 34962)),
                            material=mat, mode=4))
        self.j["meshes"].append(dict(name=name, primitives=out))
        return len(self.j["meshes"]) - 1

    def node(self, **kw):
        self.j["nodes"].append(kw)
        i = len(self.j["nodes"]) - 1
        self.j["scenes"][0]["nodes"].append(i)
        return i

    def write(self, path):
        while len(self.bin) % 4:
            self.bin.append(0)
        self.j["buffers"] = [dict(byteLength=len(self.bin))]
        for k in ("animations", "cameras", "textures", "images"):
            if not self.j[k]:
                del self.j[k]
        js = json.dumps(self.j, separators=(",", ":")).encode()
        while len(js) % 4:
            js += b" "
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as f:
            f.write(struct.pack("<4sII", b"glTF", 2, total))
            f.write(struct.pack("<I4s", len(js), b"JSON"))
            f.write(js)
            f.write(struct.pack("<I4s", len(self.bin), b"BIN\0"))
            f.write(bytes(self.bin))


def _png(img, long_side=2048):
    import cv2
    if img is None:
        img = np.full((880, 630, 3), 0x3A, np.uint8)
    a = img
    if a.dtype != np.uint8:
        a = (np.clip(a.astype(np.float32) / (65535.0 if a.dtype == np.uint16 else 1.0), 0, 1) * 255).astype(np.uint8)
    if a.ndim == 2:
        a = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
    a = a[..., :3]
    h, w = a.shape[:2]
    k = min(1.0, long_side / max(h, w))
    if k < 1:
        a = cv2.resize(a, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", a)
    return buf.tobytes()


def _qpng(q):
    ba = QByteArray()
    bf = QBuffer(ba)
    bf.open(QIODevice.WriteOnly)
    q.save(bf, "PNG")
    return bytes(ba)


def _split(data, faces):
    """A CardCrop mesh (pos, normal, uv, face per vertex) split into one primitive per group of faces,
    in metres, with glTF's uv (rows counted from the top)."""
    v = np.asarray(data, np.float32).reshape(-1, 9)
    out = []
    for fs in faces:
        sel = v[np.isin(np.round(v[:, 8]), fs)]
        pos = sel[:, 0:3] * M_PER_UNIT
        nor = sel[:, 3:6]
        n = np.linalg.norm(nor, axis=1, keepdims=True)
        nor = np.where(n > 1e-6, nor / np.maximum(n, 1e-6), np.array([0, 0, 1], np.float32))
        uv = np.stack([sel[:, 6], 1.0 - sel[:, 7]], axis=1)
        out.append((pos, nor, uv))
    return out


def _trs(m):
    """A QMatrix4x4 (scene units) as translation (metres), rotation (x, y, z, w) and scale."""
    a = np.array(m.data(), np.float64).reshape(4, 4).T          # Qt stores columns
    t = a[:3, 3] * M_PER_UNIT
    r = a[:3, :3]
    s = np.linalg.norm(r, axis=0)
    s = np.where(s > 1e-9, s, 1e-9)
    r = r / s
    if np.linalg.det(r) < 0:
        r[:, 0] *= -1
        s[0] *= -1
    w = math.sqrt(max(0.0, 1 + r[0, 0] + r[1, 1] + r[2, 2])) / 2
    x = math.sqrt(max(0.0, 1 + r[0, 0] - r[1, 1] - r[2, 2])) / 2
    y = math.sqrt(max(0.0, 1 - r[0, 0] + r[1, 1] - r[2, 2])) / 2
    z = math.sqrt(max(0.0, 1 - r[0, 0] - r[1, 1] + r[2, 2])) / 2
    x = math.copysign(x, r[2, 1] - r[1, 2])
    y = math.copysign(y, r[0, 2] - r[2, 0])
    z = math.copysign(z, r[1, 0] - r[0, 1])
    q = np.array([x, y, z, w])
    return t, q / max(1e-9, np.linalg.norm(q)), s


def export(view, path, w=1920, h=1080, fps=30, seconds=None, progress=None):
    """Write the view's cards (one, a group, or an animation) and their motion to a .glb file. seconds
    defaults to the animation's length, or one loop of a group, or a still for one card."""
    g = _GLB()
    cards = view.group or [dict(name="card", front=view.front_np, back=None, label={})]
    single = not view.group
    if seconds is None:
        seconds = view.seq.length() if view.seq is not None else (view.group_seconds() if view.group else 0.0)
    n_frames = max(1, int(round(seconds * fps)) + 1) if seconds > 0 else 1

    # the card: front and back in their photos, the edge plain stock
    edge = g.material("card edge", (0.86, 0.85, 0.82, 1.0), rough=0.7)
    parts = _split(C.build_mesh(), [(0,), (1,), (2,)])
    holders_used = {}

    def poses_at(t):
        if single:
            m = view_matrix_single(view, w, h)
            return [(m, m, dict(_holders=[]))]
        view._seq_now = t
        u = (t / max(1e-6, view.group_seconds())) % 1.0
        out, _d, _f = view._group_mvs(w, h, 0.0, 0.0, 1.0, u, C._rest())
        return out

    frames = [poses_at(i / fps) for i in range(n_frames)]
    for _fr in frames:
        for k_, (_m, _hm, ps) in enumerate(_fr):
            for nm, _x in ps.get("_holders", []):
                holders_used.setdefault(k_, [])
                if nm not in holders_used[k_]:
                    holders_used[k_].append(nm)

    nodes = []                                   # (node index, [matrix per frame or None])
    for k_, c in enumerate(cards):
        front = g.material(f"{c['name']} front", tex=g.image(_png(c.get("front"))), rough=0.35)
        back = g.material(f"{c['name']} back", tex=g.image(_png(c.get("back"))), rough=0.55)
        mesh = g.mesh(c["name"], [(parts[0][0], parts[0][1], parts[0][2], front),
                                  (parts[1][0], parts[1][1], parts[1][2], back),
                                  (parts[2][0], parts[2][1], parts[2][2], edge)])
        nd = g.node(name=c["name"], mesh=mesh)
        nodes.append((nd, [fr[k_][0] for fr in frames]))
        # its holders
        for nm in holders_used.get(k_, []):
            data, _nl = C.build_holder(nm)
            hp = _split(data, [(4,), (0, 1, 2, 6, 7)])
            clear = g.material(f"{C.HOLDERS[nm]['label']} plastic", (1, 1, 1, 1), rough=0.06, clear=True)
            prims = [(hp[1][0], hp[1][1], hp[1][2], clear)]
            if len(hp[0][0]):
                lb = c.get("label") or {}
                lab = C.slab_label(lb.get("top", ""), lb.get("name", ""), lb.get("number", ""),
                                   lb.get("condition", ""), C._label_aspect())
                prims.insert(0, (hp[0][0], hp[0][1], hp[0][2], g.material("label", tex=g.image(_qpng(lab)),
                                                                          rough=0.8, double=True)))
            hm = g.mesh(f"{c['name']} {C.HOLDERS[nm]['label']}", prims)
            hn = g.node(name=f"{c['name']} {C.HOLDERS[nm]['label']}", mesh=hm)
            mats = []
            for fr in frames:
                hs = dict(fr[k_][2].get("_holders", []))
                mats.append(hs.get(nm))           # None: not there in this frame
            nodes.append((hn, mats))
        if progress:
            progress(k_ + 1, len(cards))

    # the camera, at the origin looking down -Z
    g.j["cameras"].append(dict(type="perspective", perspective=dict(yfov=math.radians(30.0), aspectRatio=w / h,
                                                                     znear=0.01, zfar=100.0)))
    g.node(name="Camera", camera=0)

    # rest pose on every node, then keyframes
    times = np.array([i / fps for i in range(n_frames)], np.float32)
    channels, samplers = [], []
    tin = g.accessor(times, "SCALAR", minmax=True) if n_frames > 1 else None
    for nd, mats in nodes:
        first = next((m for m in mats if m is not None), None)
        ts, qs, ss = [], [], []
        prev_q = None
        for m in mats:
            if m is None:                         # not there: no size, where it last was
                t_, q_, s_ = (ts[-1] if ts else np.zeros(3)), (qs[-1] if qs else np.array([0, 0, 0, 1.0])), np.zeros(3)
                if first is not None and not ts:
                    t_, q_, _s = _trs(first)
            else:
                t_, q_, s_ = _trs(m)
                if prev_q is not None and float(np.dot(prev_q, q_)) < 0:
                    q_ = -q_                      # the short way round, so turns never spin backwards
            prev_q = q_
            ts.append(t_)
            qs.append(q_)
            ss.append(s_)
        node = g.j["nodes"][nd]
        node["translation"] = [float(x) for x in ts[0]]
        node["rotation"] = [float(x) for x in qs[0]]
        node["scale"] = [float(x) for x in ss[0]]
        if tin is None:
            continue
        for path_, vals, kind in (("translation", ts, "VEC3"), ("rotation", qs, "VEC4"), ("scale", ss, "VEC3")):
            out = g.accessor(np.array(vals, np.float32), kind)
            samplers.append(dict(input=tin, output=out, interpolation="LINEAR"))
            channels.append(dict(sampler=len(samplers) - 1, target=dict(node=nd, path=path_)))
    if channels:
        g.j["animations"].append(dict(name="CardCrop", channels=channels, samplers=samplers))
    g.write(path)
    return n_frames


def view_matrix_single(view, w, h):
    """One card as the view shows it at rest: face-on, framed."""
    from PySide6.QtGui import QMatrix4x4
    m = QMatrix4x4()
    m.translate(0, 0, -view.fit_dist(w, h))
    return m
