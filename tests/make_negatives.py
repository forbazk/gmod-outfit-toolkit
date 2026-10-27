"""Build deliberately broken .smd files (negative controls) from a healthy one.

Usage: python make_negatives.py source.smd output_folder
  inside_out.smd    : faces AND normals pointing inward (consistent, but invisible in game)
  half_normals.smd  : normals flipped on the right side (x<0), faces unchanged
  broken_weights.smd: vertices below z=20 bound to bone 5 (the head) -> tearing when walking
"""
import os
import sys


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    lines = open(src, encoding="latin-1").read().split("\n")
    start = lines.index("triangles") + 1
    head = lines[:start]
    body = lines[start:]
    tris = []
    k = 0
    while k + 3 < len(body) and body[k] != "end":
        tris.append((body[k], [body[k + 1].split(), body[k + 2].split(), body[k + 3].split()]))
        k += 4

    def write(name, rows):
        with open(os.path.join(out, name), "w", encoding="latin-1", newline="\n") as f:
            f.write("\n".join(head) + "\n")
            for mat, vs in rows:
                f.write(mat + "\n")
                for v in vs:
                    f.write(" ".join(v) + "\n")
            f.write("end\n")

    def neg_normal(v):
        v = list(v)
        for i in (4, 5, 6):
            v[i] = f"{-float(v[i]):.6f}"
        return v

    def broken(v):
        if float(v[3]) >= 20:
            return v
        return v[:9] + ["1", "5", "1.000000"]

    write("inside_out.smd", [(m, [neg_normal(v) for v in reversed(vs)]) for m, vs in tris])
    write("half_normals.smd", [(m, [neg_normal(v) if float(v[1]) < 0 else v for v in vs]) for m, vs in tris])
    write("broken_weights.smd", [(m, [broken(v) for v in vs]) for m, vs in tris])
    print("negatives written to", out)


if __name__ == "__main__":
    main()
