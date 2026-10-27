"""Pure-Python .smd reference file reader / writer and skeleton math (no Blender needed).

SMD rotations are radians applied X, then Y, then Z: R = Rz * Ry * Rx (matches Blender Source Tools).
"""
import math

import numpy as np


def read_smd(path):
    """-> dict(header=str, nodes={i: name}, parents={i: parent}, local={i: (px,py,pz,rx,ry,rz)},
              tris=[(material, [corner, corner, corner])]) with corner = list of fields (strings)."""
    nodes, parents, local, tris = {}, {}, {}, []
    header, section, frame, mat, cur = [], None, None, None, []
    for line in open(path, encoding="latin-1"):
        s = line.strip()
        if section != "triangles":
            header.append(line.rstrip("\n"))
        if section is None:
            if s in ("nodes", "skeleton", "triangles"):
                section = s
                if s == "triangles":
                    header.pop()
            continue
        if s == "end":
            section = None
            continue
        if section == "nodes":
            p = s.split('"')
            nodes[int(p[0])] = p[1]
            parents[int(p[0])] = int(p[2])
        elif section == "skeleton":
            if s.startswith("time"):
                frame = int(s.split()[1])
            elif frame == 0:
                p = s.split()
                local[int(p[0])] = tuple(map(float, p[1:7]))
        elif section == "triangles":
            if mat is None:
                mat, cur = s, []
                continue
            cur.append(s.split())
            if len(cur) == 3:
                tris.append((mat, cur))
                mat = None
    return {"header": "\n".join(header) + "\n", "nodes": nodes, "parents": parents, "local": local, "tris": tris}


def euler_matrix(x, y, z):
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return np.array([[cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
                     [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
                     [-sy, sx * cy, cx * cy]])


def world_matrices(smd):
    """-> {name: (R 3x3, head 3)} rest pose in model space."""
    world = {}

    def solve(i):
        if i in world:
            return world[i]
        px, py, pz, rx, ry, rz = smd["local"].get(i, (0, 0, 0, 0, 0, 0))
        rot, pos = euler_matrix(rx, ry, rz), np.array([px, py, pz])
        par = smd["parents"][i]
        if par >= 0:
            prot, ppos = solve(par)
            rot, pos = prot @ rot, ppos + prot @ pos
        world[i] = (rot, pos)
        return world[i]
    for i in smd["nodes"]:
        solve(i)
    return {smd["nodes"][i]: world[i] for i in smd["nodes"]}


def corner_weights(c, nodes):
    """SMD corner fields -> [(bone_name, weight)]."""
    n = int(c[9]) if len(c) > 9 else 0
    if not n:
        return [(nodes[int(c[0])], 1.0)]
    return [(nodes[int(c[10 + 2 * j])], float(c[11 + 2 * j])) for j in range(n)]


def format_corner(index_of, pos, normal, uv, weights):
    w = sorted(((b, x) for b, x in weights.items() if x > 1e-4), key=lambda t: -t[1])[:3]
    total = sum(x for _, x in w) or 1.0
    ws = " ".join(f"{index_of[b]} {x / total:.6f}" for b, x in w)
    return (f"{index_of[w[0][0]]} {pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f} {normal[0]:.6f} {normal[1]:.6f} "
            f"{normal[2]:.6f} {uv[0]} {uv[1]} {len(w)} {ws}")


def write_smd(path, header, tris):
    """tris: [(material, [line, line, line])]"""
    with open(path, "w", encoding="latin-1", newline="\n") as f:
        f.write(header)
        f.write("triangles\n")
        for mat, lines in tris:
            f.write(mat + "\n")
            for ln in lines:
                f.write(ln + "\n")
        f.write("end\n")
