"""SMD input/output inside Blender (Blender Source Tools for import, own writer validated by round trip).

On export, the skeleton (nodes + skeleton blocks) of a reference .smd is copied verbatim:
mesh vertex groups are bound to bones by name.
"""
import os

import bpy


def read_header(path):
    lines, nodes, parents, section = [], {}, {}, None
    for line in open(path, encoding="latin-1"):
        s = line.strip()
        if s == "triangles":
            break
        lines.append(line.rstrip("\n"))
        if section is None and s in ("nodes", "skeleton"):
            section = s
        elif s == "end":
            section = None
        elif section == "nodes":
            p = s.split('"')
            nodes[p[1]] = int(p[0])
            parents[p[1]] = int(p[2])
    return "\n".join(lines) + "\n", nodes, parents


def import_smd(path, clear=True):
    if clear:
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.smd(filepath=path, append="NEW_ARMATURE")
    new = set(bpy.data.objects) - before
    for ob in [o for o in new if o.name.startswith("smd_bone_vis")]:
        new.discard(ob)
        bpy.data.objects.remove(ob)
    return next(o for o in new if o.type == "MESH")


def duplicate(ob, name):
    new = ob.copy()
    new.data = ob.data.copy()
    new.name = new.data.name = name
    bpy.context.scene.collection.objects.link(new)
    return new


def apply_modifier(ob, mod):
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
        bpy.ops.object.modifier_apply(modifier=mod.name)


def vertex_weights(ob, nodes, remap=None, max_w=3):
    names = {g.index: g.name for g in ob.vertex_groups}
    out, unweighted = [], 0
    for v in ob.data.vertices:
        acc = {}
        for g in v.groups:
            if g.weight <= 0.0001 or names[g.group] not in nodes:
                continue
            b = names[g.group]
            if remap:
                b = remap[b]
            acc[nodes[b]] = acc.get(nodes[b], 0) + g.weight
        w = sorted(acc.items(), key=lambda x: -x[1])[:max_w]
        if not w:
            unweighted += 1
            w = [(nodes.get("Spine1", 0), 1.0)]
        total = sum(x for _, x in w)
        out.append([(b, x / total) for b, x in w])
    return out, unweighted


def write_smd(ob, path, header, nodes, remap=None, max_w=3, material_map=None):
    """material_map: Blender material name -> SMD material name (default: Blender name)."""
    me = ob.data
    me.calc_loop_triangles()
    weights, unweighted = vertex_weights(ob, nodes, remap, max_w)
    uv = me.uv_layers.active.data
    normals = me.corner_normals
    mats = [m.name if m else "default" for m in me.materials] or ["default"]
    if material_map:
        mats = [material_map.get(m, m) for m in mats]
    with open(path, "w", encoding="latin-1", newline="\n") as f:
        f.write(header)
        f.write("triangles\n")
        for t in me.loop_triangles:
            f.write(mats[t.material_index] + "\n")
            for li, vi in zip(t.loops, t.vertices):
                co, n, u = me.vertices[vi].co, normals[li].vector, uv[li].uv
                w = weights[vi]
                ws = " ".join(f"{b} {x:.6f}" for b, x in w)
                f.write(f"{w[0][0]} {co.x:.6f} {co.y:.6f} {co.z:.6f} {n.x:.6f} {n.y:.6f} {n.z:.6f} "
                        f"{u.x:.6f} {u.y:.6f} {len(w)} {ws}\n")
        f.write("end\n")
    return {"file": os.path.basename(path), "tris": len(me.loop_triangles),
            "verts": len(me.vertices), "unweighted": unweighted}


def phys_remap(nodes, parents, keep):
    by_index = {i: n for n, i in nodes.items()}
    remap = {}
    for name in nodes:
        cur = name
        while cur not in keep and parents[cur] >= 0:
            cur = by_index[parents[cur]]
        remap[name] = cur if cur in keep else keep[0]
    return remap
