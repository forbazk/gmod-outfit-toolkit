"""Compare two reference .smd files (geometry, UVs, normals, weights), independent of triangle order.

Triangles are matched by material + positions + UVs (winding included),
then normals (max angle) and weights (max difference) are measured numerically.

Usage: python smd_compare.py a.smd b.smd [pos_tol=0.001] [angle_tol_deg=1] [weight_tol=0.01]
Exit code 0 when identical within tolerances.
"""
import math
import sys
from collections import Counter, defaultdict


def load(path, tol):
    nodes, tris = {}, defaultdict(list)
    section, mat, cur = None, None, []
    for line in open(path, encoding="latin-1"):
        s = line.strip()
        if section is None:
            if s in ("nodes", "skeleton", "triangles"):
                section = s
            continue
        if s == "end":
            section = None
            continue
        if section == "nodes":
            p = s.split('"')
            nodes[int(p[0])] = p[1]
        elif section == "triangles":
            if mat is None:
                mat, cur = s, []
                continue
            p = s.split()
            n = int(p[9]) if len(p) > 9 else 0
            w = defaultdict(float)
            for j in range(n):
                w[nodes[int(p[10 + j * 2])]] += float(p[11 + j * 2])
            if not n:
                w[nodes[int(p[0])]] = 1.0
            key = tuple(round(float(x) / tol) for x in p[1:4] + p[7:9])
            cur.append((key, tuple(float(x) for x in p[4:7]), dict(w)))
            if len(cur) == 3:
                k = min(range(3), key=lambda i: cur[i][0])
                rot = cur[k:] + cur[:k]
                tris[(mat, tuple(c[0] for c in rot))].append([(c[1], c[2]) for c in rot])
                mat = None
    return tris


def angle(a, b):
    la, lb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    if not la or not lb:
        return 0.0
    c = sum(x * y for x, y in zip(a, b)) / (la * lb)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def main():
    a, b = sys.argv[1], sys.argv[2]
    tol = float(sys.argv[3]) if len(sys.argv) > 3 else 0.001
    tol_ang = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    tol_w = float(sys.argv[5]) if len(sys.argv) > 5 else 0.01
    ta, tb = load(a, tol), load(b, tol)
    ca = Counter({k: len(v) for k, v in ta.items()})
    cb = Counter({k: len(v) for k, v in tb.items()})
    mats_a, mats_b = Counter(), Counter()
    for (m, _), n in ca.items():
        mats_a[m] += n
    for (m, _), n in cb.items():
        mats_b[m] += n
    print(f"tris per material A {dict(mats_a)}  B {dict(mats_b)}")
    unmatched = sum(((ca - cb) + (cb - ca)).values())
    print(f"position+UV  matched {sum((ca & cb).values())}/{sum(ca.values())}  unmatched {unmatched}")
    max_ang, max_w, bad_n, bad_w = 0.0, 0.0, 0, 0
    for k in ca.keys() & cb.keys():
        for ta_i, tb_i in zip(ta[k], tb[k]):
            ang = max(angle(x[0], y[0]) for x, y in zip(ta_i, tb_i))
            dw = max(abs(x[1].get(n, 0) - y[1].get(n, 0)) for x, y in zip(ta_i, tb_i)
                     for n in set(x[1]) | set(y[1]))
            max_ang, max_w = max(max_ang, ang), max(max_w, dw)
            bad_n += ang > tol_ang
            bad_w += dw > tol_w
    print(f"normals      max angle {max_ang:.3f} deg  out of tolerance ({tol_ang}) {bad_n}")
    print(f"weights      max diff {max_w:.4f}  out of tolerance ({tol_w}) {bad_w}")
    ok = unmatched == 0 and bad_n == 0 and bad_w == 0
    print("RESULT", "OK" if ok else "DIFFERENT")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
