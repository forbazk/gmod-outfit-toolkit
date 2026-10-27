"""Check that an outfit's skeleton matches the target rig (server body / animation rig).

Compares the skeleton blocks of two .smd files: bone naming convention, missing / extra bones,
parent changes, and rest-pose world positions. A garment skinned on a different rest pose
ends up offset or twisted in game even when every bone name matches.

Usage: python rig_check.py outfit.smd target.smd [--tolerance 0.05] [--json out.json]
Exit 0 when compatible.
"""
import argparse
import json
import math
import sys


def read_skeleton(path):
    nodes, parents, local = {}, {}, {}
    section, frame = None, None
    for line in open(path, encoding="latin-1"):
        s = line.strip()
        if section is None:
            if s in ("nodes", "skeleton"):
                section = s
            elif s == "triangles":
                break
            continue
        if s == "end":
            section = None
            continue
        if section == "nodes":
            p = s.split('"')
            idx = int(p[0])
            nodes[idx] = p[1]
            parents[idx] = int(p[2])
        elif section == "skeleton":
            if s.startswith("time"):
                frame = int(s.split()[1])
                continue
            if frame != 0:
                continue
            p = s.split()
            local[int(p[0])] = tuple(map(float, p[1:7]))
    return nodes, parents, local


def euler_matrix(x, y, z):
    """SMD rotation (radians, applied X then Y then Z): R = Rz * Ry * Rx."""
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return [[cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
            [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
            [-sy, sx * cy, cx * cy]]


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mat_vec(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def world_positions(nodes, parents, local):
    world = {}

    def solve(i):
        if i in world:
            return world[i]
        px, py, pz, rx, ry, rz = local.get(i, (0, 0, 0, 0, 0, 0))
        rot = euler_matrix(rx, ry, rz)
        if parents[i] < 0:
            world[i] = (rot, [px, py, pz])
        else:
            prot, ppos = solve(parents[i])
            off = mat_vec(prot, [px, py, pz])
            world[i] = (mat_mul(prot, rot), [ppos[k] + off[k] for k in range(3)])
        return world[i]
    for i in nodes:
        solve(i)
    return {nodes[i]: world[i][1] for i in nodes}


def convention(names):
    names = set(names)
    if any(n.startswith("ValveBiped.") for n in names):
        return "ValveBiped"
    if {"Hips", "Spine", "LeftArm", "RightUpLeg"} <= names:
        return "Mixamo-style"
    return "unknown"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("outfit")
    p.add_argument("target")
    p.add_argument("--tolerance", type=float, default=0.05, help="max rest position offset (Source units)")
    p.add_argument("--json")
    a = p.parse_args()
    on, op, ol = read_skeleton(a.outfit)
    tn, tp, tl = read_skeleton(a.target)
    ow, tw = world_positions(on, op, ol), world_positions(tn, tp, tl)
    oc, tc = convention(on.values()), convention(tn.values())
    oname = {v: k for k, v in on.items()}
    tname = {v: k for k, v in tn.items()}
    missing = sorted(set(tname) - set(oname))
    extra = sorted(set(oname) - set(tname))
    reparented = []
    offsets = []
    for name in set(oname) & set(tname):
        opar = on.get(op[oname[name]], None)
        tpar = tn.get(tp[tname[name]], None)
        if opar != tpar:
            reparented.append((name, opar, tpar))
        d = math.dist(ow[name], tw[name])
        if d > a.tolerance:
            offsets.append((name, round(d, 3)))
    offsets.sort(key=lambda x: -x[1])
    problems = []
    if oc != tc:
        problems.append(f"naming convention differs: outfit {oc}, target {tc} (needs retargeting)")
    if missing:
        problems.append(f"{len(missing)} target bones missing from the outfit skeleton")
    if reparented:
        problems.append(f"{len(reparented)} bones have a different parent")
    if offsets:
        problems.append(f"{len(offsets)} bones off their target rest position (> {a.tolerance} u), "
                        f"worst {offsets[0][0]} {offsets[0][1]} u")
    print(f"outfit: {len(on)} bones ({oc})   target: {len(tn)} bones ({tc})")
    print(f"missing in outfit: {missing[:12]}{' ...' if len(missing) > 12 else ''}")
    print(f"extra in outfit (ignored by bonemerge, fine): {extra[:12]}{' ...' if len(extra) > 12 else ''}")
    for name, a_, b_ in reparented[:10]:
        print(f"parent differs: {name}: outfit {a_} / target {b_}")
    for name, d in offsets[:10]:
        print(f"rest offset: {name} {d} u")
    ok = not problems
    print("RESULT", "OK" if ok else "FAIL", "; ".join(problems))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"outfit_convention": oc, "target_convention": tc, "missing": missing, "extra": extra,
                       "reparented": reparented, "offsets": offsets, "problems": problems,
                       "world_positions": {k: [round(x, 4) for x in v] for k, v in ow.items()}}, f, indent=1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
