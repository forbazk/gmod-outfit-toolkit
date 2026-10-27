"""Retarget an outfit .smd onto another skeleton (e.g. ValveBiped -> a Mixamo-style server rig).

The garment is refitted to the target rest pose and proportions, then re-skinned:
- joints are matched through canonical names (hips, neck, head, clavicle, upper arm, forearm,
  hand, 15 finger joints, thigh, calf, foot, toe) for each naming convention;
- spine bones are matched by their height fraction between hips and neck, so 4 source vertebrae
  map onto 2 target ones (weights split between the two bracketing target bones);
- every source bone gets an affine transform taking its segment (head -> next joint) onto the
  matching target segment: rotation, translation, stretch along the bone, global scale across it;
  hands also align their palm (index -> pinky). Joints stay continuous by construction;
- vertices follow their bones with their weights (linear blend), normals are rotated;
- other source bones (attachments, twist bones) follow their nearest matched ancestor.

Usage: python retarget.py outfit.smd target_skeleton.smd output.smd [--no-fit] [--map map.json]
--no-fit only renames and re-skins (control: shows what the refit fixes).
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smd_io import corner_weights, format_corner, read_smd, world_matrices, write_smd  # noqa: E402

FINGERS = {"thumb": "0", "index": "1", "middle": "2", "ring": "3", "pinky": "4"}


def conventions():
    vb, mx = {}, {}
    vb.update(hips="ValveBiped.Bip01_Pelvis", neck="ValveBiped.Bip01_Neck1", head="ValveBiped.Bip01_Head1")
    mx.update(hips="Hips", neck="Neck", head="Head")
    for s, side in (("L", "Left"), ("R", "Right")):
        p = f"ValveBiped.Bip01_{s}_"
        vb.update({f"{s}_clav": p + "Clavicle", f"{s}_upperarm": p + "UpperArm", f"{s}_forearm": p + "Forearm",
                   f"{s}_hand": p + "Hand", f"{s}_thigh": p + "Thigh", f"{s}_calf": p + "Calf",
                   f"{s}_foot": p + "Foot", f"{s}_toe": p + "Toe0"})
        mx.update({f"{s}_clav": side + "Shoulder", f"{s}_upperarm": side + "Arm", f"{s}_forearm": side + "ForeArm",
                   f"{s}_hand": side + "Hand", f"{s}_thigh": side + "UpLeg", f"{s}_calf": side + "Leg",
                   f"{s}_foot": side + "Foot", f"{s}_toe": side + "ToeBase"})
        for f, n in FINGERS.items():
            for k in range(3):
                vb[f"{s}_{f}{k + 1}"] = p + "Finger" + n + ("" if k == 0 else str(k))
                mx[f"{s}_{f}{k + 1}"] = f"{side}Hand{f.capitalize()}{k + 1}"
    return {"ValveBiped": vb, "Mixamo-style": mx}


def segments():
    """(joint, next joint, secondary (from, to) or None); next None = inherit parent segment."""
    seg = [("neck", "head", None), ("head", None, None)]
    for s in ("L", "R"):
        seg += [(f"{s}_clav", f"{s}_upperarm", None), (f"{s}_upperarm", f"{s}_forearm", None),
                (f"{s}_forearm", f"{s}_hand", None), (f"{s}_hand", f"{s}_middle1", (f"{s}_index1", f"{s}_pinky1")),
                (f"{s}_thigh", f"{s}_calf", None), (f"{s}_calf", f"{s}_foot", None), (f"{s}_foot", f"{s}_toe", None),
                (f"{s}_toe", None, None)]
        for f in FINGERS:
            seg += [(f"{s}_{f}1", f"{s}_{f}2", None), (f"{s}_{f}2", f"{s}_{f}3", None), (f"{s}_{f}3", None, None)]
    return seg


INHERIT = {"head": "neck", "L_toe": "L_foot", "R_toe": "R_foot"}
INHERIT.update({f"{s}_{f}3": f"{s}_{f}2" for s in "LR" for f in FINGERS})


def strip(name):
    return name.split(":")[-1]


def detect(names):
    names = {strip(n) for n in names}
    best, score = None, -1
    for conv, table in conventions().items():
        hit = sum(1 for v in table.values() if v in names)
        if hit > score:
            best, score = conv, hit
    return best


class Rig:
    def __init__(self, smd, overrides=None):
        self.smd = smd
        self.world = {strip(k): v for k, v in world_matrices(smd).items()}
        self.parent = {strip(smd["nodes"][i]): (strip(smd["nodes"][p]) if p >= 0 else None)
                       for i, p in smd["parents"].items()}
        self.conv = detect(self.world)
        table = dict(conventions()[self.conv])
        table.update(overrides or {})
        self.joint = {j: b for j, b in table.items() if b in self.world}
        self.bone_joint = {b: j for j, b in self.joint.items()}
        chain, cur = [], self.joint.get("neck")
        while cur and cur != self.joint.get("hips"):
            cur = self.parent[cur]
            chain.append(cur)
        self.spine = list(reversed(chain))  # hips ... last bone below neck
        z0, z1 = self.head("hips")[2], self.head("neck")[2]
        self.frac = {b: (self.world[b][1][2] - z0) / ((z1 - z0) or 1.0) for b in self.spine}

    def head(self, joint):
        return self.world[self.joint[joint]][1]

    def spine_point(self, f):
        """Point on the hips -> neck polyline at height fraction f."""
        pts = [self.world[b][1] for b in self.spine] + [self.head("neck")]
        fr = [self.frac[b] for b in self.spine] + [1.0]
        for k in range(len(pts) - 1):
            if f <= fr[k + 1] or k == len(pts) - 2:
                t = (f - fr[k]) / ((fr[k + 1] - fr[k]) or 1.0)
                return pts[k] + (pts[k + 1] - pts[k]) * t
        return pts[-1]

    def spine_split(self, f):
        """Height fraction -> {target spine bone or neck: weight}."""
        bones = self.spine + [self.joint["neck"]]
        fr = [self.frac[b] for b in self.spine] + [1.0]
        if f <= fr[0]:
            return {bones[0]: 1.0}
        for k in range(len(bones) - 1):
            if f <= fr[k + 1]:
                t = (f - fr[k]) / ((fr[k + 1] - fr[k]) or 1.0)
                return {bones[k]: 1 - t, bones[k + 1]: t}
        return {bones[-1]: 1.0}


def rotation_between(a, b, a2=None, b2=None):
    """Rotation taking direction a to b (and, if given, the plane of a2 onto that of b2)."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    if a2 is not None:
        def frame(d, s):
            s = s - d * np.dot(s, d)
            s /= np.linalg.norm(s)
            return np.stack([d, s, np.cross(d, s)], 1)
        return frame(b, b2) @ frame(a, a2).T
    v, c = np.cross(a, b), float(np.dot(a, b))
    if c < -0.999999:
        axis = np.cross(a, [1.0, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1.0, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def axial_scale(d, axial, across):
    d = d / np.linalg.norm(d)
    return across * np.eye(3) + (axial - across) * np.outer(d, d)


def build(src, dst, fit=True):
    """-> transforms {source bone: (A 3x3, t)} and weight map {source bone: {target bone: w}}."""
    # global scale from the hips -> neck length: unlike head-to-feet height it ignores the stance
    # (spread legs or a T-pose shorten the measured height)
    g = np.linalg.norm(dst.head("neck") - dst.head("hips")) / np.linalg.norm(src.head("neck") - src.head("hips"))
    fwd = lambda r: (r.head("L_toe") + r.head("R_toe") - r.head("L_foot") - r.head("R_foot"))  # noqa: E731
    flip = np.diag([-1.0, -1.0, 1.0]) if np.dot(fwd(src)[:2], fwd(dst)[:2]) < 0 else np.eye(3)
    T, W = {}, {}
    common = [j for j in src.joint if j in dst.joint]
    for j in common:
        W[src.joint[j]] = {dst.joint[j]: 1.0}
    for b in src.spine:
        W[b] = dst.spine_split(src.frac[b])
    if not fit:
        return {b: (np.eye(3), np.zeros(3)) for b in src.world}, W, g
    # spine: each source vertebra segment onto the target spine polyline
    chain = src.spine + [src.joint["neck"]]
    for k, b in enumerate(src.spine):
        hs, ns = src.world[b][1], src.world[chain[k + 1]][1]
        ht, nt = dst.spine_point(src.frac[b]), dst.spine_point(src.frac.get(chain[k + 1], 1.0))
        R = rotation_between(flip @ (ns - hs), nt - ht) @ flip
        A = R @ axial_scale(ns - hs, np.linalg.norm(nt - ht) / np.linalg.norm(ns - hs), g)
        T[b] = (A, ht - A @ hs)
    rots = {}
    for j, nxt, sec in segments():
        if j not in src.joint or j not in dst.joint:
            continue
        hs, ht = src.head(j), dst.head(j)
        if nxt and nxt in src.joint and nxt in dst.joint:
            ds, dt = src.head(nxt) - hs, dst.head(nxt) - ht
            if sec and all(x in src.joint and x in dst.joint for x in sec):
                R = rotation_between(flip @ ds, dt, flip @ (src.head(sec[1]) - src.head(sec[0])),
                                     dst.head(sec[1]) - dst.head(sec[0])) @ flip
            else:
                R = rotation_between(flip @ ds, dt) @ flip
            A = R @ axial_scale(ds, np.linalg.norm(dt) / np.linalg.norm(ds), g)
        else:
            R = rots.get(INHERIT.get(j), flip)
            A = R * g
        rots[j] = R
        T[src.joint[j]] = (A, ht - A @ hs)
    if src.joint["hips"] not in T:
        T[src.joint["hips"]] = T[src.spine[1]] if len(src.spine) > 1 else (g * flip, np.zeros(3))
    return T, W, g


def nearest_matched(bone, src, table):
    cur = bone
    while cur is not None and cur not in table:
        cur = src.parent.get(cur)
    return cur


def main():
    p = argparse.ArgumentParser()
    p.add_argument("outfit")
    p.add_argument("target")
    p.add_argument("output")
    p.add_argument("--no-fit", action="store_true")
    p.add_argument("--map", help="JSON {canonical_joint: source_bone_name} overrides for the outfit rig")
    a = p.parse_args()
    s_smd, d_smd = read_smd(a.outfit), read_smd(a.target)
    src = Rig(s_smd, json.load(open(a.map)) if a.map else None)
    dst = Rig(d_smd)
    print(f"outfit rig: {src.conv}, {len(src.joint)} joints matched, spine {len(src.spine)} bones")
    print(f"target rig: {dst.conv}, {len(dst.joint)} joints matched, spine {len(dst.spine)} bones")
    T, W, g = build(src, dst, fit=not a.no_fit)
    print(f"global scale {g:.4f}")
    index_of = {strip(n): i for i, n in d_smd["nodes"].items()}
    nodes = {i: strip(n) for i, n in s_smd["nodes"].items()}
    unmatched = set()
    out = []
    for mat, corners in s_smd["tris"]:
        lines = []
        for c in corners:
            pos, nrm = np.array(list(map(float, c[1:4]))), np.array(list(map(float, c[4:7])))
            new_p, new_n, weights = np.zeros(3), np.zeros(3), {}
            ws = corner_weights(c, s_smd["nodes"])
            total = sum(w for _, w in ws) or 1.0
            for bone, w in ws:
                bone = strip(bone)
                tb = nearest_matched(bone, src, T)
                wb = nearest_matched(bone, src, W)
                if tb is None or wb is None:
                    unmatched.add(bone)
                    tb = tb or src.joint["hips"]
                    wb = wb or src.joint["hips"]
                A, t = T[tb]
                new_p += (w / total) * (A @ pos + t)
                new_n += (w / total) * (A @ nrm)
                for tbone, tw in W[wb].items():
                    weights[tbone] = weights.get(tbone, 0) + w * tw
            new_n /= np.linalg.norm(new_n) or 1.0
            lines.append(format_corner(index_of, new_p, new_n, (c[7], c[8]), weights))
        out.append((mat, lines))
    write_smd(a.output, d_smd["header"], out)
    if unmatched:
        print(f"bones without a match (fell back to hips): {sorted(unmatched)}")
    print(f"RESULT OK {len(out)} triangles -> {a.output}")


if __name__ == "__main__":
    main()
