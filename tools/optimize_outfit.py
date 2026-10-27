"""Decimation + LODs + physics mesh for an outfit .smd, inside Blender (Blender Source Tools required).

Usage:
  blender -b --python optimize_outfit.py -- --smd outfit.smd --out folder
          [--tris 20000,10000,5000,2500] [--phys 1500] [--phys-bones Hips,Spine,...]
          [--normals smooth|decimate|nearest|lnorproj] [--min-weight 0.02]
  --tris 0: round trip without decimation (exporter test)

Outputs: <name>.smd (LOD0), <name>_lod1..n.smd, <name>_phys.smd, report.json
The skeleton (nodes + skeleton) is copied verbatim from the source .smd.
"""
import argparse
import json
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smd_blender import apply_modifier, duplicate, import_smd, phys_remap, read_header, write_smd  # noqa: E402


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--smd", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--tris", default="20000,10000,5000,2500")
    p.add_argument("--phys", type=int, default=1500)
    p.add_argument("--phys-bones", default="")
    # "smooth" validated: 0.01 % flipped normals. nearest/lnorproj transfer picks the back side of
    # multi-layer cloth (1.6 % flipped -> dark patches); decimate leaves darkened skirt hems.
    p.add_argument("--normals", default="smooth", choices=["smooth", "decimate", "nearest", "lnorproj"])
    # influences under 2 % are invisible but still count in bones per vertex / per hardware batch
    p.add_argument("--min-weight", type=float, default=0.0, help="drop bone influences below this fraction")
    return p.parse_args(sys.argv[sys.argv.index("--") + 1:])


def decimate(ob, src, target, normals):
    current = sum(len(p.vertices) - 2 for p in ob.data.polygons)
    if target and target < current:
        mod = ob.modifiers.new("dec", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = target / current
        mod.use_symmetry = True
        mod.symmetry_axis = "X"
        apply_modifier(ob, mod)
        if normals in ("nearest", "lnorproj"):
            dt = ob.modifiers.new("nrm", "DATA_TRANSFER")
            dt.object = src
            dt.use_loop_data = True
            dt.data_types_loops = {"CUSTOM_NORMAL"}
            dt.loop_mapping = "POLYINTERP_NEAREST" if normals == "nearest" else "POLYINTERP_LNORPROJ"
            apply_modifier(ob, dt)
        elif normals == "smooth":
            with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                           selected_editable_objects=[ob]):
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
                bpy.ops.object.shade_smooth_by_angle(angle=math.radians(60))


def main():
    a = args()
    os.makedirs(a.out, exist_ok=True)
    header, nodes, parents = read_header(a.smd)
    src = import_smd(a.smd)
    name = os.path.splitext(os.path.basename(a.smd))[0]
    for m in list(src.modifiers):
        src.modifiers.remove(m)
    targets = [int(x) for x in a.tris.split(",")]
    report = {"source": a.smd, "lods": []}
    for k, target in enumerate(targets):
        ob = duplicate(src, f"{name}_lod{k}")
        decimate(ob, src, target, a.normals)
        fname = f"{name}.smd" if k == 0 else f"{name}_lod{k}.smd"
        report["lods"].append(write_smd(ob, os.path.join(a.out, fname), header, nodes, min_w=a.min_weight))
        print("LOD", report["lods"][-1])
    if a.phys_bones and a.phys:
        keep = a.phys_bones.split(",")
        ob = duplicate(src, f"{name}_phys")
        decimate(ob, src, a.phys, "smooth")
        report["phys"] = write_smd(ob, os.path.join(a.out, f"{name}_phys.smd"), header, nodes,
                                   remap=phys_remap(nodes, parents, keep), max_w=1)
        print("PHYS", report["phys"])
    with open(os.path.join(a.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)


main()
