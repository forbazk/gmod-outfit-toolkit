# gmod-outfit-toolkit

Audit, optimize, build and **validate** Garry's Mod outfit models (Source engine `.mdl` / `.smd`
/ `.blend` / `.vtf`) from the command line, with Blender running in background mode.

Built for outfit makers and server owners: one command turns a heavy compiled outfit into an
optimized, validated, ready-to-compile project, and one command ranks every outfit of a server
by cost.

Every tool ships with a test against a known reference, and every validator with a **negative
control**: a deliberately broken input it must reject. A tool is only listed here once its tests
pass (36 tests).

## Quick start

```powershell
.\gmodtk.ps1 doctor  path\to\addon\models             # rank every outfit: score, findings, fixes, gains
.\gmodtk.ps1 pipeline path\to\outfit.mdl out\outfit    # optimize + validate + QC + report, ~25 s
.\gmodtk.ps1 blend-audit path\to\outfit.blend         # catch export mistakes before compiling
.\gmodtk.ps1 pack    path\to\outfit.mdl out\release   # clean release folder, nothing useless shipped
.\gmodtk.ps1 help
```

`gmodtk.ps1` finds Blender (or uses `$env:BLENDER`) and its bundled Python: nothing else to install.

### What `pipeline` does to a real outfit (54k-triangle body_upper, no LOD)

| | Before | After |
|---|---:|---:|
| Triangles close up | 54,825 | 20,000 |
| LODs | 1 | 4 (20,000 / 10,000 / 5,000 / 2,500) |
| Shadow LOD | no | 2,500 triangles |
| Useless files shipped | 655 KB | 0 KB |
| `$mostlyopaque` (two render passes) | yes | no |
| Invisible bone influences | 966 | removed |
| Physics bones | 18 | 18 (read from the original `.phy`) |

Every LOD is validated (surface distance at rest and posed, flipped normals, areas) and rendered.

## Tools

| Command / tool | What it does | Validated by |
|---|---|---|
| `pipeline.py` | doctor -> decompile -> decimate + LODs + weight cleanup + physics mesh -> validate -> QC -> before/after report | Reference outfit: 4 LODs PASS, QC with LODs and physics bones from the `.phy` |
| `doctor.py` | Diagnosis of a model or a whole folder: download size and wasted files, triangles per LOD / bodygroup, draw calls, LODs, translucency, skinning, physics, every texture (missing, resolution, compression, mipmaps, VRAM). Severity, fix and expected gain per finding, 0-100 score, ranking | Reference findings; healthy vs broken materials; folder ranking |
| `pack.py` | Release folder in addon layout: model files + referenced materials/textures, no `.dx80.vtx` / `.sw.vtx`, missing files reported | Healthy materials exit 0; missing material exit 1 |
| `blend_audit.py` | `.blend` checks: unapplied transforms, unskinned meshes, unweighted vertices, >3 influences, stray vertex groups, missing UVs / images, oversized or non power-of-two images, rig convention | Healthy `.blend` OK; broken `.blend` with 6 planted defects FAIL |
| `rig_check.py` | Skeleton compatibility: naming convention (ValveBiped / Mixamo-style), missing bones, parents, rest-pose world positions | World positions = Blender's to 0.0001 u; moved bone and ValveBiped controls FAIL |
| `vtf.py` | `.vtf` header reader: size, format, mipmaps, flags, VRAM, truncation | Spec-built files; 10 real VTF files (7.1/7.2/7.5) match their byte size exactly |
| `materials.py` | `.vmt` parser and engine-like material lookup through `$cdmaterials` (case-insensitive) | Through doctor / pack tests |
| `mdl_to_smd.py` | Decompiles a v48 `.mdl` (all bodyparts, LOD0) to `.smd` + `info.json` (attachments, hitboxes, sequences) without Crowbar | 100 % identical to Crowbar 0.74: geometry, UVs, normals, weights, winding, skeleton |
| `optimize_outfit.py` | Symmetric decimation, LOD chain, `--min-weight` cleanup of invisible influences, physics mesh | Round trip = original; pruning keeps LOD PASS |
| `validate_lods.py` | LODs vs original: surface distance at rest and posed, flipped normals, areas, renders | Rejects LODs with transferred (flipped) normals |
| `validate_poses.py` | Poses the outfit (walk, run, crouch, arms up, twist): stretch vs a known-good reference, renders | Rejects broken weights |
| `validate_faces.py` | Rays from outside: backfaces seen from outside = holes in game | Rejects an inside-out model |
| `write_qc.py` | `.qc` with bodygroups, attachments, hitboxes, `$lod`, `$shadowlod`, locked `$collisionjoints`, no `$mostlyopaque` | Structure check |
| `tailor.py` | Procedural garments: rings, lofts, tubes, bone-chain weights, mirroring, solidify | Example garment passes every validator |
| `audit_mdl.py`, `smd_weights.py`, `smd_compare.py`, `smd_normals.py`, `smd_blender.py` | Raw audit, weight distribution, SMD comparison, normal consistency, SMD I/O in Blender | Known values, negative controls, round trip |

`examples/example_robe.py` builds a simple garment (tunic, sleeves, belt, wide trousers, boots)
with `tailor.py` on any Mixamo-style skeleton.

## Requirements

- Windows, PowerShell 5.1+
- [Blender](https://www.blender.org/) 5.x (its bundled Python runs the pure-Python tools too)
- [Blender Source Tools](https://github.com/Artfunkel/BlenderSourceTools) (master branch, Blender 5 fixes), enabled
- To compile: `studiomdl.exe` from Garry's Mod (`GarrysMod/bin`). `pipeline` prints the exact command.

## Tests

```powershell
.\gmodtk.ps1 test        # 36 tests, about 3 minutes
```

The suite needs a local reference model in `tests/fixtures` (not distributed, see
[tests/fixtures/README.md](tests/fixtures/README.md)). Optional: real `.vtf` files in
`tests/fixtures/vtf_real/` enable the real-file texture test.

## Knowledge baked into the tools

- **No LOD is the most expensive mistake**: a 50k-triangle outfit costs the same at 100 m as up
  close. Four LODs plus a shadow LOD cut far-away cost by ~95 %.
- **Normals after decimation**: recompute them (smooth by angle). Transferring them from the
  original picks the back side of multi-layer cloth and creates dark patches (1.6 % flipped
  corners vs 0.11 % on the original). Surface-distance metrics do not see this: the
  flipped-normal measure and the renders do.
- **Invisible influences**: ~5 % of vertices of a typical outfit carry bone weights under 5 %.
  They change nothing visually but count toward bones per vertex and per hardware batch.
- **Textures** usually outweigh the mesh: uncompressed BGRA8888 is 4x DXT5 and 8x DXT1, a 4096
  texture is 4x a 2048, and missing mipmaps cause shimmering at distance.
- **`$mostlyopaque`** sets `TRANSLUCENT_TWOPASS` (drawn in both opaque and translucent passes);
  prefer `$alphatest` over `$translucent`.
- **Ship only `.mdl`, `.vvd`, `.dx90.vtx`, `.phy`**: Garry's Mod does not use `.dx80.vtx` / `.sw.vtx`.
- **Unapplied transforms in Blender** (even a 1.011 scale) silently resize or offset the outfit in game.
- **Pose validation**: whole-mesh percentiles depend on the garment's composition, so the verdict
  relies on maximum stretch, p99 stretch and the rate of severe deformations, compared to an
  outfit known to work in game.
- **Wide garments**: blend hips into the leg chain progressively from the waist down, use the
  twist ("Bend") bones, give knees enough rings; hanging cords stay on the hips only.

## License

MIT
