"""Normal / winding consistency of a .smd, per material and per side (X>0 = character's left).

A corner is "flipped" when its normal points away from the triangle's geometric normal
(the face is seen from behind: invisible in game since Source culls backfaces, or dark patches).
Limitation: a piece whose faces AND normals both point inward passes; validate_faces.py covers it.

Usage: python smd_normals.py file.smd [threshold_pct=1.0]   -> exit 1 if any group exceeds it
"""
import sys
from collections import defaultdict


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def main():
    path = sys.argv[1]
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    stats = defaultdict(lambda: [0, 0])
    section, mat, tri = None, None, []
    for line in open(path, encoding="latin-1"):
        s = line.strip()
        if section is None:
            if s == "triangles":
                section = "t"
            continue
        if s == "end":
            break
        if mat is None:
            mat, tri = s, []
            continue
        p = s.split()
        tri.append((tuple(map(float, p[1:4])), tuple(map(float, p[4:7]))))
        if len(tri) == 3:
            fn = cross(sub(tri[1][0], tri[0][0]), sub(tri[2][0], tri[0][0]))
            if dot(fn, fn) > 1e-12:
                cx = sum(v[0][0] for v in tri) / 3
                side = "left" if cx > 0.05 else "right" if cx < -0.05 else "center"
                st = stats[(mat, side)]
                for _, n in tri:
                    st[0] += dot(fn, n) < 0
                    st[1] += 1
            mat = None
    worst = 0.0
    for (m, side), (bad, total) in sorted(stats.items()):
        pct = 100 * bad / max(total, 1)
        worst = max(worst, pct)
        print(f"{m:16} {side:7} flipped {pct:6.2f} %  ({bad}/{total})")
    print("RESULT", "OK" if worst <= threshold else "FAIL", f"(worst {worst:.2f} %, threshold {threshold} %)")
    sys.exit(0 if worst <= threshold else 1)


if __name__ == "__main__":
    main()
