"""Validate optimized .smd files against the original, inside Blender (Blender Source Tools required).

Per file (Source units):
- surface distance LOD->original and original->LOD (max, p99, mean), at rest AND posed
  (arms/legs/head rotated through the armature: checks that weights still follow)
- area per material, bbox, X symmetry, max weights per vertex, % flipped normals
Renders: <out>/render_{rest,posed}_{front,side}.png (workbench), all models side by side.

Pass criteria per file: <= 3 weights/vertex, flipped normals <= original + 0.1 %,
surface p99 <= 1.2 % of model height (rest and posed), area per material within +-7 %.

Usage: blender -b --python validate_lods.py -- --ref original.smd --out folder lod0.smd [lod1.smd ...]
"""
import argparse
import json
import math
import os
import statistics
import sys

import bpy
from mathutils import Euler, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

POSE = {"LeftArm": (0, 0, 50), "RightArm": (0, 0, -50), "LeftForeArm": (0, 0, 60), "RightForeArm": (0, 0, -60),
        "LeftUpLeg": (40, 0, 0), "RightUpLeg": (-30, 0, 0), "LeftLeg": (-50, 0, 0), "Spine1": (0, 15, 10),
        "Head": (0, 25, 0)}


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--ref", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--px", type=int, default=600, help="render width per model")
    p.add_argument("files", nargs="+")
    return p.parse_args(sys.argv[sys.argv.index("--") + 1:])


