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

Write-Host ""
$results | Format-Table -AutoSize
$fails = @($results | ? Result -ne 'OK').Count
Write-Host ("{0}/{1} tests OK  (temp folder: {2})" -f ($results.Count - $fails), $results.Count, $tmp)
if ($fails -eq 0) { Remove-Item $tmp -Recurse -Force -Confirm:$false }
exit $fails
