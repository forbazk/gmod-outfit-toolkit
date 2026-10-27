"""Audit an outfit .blend before export: the mistakes that cost hours after compiling.

Checks: rig naming convention, unapplied armature/mesh transforms, meshes not skinned to the
armature, vertex groups that match no bone, unweighted vertices, more than 3 influences,
missing UV map, materials without texture, missing / oversized / non power of two images,
modifiers that will be baked at export, triangle budget.

Usage: blender -b file.blend --python blend_audit.py -- [--json out.json]
Prints one line per finding and "RESULT OK|FAIL" (FAIL when a critical/high finding exists,
i.e. something that breaks the model in game). Exit 0/1.
"""
import argparse
import json
import os
import sys

import bpy

ORDER = ["critical", "high", "medium", "low", "info"]


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--json")
    return p.parse_args(argv)


def convention(names):
    names = set(names)
    if any(n.startswith("ValveBiped.") for n in names):
        return "ValveBiped"
    if {"Hips", "Spine", "LeftArm", "RightUpLeg"} <= names:
        return "Mixamo-style"
    return "unknown"


def is_identity(ob, tol=1e-4):
    return (all(abs(s - 1) < tol for s in ob.scale) and all(abs(r) < tol for r in ob.rotation_euler)
            and ob.rotation_mode in ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"))


def main():
    a = args()
    findings = []

    def add(sev, obj, problem, fix):
        findings.append({"severity": sev, "object": obj, "problem": problem, "fix": fix})

    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and not o.name.startswith("smd_bone_vis")]
    report = {"file": bpy.data.filepath, "armatures": [], "meshes": []}
    if not arms:
        add("critical", "-", "no armature in the file", "the outfit must be skinned to the target rig")
    for arm in arms:
        conv = convention(b.name for b in arm.data.bones)
        report["armatures"].append({"name": arm.name, "bones": len(arm.data.bones), "convention": conv})
        if not is_identity(arm):
            add("high", arm.name, f"armature transform not applied (scale {tuple(round(s, 3) for s in arm.scale)}, "
                f"rotation {tuple(round(r, 3) for r in arm.rotation_euler)})",
                "Ctrl+A > All Transforms on the armature (and its meshes), or animations will be offset")
    total = 0
    for ob in meshes:
        me = ob.data
        tris = sum(len(p.vertices) - 2 for p in me.polygons)
        total += tris
        info = {"name": ob.name, "tris": tris, "verts": len(me.vertices), "materials": [m.name if m else None
                                                                                      for m in me.materials]}
        report["meshes"].append(info)
        arm_mod = next((m for m in ob.modifiers if m.type == "ARMATURE" and m.object), None)
        arm = arm_mod.object if arm_mod else (ob.parent if ob.parent and ob.parent.type == "ARMATURE" else None)
        if arm is None:
            add("high", ob.name, "mesh not skinned to any armature (no Armature modifier / parent)",
                "parent it to the armature with an Armature modifier")
        if not is_identity(ob):
            add("medium", ob.name, f"mesh transform not applied (scale {tuple(round(s, 3) for s in ob.scale)})",
                "Ctrl+A > All Transforms, otherwise size/orientation can differ in game")
        others = [m.type for m in ob.modifiers if m.type != "ARMATURE"]
        if others:
            add("low", ob.name, f"modifiers baked at export: {others}",
                "check the result looks right, or apply them before skinning")
        if not me.uv_layers:
            add("high", ob.name, "no UV map: textures cannot be applied", "unwrap the mesh")
        if arm is not None:
            bones = {b.name for b in arm.data.bones}
            groups = {g.index: g.name for g in ob.vertex_groups}
            stray = sorted(n for n in groups.values() if n not in bones)
            if stray:
                add("medium", ob.name, f"{len(stray)} vertex groups match no bone (ignored at export): {stray[:6]}",
                    "rename them to bone names or delete them")
            zero, over = 0, 0
            for v in me.vertices:
                n = sum(1 for g in v.groups if g.weight > 1e-4 and groups.get(g.group) in bones)
                zero += n == 0
                over += n > 3
            info["unweighted_verts"], info["verts_over_3_influences"] = zero, over
            if zero:
                add("high", ob.name, f"{zero} vertices without any bone weight (they stay frozen in place)",
                    "Weight Paint them, or Normalize All / auto weights")
            if over:
                add("medium", ob.name, f"{over} vertices with more than 3 bone influences (studiomdl keeps 3)",
                    "Weights > Limit Total (limit 3) then Normalize All")
        for mat in [m for m in me.materials if m]:
            imgs = []
            if mat.node_tree:
                imgs = [n.image for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
            if not imgs:
                add("low", ob.name, f"material '{mat.name}' has no image texture",
                    "assign the texture, unless the server ships this material (e.g. skin_color)")
            for img in imgs:
                path = bpy.path.abspath(img.filepath) if img.filepath else ""
                if not img.packed_file and (not path or not os.path.exists(path)):
                    add("high", ob.name, f"image '{img.name}' missing on disk ({img.filepath})",
                        "File > External Data > Find Missing Files, or pack the images")
                    continue
                w, h = img.size
                if w and h:
                    if max(w, h) > 2048:
                        add("medium", ob.name, f"image '{img.name}' is {w}x{h}", "2048 max for an outfit")
                    if w & (w - 1) or h & (h - 1):
                        add("medium", ob.name, f"image '{img.name}' is {w}x{h}, not a power of two",
                            "resize to a power of two before converting to VTF")
    report["tris_total"] = total
    # budget, not breakage: optimize_outfit.py can fix it after export, so never FAIL on it
    if total > 25000:
        add("medium", "-", f"{total:,} triangles in total",
            "aim for 15-20k: optimize_outfit.py decimates and builds LODs after export")
    findings.sort(key=lambda f: ORDER.index(f["severity"]))
    report["findings"] = findings
    for ar in report["armatures"]:
        print(f"ARMATURE {ar['name']}: {ar['bones']} bones, {ar['convention']}")
    print(f"MESHES {len(meshes)}, {total:,} triangles")
    for f in findings:
        print(f"FINDING {f['severity']:8} {f['object']}: {f['problem']} -> {f['fix']}")
    bad = any(f["severity"] in ("critical", "high") for f in findings)
    print("RESULT", "FAIL" if bad else "OK")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
    sys.stdout.flush()
    os._exit(1 if bad else 0)


main()
