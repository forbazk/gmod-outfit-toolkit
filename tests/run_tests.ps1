# Test suite for the toolkit. Run it after ANY change to a tool.
# Every tool is checked against a known reference, and every validator against a negative control
# (a deliberately broken input it must reject).
#
# Requirements: Blender 5.x with Blender Source Tools enabled, and the local reference model in
# tests/fixtures (see tests/fixtures/README.md). Set $env:BLENDER if Blender is not in the default path.
# Usage: & .\tests\run_tests.ps1
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$bl = if ($env:BLENDER) { $env:BLENDER } else {
    (Get-ChildItem "C:\Program Files\Blender Foundation\Blender *\blender.exe" | Sort-Object FullName -Descending | Select-Object -First 1).FullName
}
$py = (Get-ChildItem (Join-Path (Split-Path $bl) "*\python\bin\python.exe") | Select-Object -First 1).FullName
$root = Join-Path $PSScriptRoot '..' | Resolve-Path
$t = "$root\tools"
$fx = "$PSScriptRoot\fixtures"
$tmp = Join-Path $env:TEMP "gmod-outfit-tests-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Force $tmp | Out-Null
$mdl = "$fx\reference.mdl"
$smd = "$fx\reference.smd"
$face = "$fx\reference_face.smd"
foreach ($f in $mdl, "$fx\reference.vvd", "$fx\reference.dx90.vtx", "$fx\reference.phy", $smd, $face) {
    if (-not (Test-Path $f)) { Write-Host "Missing fixture: $f (see tests/fixtures/README.md)"; exit 1 }
}
$x = Get-Content "$fx\expected.json" -Raw | ConvertFrom-Json
Write-Host "Blender: $bl"
$results = @()

function Test($name, [scriptblock]$block) {
    try { $ok = & $block } catch { $ok = $false; Write-Host $_ }
    $script:results += [pscustomobject]@{ Test = $name; Result = $(if ($ok) { 'OK' } else { 'FAIL' }) }
    Write-Host ("[{0}] {1}" -f $(if ($ok) { 'OK' } else { 'FAIL' }), $name)
}

Test 'audit_mdl: known values (tris, bones, unweighted bones, flag)' {
    $a = (& $py -I "$t\audit_mdl.py" $mdl) -join "`n"
    ($a -match "tris/LOD \[$($x.vtx_tris_lod0)\]") -and ($a -match "bones: $($x.bones)") -and
    ($a -match "bones without any weight \($($x.unweighted_bones)\)") -and ($a -match $x.mdl_flag)
}

Test 'smd_weights: zero-weight bone and bbox' {
    $a = (& $py -I "$t\smd_weights.py" $smd $x.zero_weight_bone) -join "`n"
    ($a -match "$($x.zero_weight_bone)\s+verts\s+0 ") -and ($a -match [regex]::Escape("max $($x.bbox_max)"))
}

Test 'mdl_to_smd: identical to the Crowbar SMD (geometry, UVs, normals, weights)' {
    & $py -I "$t\mdl_to_smd.py" $mdl "$tmp\decomp" | Out-Null
    $j = Get-Content "$tmp\decomp\info.json" -Raw | ConvertFrom-Json
    $script:main = "$tmp\decomp\$($j.bodyparts[0].models[0])"
    & $py -I "$t\smd_compare.py" $smd $script:main | Out-Null
    $LASTEXITCODE -eq 0
}

Test 'mdl_to_smd: identical skeleton (zero difference)' {
    $sk = { param($f) $s = $false; foreach ($l in Get-Content $f) { if ($l -match '^skeleton') { $s = $true; continue }; if ($s -and $l -match '^end') { break }; if ($s -and $l -notmatch 'time') { , ($l.Trim() -split '\s+' | % { [double]$_ }) } } }
    $a = & $sk $smd; $b = & $sk $script:main
    $max = 0; for ($i = 0; $i -lt $a.Count; $i++) { for ($j = 1; $j -lt 7; $j++) { $max = [Math]::Max($max, [Math]::Abs($a[$i][$j] - $b[$i][$j])) } }
    ($a.Count -eq $x.bones) -and ($max -lt 1e-5)
}

