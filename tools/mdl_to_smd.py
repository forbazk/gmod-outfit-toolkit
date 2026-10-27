"""Decompile a Source v48 .mdl (LOD0 meshes + QC data) without Crowbar.

Writes one reference .smd per bodypart model, plus info.json
(bones, attachments, hitboxes, sequences, bodyparts, cdmaterials...).

Usage: python mdl_to_smd.py file.mdl output_folder
"""
import json
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_mdl import cstr, i32, read_mdl  # noqa: E402


def f32s(d, off, n):
    return struct.unpack_from(f"<{n}f", d, off)


def matrix_angles(m):
    """Source 3x4 matrix -> (pitch, yaw, roll) in degrees (SDK MatrixAngles)."""
    fwd = (m[0][0], m[1][0], m[2][0])
    left = (m[0][1], m[1][1], m[2][1])
    up_z = m[2][2]
    xy = math.hypot(fwd[0], fwd[1])
    if xy > 0.001:
        yaw = math.degrees(math.atan2(fwd[1], fwd[0]))
        pitch = math.degrees(math.atan2(-fwd[2], xy))
        roll = math.degrees(math.atan2(left[2], up_z))
    else:
        yaw = math.degrees(math.atan2(-left[0], left[1]))
        pitch = math.degrees(math.atan2(-fwd[2], xy))
        roll = 0.0
    return pitch, yaw, roll


def read_extra(d, bones):
    na, ai = i32(d, 240), i32(d, 244)
    atts = []
    for k in range(na):
        o = ai + k * 92
        m = [f32s(d, o + 12 + r * 16, 4) for r in range(3)]
        atts.append({"name": cstr(d, o + i32(d, o)), "bone": bones[i32(d, o + 8)]["name"],
                     "pos": [m[0][3], m[1][3], m[2][3]], "angles": matrix_angles(m)})
    hsi = i32(d, 176)
    sets = []
    for k in range(i32(d, 172)):
        so = hsi + k * 12
        boxes = []
        n, bi = i32(d, so + 4), i32(d, so + 8)
        for b in range(n):
            bo = so + bi + b * 68
            boxes.append({"bone": bones[i32(d, bo)]["name"], "group": i32(d, bo + 4),
                          "min": f32s(d, bo + 8, 3), "max": f32s(d, bo + 20, 3)})
        sets.append({"name": cstr(d, so + i32(d, so)), "boxes": boxes})
    seqs = []
    sqi = i32(d, 192)
    for k in range(i32(d, 188)):
        o = sqi + k * 212
        seqs.append({"name": cstr(d, o + i32(d, o + 4)), "activity": cstr(d, o + i32(d, o + 8)),
                     "actweight": i32(d, o + 20)})
    return atts, sets, seqs


def bone_pose(d, bones):
    bi = i32(d, 160)
    out = []
    for k in range(len(bones)):
        o = bi + k * 216
        out.append((f32s(d, o + 32, 3), f32s(d, o + 60, 3)))
    return out


def read_vvd(path):
    d = open(path, "rb").read()
    n = i32(d, 16)
    start = i32(d, 56)
    if i32(d, 48):
        raise SystemExit("VVD with fixups (multi-LOD) is not supported")
    verts = []
    for k in range(n):
        o = start + k * 48
        w = f32s(d, o, 3)
        b = d[o + 12:o + 15]
        nb = d[o + 15]
        verts.append({"w": [(b[j], w[j]) for j in range(nb)], "pos": f32s(d, o + 16, 3),
                      "n": f32s(d, o + 28, 3), "uv": f32s(d, o + 40, 2)})
    return verts


def read_vtx_lod0(path):
    """-> [bodypart][model][mesh] = list of triangles (origMeshVertID x3)."""
    d = open(path, "rb").read()
    nbp, bpo = i32(d, 28), i32(d, 32)
    res = []
    for b in range(nbp):
        bo = bpo + b * 8
        models = []
        for m in range(i32(d, bo)):
            mo = bo + i32(d, bo + 4) + m * 8
            meshes = []
            if i32(d, mo) > 0:
                lo = mo + i32(d, mo + 4)
                for s in range(i32(d, lo)):
                    so = lo + i32(d, lo + 4) + s * 9
                    tris = []
                    for g in range(i32(d, so)):
                        go = so + i32(d, so + 4) + g * 25
                        nv, vo, ni, io = (i32(d, go + x) for x in (0, 4, 8, 12))
                        ids = [struct.unpack_from("<H", d, go + vo + v * 9 + 4)[0] for v in range(nv)]
                        idx = struct.unpack_from(f"<{ni}H", d, go + io)
                        for t in range(0, ni, 3):
                            # Source stores triangles with reversed winding
                            tris.append((ids[idx[t]], ids[idx[t + 2]], ids[idx[t + 1]]))
                    meshes.append(tris)
            models.append(meshes)
        res.append(models)
    return res


