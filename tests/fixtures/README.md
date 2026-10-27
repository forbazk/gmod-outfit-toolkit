# Test fixtures

The test suite runs against a **reference outfit model that works in game**. Models are
third-party assets, so they are not distributed: put your own here (they are git-ignored).

| File | What it is |
|---|---|
| `reference.mdl`, `reference.vvd`, `reference.dx90.vtx`, `reference.phy` | A compiled outfit (Source MDL v48) with a Mixamo-style skeleton (`Hips`, `Spine`, `Spine1`, `Neck`, `Head`, `Left/RightArm`, `Left/RightForeArm`, `Left/RightUpLeg`, ...) |
| `reference.smd` | The main body mesh of that model, decompiled with **Crowbar 0.74** (ground truth for `mdl_to_smd.py`) |
| `reference_face.smd` | Its face bodygroup mesh, used as an occluder by `validate_faces.py` |

Committed files:

- `expected.json`: known values of the reference model (triangle count, bones, attachments...).
  Update them by hand from `audit_mdl.py` / `mdl_to_smd.py` output if you switch references.
- `reference_poses.json`: pose deformation statistics of the reference, used by
  `validate_poses.py` as the "known good" baseline. Regenerate it with:

```powershell
blender -b --python tools/validate_poses.py -- --smd tests/fixtures/reference.smd --out out/ref --no-render --write-reference tests/fixtures/reference_poses.json
```
