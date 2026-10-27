"""Source materials: .vmt parsing and resolution of a model's materials and textures.

Lookup rule (as the engine does): for each texture name of the model, try every $cdmaterials
path in order: <materials_root>/<cdmaterials>/<name>.vmt. Texture parameters of the .vmt
($basetexture, $bumpmap, ...) are resolved as <materials_root>/<value>.vtf.

Usage: python materials.py file.mdl [materials_root]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_mdl import read_mdl  # noqa: E402
from vtf import read_vtf  # noqa: E402

TEXTURE_KEYS = ("$basetexture", "$bumpmap", "$normalmap", "$phongexponenttexture", "$envmapmask",
                "$detail", "$lightwarptexture", "$selfillummask", "$basetexture2", "$blendmodulatetexture")
TOKEN = re.compile(r'"([^"]*)"|([^\s{}"]+)|([{}])')


def parse_vmt(text):
    """-> (shader, {key_lowercase: value}) ; nested blocks (proxies) are flattened under their own keys."""
    text = re.sub(r"//[^\n]*", "", text)
    tokens = [m.group(1) if m.group(1) is not None else m.group(2) or m.group(3) for m in TOKEN.finditer(text)]
    if not tokens:
        return None, {}
    shader = tokens[0]
    params, depth, i = {}, 0, 1
    while i < len(tokens):
        t = tokens[i]
        if t == "{":
            depth += 1
        elif t == "}":
            depth -= 1
        elif i + 1 < len(tokens) and tokens[i + 1] not in ("{", "}"):
            if depth == 1:
                params[t.lower()] = tokens[i + 1]
            i += 1
        i += 1
    return shader, params


def find_file(root, rel):
    """Case-insensitive file lookup below root (Source paths are case-insensitive)."""
    rel = rel.replace("\\", "/").strip("/")
    path = os.path.join(root, *rel.split("/"))
    if os.path.exists(path):
        return path
    cur = root
    for part in rel.split("/"):
        if not os.path.isdir(cur):
            return None
        match = next((e for e in os.listdir(cur) if e.lower() == part.lower()), None)
        if match is None:
            return None
        cur = os.path.join(cur, match)
    return cur


def guess_materials_root(mdl_path):
    """<addon>/models/.../x.mdl -> <addon>/materials when it exists."""
    cur = os.path.dirname(os.path.abspath(mdl_path))
    while True:
        if os.path.basename(cur).lower() == "models":
            cand = os.path.join(os.path.dirname(cur), "materials")
            return cand if os.path.isdir(cand) else None
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def resolve(mdl_path, root):
    """-> list of {texture, vmt, shader, params, textures:[{key, name, vtf, info}]}"""
    m = read_mdl(mdl_path)
    out = []
    for tex in m["textures"]:
        entry = {"texture": tex, "vmt": None, "shader": None, "params": {}, "textures": []}
        if root:
            for cd in m["cdmaterials"]:
                found = find_file(root, f"{cd}/{tex}.vmt")
                if found:
                    entry["vmt"] = found
                    break
        if entry["vmt"]:
            shader, params = parse_vmt(open(entry["vmt"], encoding="utf-8", errors="replace").read())
            entry["shader"], entry["params"] = shader, params
            for key in TEXTURE_KEYS:
                if key in params:
                    vtf = find_file(root, params[key] + ".vtf")
                    entry["textures"].append({"key": key, "name": params[key], "vtf": vtf,
                                              "info": read_vtf(vtf) if vtf else None})
        out.append(entry)
    return out


def main():
    mdl = sys.argv[1]
    root = sys.argv[2] if len(sys.argv) > 2 else guess_materials_root(mdl)
    print(f"materials root: {root}")
    for e in resolve(mdl, root):
        if not e["vmt"]:
            print(f"{e['texture']}: VMT NOT FOUND")
            continue
        print(f"{e['texture']}: {e['shader']} {e['vmt']}")
        for t in e["textures"]:
            i = t["info"]
            state = "MISSING" if not t["vtf"] else (f"{i['width']}x{i['height']} {i['format']} mips {i['mipmaps']}"
                                                   if i["valid"] else f"INVALID {i['error']}")
            print(f"   {t['key']} {t['name']}: {state}")


if __name__ == "__main__":
    main()
