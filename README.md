# gmod-outfit-toolkit

Tools to audit, optimize, build and **validate** Garry's Mod outfit models (Source engine
`.mdl` / `.smd`), driven from the command line with Blender in background mode.

Every tool ships with a test against a known reference, and every validator with a
**negative control**: a deliberately broken input it must reject. A tool is only listed
here once its tests pass.

## What's inside

| Tool | Runs in | What it does | Validated by |
|---|---|---|---|
| `audit_mdl.py` | Python | Reads `.mdl` / `.vvd` / `.vtx` / `.phy`: flags, bodygroups, materials, LODs, triangle counts, unweighted bones, physics solids | Known values of the reference model |
| `smd_weights.py` | Python | Per-bone weight distribution + bounding box of a `.smd` | Known values |
| `mdl_to_smd.py` | Python | Decompiles a v48 `.mdl` (all bodyparts, LOD0) to `.smd` + `info.json` (attachments, hitboxes, sequences) without Crowbar | 100 % identical to Crowbar 0.74 output: geometry, UVs, normals, weights, winding, skeleton |
| `smd_compare.py` | Python | Order-independent comparison of two `.smd` (positions, UVs, normals, weights) | Detects a single moved vertex |
| `smd_normals.py` | Python | Normal / winding consistency per material and side | Rejects half-flipped normals |
| `write_qc.py` | Python | Generates a `.qc`: bodygroups, attachments, hitboxes, `$lod`, `$shadowlod`, locked `$collisionjoints`, no `$mostlyopaque` | Structure check (compilation not tested yet) |
| `optimize_outfit.py` | Blender | Symmetric decimation, LOD chain, physics mesh | Round trip without decimation = original |
| `validate_lods.py` | Blender | Compares LODs to the original: surface distance at rest and posed, flipped normals, areas, renders | Rejects LODs with transferred (flipped) normals |
| `validate_poses.py` | Blender | Poses the outfit (walk, run, crouch, arms up, twist), measures edge stretch against a known-good reference, renders | Rejects broken weights |
| `validate_faces.py` | Blender | Casts rays from outside: backfaces seen from outside = holes in game | Rejects an inside-out model |
| `tailor.py` | Blender | Procedural garment building: rings, lofts, tubes, bone-chain weights, mirroring, solidify | Example garment passes all validators |
| `smd_blender.py` | Blender | SMD import (Blender Source Tools) and export reusing a reference skeleton | Round trip |

`examples/example_robe.py` builds a simple garment (tunic, sleeves, belt, wide trousers,
boots) with `tailor.py` on any Mixamo-style skeleton.

## Requirements

- Windows, PowerShell 5.1+
- [Blender](https://www.blender.org/) 5.x (its bundled Python runs the pure-Python tools too)
- [Blender Source Tools](https://github.com/Artfunkel/BlenderSourceTools) (master branch, Blender 5 fixes), enabled
- To compile models: `studiomdl.exe` from Garry's Mod (`GarrysMod/bin`)

## Usage

```powershell
$bl = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
$py = "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe"

# Audit and decompile
& $py tools/audit_mdl.py path/to/model.mdl
& $py tools/mdl_to_smd.py path/to/model.mdl out/decompiled

# Optimize: LOD0 20k tris + 3 LODs + physics mesh, then validate
& $bl -b --python tools/optimize_outfit.py -- --smd out/decompiled/body.smd --out out/optim --tris 20000,10000,5000,2500 --phys 1500 --phys-bones Hips,Spine,Spine1,Head
& $bl -b --python tools/validate_lods.py -- --ref out/decompiled/body.smd --out out/optim/check out/optim/body.smd out/optim/body_lod1.smd

# Write the QC
& $py tools/write_qc.py out/decompiled/info.json out/optim out/optim/model.qc --phys-bones Hips,Spine,Spine1,Head

# Build a garment and validate it
& $bl -b --python examples/example_robe.py -- --skeleton out/decompiled/body.smd --out out/robe --render
& $bl -b --python tools/validate_poses.py -- --smd out/robe/example_robe.smd --out out/robe/poses
& $py tools/smd_normals.py out/robe/example_robe.smd
& $bl -b --python tools/validate_faces.py -- --smd out/robe/example_robe.smd
```

## Tests

```powershell
& .\tests\run_tests.ps1     # 20 tests, about 1 minute
```

The suite needs a local reference model in `tests/fixtures` (not distributed, see
[tests/fixtures/README.md](tests/fixtures/README.md)). Set `$env:BLENDER` if Blender is not
installed in the default location.

## Lessons baked into the tools

- **Normals after decimation**: recompute them (smooth by angle). Transferring them from the
  original picks the back side of multi-layer cloth and creates dark patches (1.6 % flipped
  corners vs 0.11 % on the original). Surface-distance metrics do not see this defect: the
  flipped-normal measure and the renders do.
- **Pose validation**: whole-mesh percentiles depend on the garment's composition, so the
  verdict relies on maximum stretch, p99 stretch and the rate of severe deformations,
  compared to an outfit known to work in game.
- **Wide garments**: blend hips into the leg chain progressively from the waist down, use the
  twist ("Bend") bones, and give knees enough rings; hanging cords stay on the hips only.
- **`$mostlyopaque`** sets `TRANSLUCENT_TWOPASS` (two render passes): avoid it, prefer
  `$alphatest` over `$translucent` in materials.
- Ship only `.mdl`, `.vvd`, `.dx90.vtx`, `.phy`: Garry's Mod does not use `.dx80.vtx` / `.sw.vtx`.

## License

MIT
