# tools/run_all_tests.ps1
# One-click OFFLINE regression runner (no real device / no adb needed).
#
#   .\tools\run_all_tests.ps1                 # run everything, exit 0 = green / 1 = red
#   .\tools\run_all_tests.ps1 -ProveRed       # self-test: a deliberately broken test must turn the suite red
#   .\tools\run_all_tests.ps1 -IncludeVerify  # also run the frame-replay verifiers
#
# What it runs:
#   * every tools/test_*.py            (pure, deterministic, device-free)  -- counted
#   * tools/validate_schema.py         (pipeline / interface JSON vs schema) -- counted, argv mirrors CI
#   * tools/contract_hooks/hooks_115.py --run-prove-red  (every hook's prove_red, #115) -- counted
#   * every tools/verify_*.py          -- SKIPPED by default, see below
#
# On the `run_` prefix: in tools/ that usually means a live/device runner
# (run_side_live.py, run_pipeline.py). This one is offline, but the name is fixed
# by the spec (parent issue #1: "本分支目前没有一键跑全部离线测试的入口
# (run_all_tests.ps1 只存在于另一条线)"), so keep it.
#
# Why verify_*.py are skipped by default: they are offline frame-replay verifiers.
# They replay real 1080p captures that only exist on the capture machine, and two
# of them hardcode that temp path. Running them on a bare checkout would go red for
# an environmental reason and make "red" untrustworthy. -IncludeVerify runs them.
# Two of them (verify_phantom_merge_offline.py / verify_tasks_merge_offline.py)
# assert nothing -- they print first-hit lines for a cross-worktree diff -- so a
# zero exit there is DIAG, never counted as a pass.
#
# Exit code 0 = all green; 1 = at least one failed; 2 = no python found.
#
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads BOM-less UTF-8 as GBK.

[CmdletBinding()]
param(
    [switch]$ProveRed,
    [switch]$IncludeVerify
)

$ErrorActionPreference = 'Continue'

# Several offline tests print non-ASCII glyphs (check mark / warning sign). On a
# GBK console the child python raises UnicodeEncodeError and exits 1 for a reason
# that has nothing to do with the code under test -> force utf-8.
$env:PYTHONIOENCODING = 'utf-8'

$tools = $PSScriptRoot
$wt = Split-Path -Parent $tools

# Pin the child processes' working directory to the repo root. Push-Location only
# moves PowerShell's location; a native exe launched with '&' starts in
# [Environment]::CurrentDirectory, so set both (see the audit note on the sibling
# line that produced the once-flaky "40 passed / 38 passed" results).
Push-Location -LiteralPath $wt
[Environment]::CurrentDirectory = $wt

# verify_*.py that assert nothing: report DIAG, never count a zero exit as a pass.
$diagOnly = @('verify_phantom_merge_offline.py', 'verify_tasks_merge_offline.py')

