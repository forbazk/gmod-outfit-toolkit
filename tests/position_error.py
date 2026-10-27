"""Corner-by-corner comparison of two .smd with the same triangle order (e.g. retarget ground truth).

Usage: python position_error.py result.smd expected.smd
Prints position error (mean, p99, max), normal angle p99 and the share of corners whose
dominant bone differs.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from smd_io import corner_weights, read_smd  # noqa: E402


def main():
    a, b = read_smd(sys.argv[1]), read_smd(sys.argv[2])
    pa = np.array([list(map(float, c[1:4])) for _, cs in a["tris"] for c in cs])
    pb = np.array([list(map(float, c[1:4])) for _, cs in b["tris"] for c in cs])
    na = np.array([list(map(float, c[4:7])) for _, cs in a["tris"] for c in cs])
    nb = np.array([list(map(float, c[4:7])) for _, cs in b["tris"] for c in cs])
    d = np.linalg.norm(pa - pb, axis=1)
    cos = np.clip((na * nb).sum(1) / (np.linalg.norm(na, axis=1) * np.linalg.norm(nb, axis=1) + 1e-12), -1, 1)
    ang = np.degrees(np.arccos(cos))
    dom = lambda smd: [max(corner_weights(c, smd["nodes"]), key=lambda t: t[1])[0]  # noqa: E731
                       for _, cs in smd["tris"] for c in cs]
    mismatch = np.mean([x != y for x, y in zip(dom(a), dom(b))])
    print(f"ERROR mean {d.mean():.4f} p99 {np.percentile(d, 99):.4f} max {d.max():.4f} "
          f"normal_p99 {np.percentile(ang, 99):.2f} dominant_bone_mismatch {100 * mismatch:.2f}%")


if __name__ == "__main__":
    main()
