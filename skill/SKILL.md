---
name: gmod-outfit
description: Garry's Mod outfit workflow — audit a Source .mdl/.smd, decompile without Crowbar, optimize (decimation + LODs + physics), build garments procedurally, validate (poses, normals, backfaces), write the .qc. Use whenever a task touches a GMod outfit or .mdl/.vvd/.vtx/.phy/.smd/.qc files.
---

# GMod outfit toolkit

Tools live in `tools/` of the gmod-outfit-toolkit repository. Blender 5.x with Blender Source
Tools is required; use Blender's bundled Python for the pure-Python tools.

## Rule: nothing is used unless validated

- Run `tests/run_tests.ps1` after ANY change to a tool; it must end with `N/N tests OK`.
- A new tool needs a test against a known reference AND a negative control proving the
  test can fail. Document it in the README table.

## Workflow

1. `audit_mdl.py` on the model: list optimization points (triangles, missing LODs,
   `TRANSLUCENT_TWOPASS`, unweighted bones, embedded bodygroups, useless `.phy`/hitboxes,
   `.dx80.vtx`, generic material names).
2. `mdl_to_smd.py` to get every bodypart as `.smd` + `info.json`.
3. `optimize_outfit.py` (LOD0 ~20k tris + LODs + physics mesh), then `validate_lods.py`:
   every file must PASS, and look at the renders (zoom on belts and hems, posed).
4. Building a garment: a per-outfit script using `tailor.py` (see `examples/example_robe.py`):
   left pieces, `mirror`, center pieces, `join`, export with `smd_blender.write_smd`.
5. Validate every iteration: `validate_poses.py` + `smd_normals.py` +
   `validate_faces.py --with face.smd` + look at the renders.
6. `write_qc.py`, compile with studiomdl, re-audit the compiled model.

## Pitfalls

- Blender Source Tools in background mode: never call `read_factory_settings` (it disables the
  add-on); import several SMDs with `append="NEW_ARMATURE"`.
- Crowbar SMD lines are indented: `.Trim()` before splitting.
- Per-face coloring (`assign_where`) is stair-stepped: preview only, textures do the real work.
- Diagnosing poses: when many pieces sit on `Hips`, locate the offending edges by position
  before fixing weights.
- PowerShell 5.1: save `.ps1` with accents as UTF-8 with BOM; always `@(...).Count`.
