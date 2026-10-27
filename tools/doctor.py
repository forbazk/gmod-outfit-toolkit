"""Outfit doctor: actionable diagnosis of one model or a whole folder of models.

For every .mdl: download size and wasted files, triangles per LOD and per bodygroup, draw calls,
LODs, translucency, skinning, physics, and (when the materials folder is found) every texture:
missing files, resolution, compression, mipmaps, VRAM. Each finding has a severity, a concrete fix
and, where measurable, the expected gain. Models get a 0-100 score; folders get a ranking.

Usage: python doctor.py <model.mdl | folder> [--materials materials_root] [--out report_folder]
Writes report.md + report.json in --out (default: print only). Exit 0.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_mdl import read_mdl, read_phy, read_vtx, read_vvd  # noqa: E402
from materials import guess_materials_root, resolve  # noqa: E402
from vtf import COMPRESSED, FORMATS  # noqa: E402

SEVERITY = {"critical": 25, "high": 12, "medium": 5, "low": 2, "info": 0}
SHIPPED = (".mdl", ".vvd", ".dx90.vtx", ".phy")
WASTE = (".dx80.vtx", ".sw.vtx", ".xbox.vtx")


def kb(n):
    return f"{n / 1024:,.0f} KB"


def vtx_tris_by_model(path):
    """-> {(bodypart, model): [tris per LOD]} from a .dx90.vtx."""
    import struct
    d = open(path, "rb").read()
    i32 = lambda o: struct.unpack_from("<i", d, o)[0]  # noqa: E731
    out = {}
    bpo = i32(32)
    for b in range(i32(28)):
        bo = bpo + b * 8
        for m in range(i32(bo)):
            mo = bo + i32(bo + 4) + m * 8
            lods = []
            for lod in range(i32(mo)):
                lo = mo + i32(mo + 4) + lod * 12
                tris = 0
                for s in range(i32(lo)):
                    so = lo + i32(lo + 4) + s * 9
                    for g in range(i32(so)):
                        go = so + i32(so + 4) + g * 25
                        tris += i32(go + 8) // 3
                lods.append(tris)
            out[(b, m)] = lods
    return out


def diagnose(mdl, materials_root=None):
    base = mdl[:-4]
    m = read_mdl(mdl)
    f = []

    def add(sev, area, problem, fix, gain=None):
        f.append({"severity": sev, "area": area, "problem": problem, "fix": fix, "gain": gain})

    files = {ext: os.path.getsize(base + ext) for ext in SHIPPED + WASTE if os.path.exists(base + ext)}
    shipped = sum(v for k, v in files.items() if k in SHIPPED)
    waste = {k: v for k, v in files.items() if k in WASTE}
    for ext, size in waste.items():
        add("low", "download", f"{ext} shipped but unused by Garry's Mod", f"delete {os.path.basename(base)}{ext}",
            f"-{kb(size)} per player download")
    for ext in (".vvd", ".dx90.vtx"):
        if ext not in files:
            add("critical", "files", f"{ext} missing: the model will not load", "recompile the model")
    r = {"model": mdl, "name": m["name"], "flags": m["flags"], "download_bytes": shipped,
         "wasted_bytes": sum(waste.values())}

    if ".dx90.vtx" in files:
        vtx = read_vtx(base + ".dx90.vtx")
        by_model = vtx_tris_by_model(base + ".dx90.vtx")
        default = sum(by_model.get((b, 0), [0])[0] for b in range(len(m["bodyparts"])))
        heaviest = sum(max((v[0] for (bb, _), v in by_model.items() if bb == b), default=0)
                       for b in range(len(m["bodyparts"])))
        r.update(lods=vtx["numlods"], tris_lod=vtx["lod_tris"], tris_default=default, tris_heaviest=heaviest)
        if vtx["numlods"] <= 1:
            if heaviest > 8000:
                target = min(heaviest, 20000)
                add("critical" if heaviest > 40000 else "high", "geometry",
                    f"no LOD: {heaviest:,} triangles drawn even at 100 m",
                    "generate LODs (optimize_outfit.py) and add $lod blocks (write_qc.py)",
                    f"far away: {heaviest:,} -> ~{target // 8:,} triangles per player")
        if heaviest > 40000:
            add("high", "geometry", f"{heaviest:,} triangles in the heaviest bodygroup combination",
                "decimate LOD0 to ~20,000 triangles (optimize_outfit.py, then validate_lods.py)",
                f"-{100 - 100 * 20000 // heaviest} % triangles close up")
        elif heaviest > 25000:
            add("medium", "geometry", f"{heaviest:,} triangles (comfortable outfit budget is 15-20k)",
                "decimate LOD0 to ~20,000 triangles", f"-{100 - 100 * 20000 // heaviest} % triangles close up")
        if vtx["maxBonesPerVert"] > 3:
            add("high", "skinning", f"{vtx['maxBonesPerVert']} bones per vertex", "limit weights to 3 per vertex")
        r["strip_groups"] = vtx["stripgroups_lod0"]

    draw = 0
    used_materials = set()
    for bp in m["bodyparts"]:
        if bp["models"]:
            mo = bp["models"][0]
            draw += len(mo["meshes"])
            for me in mo["meshes"]:
                used_materials.add(m["textures"][m["skins"][0][me["material"]]] if m["skins"] else me["material"])
    r["draw_calls_default"] = draw
    if draw > 6:
        add("medium", "rendering", f"{draw} materials drawn by default (one draw call each)",
            "merge textures into an atlas: 1-3 materials per outfit")
    if "TRANSLUCENT_TWOPASS" in m["flags"]:
        add("medium", "rendering", "TRANSLUCENT_TWOPASS flag ($mostlyopaque): drawn in both opaque and translucent passes",
            "remove $mostlyopaque from the QC; use $alphatest instead of $translucent in the VMTs",
            "one render pass instead of two")
    hidden = [bp["name"] for bp in m["bodyparts"]
              if len(bp["models"]) > 1 and not bp["models"][0]["meshes"]]
    if hidden:
        r["optional_bodygroups"] = hidden

    if os.path.exists(base + ".vvd"):
        v = read_vvd(base + ".vvd")
        total = sum(v["weights_per_vert"].values())
        r["weights_3_pct"] = round(100 * v["weights_per_vert"].get(3, 0) / max(total, 1), 1)
        unweighted = [b["name"] for k, b in enumerate(m["bones"]) if v["bone_weight"].get(k, 0) == 0]
        r["bones"], r["bones_unweighted"] = len(m["bones"]), len(unweighted)
    if os.path.exists(base + ".phy"):
        p = read_phy(base + ".phy")
        r["phy_solids"] = p["solids"]
        if p["solids"] > 1 and '"xmin" "0.000000"' in p["text"] and '"xmax" "0.000000"' in p["text"]:
            add("info", "physics", f"{p['solids']} physics solids with locked joints (rigid ragdoll)",
                "if the outfit is bonemerged on the player, a single $collisionmodel is enough")

    root = materials_root or guess_materials_root(mdl)
    r["materials_root"] = root
    r["textures"] = []
    if root is None:
        add("info", "textures", "materials folder not found: textures not checked",
            "pass --materials <addon>/materials")
    else:
        vram = 0
        for e in resolve(mdl, root):
            if e["vmt"] is None:
                default = e["texture"] in used_materials
                add("critical" if default else "high", "textures",
                    f"material '{e['texture']}' not found in any $cdmaterials path"
                    + ("" if default else " (used by an optional bodygroup)"),
                    "ship the .vmt or fix $cdmaterials (purple/black checkerboard in game)")
                continue
            p = e["params"]
            if p.get("$translucent") == "1":
                add("medium", "rendering", f"{e['texture']}.vmt uses $translucent (sorting issues, costlier)",
                    "use $alphatest 1 (+ $alphatestreference 0.5) unless real transparency is needed")
            for t in e["textures"]:
                i = t["info"]
                label = f"{e['texture']} {t['key']}"
                if not t["vtf"]:
                    add("critical", "textures", f"{label}: {t['name']}.vtf missing", "ship the texture")
                    continue
                if not i["valid"]:
                    add("critical", "textures", f"{label}: {i['error']}", "re-export the texture")
                    continue
                vram += i["vram"]
                r["textures"].append({"material": e["texture"], "key": t["key"], "name": t["name"],
                                      "size": f"{i['width']}x{i['height']}", "format": i["format"],
                                      "mipmaps": i["mipmaps"], "vram": i["vram"], "file": i["size"]})
                side = max(i["width"], i["height"])
                if i["format"] not in COMPRESSED:
                    bpp = next(v[1] for v in FORMATS.values() if v[0] == i["format"])
                    add("high" if side >= 1024 else "medium", "textures",
                        f"{label}: uncompressed {i['format']} {i['width']}x{i['height']} ({kb(i['vram'])} VRAM)",
                        "export as DXT1 (no alpha) or DXT5 (alpha)",
                        f"DXT5: -{100 - round(100 / bpp)} %, DXT1: -{100 - round(50 / bpp)} % VRAM and download")
                if side > 2048:
                    add("high", "textures", f"{label}: {i['width']}x{i['height']} texture",
                        "2048 max for an outfit (1024 for small parts)", "-75 % VRAM per halving")
                if not i["full_mip_chain"] and "NOMIP" not in i["flags"] and side > 64:
                    add("medium", "textures", f"{label}: {i['mipmaps']} mipmap(s) only",
                        "export with mipmaps (shimmering and cache misses at distance otherwise)")
                if not i["power_of_two"]:
                    add("medium", "textures", f"{label}: {i['width']}x{i['height']} not a power of two",
                        "resize to a power of two")
        r["vram_bytes"] = vram
        if vram > 48 * 1024 * 1024:
            add("high", "textures", f"{kb(vram)} of texture memory for one outfit",
                "reduce resolutions / compress (budget ~16-32 MB)")
    order = list(SEVERITY)
    f.sort(key=lambda x: order.index(x["severity"]))
    r["findings"] = f
    r["score"] = max(0, 100 - sum(SEVERITY[x["severity"]] for x in f))
    return r


def markdown(reports, base=None):
    def label(r):
        return os.path.relpath(r["model"], base) if base else os.path.basename(r["model"])
    lines = ["# Outfit doctor report", ""]
    if len(reports) > 1:
        lines += ["| Score | Model | Triangles (heaviest) | LODs | Draw calls | Download | Wasted |",
                  "|---:|---|---:|---:|---:|---:|---:|"]
        for r in sorted(reports, key=lambda x: x["score"]):
            lines.append(f"| {r['score']} | {label(r)} | {r.get('tris_heaviest', 0):,} | "
                         f"{r.get('lods', '?')} | {r['draw_calls_default']} | {kb(r['download_bytes'])} | "
                         f"{kb(r['wasted_bytes'])} |")
        lines.append("")
    for r in sorted(reports, key=lambda x: x["score"]):
        lines += [f"## {label(r)} — score {r['score']}/100", "",
                  f"- internal name: `{r['name']}`",
                  f"- triangles: default {r.get('tris_default', 0):,}, heaviest {r.get('tris_heaviest', 0):,}, "
                  f"per LOD {r.get('tris_lod')}",
                  f"- draw calls (default bodygroups): {r['draw_calls_default']}",
                  f"- download: {kb(r['download_bytes'])} (+{kb(r['wasted_bytes'])} useless files)"]
        if "vram_bytes" in r:
            lines.append(f"- texture memory: {kb(r['vram_bytes'])}")
        lines += ["", "| Severity | Area | Problem | Fix | Gain |", "|---|---|---|---|---|"]
        for x in r["findings"]:
            lines.append(f"| {x['severity']} | {x['area']} | {x['problem']} | {x['fix']} | {x['gain'] or ''} |")
        lines.append("")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("target")
    p.add_argument("--materials")
    p.add_argument("--out")
    a = p.parse_args()
    if os.path.isdir(a.target):
        mdls = [os.path.join(dp, fn) for dp, _, fns in os.walk(a.target) for fn in fns if fn.lower().endswith(".mdl")]
    else:
        mdls = [a.target]
    reports = [diagnose(m, a.materials) for m in sorted(mdls)]
    text = markdown(reports, a.target if os.path.isdir(a.target) else None)
    print(text)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        open(os.path.join(a.out, "report.md"), "w", encoding="utf-8").write(text)
        json.dump(reports, open(os.path.join(a.out, "report.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
