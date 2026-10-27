"""Build a healthy and a broken .blend from a skinned .smd (Blender Source Tools required).

Usage: blender -b --python make_blends.py -- reference.smd output_folder
  good.blend: the imported outfit, a 1024x1024 image texture saved next to it
  bad.blend : armature scaled x2, 50 vertices unweighted, a stray vertex group,
              a material pointing to a missing image, 5 vertices with 4 influences
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import smd_blender as S  # noqa: E402


def textured(ob, img):
    for mat in ob.data.materials:
        mat.use_nodes = True
        node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = img


def main():
    smd, out = sys.argv[-2], sys.argv[-1]
    os.makedirs(out, exist_ok=True)
    ob = S.import_smd(smd)
    img = bpy.data.images.new("tex", 1024, 1024)
    img.filepath_raw = os.path.join(out, "tex.png")
    img.file_format = "PNG"
    img.save()
    textured(ob, img)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "good.blend"))
    arm = ob.parent
    arm.scale = (2, 2, 2)
    for v in list(ob.data.vertices)[:50]:
        for g in list(v.groups):
            ob.vertex_groups[g.group].remove([v.index])
    ob.vertex_groups.new(name="NotABone").add([100], 1.0, "REPLACE")
    names = [g.name for g in ob.vertex_groups if g.name != "NotABone"][:4]
    for vi in range(200, 205):
        for n in names:
            ob.vertex_groups[n].add([vi], 0.25, "REPLACE")
    lost = bpy.data.images.new("lost", 64, 64)
    lost.filepath = os.path.join(out, "does_not_exist.png")
    lost.source = "FILE"
    mat = bpy.data.materials.new("lost_mat")
    mat.use_nodes = True
    mat.node_tree.nodes.new("ShaderNodeTexImage").image = lost
    ob.data.materials.append(mat)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "bad.blend"))
    print("blends written to", out)


main()
