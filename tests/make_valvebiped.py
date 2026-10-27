"""Ground truth for retarget.py, built from a Mixamo-style reference outfit.

expected.smd : the reference mesh, weights collapsed onto its main joints (twist, cape, face and
               weapon bones folded into their parent joint), same skeleton.
valvebiped.smd: the same garment as if made on a ValveBiped rig: main bones renamed (plus an extra
               unweighted vertebra), arms raised to a T-pose, legs spread, scaled x1.12 and moved.
Retargeting valvebiped.smd onto the reference skeleton must give back expected.smd.

Usage: python make_valvebiped.py reference.smd output_folder
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from retarget import conventions  # noqa: E402
from smd_io import corner_weights, read_smd, world_matrices, write_smd  # noqa: E402

VB, MX = conventions()["ValveBiped"], conventions()["Mixamo-style"]
SPINE_VB = {"Hips": "ValveBiped.Bip01_Pelvis", "Spine": "ValveBiped.Bip01_Spine", "Spine1": "ValveBiped.Bip01_Spine2"}


def rot(axis, deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    x, y, z = axis
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    smd = read_smd(src)
    world = world_matrices(smd)
    name_of = smd["nodes"]
    parent = {name_of[i]: (name_of[p] if p >= 0 else None) for i, p in smd["parents"].items()}
    rename = {MX[j]: VB[j] for j in MX if MX[j] in world}
    rename.update({k: v for k, v in SPINE_VB.items() if k in world})
    main_set = set(rename)

    def collapse(b):
        while b not in main_set:
            b = parent[b]
        return b

    def fmt(index, pos, nrm, uv, ws):
        pos, nrm = [float(x) for x in pos], [float(x) for x in nrm]
        w = sorted(ws.items(), key=lambda t: -t[1])[:3]
        tot = sum(x for _, x in w)
        return (f"{index[w[0][0]]} {pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f} {nrm[0]:.6f} {nrm[1]:.6f} {nrm[2]:.6f} "
                f"{uv[0]} {uv[1]} {len(w)} " + " ".join(f"{index[b]} {x / tot:.6f}" for b, x in w))

    # expected: original geometry, collapsed weights, reference skeleton
    ref_index = {n: i for i, n in name_of.items()}
    tris_c = []
    for mat, corners in smd["tris"]:
        lines = []
        for c in corners:
            ws = {}
            for b, w in corner_weights(c, name_of):
                ws[collapse(b)] = ws.get(collapse(b), 0) + w
            lines.append(fmt(ref_index, c[1:4], c[4:7], (c[7], c[8]), ws))
        tris_c.append((mat, lines))
    write_smd(os.path.join(out, "expected.smd"), smd["header"], tris_c)

    # pose: world rotations about the bone head, inherited by descendants
    pose = {VB["L_upperarm"]: rot((0, 1, 0), -40), VB["R_upperarm"]: rot((0, 1, 0), 40),
            VB["L_thigh"]: rot((0, 1, 0), 6), VB["R_thigh"]: rot((0, 1, 0), -6)}
    scale, shift = 1.12, np.array([0.0, 0.5, 1.0])
    M = {}

    def matrix(b):
        if b in M:
            return M[b]
        p = parent[b]
        while p is not None and p not in main_set:
            p = parent[p]
        A, t = (np.eye(3), np.zeros(3)) if p is None else matrix(p)
        R = pose.get(rename[b])
        if R is not None:
            h = A @ world[b][1] + t
            A, t = R @ A, R @ (t - h) + h
        M[b] = (A, t)
        return M[b]
    for b in main_set:
        matrix(b)
    final = {b: (scale * A, scale * t + shift) for b, (A, t) in M.items()}
    heads = {rename[b]: final[b][0] @ world[b][1] + final[b][1] for b in main_set}
    # extra unweighted vertebra between Spine and Spine2 (exercises the spine interpolation)
    sp, sp2 = SPINE_VB["Spine"], SPINE_VB["Spine1"]
    heads["ValveBiped.Bip01_Spine1"] = (heads[sp] + heads[sp2]) / 2
    vb_parent = {rename[b]: None for b in main_set}
    for b in main_set:
        p = parent[b]
        while p is not None and p not in main_set:
            p = parent[p]
        vb_parent[rename[b]] = rename[p] if p else None
    vb_parent["ValveBiped.Bip01_Spine1"] = sp
    vb_parent[sp2] = "ValveBiped.Bip01_Spine1"
    order = []

    def visit(n):
        if n in order:
            return
        if vb_parent[n]:
            visit(vb_parent[n])
        order.append(n)
    for n in heads:
        visit(n)
    vb_index = {n: i for i, n in enumerate(order)}
    head = ["version 1", "nodes"] + [f'{vb_index[n]} "{n}" {vb_index[vb_parent[n]] if vb_parent[n] else -1}'
                                     for n in order]
    head += ["end", "skeleton", "time 0"]
    for n in order:
        p = heads[n] - (heads[vb_parent[n]] if vb_parent[n] else 0)
        head.append(f"{vb_index[n]} {p[0]:.6f} {p[1]:.6f} {p[2]:.6f} 0.000000 0.000000 0.000000")
    head.append("end")
    tris_v = []
    for (mat, corners), (_, lines_c) in zip(smd["tris"], tris_c):
        lines = []
        for c, lc in zip(corners, lines_c):
            f = lc.split()
            ws = {name_of[int(f[10 + 2 * j])]: float(f[11 + 2 * j]) for j in range(int(f[9]))}
            pos, nrm = np.array(list(map(float, c[1:4]))), np.array(list(map(float, c[4:7])))
            np_, nn = np.zeros(3), np.zeros(3)
            for b, w in ws.items():
                A, t = final[b]
                np_ += w * (A @ pos + t)
                nn += w * (A @ nrm)
            nn /= np.linalg.norm(nn)
            lines.append(fmt(vb_index, np_, nn, (c[7], c[8]), {rename[b]: w for b, w in ws.items()}))
        tris_v.append((mat, lines))
    write_smd(os.path.join(out, "valvebiped.smd"), "\n".join(head) + "\n", tris_v)
    print("written", out)


if __name__ == "__main__":
    main()