def write_smd(path, bones, pose, tris_by_mat, verts):
    with open(path, "w", encoding="latin-1", newline="\n") as f:
        f.write("version 1\nnodes\n")
        for k, b in enumerate(bones):
            f.write(f'{k} "{b["name"]}" {b["parent"]}\n')
        f.write("end\nskeleton\ntime 0\n")
        for k, (p, r) in enumerate(pose):
            f.write(f"{k} {p[0]:.6f} {p[1]:.6f} {p[2]:.6f} {r[0]:.6f} {r[1]:.6f} {r[2]:.6f}\n")
        f.write("end\ntriangles\n")
        for mat, tris in tris_by_mat:
            for tri in tris:
                f.write(mat + "\n")
                for vi in tri:
                    v = verts[vi]
                    p, n, uv = v["pos"], v["n"], v["uv"]
                    ws = " ".join(f"{bi} {w:.6f}" for bi, w in v["w"])
                    f.write(f"{v['w'][0][0]} {p[0]:.6f} {p[1]:.6f} {p[2]:.6f} {n[0]:.6f} {n[1]:.6f} "
                            f"{n[2]:.6f} {uv[0]:.6f} {1 - uv[1]:.6f} {len(v['w'])} {ws}\n")
        f.write("end\n")


def main():
    mdl, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    base = mdl[:-4]
    d = open(mdl, "rb").read()
    info = read_mdl(mdl)
    bones = info["bones"]
    pose = bone_pose(d, bones)
    verts = read_vvd(base + ".vvd")
    vtx = read_vtx_lod0(base + ".dx90.vtx")
    atts, sets, seqs = read_extra(d, bones)
    model_offset = {}
    bpi = i32(d, 236)
    for b in range(len(info["bodyparts"])):
        o = bpi + b * 16
        for m in range(i32(d, o + 4)):
            mo = o + i32(d, o + 12) + m * 148
            model_offset[(b, m)] = (i32(d, mo + 84) // 48,
                                    [i32(d, mo + i32(d, mo + 76) + s * 116 + 12) for s in range(i32(d, mo + 72))])
    textures, skin0 = info["textures"], info["skins"][0]
    bodyparts = []
    for b, bp in enumerate(info["bodyparts"]):
        entries = []
        for m, mo in enumerate(bp["models"]):
            if not mo["meshes"]:
                entries.append(None)
                continue
            vbase, mesh_off = model_offset[(b, m)]
            tris_by_mat = []
            for s, me in enumerate(mo["meshes"]):
                off = vbase + mesh_off[s]
                tris = [tuple(off + v for v in t) for t in vtx[b][m][s]]
                tris_by_mat.append((textures[skin0[me["material"]]], tris))
            name = os.path.splitext(mo["name"])[0] or f"{bp['name']}_{m}"
            write_smd(os.path.join(out, name + ".smd"), bones, pose, tris_by_mat, verts)
            n = sum(len(t) for _, t in tris_by_mat)
            print(f"{bp['name']}/{name}.smd: {n} tris")
            entries.append(name + ".smd")
        bodyparts.append({"name": bp["name"], "models": entries})
    info_out = {k: info[k] for k in ("name", "flags", "surfaceprop", "includemodels", "cdmaterials",
                                     "textures", "skins")}
    info_out.update(bones=[{"name": b["name"], "parent": b["parent"]} for b in bones],
                    attachments=atts, hitboxsets=sets, sequences=seqs, bodyparts=bodyparts)
    with open(os.path.join(out, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info_out, f, indent=1, ensure_ascii=False)
    print("attachments", [(a["name"], a["bone"]) for a in atts])
    print("sequences", seqs)


if __name__ == "__main__":
    main()