# Find python: walk up for a .venv so renaming / moving the workspace (or running
# from a worktree) does not break it; fall back to PATH.
function Find-Python {
    $d = $wt
    for ($i = 0; $i -lt 8 -and $d; $i++) {
        $c = Join-Path $d '.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $c) { return $c }
        $p = Split-Path $d -Parent
        if (-not $p -or $p -eq $d) { break }
        $d = $p
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "python not found (searched for .venv upward from $wt, and PATH)"
    Pop-Location
    exit 2
}
Write-Host ("using python: " + $py)

# -ProveRed plants a deliberately failing test so the aggregate red signal is
# exercised end to end: it must show up in the failed list and drive exit code 1.
# (The contract skeleton has its own --prove-red, which proves a failing *probe*
# turns its harness red; this proves the runner's exit-code plumbing.)
$proveFile = $null
if ($ProveRed) {
    $proveFile = Join-Path $tools 'test__prove_red_tmp.py'
    @(
        '# temporary file written by run_all_tests.ps1 -ProveRed; safe to delete.',
        'import sys',
        "print('deliberate failure written by -ProveRed')",
        'sys.exit(1)'
    ) | Set-Content -LiteralPath $proveFile -Encoding ascii
}

$ok = 0
$failed = New-Object System.Collections.ArrayList
$skipped = New-Object System.Collections.ArrayList

try {
    $scripts = Get-ChildItem -LiteralPath $tools -Filter '*.py' -File |
        Where-Object { $_.Name -match '^(test_|verify_)' } |
        Sort-Object Name

    foreach ($s in $scripts) {
        if ($s.Name -like 'verify_*' -and -not $IncludeVerify) {
            Write-Host ("==== " + $s.Name + "  [SKIP: offline frame-replay verifier; stage captured frames and pass -IncludeVerify]")
            [void]$skipped.Add($s.Name)
            continue
        }
        Write-Host ("==== " + $s.Name + " ====")
        & $py $s.FullName 2>&1 | ForEach-Object { $_ }
        if ($LASTEXITCODE -ne 0) {
            [void]$failed.Add($s.Name)
        } elseif ($diagOnly -contains $s.Name) {
            Write-Host ("     [DIAG] " + $s.Name + " asserts nothing (cross-worktree diff tool) -- not counted as a pass")
            [void]$skipped.Add($s.Name)
        } else {
            $ok++
        }
    }

    # Mirror the canonical CI invocation (.github/workflows/check.yml) so a local
    # green cannot diverge from a CI green.
    Write-Host "==== validate_schema.py ===="
    & $py (Join-Path $tools 'validate_schema.py') `
        --schema-dir (Join-Path $wt 'deps\tools') `
        --resource-dirs 'assets/resource' `
        --exclude-dirs 'assets/resource/announcement' `
        --interface-files 'assets/interface.json' 2>&1 | ForEach-Object { $_ }
    if ($LASTEXITCODE -eq 0) { $ok++ } else { [void]$failed.Add('validate_schema.py') }

    # --- #115 meta-guard: every hook's prove_red must actually RUN here. -------------
    # Rationale: hooks are discovered by import only, so a prove_red() that nobody calls
    # is indistinguishable from a dead one -- and a prove_red whose red leg is vacuous
    # never turns anything red. hooks_115 walks tools/contract_hooks/hooks_*.py and runs
    # each prove_red() as a standalone script (exit 0 = green impl + all of its own
    # red legs held). Any red here -> the suite is red.
    # Deliberately NOT a whitelist: the requirement is the whole discovered set. If a
    # narrowed list is ever passed (--only ...), hooks_115 asserts it still covers every
    # hook that has a prove_red (see probe_meta_suite_runs_prove_red).
    Write-Host "==== contract_hooks/hooks_115.py --run-prove-red (every hook's prove_red) ===="
    & $py (Join-Path $tools 'contract_hooks\hooks_115.py') --run-prove-red 2>&1 | ForEach-Object { $_ }
    if ($LASTEXITCODE -eq 0) { $ok++ } else { [void]$failed.Add('contract_hooks/prove_red_all') }
}
finally {
    if ($proveFile) { Remove-Item -LiteralPath $proveFile -Force -ErrorAction SilentlyContinue }
}

Write-Host ""
Write-Host ("RESULT: " + $ok + " passed, " + $failed.Count + " failed, " + $skipped.Count + " skipped")
Write-Host "(seam guards not yet wired are reported PENDING by test_offline_contract.py and do not fail the suite)"

if ($ProveRed) {
    $others = @($failed | Where-Object { $_ -ne 'test__prove_red_tmp.py' })
    if ($others.Count -gt 0) {
        Write-Host ("PROVE-RED: real failures present too, fix those first -> " + ($others -join ', '))
        Pop-Location
        exit 1
    }
    if ($failed -contains 'test__prove_red_tmp.py') {
        Write-Host "PROVE-RED OK: a deliberately broken test turned the suite red (exit 1) -- red is a usable signal."
        Pop-Location
        exit 0
    }
    Write-Host "PROVE-RED FAILED: the deliberately broken test did NOT turn the suite red."
    Pop-Location
    exit 1
}

if ($failed.Count -gt 0) {
    Write-Host ("FAILED: " + ($failed -join ', '))
    Pop-Location
    exit 1
}
Write-Host "ALL GREEN"
Pop-Location
exit 0
