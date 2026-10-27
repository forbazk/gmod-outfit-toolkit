"""Example garment built with tailor.py: tunic, collar, sleeves, belt, wide trousers, boots.

Needs a reference .smd whose skeleton uses Mixamo-style bone names (Hips, Spine, Spine1, Neck,
Left/RightArm, Left/RightForeArm, Left/RightHand, Left/RightUpLeg, Left/RightLeg, Left/RightFoot).
The output .smd reuses that skeleton verbatim.

Usage: blender -b --python example_robe.py -- --skeleton reference.smd --out folder [--render]
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import smd_blender as S  # noqa: E402
import tailor as T  # noqa: E402

X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
COLORS = {"cloth": (0.25, 0.35, 0.6), "trim": (0.85, 0.75, 0.45), "dark": (0.08, 0.08, 0.1)}
# full chains including twist ("Bend") bones; missing bones are skipped (see chain())
ARM = ["LeftArm", "LeftArmBend2", "LeftArmBend3", "LeftForeArmBend1", "LeftForeArmBend2", "LeftForeArmBend3",
       "LeftHand"]
LEG = ["LeftUpLeg", "LeftUpLegBend01", "LeftUpLegBend02", "LeftLeg", "LeftLegBend01", "LeftLegBend02",
       "LeftLegBend03", "LeftFoot"]


def chain(rig, bones):
    return [b for b in bones if b in rig.bones]


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--skeleton", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--render", action="store_true")
    return p.parse_args(sys.argv[sys.argv.index("--") + 1:])


def M(name):
    return T.material(name, COLORS[name])


def heights(rig):
    hips, neck = rig.p("Hips").z, rig.p("Neck").z
    return hips, neck, rig.p("LeftArm")


def tunic(rig):
    hips, neck, shoulder = heights(rig)
    half = abs(shoulder.x) + 1.2
    prof = [(hips + 1.5, half * 0.85, 4.3), (hips + 5, half * 0.8, 4.0), (hips + 9, half * 0.85, 4.1),
            (hips + 14, half * 0.95, 4.4), (neck - 2.5, half * 1.05, 4.2), (neck - 0.9, half * 0.85, 3.8),
            (neck, 4.4, 3.4)]
    rings = [T.Ring(Vector((0, 0.3, z)), (X, Y), rx, ry,
                    T.along_bones(rig, ["Hips", "Spine", "Spine1", "Neck"], Vector((0, 0, z))), p=2.3)
             for z, rx, ry in prof]
    return T.loft("tunic", rings, 32, M("cloth"))


def collar(rig):
    _, neck, _ = heights(rig)
    rings = [T.Ring(Vector((0, 0.35, z)), (X, Y), r, r * 0.95,
                    T.along_bones(rig, ["Spine1", "Neck", "Head"], Vector((0, 0, z))))
             for z, r in ((neck - 1.2, 4.3), (neck + 0.6, 4.0), (neck + 2.4, 3.8))]
    # thickness gives the collar an inner surface (visible from above when no head covers it)
    return T.solidify(T.loft("collar", rings, 18, M("trim")), 0.15)


def belt(rig):
    hips, _, _ = heights(rig)
    rings = [T.Ring(Vector((0, 0.2, z)), (X, Y), 6.9, 4.8, {"Spine": 0.5, "Hips": 0.5}, p=2.4)
             for z in (hips + 2.5, hips + 4.5)]
    return T.loft("belt", rings, 32, M("dark"))


def sleeve(rig):
    s, e, w = rig.p("LeftArm"), rig.p("LeftForeArm"), rig.p("LeftHand")
    pts = T.resample([s - (e - s).normalized() * 1.0, e, w], 12)
    radii = [2.3 - 0.8 * k / 11 for k in range(12)]
    bones = chain(rig, ARM)
    return T.tube("sleeve_L", pts, radii, 14, M("cloth"), lambda i, t: T.along_bones(rig, bones, pts[i]))


def trouser_leg(rig):
    hips = rig.p("Hips").z
    foot = rig.p("LeftFoot")
    prof = []
    # dense rings (17) so knee bends spread over several edges instead of folding one
    for k in range(17):
        f = k / 16
        z = hips + 3 - (hips + 3 - (foot.z + 2)) * f
        cx = 3.0 + (foot.x - 3.0) * f
        prof.append((z, cx, 3.8 + 2.4 * f, 4.7 + 2.0 * f, min(0.9, 0.2 + 0.9 * f)))
    rings = []
    bones = chain(rig, LEG)
    for z, cx, rx, ry, lw in prof:
        w = T.mix((1 - lw, {"Hips": 1.0}), (lw, T.along_bones(rig, bones, Vector((cx, 0, z)))))
        p = 2.2 + 2.6 * max(0.0, (z - (hips - 8)) / 11)
        rings.append(T.Ring(Vector((cx, 0.3, z)), (X, Y), rx, ry, w, p=p))
    ob = T.loft("trousers_L", rings, 36, M("cloth"))
    for v in ob.data.vertices:
        if v.co.z > hips - 8 and v.co.x < -0.25:
            v.co.x = -0.25
    return T.solidify(ob, 0.18)


def boot(rig):
    foot, leg = rig.p("LeftFoot"), rig.p("LeftLeg")
    path = T.resample([foot.lerp(leg, 0.3), foot + Vector((0, -1.0, -2.0)), foot + Vector((0, -5.5, -3.0))], 6)
    return T.tube("boot_L", path, [1.8, 1.8, 1.9, 1.8, 1.4, 0.9], 14, M("dark"),
                  lambda i, t: {"LeftFoot": 1.0} if t < 0.6 else {"LeftToeBase": 1.0}
                  if "LeftToeBase" in rig.bones else {"LeftFoot": 1.0}, cap_end=True)


def build(skeleton):
    ref = S.import_smd(skeleton)
    arm = ref.parent
    rig = T.Rig(arm)
    left = [sleeve(rig), trouser_leg(rig), boot(rig)]
    center = [tunic(rig), collar(rig), belt(rig)]
    right = [T.mirror(o) for o in left]
    bpy.data.objects.remove(ref)
    pieces = left + right + center
    for o in pieces:
        for m in list(o.modifiers):
            o.modifiers.remove(m)
    robe = T.join(pieces, "example_robe")
    robe.parent = arm
    mod = robe.modifiers.new("arm", "ARMATURE")
    mod.object = arm
    T.smooth(robe, 50)
    return robe


def render(out):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x, scene.render.resolution_y = 700, 900
    cd = bpy.data.cameras.new("cam")
    cd.type = "ORTHO"
    cd.ortho_scale = 76
    cam = bpy.data.objects.new("cam", cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    for view, rot, loc in (("front", (90, 0, 0), (0, -200, 34)), ("side", (90, 0, 90), (200, 0, 34))):
        cam.rotation_euler = [math.radians(a) for a in rot]
        cam.location = loc
        scene.render.filepath = os.path.join(out, f"example_robe_{view}.png")
        bpy.ops.render.render(write_still=True)


def main():
    a = args()
    os.makedirs(a.out, exist_ok=True)
    robe = build(a.skeleton)
    header, nodes, _ = S.read_header(a.skeleton)
    info = S.write_smd(robe, os.path.join(a.out, "example_robe.smd"), header, nodes)
    print("EXAMPLE", info)
    if a.render:
        render(a.out)


main()
