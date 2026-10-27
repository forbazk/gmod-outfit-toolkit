"""Validate the skinning of an outfit .smd by posing it (walk, run, crouch, arms up, twist).

Per pose: edge stretch (posed length / rest length) p01, p99, max + where (dominant bone),
and the bones holding the most compressed / stretched edges.
Static checks: <= 3 weights per vertex, no unweighted vertex.
Renders: <out>/pose_<name>_{front,side}.png.

Verdict is relative to a reference outfit known to work in game
(default tests/fixtures/reference_poses.json). Per pose, FAIL when
  max > max(ref_max * 1.25, 3.0)                         (tearing, broken weights)
  p99 > ref_p99 * 1.15 + 0.05                            (overall stretch)
  severe_stretch_pct > max(ref * 1.5, 0.5)               (edges stretched beyond 180 %)
  severe_compression_pct > ref + 1.0                     (edges squashed below 40 %)
p01 is reported but not judged: whole-mesh percentiles depend on the garment's composition
(trousers that are half of a small mesh fail p01 while folding exactly like a validated outfit).

Usage: blender -b --python validate_poses.py -- --smd outfit.smd --out folder [--px 700]
       [--reference ref.json] [--write-reference ref.json] [--no-render]
"""
import argparse
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smd_blender as S  # noqa: E402

REFERENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "fixtures",
                         "reference_poses.json")
X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
# world-space rotations (character faces -Y, +X = its left). (bone, axis, degrees), applied in order
POSES = {
    "walk": [("LeftUpLeg", X, -35), ("LeftLeg", X, 30), ("RightUpLeg", X, 25), ("RightLeg", X, 10),
             ("LeftArm", X, 20), ("RightArm", X, -20)],
    "run": [("LeftUpLeg", X, -65), ("LeftLeg", X, 75), ("RightUpLeg", X, 35), ("RightLeg", X, 60),
            ("LeftArm", X, 45), ("RightArm", X, -45), ("LeftForeArm", X, -60), ("RightForeArm", X, -60)],
    "crouch": [("LeftUpLeg", X, -85), ("RightUpLeg", X, -85), ("LeftLeg", X, 110), ("RightLeg", X, 110),
               ("Spine", X, -15)],
    "arms_up": [("LeftArm", Y, -75), ("RightArm", Y, 75), ("LeftForeArm", Y, -30), ("RightForeArm", Y, 30)],
    "twist": [("Spine", Z, 20), ("Spine1", Z, 20), ("Head", Z, 35), ("LeftArm", Z, -40), ("RightArm", Z, -40)],
}


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--smd", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--px", type=int, default=700)
    p.add_argument("--reference", default=REFERENCE)
    p.add_argument("--write-reference")
    p.add_argument("--no-render", action="store_true")
    return p.parse_args(sys.argv[sys.argv.index("--") + 1:])


def rotate_world(arm, bone, axis, deg):
    if bone not in arm.pose.bones:
        return
    bpy.context.view_layer.update()
    pb = arm.pose.bones[bone]
    pivot = pb.matrix.translation.copy()
    r = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-pivot)
    pb.matrix = r @ pb.matrix
    bpy.context.view_layer.update()


def reset(arm):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()


