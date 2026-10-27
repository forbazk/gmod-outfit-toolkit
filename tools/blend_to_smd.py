"""Export a skinned outfit from a .blend to a reference .smd (no Blender Source Tools needed).

Object transforms are baked (an unapplied scale or rotation no longer resizes the outfit in game),
non-armature modifiers are applied, faces are triangulated, weights are limited to 3 per vertex and
normalized. The skeleton comes from the armature's rest pose (world space).

Usage: blender -b file.blend --python blend_to_smd.py -- --out outfit.smd [--mesh name] [--armature name]
       [--min-weight 0.0]
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smd_blender import vertex_weights  # noqa: E402


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--mesh", action="append")
    p.add_argument("--armature")
    p.add_argument("--min-weight", type=float, default=0.0)
    return p.parse_args(sys.argv[sys.argv.index("--") + 1:])


def skeleton(arm):
    bones = list(arm.data.bones)
    order, seen = [], set()

    def visit(b):
        if b.name in seen:
            return
        if b.parent:
            visit(b.parent)
        seen.add(b.name)
        order.append(b)
    for b in bones:
        visit(b)
    index = {b.name: i for i, b in enumerate(order)}
    lines = ["version 1", "nodes"]
    lines += [f'{index[b.name]} "{b.name}" {index[b.parent.name] if b.parent else -1}' for b in order]
    lines += ["end", "skeleton", "time 0"]
    for b in order:
        world = arm.matrix_world @ b.matrix_local
        local = (arm.matrix_world @ b.parent.matrix_local).inverted() @ world if b.parent else world
        loc, rot, _ = local.decompose()
        e = rot.to_matrix().to_euler("XYZ")
        lines.append(f"{index[b.name]} {loc.x:.6f} {loc.y:.6f} {loc.z:.6f} {e.x:.6f} {e.y:.6f} {e.z:.6f}")
    lines.append("end")
    return "\n".join(lines) + "\n", index


def main():
    a = args()
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    arm = bpy.data.objects[a.armature] if a.armature else arms[0]
    meshes = [bpy.data.objects[n] for n in a.mesh] if a.mesh else [
        o for o in bpy.data.objects if o.type == "MESH" and not o.name.startswith("smd_bone_vis")
        and (o.parent == arm or any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers))]
    header, index = skeleton(arm)
    for o in meshes:
        for m in o.modifiers:
            if m.type == "ARMATURE":
                m.show_viewport = False
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    out, total, unweighted = [], 0, 0
    for o in meshes:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh(preserve_all_data_layers=True, depsgraph=dg)
        me.calc_loop_triangles()
        mw = o.matrix_world
        nm = mw.to_3x3().inverted().transposed()
        tmp = type("O", (), {})()
        tmp.vertex_groups, tmp.data = o.vertex_groups, me
        weights, unw, _ = vertex_weights(tmp, index, max_w=3, min_w=a.min_weight)
        unweighted += unw
        uv = me.uv_layers.active.data if me.uv_layers.active else None
        mats = [m.name if m else "default" for m in me.materials] or ["default"]
        for t in me.loop_triangles:
            lines = []
            for li, vi in zip(t.loops, t.vertices):
                co = mw @ me.vertices[vi].co
                n = (nm @ me.corner_normals[li].vector).normalized()
                u = uv[li].uv if uv else (0.0, 0.0)
                w = weights[vi]
                ws = " ".join(f"{b} {x:.6f}" for b, x in w)
                lines.append(f"{w[0][0]} {co.x:.6f} {co.y:.6f} {co.z:.6f} {n.x:.6f} {n.y:.6f} {n.z:.6f} "
                             f"{u[0]:.6f} {u[1]:.6f} {len(w)} {ws}")
            out.append((mats[t.material_index], lines))
        total += len(me.loop_triangles)
        ev.to_mesh_clear()
    with open(a.out, "w", encoding="latin-1", newline="\n") as f:
        f.write(header + "triangles\n")
        for mat, lines in out:
            f.write(mat + "\n" + "\n".join(lines) + "\n")
        f.write("end\n")
    print(f"EXPORT {len(meshes)} mesh(es), {total} triangles, {len(index)} bones, {unweighted} unweighted "
          f"vertices -> {a.out}")
    sys.stdout.flush()
    os._exit(0)


main()