def load(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.smd(filepath=path, append="NEW_ARMATURE")
    new = set(bpy.data.objects) - before
    mesh = next(o for o in new if o.type == "MESH" and not o.name.startswith("smd_bone_vis"))
    arm = next(o for o in new if o.type == "ARMATURE")
    for o in new:
        if o.name.startswith("smd_bone_vis"):
            bpy.data.objects.remove(o)
    return mesh, arm


def set_pose(arm, posed):
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        r = POSE.get(pb.name, (0, 0, 0)) if posed else (0, 0, 0)
        pb.rotation_euler = Euler([math.radians(x) for x in r])
    bpy.context.view_layer.update()


def world_mesh(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    verts = [ob.matrix_world @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    ev.to_mesh_clear()
    return verts, polys


def surface_dist(src_verts, tree):
    d = sorted((tree.find_nearest(v)[3] or 0.0) for v in src_verts)
    return {"max": round(d[-1], 3), "p99": round(d[int(len(d) * 0.99)], 3), "mean": round(statistics.fmean(d), 4)}


def compare(lod, ref):
    lv, lp = world_mesh(lod)
    rv, rp = world_mesh(ref)
    tl, tr = BVHTree.FromPolygons(lv, lp), BVHTree.FromPolygons(rv, rp)
    return {"lod_to_ref": surface_dist(lv, tr), "ref_to_lod": surface_dist(rv, tl)}


def mat_areas(ob):
    me = ob.data
    names = [m.name for m in me.materials]
    acc = {}
    for p in me.polygons:
        acc[names[p.material_index]] = acc.get(names[p.material_index], 0) + p.area
    return {k: round(v, 1) for k, v in acc.items()}


def symmetry(ob):
    kd = KDTree(len(ob.data.vertices))
    for v in ob.data.vertices:
        kd.insert(v.co, v.index)
    kd.balance()
    d = sorted(kd.find(Vector((-v.co.x, v.co.y, v.co.z)))[2] for v in ob.data.vertices)
    return {"max": round(d[-1], 3), "p99": round(d[int(len(d) * 0.99)], 3)}


def flipped_normals(path):
    """% of corners whose normal points away from the face (=> dark patches in game)."""
    bad = total = 0
    tri, section = [], None
    for line in open(path, encoding="latin-1"):
        s = line.split()
        if s and s[0] == "triangles":
            section = True
            continue
        if not section or len(s) < 9:
            continue
        tri.append((Vector(map(float, s[1:4])), Vector(map(float, s[4:7]))))
        if len(tri) == 3:
            fn = (tri[1][0] - tri[0][0]).cross(tri[2][0] - tri[0][0])
            if fn.length > 1e-9:
                for _, n in tri:
                    bad += fn.dot(n) < 0
                    total += 1
            tri = []
    return round(100 * bad / max(total, 1), 3)


def max_weights(path):
    m, section = 0, None
    for line in open(path, encoding="latin-1"):
        s = line.split()
        if s and s[0] == "triangles":
            section = True
        elif section and len(s) > 9:
            m = max(m, int(s[9]))
    return m


def render(objs, path, posed_label, px=600):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_cavity = True
    scene.render.resolution_x = px * len(objs)
    for o in bpy.data.objects:
        o.hide_render = o not in objs
    cam_data = bpy.data.cameras.get("cam") or bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    span = 70
    # ortho_scale = visible width (largest frame dimension)
    cam_data.ortho_scale = max(span * len(objs), 80)
    scene.render.resolution_y = int(scene.render.resolution_x * 80 / cam_data.ortho_scale)
    cam = bpy.data.objects.get("cam") or bpy.data.objects.new("cam", cam_data)
    if cam.name not in scene.collection.objects:
        scene.collection.objects.link(cam)
    for k, o in enumerate(objs):
        (o.parent or o).location.x = (k - (len(objs) - 1) / 2) * span
    bpy.context.view_layer.update()
    for view, rot, loc in (("front", (90, 0, 0), (0, -200, 35)), ("side", (90, 0, 90), (200, 0, 35))):
        cam.rotation_euler = Euler([math.radians(x) for x in rot])
        cam.location = loc
        scene.camera = cam
        scene.render.filepath = f"{path}_{posed_label}_{view}.png"
        bpy.ops.render.render(write_still=True)
    for o in objs:
        (o.parent or o).location.x = 0
    bpy.context.view_layer.update()


def verdict(r, ref, height):
    fails = []
    if r["max_weights_per_vertex"] > 3:
        fails.append("more than 3 weights per vertex")
    if r["flipped_normals_pct"] > ref["flipped_normals_pct"] + 0.1:
        fails.append(f"flipped normals {r['flipped_normals_pct']}% > ref+0.1")
    for state in ("rest", "posed"):
        p99 = max(r[state]["lod_to_ref"]["p99"], r[state]["ref_to_lod"]["p99"])
        if p99 > 0.012 * height:
            fails.append(f"surface distance {state} p99 {p99} > 1.2 % of height")
    for mat, ratio in r["area_ratio"].items():
        if not 0.93 <= ratio <= 1.07:
            fails.append(f"area {mat} x{ratio}")
    return fails


def main():
    a = args()
    os.makedirs(a.out, exist_ok=True)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    ref, ref_arm = load(a.ref)
    ref_areas = mat_areas(ref)
    report = {"ref": {"file": a.ref, "tris": len(ref.data.polygons), "areas": ref_areas,
                      "flipped_normals_pct": flipped_normals(a.ref),
                      "symmetry": symmetry(ref), "bbox": [list(ref.bound_box[0]), list(ref.bound_box[6])]}}
    loaded = []
    for path in a.files:
        ob, arm = load(path)
        loaded.append((path, ob, arm))
        r = {"tris": len(ob.data.polygons), "max_weights_per_vertex": max_weights(path),
             "flipped_normals_pct": flipped_normals(path),
             "areas": mat_areas(ob), "symmetry": symmetry(ob),
             "bbox": [list(ob.bound_box[0]), list(ob.bound_box[6])]}
        r["area_ratio"] = {k: round(r["areas"].get(k, 0) / v, 3) for k, v in ref_areas.items()}
        for posed in (False, True):
            set_pose(ref_arm, posed)
            set_pose(arm, posed)
            r["posed" if posed else "rest"] = compare(ob, ref)
        set_pose(arm, False)
        set_pose(ref_arm, False)
        r["failures"] = verdict(r, report["ref"], ref.dimensions.z)
        r["verdict"] = "PASS" if not r["failures"] else "FAIL"
        key = os.path.join(os.path.basename(os.path.dirname(path)), os.path.basename(path))
        report[key] = r
        print("VALID", key, json.dumps(r))
    objs = [ref] + [ob for _, ob, _ in loaded]
    for posed in (False, True):
        for o in [ref_arm] + [arm for _, _, arm in loaded]:
            set_pose(o, posed)
        render(objs, os.path.join(a.out, "render"), "posed" if posed else "rest", a.px)
    with open(os.path.join(a.out, "validation.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    for k, r in report.items():
        if k != "ref":
            print(f"VERDICT {k} {r['verdict']} {r['failures']}")


main()