def posed_coords(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    co = [ob.matrix_world @ v.co for v in me.vertices]
    ev.to_mesh_clear()
    return co


def dominant(ob, vi):
    names = {g.index: g.name for g in ob.vertex_groups}
    gs = ob.data.vertices[vi].groups
    return names[max(gs, key=lambda g: g.weight).group] if len(gs) else "?"


def stretch(ob, rest, posed):
    ratios = []
    for e in ob.data.edges:
        a, b = e.vertices
        l0 = (rest[a] - rest[b]).length
        if l0 < 1e-4:
            continue
        ratios.append(((posed[a] - posed[b]).length / l0, a))
    ratios.sort()
    n = len(ratios)
    worst = ratios[-1]

    def zones(sample):
        acc = {}
        for _, vi in sample:
            b = dominant(ob, vi)
            acc[b] = acc.get(b, 0) + 1
        return dict(sorted(acc.items(), key=lambda x: -x[1])[:4])
    return {"severe_compression_pct": round(100 * sum(1 for r, _ in ratios if r < 0.4) / n, 3),
            "severe_stretch_pct": round(100 * sum(1 for r, _ in ratios if r > 1.8) / n, 3),
            "p01": round(ratios[int(n * 0.01)][0], 3), "p99": round(ratios[int(n * 0.99)][0], 3),
            "max": round(worst[0], 3), "max_bone": dominant(ob, worst[1]),
            "max_pos": [round(x, 1) for x in rest[worst[1]]], "min": round(ratios[0][0], 3),
            "compression_zones": zones(ratios[:max(1, n // 100)]),
            "stretch_zones": zones(ratios[-max(1, n // 100):])}


def static_checks(ob, path):
    unweighted = sum(1 for v in ob.data.vertices if not any(g.weight > 1e-4 for g in v.groups))
    smd_max = 0
    section = False
    for line in open(path, encoding="latin-1"):
        s = line.split()
        if s and s[0] == "triangles":
            section = True
        elif section and len(s) > 9:
            smd_max = max(smd_max, int(s[9]))
    return {"max_weights_per_vertex": smd_max, "unweighted": unweighted}


def render(out, name, px):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_cavity = True
    scene.render.resolution_x, scene.render.resolution_y = px, int(px * 1.25)
    cam = bpy.data.objects.get("cam_valid")
    if cam is None:
        cd = bpy.data.cameras.new("cam_valid")
        cd.type = "ORTHO"
        cd.ortho_scale = 80
        cam = bpy.data.objects.new("cam_valid", cd)
        scene.collection.objects.link(cam)
    scene.camera = cam
    for view, rot, loc in (("front", (90, 0, 0), (0, -200, 34)), ("side", (90, 0, 90), (200, 0, 34))):
        cam.rotation_euler = [math.radians(a) for a in rot]
        cam.location = loc
        scene.render.filepath = os.path.join(out, f"pose_{name}_{view}.png")
        bpy.ops.render.render(write_still=True)


def main():
    a = args()
    os.makedirs(a.out, exist_ok=True)
    ob = S.import_smd(a.smd)
    arm = ob.parent
    rest = [ob.matrix_world @ v.co for v in ob.data.vertices]
    report = {"tris": sum(len(p.vertices) - 2 for p in ob.data.polygons)}
    report.update(static_checks(ob, a.smd))
    failures = []
    if report["max_weights_per_vertex"] > 3:
        failures.append("more than 3 weights per vertex")
    if report["unweighted"]:
        failures.append(f"{report['unweighted']} unweighted vertices")
    ref = None
    if not a.write_reference:
        with open(a.reference, encoding="utf-8") as f:
            ref = json.load(f)["poses"]
    report["poses"] = {}
    for name, ops in POSES.items():
        reset(arm)
        for bone, axis, deg in ops:
            rotate_world(arm, bone, axis, deg)
        st = stretch(ob, rest, posed_coords(ob))
        report["poses"][name] = st
        print("POSE", name, json.dumps(st))
        if ref:
            r = ref[name]
            if st["max"] > max(r["max"] * 1.25, 3.0):
                failures.append(f"{name}: stretch max {st['max']} (ref {r['max']}) {st['max_bone']} {st['max_pos']}")
            if st["p99"] > r["p99"] * 1.15 + 0.05:
                failures.append(f"{name}: stretch p99 {st['p99']} (ref {r['p99']})")
            if st["severe_stretch_pct"] > max(r["severe_stretch_pct"] * 1.5, 0.5):
                failures.append(f"{name}: severe stretch {st['severe_stretch_pct']} % "
                                f"(ref {r['severe_stretch_pct']} %)")
            if st["severe_compression_pct"] > r["severe_compression_pct"] + 1.0:
                failures.append(f"{name}: severe compression {st['severe_compression_pct']} % "
                                f"(ref {r['severe_compression_pct']} %)")
        if not a.no_render:
            render(a.out, name, a.px)
    reset(arm)
    report["failures"] = failures
    report["verdict"] = "PASS" if not failures else "FAIL"
    with open(os.path.join(a.out, "pose_validation.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    if a.write_reference:
        with open(a.write_reference, "w", encoding="utf-8") as f:
            json.dump({"poses": {k: {m: v[m] for m in ("p01", "p99", "max", "severe_stretch_pct",
                                                       "severe_compression_pct")}
                                 for k, v in report["poses"].items()}}, f, indent=1)
        print("REFERENCE written", a.write_reference)
        return
    print("VERDICT", report["verdict"], failures)


main()