Test 'mdl_to_smd: info.json (attachments, hitboxes, bodygroups)' {
    $j = Get-Content "$tmp\decomp\info.json" -Raw | ConvertFrom-Json
    ($j.attachments.Count -eq $x.attachments) -and ($j.hitboxsets[0].boxes.Count -eq $x.hitboxes) -and
    ($j.bodyparts.Count -eq $x.bodygroups)
}

Test 'smd_compare: detects a difference (negative control)' {
    $lines = Get-Content $smd
    $i = [Array]::IndexOf($lines, 'triangles') + 2
    $p = $lines[$i].Trim() -split '\s+'; $p[1] = [string]([double]$p[1] + 1); $lines[$i] = $p -join ' '
    $lines | Set-Content "$tmp\altered.smd" -Encoding ascii
    & $py -I "$t\smd_compare.py" $smd "$tmp\altered.smd" | Out-Null
    $LASTEXITCODE -eq 1
}

Test 'optimize_outfit: Blender round trip without decimation = original' {
    & $bl -b --python "$t\optimize_outfit.py" -- --smd $smd --out "$tmp\rt" --tris 0 2>&1 | Out-Null
    & $py -I "$t\smd_compare.py" $smd "$tmp\rt\reference.smd" | Out-Null
    $LASTEXITCODE -eq 0
}

Test 'optimize_outfit: LODs + physics mesh, no unweighted vertex' {
    & $bl -b --python "$t\optimize_outfit.py" -- --smd $smd --out "$tmp\opt" --tris $x.lod_targets --phys 1500 --phys-bones $x.physics_bones 2>&1 | Out-Null
    $r = Get-Content "$tmp\opt\report.json" -Raw | ConvertFrom-Json
    $targets = $x.lod_targets -split ',' | % { [int]$_ }
    $ok = $true
    for ($k = 0; $k -lt $targets.Count; $k++) { $ok = $ok -and ($r.lods[$k].tris -le $targets[$k]) -and ($r.lods[$k].tris -ge $targets[$k] * 0.98) }
    $ok -and (@($r.lods | ? unweighted -gt 0).Count -eq 0) -and ($r.phys.unweighted -eq 0)
}

Test 'optimize_outfit --normals nearest: produces the known defect (for the control)' {
    & $bl -b --python "$t\optimize_outfit.py" -- --smd $smd --out "$tmp\nearest" --tris ($x.lod_targets -split ',')[0] --normals nearest 2>&1 | Out-Null
    Test-Path "$tmp\nearest\reference.smd"
}

Test 'validate_lods: every LOD PASS, nearest control FAIL (flipped normals)' {
    $n = ($x.lod_targets -split ',').Count
    $f = @("$tmp\opt\reference.smd") + (1..($n - 1) | % { "$tmp\opt\reference_lod$_.smd" }) + @("$tmp\nearest\reference.smd")
    $v = (& $bl -b --python "$t\validate_lods.py" -- --ref $smd --out "$tmp\val" @f 2>&1) -join "`n"
    (([regex]::Matches($v, 'VERDICT opt\\\S+ PASS')).Count -eq $n) -and ($v -match 'VERDICT nearest\\\S+ FAIL \[.flipped normals')
}

