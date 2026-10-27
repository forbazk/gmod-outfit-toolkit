"""Per-bone weight distribution in a .smd, plus the bounding box.

Usage: python smd_weights.py file.smd [bone_name_filter]
"""
import sys
from collections import defaultdict


def main():
    path = sys.argv[1]
    filt = sys.argv[2].lower() if len(sys.argv) > 2 else ""
    nodes, weight, verts = {}, defaultdict(float), defaultdict(int)
    lo, hi = [1e9] * 3, [-1e9] * 3
    section, expect_mat = None, True
    count = 0
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
            if expect_mat:
                expect_mat, count = False, 0
                continue
            p = s.split()
            for k in range(3):
                x = float(p[1 + k])
                lo[k], hi[k] = min(lo[k], x), max(hi[k], x)
            n = int(p[9]) if len(p) > 9 else 0
            for j in range(n):
                b = int(p[10 + j * 2])
                weight[b] += float(p[11 + j * 2])
                verts[b] += 1
            if not n:
                weight[int(p[0])] += 1
                verts[int(p[0])] += 1
            count += 1
            if count == 3:
                expect_mat = True
    print(f"bbox min {[round(v, 2) for v in lo]} max {[round(v, 2) for v in hi]}")
    for k, name in sorted(nodes.items()):
        if filt in name.lower():
            print(f"{k:3} {name:28} verts {verts[k]:7}  weight {weight[k]:10.1f}")


if __name__ == "__main__":
    main()
