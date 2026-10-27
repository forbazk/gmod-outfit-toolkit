"""Procedural tailoring of garments around a Source skeleton, inside Blender.

A piece is a "loft": a sequence of rings (cross-sections) along a path. Each ring carries its
shape (ellipse / superellipse, angular opening, bumps), its UVs (u = around, v = along) and its
bone weights. The resulting mesh exports directly with smd_blender.write_smd.

Axes of the target rig: +X = character's left, -Y = front, +Z = up.
"""
import math

import bmesh
import bpy
from mathutils import Vector

SWAP = (("Left", "Right"), ("L_", "R_"))


class Rig:
    """Rest positions of the bones (world space) read from an armature imported by BST."""

    def __init__(self, armature):
        self.arm = armature
        self.bones = {}
        for b in armature.data.bones:
            self.bones[b.name] = (armature.matrix_world @ b.head_local, armature.matrix_world @ b.tail_local)

    def p(self, name):
        return self.bones[name][0].copy()


def along_bones(rig, bones, pt):
    """Weights by projecting pt on the chain of bone heads (interpolated between neighbours)."""
    heads = [rig.p(b) for b in bones]
    if len(heads) == 1:
        return {bones[0]: 1.0}
    best = None
    for k in range(len(heads) - 1):
        a, b = heads[k], heads[k + 1]
        ab = b - a
        s = max(0.0, min(1.0, (pt - a).dot(ab) / ab.length_squared)) if ab.length_squared > 1e-9 else 0.0
        d = (a + ab * s - pt).length
        if best is None or d < best[0]:
            best = (d, k, s)
    _, k, s = best
    w = {bones[k]: 1 - s, bones[k + 1]: s}
    return {b: x for b, x in w.items() if x > 0.001}


def mix(*pairs):
    """mix((0.3, weights_a), (0.7, weights_b)) -> blended weight dict."""
    out = {}
    for f, w in pairs:
        for b, x in w.items():
            out[b] = out.get(b, 0) + f * x
    return out


def mirror_name(name):
    for a, b in SWAP:
        if a in name:
            return name.replace(a, b)
        if b in name:
            return name.replace(b, a)
    return name


def frame_along(points, up=Vector((0, 0, 1))):
    """Frames (tangent, a, b) along a polyline, by parallel transport."""
    frames = []
    prev_a = None
    for i, p in enumerate(points):
        t = (points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]).normalized()
        if prev_a is None:
            a = up.cross(t)
            if a.length < 1e-4:
                a = Vector((0, -1, 0)).cross(t)
            a.normalize()
        else:
            a = (prev_a - t * prev_a.dot(t)).normalized()
        b = t.cross(a).normalized()
        frames.append((t, a, b))
        prev_a = a
    return frames


def superellipse(theta, rx, ry, p=2.0):
    c, s = math.cos(theta), math.sin(theta)
    x = math.copysign(abs(c) ** (2 / p), c) * rx
    y = math.copysign(abs(s) ** (2 / p), s) * ry
    return x, y


class Ring:
    """Cross-section of a piece.

    center: Vector; axes: (A, B) unit vectors spanning the ring plane
    rx, ry: radii along A and B; p: superellipse exponent (2 = ellipse, 6+ = rounded rectangle)
    bump(theta) -> radius multiplier (pleats, bulges); weights: {bone: weight}
    """

    def __init__(self, center, axes, rx, ry, weights, p=2.0, bump=None):
        self.center, self.axes = center, axes
        self.rx, self.ry, self.p = rx, ry, p
        self.weights, self.bump = weights, bump

    def point(self, theta):
        x, y = superellipse(theta, self.rx, self.ry, self.p)
        k = self.bump(theta) if self.bump else 1.0
        return self.center + self.axes[0] * (x * k) + self.axes[1] * (y * k)


def loft(name, rings, segments, material, uv_rect=(0, 0, 1, 1), closed=True, arc=(0.0, 2 * math.pi),
         cap_start=False, cap_end=False, flip=False):
    """Build a mesh from rings. arc = angular range when closed=False.

    UVs: u around (arc), v along the cumulative length, remapped into uv_rect (u0, v0, u1, v1).
    Faces are wound so normals point outward (flip for inward). Caps point away from the piece.
    """
    me = bpy.data.meshes.new(name)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    deform = bm.verts.layers.deform.verify()
    n_cols = segments if closed else segments + 1
    thetas = [arc[0] + (arc[1] - arc[0]) * j / segments for j in range(n_cols)]
    groups = {}
    lengths = [0.0]
    for i in range(1, len(rings)):
        lengths.append(lengths[-1] + (rings[i].center - rings[i - 1].center).length)
    total = lengths[-1] or 1.0
    grid = []
    for ring in rings:
        row = []
        for th in thetas:
            v = bm.verts.new(ring.point(th))
            for bone, w in ring.weights.items():
                if w <= 0:
                    continue
                if bone not in groups:
                    groups[bone] = ob.vertex_groups.new(name=bone).index
                v[deform][groups[bone]] = w
            row.append(v)
        grid.append(row)
    u0, v0, u1, v1 = uv_rect
    for i in range(len(rings) - 1):
        for j in range(segments):
            jn = (j + 1) % n_cols if closed else j + 1
            quad = [grid[i][j], grid[i][jn], grid[i + 1][jn], grid[i + 1][j]]
            uvs = [(j, i), (j + 1, i), (j + 1, i + 1), (j, i + 1)]
            if flip:
                quad.reverse()
                uvs.reverse()
            f = bm.faces.new(quad)
            f.material_index = 0
            for loop, (jj, ii) in zip(f.loops, uvs):
                loop[uv_layer].uv = (u0 + (u1 - u0) * jj / segments, v0 + (v1 - v0) * lengths[ii] / total)
    bm.normal_update()
    bm.faces.ensure_lookup_table()
    # orientation: the first face must point away from the center of its ring
    f0 = bm.faces[0]
    outward = f0.calc_center_median() - rings[0].center
    if (f0.normal.dot(outward) < 0) != flip:
        for f in bm.faces:
            f.normal_flip()
    # caps: normal along the piece's extension (outward, or inward when flip)
    for cap, idx, nxt in ((cap_start, 0, 1), (cap_end, len(rings) - 1, len(rings) - 2)):
        if cap and len(rings) > 1:
            f = bm.faces.new(grid[idx])
            f.normal_update()
            away = rings[idx].center - rings[nxt].center
            if (f.normal.dot(away) < 0) != flip:
                f.normal_flip()
            for loop in f.loops:
                loop[uv_layer].uv = (u0, v0)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material)
    return ob