Test 'write_qc: bodygroups, $lod, $shadowlod, attachments, $hbox, collisionjoints, no $mostlyopaque' {
    Copy-Item "$tmp\decomp\*.smd" "$tmp\opt" -Exclude (Split-Path $script:main -Leaf)
    Copy-Item "$tmp\opt\reference.smd" "$tmp\opt\$(Split-Path $script:main -Leaf)" -Force
    $stem = [IO.Path]::GetFileNameWithoutExtension($script:main)
    Get-ChildItem "$tmp\opt\reference_*.smd" | % { Copy-Item $_.FullName ("$tmp\opt\" + ($_.Name -replace '^reference', $stem)) -Force }
    & $py -I "$t\write_qc.py" "$tmp\decomp\info.json" "$tmp\opt" "$tmp\opt\test.qc" --phys-bones $x.physics_bones | Out-Null
    $q = Get-Content "$tmp\opt\test.qc" -Raw
    $n = ($x.lod_targets -split ',').Count - 1
    (([regex]::Matches($q, '\$bodygroup')).Count -eq $x.bodygroups) -and (([regex]::Matches($q, '\$lod \d')).Count -eq $n) -and
    ($q -match '\$shadowlod') -and (([regex]::Matches($q, '\$attachment')).Count -eq $x.attachments) -and
    (([regex]::Matches($q, '\$hbox \d')).Count -eq $x.hitboxes) -and ($q -match '\$collisionjoints') -and ($q -notmatch 'mostlyopaque') -and
    (@(([regex]::Matches($q, 'studio "([^"]+)"') | % { $_.Groups[1].Value }) | ? { -not (Test-Path "$tmp\opt\$_") }).Count -eq 0)
}

& $py -I "$PSScriptRoot\make_negatives.py" $smd "$tmp\neg" | Out-Null

Test 'smd_normals: reference OK' {
    & $py -I "$t\smd_normals.py" $smd | Out-Null; $LASTEXITCODE -eq 0
}

Test 'smd_normals: half_normals control FAIL' {
    & $py -I "$t\smd_normals.py" "$tmp\neg\half_normals.smd" | Out-Null; $LASTEXITCODE -eq 1
}

Test 'smd_normals: inside_out control passes (known limit, covered by validate_faces)' {
    & $py -I "$t\smd_normals.py" "$tmp\neg\inside_out.smd" | Out-Null; $LASTEXITCODE -eq 0
}

Test 'validate_faces: reference + face OK' {
    $v = (& $bl -b --python "$t\validate_faces.py" -- --smd $smd --with $face 2>&1) -join "`n"
    $v -match 'RESULT OK'
}

Test 'validate_faces: inside_out control FAIL' {
    $v = (& $bl -b --python "$t\validate_faces.py" -- --smd "$tmp\neg\inside_out.smd" --with $face 2>&1) -join "`n"
    $v -match 'RESULT FAIL'
}

Test 'validate_poses: reference PASS against its own reference data' {
    $v = (& $bl -b --python "$t\validate_poses.py" -- --smd $smd --out "$tmp\vp" --no-render 2>&1) -join "`n"
    $v -match 'VERDICT PASS'
}

Test 'validate_poses: broken_weights control FAIL' {
    $v = (& $bl -b --python "$t\validate_poses.py" -- --smd "$tmp\neg\broken_weights.smd" --out "$tmp\vp2" --no-render 2>&1) -join "`n"
    $v -match 'VERDICT FAIL'
}

Test 'tailor: example garment builds, no unweighted vertex' {
    $v = (& $bl -b --python "$root\examples\example_robe.py" -- --skeleton $smd --out "$tmp\robe" 2>&1) -join "`n"
    $v -match "'unweighted': 0"
}

Test 'tailor: example garment passes poses, normals and backface checks' {
    $s = "$tmp\robe\example_robe.smd"
    $a = (& $bl -b --python "$t\validate_poses.py" -- --smd $s --out "$tmp\robe\v" --no-render 2>&1) -join "`n"
    & $py -I "$t\smd_normals.py" $s | Out-Null; $n = $LASTEXITCODE
    $f = (& $bl -b --python "$t\validate_faces.py" -- --smd $s 2>&1) -join "`n"
    ($a -match 'VERDICT PASS') -and ($n -eq 0) -and ($f -match 'RESULT OK')
}

Test 'rig_check: reference vs itself OK' {
    & $py -I "$t\rig_check.py" $smd $smd | Out-Null; $LASTEXITCODE -eq 0
}

Test 'rig_check: moved_bone control FAIL (rest offset)' {
    $v = (& $py -I "$t\rig_check.py" "$tmp\neg\moved_bone.smd" $smd) -join "`n"
    ($LASTEXITCODE -eq 1) -and ($v -match 'off their target rest position')
}

Test 'rig_check: valvebiped control FAIL (naming convention)' {
    $v = (& $py -I "$t\rig_check.py" "$tmp\neg\valvebiped.smd" $smd) -join "`n"
    ($LASTEXITCODE -eq 1) -and ($v -match 'naming convention differs')
}

Test 'vtf: spec-built files read exactly; truncated and fake files rejected' {
    New-Item -ItemType Directory -Force "$tmp\vtf" | Out-Null
    & $py -I "$PSScriptRoot\make_vtf.py" "$tmp\vtf\good.vtf" 1024 1024 15 0
    & $py -I "$PSScriptRoot\make_vtf.py" "$tmp\vtf\fat.vtf" 4096 4096 12 1
    & $py -I "$PSScriptRoot\make_vtf.py" "$tmp\vtf\cut.vtf" 512 512 13 0 --truncate
    Set-Content "$tmp\vtf\fake.vtf" "not a texture"
    $v = (& $py -I "$t\vtf.py" "$tmp\vtf\good.vtf" "$tmp\vtf\fat.vtf" "$tmp\vtf\cut.vtf" "$tmp\vtf\fake.vtf") -join "`n"
    ($v -match 'good.vtf: 1024x1024 DXT5 mips 11 .*VRAM 1,365 KB') -and ($v -match 'fat.vtf: 4096x4096 BGRA8888 mips 1 .*VRAM 65,536 KB') -and
    ($v -match 'cut.vtf: INVALID truncated') -and ($v -match 'fake.vtf: INVALID not a VTF')
}

if (Test-Path "$fx\vtf_real") {
    Test 'vtf: real files from Valve tools (tests/fixtures/vtf_real) parse to their exact byte size' {
        $code = "import sys,glob,os; sys.path.insert(0, r'$t'); from vtf import read_vtf; rs=[read_vtf(f) for f in glob.glob(r'$fx\vtf_real\*.vtf') if open(f,'rb').read(4)==b'VTF\0']; print(len(rs), sum(r['valid'] and r['size']==r['expected_size'] for r in rs))"
        $n = (& $py -I -c $code) -split ' '
        ([int]$n[0] -gt 0) -and ($n[0] -eq $n[1])
    }
}

& $py -I "$PSScriptRoot\make_materials.py" $mdl "$tmp\mat_good" good | Out-Null
& $py -I "$PSScriptRoot\make_materials.py" $mdl "$tmp\mat_bad" bad | Out-Null

Test 'doctor: reference findings (no LOD critical, triangles, twopass) and score' {
    $j = (& $py -I "$t\doctor.py" $mdl --out "$tmp\doc") | Out-Null; $r = (Get-Content "$tmp\doc\report.json" -Raw | ConvertFrom-Json)[0]
    $p = ($r.findings | % problem) -join "`n"
    ($r.score -lt 70) -and ($p -match 'no LOD') -and ($p -match 'TRANSLUCENT_TWOPASS') -and ($r.tris_heaviest -ge $x.vtx_tris_lod0 * 0.9)
}

Test 'doctor: healthy materials -> no texture finding' {
    & $py -I "$t\doctor.py" $mdl --materials "$tmp\mat_good" --out "$tmp\doc_good" | Out-Null
    $r = (Get-Content "$tmp\doc_good\report.json" -Raw | ConvertFrom-Json)[0]
    (@($r.findings | ? area -eq 'textures').Count -eq 0) -and ($r.textures.Count -gt 0)
}

Test 'doctor: broken materials control -> missing, uncompressed, oversized, no mips, translucent' {
    & $py -I "$t\doctor.py" $mdl --materials "$tmp\mat_bad" --out "$tmp\doc_bad" | Out-Null
    $p = ((Get-Content "$tmp\doc_bad\report.json" -Raw | ConvertFrom-Json)[0].findings | % problem) -join "`n"
    ($p -match 'not found in any \$cdmaterials') -and ($p -match 'uncompressed BGRA8888') -and ($p -match '4096x4096 texture') -and
    ($p -match 'mipmap\(s\) only') -and ($p -match 'uses \$translucent')
}

New-Item -ItemType Directory -Force "$tmp\batch\clean", "$tmp\batch\waste" | Out-Null
foreach ($e in 'mdl', 'vvd', 'dx90.vtx', 'phy') { Copy-Item "$fx\reference.$e" "$tmp\batch\clean\"; Copy-Item "$fx\reference.$e" "$tmp\batch\waste\" }
Copy-Item "$fx\reference.dx90.vtx" "$tmp\batch\waste\reference.dx80.vtx"

Test 'doctor: folder mode ranks every model, wasted .dx80.vtx counted' {
    & $py -I "$t\doctor.py" "$tmp\batch" --out "$tmp\doc_batch" | Out-Null
    $r = Get-Content "$tmp\doc_batch\report.json" -Raw | ConvertFrom-Json
    $w = $r | ? { $_.model -match 'waste' }; $c = $r | ? { $_.model -match 'clean' }
    ($r.Count -eq 2) -and ($w.wasted_bytes -gt 0) -and ($c.wasted_bytes -eq 0) -and ($w.score -lt $c.score)
}

Test 'pack: release folder without .dx80.vtx, materials copied, exit 0' {
    & $py -I "$t\pack.py" "$tmp\batch\waste\reference.mdl" "$tmp\pack" --materials "$tmp\mat_good" | Out-Null
    $files = @(Get-ChildItem "$tmp\pack" -Recurse -File)
    ($LASTEXITCODE -eq 0) -and (@($files | ? Name -like '*.dx80.vtx').Count -eq 0) -and (@($files | ? Name -like '*.vtf').Count -gt 0) -and
    (@($files | ? Name -like '*.mdl').Count -eq 1)
}

Test 'pack: missing material control -> INCOMPLETE, exit 1' {
    $v = (& $py -I "$t\pack.py" "$tmp\batch\waste\reference.mdl" "$tmp\pack_bad" --materials "$tmp\mat_bad") -join "`n"
    ($LASTEXITCODE -eq 1) -and ($v -match 'MISSING material')
}

Test 'optimize_outfit --min-weight 0.02: no influence under 2 %, LOD still PASS' {
    & $bl -b --python "$t\optimize_outfit.py" -- --smd $smd --out "$tmp\mw" --tris 0 --min-weight 0.02 2>&1 | Out-Null
    $count = { param($f) $code = "import sys; tri=False; low=0`nfor l in open(r'$f', encoding='latin-1'):`n s=l.split()`n if s and s[0]=='triangles': tri=True; continue`n if tri and len(s)>10: low+=sum(1 for j in range(int(s[9])) if float(s[11+2*j])<0.0199)`nprint(low)"; [int](& $py -I -c $code) }
    $before = & $count $smd
    $after = & $count "$tmp\mw\reference.smd"
    $v = (& $bl -b --python "$t\validate_lods.py" -- --ref $smd --out "$tmp\mw\v" "$tmp\mw\reference.smd" 2>&1) -join "`n"
    ($before -gt 0) -and ($after -eq 0) -and ($v -match 'VERDICT \S+ PASS')
}

& $bl -b --python "$PSScriptRoot\make_blends.py" -- $smd "$tmp\blends" 2>&1 | Out-Null

Test 'blend_audit: healthy .blend OK' {
    $v = (& $bl -b "$tmp\blends\good.blend" --python "$t\blend_audit.py" 2>&1) -join "`n"
    $v -match 'RESULT OK'
}

Test 'blend_audit: broken .blend control -> scale, unweighted, missing image, stray group, >3 influences' {
    $v = (& $bl -b "$tmp\blends\bad.blend" --python "$t\blend_audit.py" 2>&1) -join "`n"
    ($v -match 'RESULT FAIL') -and ($v -match 'armature transform not applied') -and ($v -match '50 vertices without any bone weight') -and
    ($v -match "image 'lost' missing") -and ($v -match 'NotABone') -and ($v -match '5 vertices with more than 3')
}

Test 'pipeline: compiled model -> 4 validated LODs, QC with LODs + physics from the .phy, report' {
    $v = (& $py -I "$t\pipeline.py" "$tmp\batch\waste\reference.mdl" "$tmp\pipe") -join "`n"
    $qc = Get-Content (Get-ChildItem "$tmp\pipe\optimized\*.qc")[0].FullName -Raw
    $nphys = @(($x.physics_bones -split ',')).Count
    ($LASTEXITCODE -eq 0) -and ($v -match 'RESULT OK') -and (([regex]::Matches($v, '\*\*PASS\*\*')).Count -eq 4) -and
    (([regex]::Matches($qc, '\$lod "?\d')).Count -eq 3) -and (([regex]::Matches($qc, '\$jointconstrain')).Count -eq ($nphys - 1) * 3) -and
    (Test-Path "$tmp\pipe\report.md")
}

Test 'pipeline: $lod values = 100 x measured LOD error (1 px), increasing, quoted decimals' {
    $j = Get-Content "$tmp\pipe\optimized\validation\validation.json" -Raw | ConvertFrom-Json
    $qc = Get-Content (Get-ChildItem "$tmp\pipe\optimized\*.qc")[0].FullName -Raw
    $got = [regex]::Matches($qc, '\$lod "?([\d.]+)"?') | % { [double]$_.Groups[1].Value }
    $exp = @(); $prev = 0
    foreach ($k in 1..3) {
        $r = ($j.PSObject.Properties | ? { $_.Name -match "_lod$k\.smd$" }).Value
        $e = (@($r.rest.lod_to_ref.p99, $r.rest.ref_to_lod.p99, $r.posed.lod_to_ref.p99, $r.posed.ref_to_lod.p99) | Measure-Object -Maximum).Maximum
        $v = [Math]::Round([Math]::Max(100 * $e, 1.0), 1); if ($v -le $prev) { $v = $prev + 0.5 }; $exp += $v; $prev = $v
    }
    $ok = $got.Count -eq 3
    for ($k = 0; $k -lt 3; $k++) { $ok = $ok -and ([Math]::Abs($got[$k] - $exp[$k]) -lt 0.051) }
    $ok -and ($got[0] -lt $got[1]) -and ($got[1] -lt $got[2]) -and ($qc -match '\$lod "\d+\.\d"')
}

Test 'write_qc: integer $lod values stay unquoted' {
    & $py -I "$t\write_qc.py" "$tmp\decomp\info.json" "$tmp\opt" "$tmp\opt\int.qc" --lods 10,20,40 | Out-Null
    $q = Get-Content "$tmp\opt\int.qc" -Raw
    ($q -match '\$lod 10\r?\n') -and ($q -notmatch '\$lod "')
}

Test 'gmodtk launcher: finds Blender, runs Python and Blender tools' {
    $h = (& "$root\gmodtk.ps1" help) -join "`n"
    $d = (& "$root\gmodtk.ps1" rig-check $smd $smd) -join "`n"
    ($h -match 'pipeline <model.mdl>') -and ($d -match 'RESULT OK')
}

Test 'dxt: codec agrees with Blender DDS reader (synthetic + real Valve blocks), quality, garbage control' {
    $real = if (Test-Path "$fx\vtf_real") { "$fx\vtf_real" } else { "" }
    $v = (& $bl -b --python "$PSScriptRoot\check_dxt.py" -- "$tmp\dxt" $real 2>&1) -join "`n"
    ($v -match 'RESULT OK') -and ($v -notmatch 'CHECK FAIL') -and ([regex]::Matches($v, 'CHECK OK').Count -ge 11)
}

Test 'texture: PNG -> VTF (DXT1 opaque, DXT5 + $alphatest VMT, power of two, --max), exact file sizes' {
    $d = "$tmp\dxt"
    & $bl -b --python "$t\texture.py" -- "$d\flowers.png" "$d\out\flowers.vtf" 2>&1 | Out-Null
    & $bl -b --python "$t\texture.py" -- "$d\cutout.png" "$d\out\cutout.vtf" --vmt "$d\out\cutout.vmt" --material-path "models/x/cutout" 2>&1 | Out-Null
    & $bl -b --python "$t\texture.py" -- "$d\odd_300x200.png" "$d\out\odd.vtf" 2>&1 | Out-Null
    & $bl -b --python "$t\texture.py" -- "$d\flowers.png" "$d\out\small.vtf" --max 64 2>&1 | Out-Null
    $code = "import sys,os; sys.path.insert(0, r'$t'); from vtf import read_vtf`nfor n in ('flowers','cutout','odd','small'):`n r=read_vtf(os.path.join(r'$d\out', n+'.vtf')); print(n, r['valid'] and r['size']==r['expected_size'], r['width'], r['height'], r['format'], r['full_mip_chain'])"
    $v = (& $py -I -c $code) -join "`n"
    $vmt = Get-Content "$d\out\cutout.vmt" -Raw
    ($v -match 'flowers True 256 256 DXT1 True') -and ($v -match 'cutout True 256 256 DXT5 True') -and
    ($v -match 'odd True 256 128 DXT1 True') -and ($v -match 'small True 64 64 DXT1 True') -and
    ($vmt -match '\$alphatest" "1"') -and ($vmt -match 'models/x/cutout') -and ($vmt -notmatch 'translucent')
}

& $py -I "$PSScriptRoot\make_valvebiped.py" $smd "$tmp\vb" | Out-Null

Test 'retarget: ValveBiped T-pose outfit (x1.12, moved) back onto the reference rig = original geometry' {
    & $py -I "$t\retarget.py" "$tmp\vb\valvebiped.smd" $smd "$tmp\vb\fit.smd" | Out-Null
    $e = (& $py -I "$PSScriptRoot\position_error.py" "$tmp\vb\fit.smd" "$tmp\vb\expected.smd") -join ' '
    $m = [regex]::Match($e, 'mean ([\d.]+) p99 ([\d.]+) max ([\d.]+) .*mismatch ([\d.]+)%')
    & $py -I "$t\rig_check.py" "$tmp\vb\fit.smd" $smd | Out-Null
    ($LASTEXITCODE -eq 0) -and ([double]$m.Groups[1].Value -lt 0.1) -and ([double]$m.Groups[2].Value -lt 0.5) -and
    ([double]$m.Groups[3].Value -lt 1.0) -and ([double]$m.Groups[4].Value -lt 0.5)
}

Test 'retarget --no-fit control: renaming alone leaves the garment far off (p99 > 5 u)' {
    & $py -I "$t\retarget.py" "$tmp\vb\valvebiped.smd" $smd "$tmp\vb\nofit.smd" --no-fit | Out-Null
    $e = (& $py -I "$PSScriptRoot\position_error.py" "$tmp\vb\nofit.smd" "$tmp\vb\expected.smd") -join ' '
    [double]([regex]::Match($e, 'p99 ([\d.]+)').Groups[1].Value) -gt 5
}

Test 'validate_poses: poses a ValveBiped rig through canonical joints (limbs really move)' {
    & $bl -b --python "$t\validate_poses.py" -- --smd "$tmp\vb\valvebiped.smd" --out "$tmp\vb\poses" --no-render 2>&1 | Out-Null
    $j = Get-Content "$tmp\vb\poses\pose_validation.json" -Raw | ConvertFrom-Json
    ($j.poses.run.p99 -gt 1.05) -and ($j.poses.arms_up.max_elongation -gt 0.1) -and ($j.poses.twist.p99 -gt 1.02)
}

Test 'blend_to_smd: .blend export round trip = original (geometry, UVs, weights, skeleton)' {
    & $bl -b "$tmp\blends\good.blend" --python "$t\blend_to_smd.py" -- --out "$tmp\blends\exported.smd" 2>&1 | Out-Null
    & $py -I "$t\smd_compare.py" $smd "$tmp\blends\exported.smd" | Out-Null; $c = $LASTEXITCODE
    & $py -I "$t\rig_check.py" "$tmp\blends\exported.smd" $smd --tolerance 0.001 | Out-Null
    ($c -eq 0) -and ($LASTEXITCODE -eq 0)
}

Test 'blend_to_smd: unapplied armature scale control is caught downstream by rig_check' {
    & $bl -b "$tmp\blends\bad.blend" --python "$t\blend_to_smd.py" -- --out "$tmp\blends\exported_bad.smd" 2>&1 | Out-Null
    $v = (& $py -I "$t\rig_check.py" "$tmp\blends\exported_bad.smd" $smd) -join "`n"
    ($LASTEXITCODE -eq 1) -and ($v -match 'off their target rest position')
}

Write-Host ""
$results | Format-Table -AutoSize
$fails = @($results | ? Result -ne 'OK').Count
Write-Host ("{0}/{1} tests OK  (temp folder: {2})" -f ($results.Count - $fails), $results.Count, $tmp)
if ($fails -eq 0) { Remove-Item $tmp -Recurse -Force -Confirm:$false }
exit $fails
