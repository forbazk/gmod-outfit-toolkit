"""Build a clean release folder (addon layout) for a model: only the files Garry's Mod loads.

Copies .mdl/.vvd/.dx90.vtx/.phy to models/<internal path>, plus every material (.vmt) and texture
(.vtf) the model references when the materials folder is available. Skips .dx80.vtx / .sw.vtx,
and reports the bytes saved and anything missing.

Usage: python pack.py model.mdl output_folder [--materials materials_root]
Exit 1 when a referenced material or texture is missing.
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_mdl import read_mdl  # noqa: E402
from doctor import SHIPPED, WASTE, kb  # noqa: E402
from materials import guess_materials_root, resolve  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("model")
    p.add_argument("out")
    p.add_argument("--materials")
    a = p.parse_args()
    base = a.model[:-4]
    m = read_mdl(a.model)
    rel = m["name"].replace("\\", "/")
    if not rel.lower().startswith("models/"):
        rel = "models/" + rel
    dest_base = os.path.join(a.out, *rel[:-4].split("/"))
    os.makedirs(os.path.dirname(dest_base), exist_ok=True)
    copied, skipped, missing = 0, 0, []
    for ext in SHIPPED:
        if os.path.exists(base + ext):
            shutil.copyfile(base + ext, dest_base + ext)
            copied += os.path.getsize(base + ext)
            print(f"model    {rel[:-4]}{ext}")
        elif ext != ".phy":
            missing.append(base + ext)
    for ext in WASTE:
        if os.path.exists(base + ext):
            skipped += os.path.getsize(base + ext)
            print(f"skipped  {os.path.basename(base)}{ext} ({kb(os.path.getsize(base + ext))}, unused by Garry's Mod)")
    root = a.materials or guess_materials_root(a.model)
    if root is None:
        print("materials folder not found: model files only (pass --materials)")
    else:
        for e in resolve(a.model, root):
            if not e["vmt"]:
                missing.append(f"material {e['texture']}")
                continue
            files = [e["vmt"]] + [t["vtf"] for t in e["textures"] if t["vtf"]]
            missing += [f"texture {t['name']}" for t in e["textures"] if not t["vtf"]]
            for src in files:
                dst = os.path.join(a.out, "materials", os.path.relpath(src, root))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if not os.path.exists(dst):
                    shutil.copyfile(src, dst)
                    copied += os.path.getsize(src)
                    print(f"material {os.path.relpath(src, root)}")
    print(f"packed {kb(copied)}, left out {kb(skipped)} of useless files")
    for x in missing:
        print(f"MISSING {x}")
    print("RESULT", "OK" if not missing else "INCOMPLETE")
    sys.exit(0 if not missing else 1)


if __name__ == "__main__":
    main()
