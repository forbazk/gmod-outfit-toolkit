"""Build a materials folder for a model's textures (VMT + VTF from the spec), good or broken.

Usage: python make_materials.py model.mdl materials_root good|bad
  good: every texture = VertexLitGeneric, 1024x1024 DXT5, full mip chain
  bad : first texture $translucent + 4096x4096 BGRA8888 without mipmaps, last texture's VMT missing
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, HERE)
from audit_mdl import read_mdl  # noqa: E402
from make_vtf import build  # noqa: E402


def main():
    mdl, root, mode = sys.argv[1], sys.argv[2], sys.argv[3]
    m = read_mdl(mdl)
    cd = m["cdmaterials"][0].replace("\\", "/").strip("/")
    folder = os.path.join(root, *cd.split("/"))
    os.makedirs(folder, exist_ok=True)
    for k, tex in enumerate(m["textures"]):
        bad = mode == "bad"
        if bad and k == len(m["textures"]) - 1:
            continue
        extra = '\t"$translucent" "1"\n' if bad and k == 0 else ""
        with open(os.path.join(folder, tex + ".vmt"), "w", encoding="utf-8") as f:
            f.write(f'"VertexLitGeneric"\n{{\n\t"$basetexture" "{cd}/{tex}"\n{extra}}}\n')
        data = build(4096, 4096, 12, 1) if bad and k == 0 else build(1024, 1024, 15, 0)
        with open(os.path.join(folder, tex + ".vtf"), "wb") as f:
            f.write(data)
    print("materials written to", folder)


if __name__ == "__main__":
    main()
