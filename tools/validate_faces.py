"""Backfaces seen from outside = holes in game (Source does not render the back of faces).

Casts rays from a cylinder around the model (plus top and bottom) toward the vertical axis,
and counts first hits on faces pointing the wrong way, per material.
Output: % of rays landing on a backface + worst zones. Exit 1 above the threshold.

Usage: blender -b --python validate_faces.py -- --smd outfit.smd [--threshold 2.0] [--with face.smd ...]
"""
import argparse
import math
import os
import sys
from collections import Counter

from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smd_blender as S  # noqa: E402


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--smd", required=True)
    p.add_argument("--threshold", type=float, default=2.0)
    p.add_argument("--with", dest="occluders", nargs="*", default=[],
                   help="extra SMDs used as occluders only (e.g. the face bodygroup), not counted")
    return p.parse_args(sys.argv[sys.argv.index("--") + 1:])


def main():
    a = args()
    ob = S.import_smd(a.smd)
    verts, polys, mats, normals = [], [], [], []
    for k, o in enumerate([ob] + [S.import_smd(p, clear=False) for p in a.occluders]):
        me = o.data
        base = len(verts)
        verts += [v.co.copy() for v in me.vertices]
        polys += [tuple(base + i for i in p.vertices) for p in me.polygons]
        mats += [me.materials[p.material_index].name if k == 0 else None for p in me.polygons]
        normals += [p.normal.copy() for p in me.polygons]
    tree = BVHTree.FromPolygons(verts, polys)
    zmin = min(v.z for v in verts)
    zmax = max(v.z for v in verts)
    radius = max(math.hypot(v.x, v.y) for v in verts) + 10
    hits, back = Counter(), Counter()
    zones = Counter()
    rays = []
    for k in range(240):
        th = 2 * math.pi * k / 240
        for j in range(120):
            z = zmin + (zmax - zmin) * (j + 0.5) / 120
            for tilt in (-0.35, 0.0, 0.35):
                o = Vector((math.cos(th) * radius, math.sin(th) * radius, z + tilt * radius))
                rays.append((o, (Vector((0, 0, z)) - o).normalized()))
    for k in range(60):
        for j in range(60):
            x = -radius + 2 * radius * (k + 0.5) / 60
            y = -radius + 2 * radius * (j + 0.5) / 60
            rays.append((Vector((x, y, zmax + 20)), Vector((0, 0, -1))))
            rays.append((Vector((x, y, zmin - 20)), Vector((0, 0, 1))))
    for o, d in rays:
        loc, _, idx, _ = tree.ray_cast(o, d)
        if idx is None or mats[idx] is None:
            continue
        m = mats[idx]
        hits[m] += 1
        if normals[idx].dot(d) > 0:
            back[m] += 1
            zones[(m, round(loc.x / 3) * 3, round(loc.y / 3) * 3, round(loc.z / 3) * 3)] += 1
    total_h, total_b = sum(hits.values()), sum(back.values())
    for m in sorted(hits):
        print(f"FACES {m:16} backface {100 * back[m] / hits[m]:6.2f} %  ({back[m]}/{hits[m]})")
    for (m, x, y, z), n in zones.most_common(6):
        print(f"ZONE {m} x={x} y={y} z={z}: {n}")
    pct = 100 * total_b / max(total_h, 1)
    ok = pct <= a.threshold
    print("RESULT", "OK" if ok else "FAIL", f"backfaces seen from outside {pct:.2f} % (threshold {a.threshold} %)")
    sys.exit(0 if ok else 1)


main()
