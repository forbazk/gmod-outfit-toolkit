"""Generate a .qc from info.json (mdl_to_smd.py) and optimized SMDs (optimize_outfit.py).

Carries over: $modelname, $cdmaterials, $includemodel, $surfaceprop, bodygroups, attachments,
hitboxes, sequence. Adds: $lod (for every <ref>_lodN.smd found), $shadowlod,
$collisionjoints (<ref>_phys.smd) with locked joints.
Does NOT write $mostlyopaque (TRANSLUCENT_TWOPASS flag = two render passes).

Usage: python write_qc.py info.json smd_folder output.qc [--modelname path.mdl]
       [--lods 10,20,40] [--phys-bones Hips,...] [--mass 18]
"""
import argparse
import json
import os


def main():
    p = argparse.ArgumentParser()
    p.add_argument("info")
    p.add_argument("folder")
    p.add_argument("output")
    p.add_argument("--modelname")
    p.add_argument("--lods", default="10,20,40")
    p.add_argument("--phys-bones", default="")
    p.add_argument("--mass", type=float, default=18)
    a = p.parse_args()
    info = json.load(open(a.info, encoding="utf-8"))
    d = a.folder
    ref = info["bodyparts"][0]["models"][0]
    stem = os.path.splitext(ref)[0]
    L = []
    w = L.append
    w(f'$modelname "{a.modelname or info["name"]}"')
    for inc in info["includemodels"]:
        w(f'$includemodel "{inc[len("models/"):] if inc.startswith("models/") else inc}"')
    w("")
    for bp in info["bodyparts"]:
        w(f'$bodygroup "{bp["name"]}"\n{{')
        for m in bp["models"]:
            w('\tblank' if m is None else f'\tstudio "{m}"')
        w("}")
    w("")
    w(f'$surfaceprop "{info["surfaceprop"]}"')
    w('$contents "solid"')
    for cd in info["cdmaterials"]:
        w(f'$cdmaterials "{cd}"')
    w("")
    for at in info["attachments"]:
        x, y, z = at["pos"]
        pi, ya, ro = at["angles"]
        w(f'$attachment "{at["name"]}" "{at["bone"]}" {x:.6f} {y:.6f} {z:.6f} rotate {pi:.6f} {ya:.6f} {ro:.6f}')
    w("")
    for hs in info["hitboxsets"]:
        w(f'$hboxset "{hs["name"]}"')
        for b in hs["boxes"]:
            mn, mx = b["min"], b["max"]
            w(f'$hbox {b["group"]} "{b["bone"]}" {mn[0]:.6f} {mn[1]:.6f} {mn[2]:.6f} {mx[0]:.6f} {mx[1]:.6f} {mx[2]:.6f}')
    w("")
    lods = [x for x in a.lods.split(",") if x]
    last = None
    for k, dist in enumerate(lods, 1):
        f = f"{stem}_lod{k}.smd"
        if not os.path.exists(os.path.join(d, f)):
            break
        # Valve wiki: floating-point thresholds must be quoted
        value = dist if float(dist).is_integer() else f'"{dist}"'
        w(f"$lod {value}\n{{\n\treplacemodel \"{ref}\" \"{f}\"\n}}")
        last = f
    if last:
        w(f"$shadowlod\n{{\n\treplacemodel \"{ref}\" \"{last}\"\n}}")
    w("")
    for s in info["sequences"]:
        act = f' activity "{s["activity"]}" {s["actweight"]}' if s["activity"] else ""
        w(f'$sequence "{s["name"]}" "{ref}" fps 30{act}')
    phys = f"{stem}_phys.smd"
    if os.path.exists(os.path.join(d, phys)) and a.phys_bones:
        bones = a.phys_bones.split(",")
        w("")
        w(f'$collisionjoints "{phys}"\n{{')
        w(f"\t$mass {a.mass:g}\n\t$inertia 1\n\t$damping 0\n\t$rotdamping 0")
        w(f'\t$rootbone "{bones[0]}"')
        for b in bones[1:]:
            for axis in "xyz":
                w(f'\t$jointconstrain "{b}" {axis} limit 0 0 0')
        w("}")
    with open(a.output, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    print(open(a.output, encoding="utf-8").read())


if __name__ == "__main__":
    main()
