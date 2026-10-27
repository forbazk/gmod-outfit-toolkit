"""One command from a compiled outfit to an optimized, validated, ready-to-compile project.

Steps: doctor (before) -> decompile -> decimate + LODs + weight cleanup + physics mesh
       -> validate every LOD -> write the QC (all bodygroups, LODs, shadow LOD, physics bones
       read from the original .phy) -> report.md (before / after, verdicts, compile command).

Usage: python pipeline.py model.mdl output_folder [--tris 20000,10000,5000,2500] [--min-weight 0.02]
       [--phys 1500] [--materials materials_root]
Blender is found through $BLENDER or the default install folder. Exit 0 only if every LOD passes.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from audit_mdl import read_phy  # noqa: E402
from doctor import diagnose, kb  # noqa: E402


def find_blender():
    if os.environ.get("BLENDER"):
        return os.environ["BLENDER"]
    found = sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe"), reverse=True)
    if not found:
        sys.exit("Blender not found: set the BLENDER environment variable")
    return found[0]


def run(cmd, label):
    print(f"--- {label}")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = p.stdout + p.stderr
    if "Traceback" in out:
        print(out[-3000:])
        sys.exit(f"{label} failed")
    return out


def phys_bones(mdl):
    phy = mdl[:-4] + ".phy"
    if not os.path.exists(phy):
        return []
    text = read_phy(phy)["text"]
    return re.findall(r'solid \{\s*"index" "\d+"\s*"name" "([^"]+)"', text)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("model")
    p.add_argument("out")
    p.add_argument("--tris", default="20000,10000,5000,2500")
    p.add_argument("--min-weight", default="0.02")
    p.add_argument("--phys", default="1500")
    p.add_argument("--materials")
    a = p.parse_args()
    bl, py = find_blender(), sys.executable
    os.makedirs(a.out, exist_ok=True)
    dec, opt = os.path.join(a.out, "decompiled"), os.path.join(a.out, "optimized")
    before = diagnose(a.model, a.materials)
    run([py, "-I", os.path.join(HERE, "mdl_to_smd.py"), a.model, dec], "decompile")
    info = json.load(open(os.path.join(dec, "info.json"), encoding="utf-8"))
    main_smd = os.path.join(dec, info["bodyparts"][0]["models"][0])
    bones = phys_bones(a.model)
    cmd = [bl, "-b", "--python", os.path.join(HERE, "optimize_outfit.py"), "--", "--smd", main_smd, "--out", opt,
           "--tris", a.tris, "--min-weight", a.min_weight]
    if bones:
        cmd += ["--phys", a.phys, "--phys-bones", ",".join(bones)]
    run(cmd, "optimize")
    report = json.load(open(os.path.join(opt, "report.json"), encoding="utf-8"))
    lods = [os.path.join(opt, x["file"]) for x in report["lods"]]
    val = run([bl, "-b", "--python", os.path.join(HERE, "validate_lods.py"), "--", "--ref", main_smd,
               "--out", os.path.join(opt, "validation")] + lods, "validate LODs")
    verdicts = re.findall(r"VERDICT (\S+) (PASS|FAIL) (.*)", val)
    for bp in info["bodyparts"][1:]:
        for m in bp["models"]:
            if m:
                shutil.copyfile(os.path.join(dec, m), os.path.join(opt, m))
    qc = os.path.join(opt, os.path.splitext(os.path.basename(a.model))[0] + ".qc")
    cmd = [py, "-I", os.path.join(HERE, "write_qc.py"), os.path.join(dec, "info.json"), opt, qc]
    if bones:
        cmd += ["--phys-bones", ",".join(bones)]
    run(cmd, "write QC")
    ok = bool(verdicts) and all(v[1] == "PASS" for v in verdicts)
    tri_lods = [x["tris"] for x in report["lods"]]
    pruned = sum(x.get("pruned_influences", 0) for x in report["lods"][:1])
    lines = [f"# Optimization report: {os.path.basename(a.model)}", "",
             "| | Before | After |", "|---|---:|---:|",
             f"| Doctor score | {before['score']}/100 | (recompile, then run doctor) |",
             f"| Triangles close up | {before.get('tris_heaviest', 0):,} | {tri_lods[0]:,} (+ unchanged bodygroups) |",
             f"| LODs | {before.get('lods', 1)} | {len(tri_lods)} ({' / '.join(f'{t:,}' for t in tri_lods)}) |",
             f"| Shadow LOD | no | {tri_lods[-1]:,} triangles |",
             f"| Useless files shipped | {kb(before['wasted_bytes'])} | 0 KB (ship .mdl .vvd .dx90.vtx .phy) |",
             f"| $mostlyopaque | {'yes' if 'TRANSLUCENT_TWOPASS' in before.get('flags', []) else '-'} | no |",
             f"| Invisible bone influences removed | - | {pruned:,} |",
             f"| Physics bones | {len(bones)} | {len(bones)} (from the original .phy) |", "",
             "## Validation", ""]
    lines += [f"- `{v[0]}`: **{v[1]}** {v[2] if v[2] != '[]' else ''}" for v in verdicts]
    lines += ["", f"Renders: `{os.path.join(opt, 'validation')}`", "", "## Doctor findings before optimization", ""]

    def status(x):
        if x["area"] == "geometry" or "TRANSLUCENT_TWOPASS" in x["problem"]:
            return "**fixed by this pipeline**"
        if x["area"] == "download":
            return "**fixed when packing** (pack.py)"
        return "still to do"
    lines += [f"- {x['severity']}: {x['problem']} -> {x['fix']} — {status(x)}" for x in before["findings"]]
    lines += ["", "## Compile", "", "```", f'studiomdl.exe -game "<GarrysMod>\\garrysmod" -nop4 "{qc}"', "```",
              "", "Then: `pack.py` on the compiled model for a clean release folder."]
    open(os.path.join(a.out, "report.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("RESULT", "OK" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
