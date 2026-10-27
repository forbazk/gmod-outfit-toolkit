# gmod-outfit-toolkit launcher: finds Blender (and its bundled Python) and runs a tool.
# Usage: .\gmodtk.ps1 <command> [arguments]       (.\gmodtk.ps1 help for the list)
param([Parameter(Position = 0)][string]$Command = 'help', [Parameter(ValueFromRemainingArguments = $true)]$Rest)
$env:PYTHONIOENCODING = 'utf-8'
$bl = if ($env:BLENDER) { $env:BLENDER } else {
    (Get-ChildItem "C:\Program Files\Blender Foundation\Blender *\blender.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1).FullName
}
if (-not $bl) { Write-Host 'Blender not found: install Blender 5.x or set $env:BLENDER'; exit 1 }
$env:BLENDER = $bl
$py = (Get-ChildItem (Join-Path (Split-Path $bl) "*\python\bin\python.exe") | Select-Object -First 1).FullName
$t = Join-Path $PSScriptRoot 'tools'
$python = @{
    'doctor' = 'doctor.py'; 'pipeline' = 'pipeline.py'; 'decompile' = 'mdl_to_smd.py'; 'audit' = 'audit_mdl.py'
    'qc' = 'write_qc.py'; 'pack' = 'pack.py'; 'rig-check' = 'rig_check.py'; 'normals' = 'smd_normals.py'
    'compare' = 'smd_compare.py'; 'weights' = 'smd_weights.py'; 'vtf' = 'vtf.py'; 'materials' = 'materials.py'
    'retarget' = 'retarget.py'
}
$blender = @{
    'optimize' = 'optimize_outfit.py'; 'validate-lods' = 'validate_lods.py'; 'validate-poses' = 'validate_poses.py'
    'validate-faces' = 'validate_faces.py'; 'texture' = 'texture.py'
}
if ($python.ContainsKey($Command)) {
    & $py -I (Join-Path $t $python[$Command]) @Rest; exit $LASTEXITCODE
}
if ($blender.ContainsKey($Command)) {
    & $bl -b --python (Join-Path $t $blender[$Command]) -- @Rest 2>&1 | Where-Object { "$_" -notmatch '^(Blender \d|Read prefs|SMD |- |Info: |\d\d:\d\d\.\d+ )' }
    exit $LASTEXITCODE
}
if ($Command -eq 'blend-audit') {
    $file, $more = $Rest
    & $bl -b $file --python (Join-Path $t 'blend_audit.py') -- @more 2>&1 | Where-Object { "$_" -match '^(ARMATURE|MESHES|FINDING|RESULT)' }
    exit $LASTEXITCODE
}
if ($Command -eq 'blend-export') {
    $file, $more = $Rest
    & $bl -b $file --python (Join-Path $t 'blend_to_smd.py') -- @more 2>&1 | Where-Object { "$_" -match '^EXPORT' }
    exit $LASTEXITCODE
}
if ($Command -eq 'test') { & (Join-Path $PSScriptRoot 'tests\run_tests.ps1'); exit $LASTEXITCODE }
@"
gmod-outfit-toolkit  (Blender: $bl)

  pipeline <model.mdl> <out>        doctor -> decompile -> optimize -> validate -> QC -> report (one command)
  doctor <model.mdl|folder>         diagnosis, score, fixes and gains; a folder ranks every outfit
  pack <model.mdl> <out>            clean release folder (no .dx80/.sw), missing materials reported
  texture <in.png> <out.vtf> [--vmt out.vmt --material-path p] [--max 2048] [--normal]
                                    image -> VTF (DXT1/DXT5 auto, mipmaps, power of two) + VMT
  blend-audit <file.blend>          export mistakes: transforms, weights, missing images, rig
  rig-check <outfit.smd> <rig.smd>  skeleton compatibility (names, parents, rest pose)
  blend-export <file.blend> --out <outfit.smd>   .blend -> .smd, transforms baked, weights limited to 3
  retarget <outfit.smd> <target_rig.smd> <out.smd>   refit + re-skin onto another rig (ValveBiped -> server)
  decompile <model.mdl> <out>       .mdl -> .smd + info.json (Crowbar-identical)
  optimize -- --smd ... --out ...   decimation + LODs + weight cleanup + physics mesh
  validate-lods | validate-poses | validate-faces   quality gates (see README)
  qc | audit | normals | compare | weights | vtf | materials    single-purpose tools
  test                              run the test suite
"@
