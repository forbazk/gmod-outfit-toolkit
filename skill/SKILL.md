---
name: gmod-outfit
description: Garry's Mod outfit workflow — diagnose (doctor), optimize in one command (pipeline), audit .blend files, check rigs, audit textures (.vtf/.vmt), pack releases, build garments procedurally, validate (LODs, poses, normals, backfaces), write the .qc. Use whenever a task touches a GMod outfit or .mdl/.vvd/.vtx/.phy/.smd/.qc/.vtf/.vmt/.blend outfit files.
---

# GMod outfit toolkit

Entry point: `gmodtk.ps1 <command>` at the repository root (finds Blender and its Python).

## Rule: nothing is used unless validated

- Run `gmodtk.ps1 test` after ANY change to a tool; it must end with `N/N tests OK`.
- A new tool needs a test against a known reference AND a negative control proving the test can
  fail. Document it in the README table.

## Workflow

1. `doctor <model|folder>`: score, findings, fixes, gains. On a server folder it ranks outfits.
2. Optimizing a compiled outfit: `pipeline <model.mdl> <out>` (decompile, LODs, weight cleanup,
   physics, validation, QC, report). Read `report.md` and look at the validation renders.
3. Working from a `.blend`: `blend-audit <file.blend>` first (transforms, weights, images),
   `rig-check <outfit.smd> <target.smd>` when the skeleton may differ from the server's.
4. Building a garment: a per-outfit script on top of `tailor.py` (see `examples/example_robe.py`),
   then `validate-poses`, `normals`, `validate-faces --with face.smd` at every iteration.
5. Compile with studiomdl (command printed by `pipeline`), then `doctor` again, then
   `pack <model.mdl> <out>` for the release folder.

## Pitfalls

- Never transfer normals from the original after decimation (dark patches on layered cloth).
- Blender Source Tools in background mode: never call `read_factory_settings`; import several
  SMDs with `append="NEW_ARMATURE"`.
- Crowbar SMD lines are indented: trim before splitting.
- Pose verdicts are relative to a known-good reference; whole-mesh percentiles depend on the
  garment's composition, use max stretch and severe-deformation rates.
- PowerShell 5.1: save `.ps1` with accents as UTF-8 with BOM; always `@(...).Count`.