def tube(name, path, radii, segments, material, weights_fn, up=Vector((0, 0, 1)), p=2.0, ry_scale=1.0,
         bump=None, **kw):
    """Tube along a polyline. radii: radius per point; weights_fn(i, t) -> {bone: weight}."""
    frames = frame_along(path, up)
    rings = []
    n = len(path)
    for i, (pt, (t, a, b)) in enumerate(zip(path, frames)):
        r = radii[i]
        rings.append(Ring(pt, (a, b), r, r * ry_scale, weights_fn(i, i / max(n - 1, 1)), p=p, bump=bump))
    return loft(name, rings, segments, material, **kw)


def resample(points, count):
    """Resample a polyline into `count` evenly spaced points."""
    lengths = [0.0]
    for i in range(1, len(points)):
        lengths.append(lengths[-1] + (points[i] - points[i - 1]).length)
    total = lengths[-1]
    out = []
    for k in range(count):
        d = total * k / (count - 1)
        i = max(j for j in range(len(points) - 1) if lengths[j] <= d + 1e-9) if d < total else len(points) - 2
        seg = lengths[i + 1] - lengths[i] or 1.0
        out.append(points[i].lerp(points[i + 1], (d - lengths[i]) / seg))
    return out


def chain_weights(t, stops):
    """Weights along a chain: stops = [(t, {bone: weight}), ...] sorted, linear interpolation."""
    if t <= stops[0][0]:
        return dict(stops[0][1])
    for (ta, wa), (tb, wb) in zip(stops, stops[1:]):
        if t <= tb:
            k = (t - ta) / ((tb - ta) or 1.0)
            out = {}
            for bone in set(wa) | set(wb):
                out[bone] = wa.get(bone, 0) * (1 - k) + wb.get(bone, 0) * k
            return out
    return dict(stops[-1][1])


def mirror(ob, name=None):
    """X-mirrored copy of a piece, Left<->Right vertex groups swapped, faces rewound."""
    new = ob.copy()
    new.data = ob.data.copy()
    new.name = new.data.name = name or mirror_name(ob.name)
    bpy.context.scene.collection.objects.link(new)
    bm = bmesh.new()
    bm.from_mesh(new.data)
    for v in bm.verts:
        v.co.x = -v.co.x
    for f in bm.faces:
        f.normal_flip()
    bm.to_mesh(new.data)
    bm.free()
    for g in new.vertex_groups:
        g.name = g.name + "__tmp"
    for g in new.vertex_groups:
        g.name = mirror_name(g.name[:-5])
    return new


def assign_rows(ob, rows, mat, segments):
    """Material on rows of faces of a loft (row i = between ring i and i+1).
    Call before solidify/join (loft faces are ordered row by row)."""
    if mat.name not in [m.name for m in ob.data.materials]:
        ob.data.materials.append(mat)
    idx = [m.name for m in ob.data.materials].index(mat.name)
    for p in ob.data.polygons:
        if p.index // segments in rows:
            p.material_index = idx


def assign_where(ob, test, mat):
    """Material on faces whose center satisfies test(Vector). Stair-stepped: preview only."""
    if mat.name not in [m.name for m in ob.data.materials]:
        ob.data.materials.append(mat)
    idx = [m.name for m in ob.data.materials].index(mat.name)
    for p in ob.data.polygons:
        if test(p.center):
            p.material_index = idx


def solidify(ob, thickness, offset=-1.0):
    mod = ob.modifiers.new("solid", "SOLIDIFY")
    mod.thickness = thickness
    mod.offset = offset
    mod.use_rim = True
    mod.use_even_offset = True
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return ob


def material(name, color):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1.0)
    return m


def join(objs, name):
    """Merge pieces into one object (materials and vertex groups merged by name)."""
    base = objs[0]
    with bpy.context.temp_override(active_object=base, object=base, selected_objects=objs,
                                   selected_editable_objects=objs):
        bpy.ops.object.join()
    base.name = base.data.name = name
    return base


def smooth(ob, angle=50):
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                   selected_editable_objects=[ob]):
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle))


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)
