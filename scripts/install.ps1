<#
.SYNOPSIS
  StaticSight engine installer for Windows (opt-in; nothing is changed without confirmation).

.DESCRIPTION
  Checks and installs the CLI engines StaticSight needs:
    ctags    Universal Ctags with JSON output   (required)
    rg       ripgrep                            (required)
    git      Git for Windows                    (required)
    cppcheck                                    (recommended)
    global   GNU Global gtags/global            (optional; StaticSight falls back to ripgrep)
  Package managers, in order of preference: scoop, winget, choco (override with -Manager).
  Pitfall handled: `scoop install ctags` is the old Exuberant Ctags 5.8 (no JSON) - this script installs
  Universal Ctags (scoop extras/universal-ctags, winget UniversalCtags.Ctags, choco universal-ctags).
  STATICSIGHT_DISABLE_ENGINES=a,b makes the script treat those engines as missing (for testing).

  Python packages (installed with pip for the Python that runs staticsight.py, from requirements*.txt):
    mcp                                         (required)
    onnxruntime, tokenizers, numpy              (semantic search; with -WithSemantic)
  The Python is `py -3`, `python` or `python3` (first that is >= 3.10), or -Python C:\path\to\python.exe.

  -WithSemantic also installs the semantic-search packages and downloads the pinned embedding model
  (~165 MB, sha256-verified) into the per-user cache.

.EXAMPLE
  .\scripts\install.ps1 -Check
  .\scripts\install.ps1 -DryRun
  .\scripts\install.ps1 -Yes -NoGlobal
  .\scripts\install.ps1 -WithSemantic -Python C:\venvs\staticsight\Scripts\python.exe
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$NoGlobal,
    [switch]$WithSemantic,
    [string]$Python = '',
    [ValidateSet('auto', 'scoop', 'winget', 'choco')]
    [string]$Manager = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Disabled = @(($env:STATICSIGHT_DISABLE_ENGINES -split ',') | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })

function Find-Engine([string]$Name) {
    if ($Disabled -contains $Name.ToLower()) { return $null }
    $cmd = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $cmd) { return $null }
    # StaticSight refuses .cmd/.bat shims (they would need cmd.exe); report them as missing.
    if ($cmd.Source -match '\.(cmd|bat)$') { return $null }
    return $cmd.Source
}

function Get-FirstLine([string]$Exe, [string[]]$ArgList) {
    try {
        $out = & $Exe @ArgList 2>&1 | Out-String
        return (($out -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -First 1).Trim()
    } catch { return '' }
}

function Test-CtagsJson {
    $exe = Find-Engine 'ctags'
    if (-not $exe) { return @{ Ok = $false; Detail = 'not found' } }
    $ver = Get-FirstLine $exe @('--version')
    $features = (& $exe --list-features 2>&1 | Out-String)
    if ($ver -match 'Exuberant' -or $features -notmatch 'json') {
        return @{ Ok = $false; Detail = "installed ($ver) but has no JSON output - Universal Ctags needed" }
    }
    return @{ Ok = $true; Detail = $ver }
}

$Engines = @(
    @{ Name = 'ctags'; Level = 'required' },
    @{ Name = 'rg'; Level = 'required' },
    @{ Name = 'git'; Level = 'required' },
    @{ Name = 'cppcheck'; Level = 'recommended' },
    @{ Name = 'global'; Level = 'optional' },
    @{ Name = 'gtags'; Level = 'optional' }
)

function Get-Status {
    $rows = @()
    foreach ($e in $Engines) {
        if ($e.Name -eq 'ctags') {
            $t = Test-CtagsJson
            $rows += [pscustomobject]@{ Name = $e.Name; Level = $e.Level; Ok = $t.Ok; Detail = $t.Detail }
            continue
        }
        $exe = Find-Engine $e.Name
        if ($exe) {
            $rows += [pscustomobject]@{ Name = $e.Name; Level = $e.Level; Ok = $true; Detail = (Get-FirstLine $exe @('--version')) }
        } else {
            $detail = if ($e.Level -eq 'optional') { 'not found (ripgrep fallback will be used)' } else { 'not found' }
            $rows += [pscustomobject]@{ Name = $e.Name; Level = $e.Level; Ok = $false; Detail = $detail }
        }
    }
    return $rows
}

function Write-Status($Rows) {
    Write-Output 'StaticSight engines:'
    foreach ($r in $Rows) {
        $mark = if ($r.Ok) { 'OK  ' } elseif ($r.Level -eq 'required') { 'FAIL' } else { 'WARN' }
        Write-Output ('  {0} {1,-9} [{2}] {3}' -f $mark, $r.Name, $r.Level, $r.Detail)
    }
}

function Test-RequiredOk($Rows) {
    return -not ($Rows | Where-Object { $_.Level -eq 'required' -and -not $_.Ok })
}

# Package ids per manager ('' = not available there).
$Packages = @{
    scoop  = @{ ctags = 'extras/universal-ctags'; rg = 'ripgrep'; git = 'git'; cppcheck = 'cppcheck'; global = 'global' }
    winget = @{ ctags = 'UniversalCtags.Ctags'; rg = 'BurntSushi.ripgrep.MSVC'; git = 'Git.Git'; cppcheck = 'Cppcheck.Cppcheck'; global = '' }
    # choco's "global" package is not GNU Global 6.x, so it is deliberately not used.
    choco  = @{ ctags = 'universal-ctags'; rg = 'ripgrep'; git = 'git'; cppcheck = 'cppcheck'; global = '' }
}

$Repo = Split-Path -Parent $PSScriptRoot

# The Python that will run staticsight.py, as @{ Exe; Pre }: -Python, else `py -3`, `python`, `python3` (>= 3.10).
function Get-Python310 {
    $cands = @(@('py', '-3'), @('python'), @('python3'))
    if ($Python) { $cands = @(, @($Python)) }
    foreach ($c in $cands) {
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        # @(...) around the whole `if`: PowerShell unrolls a one-element array returned by a statement
        [string[]]$pre = @(if ($c.Count -gt 1) { $c[1..($c.Count - 1)] })
        & $c[0] @(@($pre) + @('-c', 'import sys; sys.exit(sys.version_info < (3, 10))')) 2>$null
        if ($LASTEXITCODE -eq 0) { return @{ Exe = $c[0]; Pre = $pre } }
    }
    return $null
}

function Invoke-Py($Py, [string[]]$ArgList) {
    $out = & $Py.Exe @(@($Py.Pre) + $ArgList) 2>$null | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out.Trim() }
}

function Test-PyHas($Py, [string[]]$Modules) {
    $code = "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in sys.argv[1:]) else 1)"
    return (Invoke-Py $Py (@('-c', $code) + $Modules)).Code -eq 0
}

function Test-PyPipOk($Py) {
    $code = "import importlib.util, os, sys, sysconfig; m = os.path.exists(os.path.join(sysconfig.get_path('stdlib'), 'EXTERNALLY-MANAGED')); sys.exit(0 if importlib.util.find_spec('pip') and (sys.prefix != sys.base_prefix or not m) else 1)"
    return (Invoke-Py $Py @('-c', $code)).Code -eq 0
}

function Get-PythonStatus($Py) {
    $rows = @()
    if ($null -eq $Py) {
        $rows += [pscustomobject]@{ Name = 'python'; Level = 'required'; Ok = $false; Detail = 'Python >= 3.10 not found (py -3, python, python3); or use the TypeScript implementation with Node >= 22.13' }
        return $rows
    }
    $ver = (Invoke-Py $Py @('-c', 'import sys; print("Python", sys.version.split()[0], "(" + sys.executable + ")")')).Out
    $rows += [pscustomobject]@{ Name = 'python'; Level = 'required'; Ok = $true; Detail = $ver }
    if (Test-PyHas $Py @('mcp')) {
        $v = (Invoke-Py $Py @('-c', 'from importlib.metadata import version; print("mcp", version("mcp"))')).Out
        $rows += [pscustomobject]@{ Name = 'mcp'; Level = 'required'; Ok = $true; Detail = $v }
    } else {
        $rows += [pscustomobject]@{ Name = 'mcp'; Level = 'required'; Ok = $false; Detail = 'not installed (runs the MCP server and the command line)' }
    }
    if (Test-PyHas $Py @('onnxruntime', 'tokenizers', 'numpy')) {
        $rows += [pscustomobject]@{ Name = 'semantic'; Level = 'optional'; Ok = $true; Detail = 'onnxruntime, tokenizers, numpy' }
    } else {
        $rows += [pscustomobject]@{ Name = 'semantic'; Level = 'optional'; Ok = $false; Detail = 'onnxruntime/tokenizers/numpy not installed (only needed for semantic search)' }
    }
    return $rows
}

function Write-PythonStatus($Py, $Rows) {
    $who = if ($Py) { (@($Py.Exe) + @($Py.Pre)) -join ' ' } else { 'python' }
    Write-Output "Python packages (for $who):"
    foreach ($r in $Rows) {
        $mark = if ($r.Ok) { 'OK  ' } elseif ($r.Level -eq 'required') { 'FAIL' } else { 'WARN' }
        Write-Output ('  {0} {1,-9} [{2}] {3}' -f $mark, $r.Name, $r.Level, $r.Detail)
    }
}

# Python packages and model: steps as @(exe, @(args)), plus a note when pip cannot install automatically.
function Get-PythonPlan($Py) {
    $steps = @()
    $note = ''
    $haveAll = $false
    if ($null -eq $Py) {
        $note = 'Python packages: no Python >= 3.10 found; install Python 3.10+ (winget install Python.Python.3.12) or use the TypeScript implementation.'
    } else {
        $needPkgs = (-not (Test-PyHas $Py @('mcp'))) -or ($WithSemantic -and -not (Test-PyHas $Py @('onnxruntime', 'tokenizers', 'numpy')))
        if ($needPkgs) {
            if (Test-PyPipOk $Py) {
                $inst = @('staticsight.py', '--install') + $(if ($WithSemantic) { @('--semantic') } else { @() }) + @('--yes')
                $steps += , @($Py.Exe, @(@($Py.Pre) + $inst))
                $haveAll = $true
            } else {
                $note = "Python packages: pip cannot install for this Python (no pip, or an OS-managed Python). Run '$($Py.Exe) $($Py.Pre -join ' ') staticsight.py --install' to see the options, then re-run with -Python <venv python>."
            }
        } else { $haveAll = $true }
    }
    if ($WithSemantic) {
        if ($haveAll) {
            $steps += , @($Py.Exe, @(@($Py.Pre) + @('staticsight.py', 'model', 'download')))
        } elseif ((Get-Command node -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $Repo 'staticsight-ts/package.json'))) {
            $steps += , @('node', @((Join-Path $Repo 'staticsight-ts/dist/server.js'), 'model', 'download'))
        }
    }
    return @{ Steps = $steps; Note = $note }
}

function Invoke-PythonPlan($PyPlan) {
    Push-Location $Repo
    try {
        foreach ($s in $PyPlan.Steps) {
            Write-Output ('> {0} {1}' -f $s[0], ($s[1] -join ' '))
            & $s[0] @($s[1])
            if ($LASTEXITCODE -ne 0) { Write-Error "command failed: $($s[0]) $($s[1] -join ' ')"; return $false }
        }
    } finally { Pop-Location }
    return $true
}

$Py = Get-Python310
$rows = Get-Status
Write-Status $rows
Write-Output ''
$pyRows = Get-PythonStatus $Py
Write-PythonStatus $Py $pyRows
if ($Check) {
    if ((Test-RequiredOk $rows) -and (Test-RequiredOk $pyRows)) { Write-Output 'Result: all required engines and packages OK'; exit 0 }
    Write-Output 'Result: something required is missing or unusable (FAIL)'; exit 1
}
Write-Output ''
$pyPlan = Get-PythonPlan $Py

$missing = @()
foreach ($name in @('ctags', 'rg', 'git', 'cppcheck')) {
    if (-not ($rows | Where-Object { $_.Name -eq $name }).Ok) { $missing += $name }
}
if (-not $NoGlobal -and (-not ($rows | Where-Object { $_.Name -eq 'global' }).Ok -or -not ($rows | Where-Object { $_.Name -eq 'gtags' }).Ok)) {
    $missing += 'global'
}
if ($missing.Count -eq 0 -and $pyPlan.Steps.Count -eq 0) {
    Write-Output 'Nothing to install.'
    if ($pyPlan.Note) { Write-Output $pyPlan.Note }
    exit 0
}

$pm = $Manager
if ($pm -eq 'auto') {
    $pm = @('scoop', 'winget', 'choco') | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
}
if (-not $pm -and $missing.Count -gt 0) {
    Write-Error ("No supported package manager found (scoop, winget, choco). Install manually: {0}. See https://scoop.sh or 'winget'." -f ($missing -join ', '))
    exit 1
}

$plan = @()
$skipped = @()
if ($pm -eq 'scoop' -and ($missing -contains 'ctags')) {
    $plan += , @('scoop', @('bucket', 'add', 'extras'))
}
foreach ($m in $missing) {
    $id = $Packages[$pm][$m]
    if (-not $id) { $skipped += $m; continue }
    switch ($pm) {
        'scoop' { $plan += , @('scoop', @('install', $id)) }
        'winget' { $plan += , @('winget', @('install', '--id', $id, '-e', '--accept-source-agreements', '--accept-package-agreements')) }
        'choco' { $plan += , @('choco', @('install', $id, '-y')) }
    }
}

Write-Output $(if ($pm) { "Install plan ($pm):" } else { 'Install plan:' })
foreach ($step in $plan) { Write-Output ('  - {0} {1}' -f $step[0], ($step[1] -join ' ')) }
foreach ($step in $pyPlan.Steps) { Write-Output ('  - {0} {1}' -f $step[0], ($step[1] -join ' ')) }
if ($pyPlan.Note) { Write-Output $pyPlan.Note }
foreach ($s in $skipped) {
    Write-Output ("  - skipped {0}: not available via {1} (GNU Global: install scoop and run 'scoop install global'; optional)" -f $s, $pm)
}
if ($DryRun) { Write-Output '(dry run: nothing changed)'; exit 0 }
if ($plan.Count -eq 0 -and $pyPlan.Steps.Count -eq 0) { Write-Output 'Nothing installable with this package manager.'; exit 0 }

if (-not $Yes) {
    if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) {
        Write-Error 'Refusing to install without confirmation on a non-interactive shell; re-run with -Yes.'
        exit 1
    }
    $answer = Read-Host 'Proceed? [y/N]'
    if ($answer -notmatch '^[Yy]$') { Write-Output 'Aborted; nothing changed.'; exit 1 }
}

foreach ($step in $plan) {
    Write-Output ('> {0} {1}' -f $step[0], ($step[1] -join ' '))
    & $step[0] @($step[1])
    if ($LASTEXITCODE -ne 0 -and -not ($step[1][0] -eq 'bucket')) { Write-Error "command failed: $($step[0]) $($step[1] -join ' ')"; exit 1 }
}

# cppcheck's MSI (winget/choco) installs to Program Files without touching PATH: offer the fix.
$cppDir = if ($env:ProgramFiles) { Join-Path $env:ProgramFiles 'Cppcheck' } else { '' }
if ($cppDir -and -not (Find-Engine 'cppcheck') -and (Test-Path (Join-Path $cppDir 'cppcheck.exe'))) {
    Write-Output "cppcheck is installed in '$cppDir' but not on PATH."
    $add = $Yes
    if (-not $Yes) { $add = (Read-Host "Add it to your user PATH? [y/N]") -match '^[Yy]$' }
    if ($add) {
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ";$cppDir"), 'User')
        $env:Path = "$env:Path;$cppDir"
        Write-Output 'Added. Open a new terminal (and restart your editor) to pick it up.'
    }
}

if ($pyPlan.Steps.Count -gt 0 -and -not (Invoke-PythonPlan $pyPlan)) { Write-Output 'Python package installation failed (see above).'; exit 1 }

# Refresh PATH for this session from the machine + user scopes, then re-check.
if ($IsWindows -or $env:OS -eq 'Windows_NT') {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
}
Write-Output ''
$rows = Get-Status
Write-Status $rows
Write-Output ''
$pyRows = Get-PythonStatus $Py
Write-PythonStatus $Py $pyRows
if ((Test-RequiredOk $rows) -and (Test-RequiredOk $pyRows)) { Write-Output 'Result: all required engines and packages OK (restart your editor so the MCP server sees the new PATH)'; exit 0 }
Write-Output 'Result: something required is still missing'
exit 1
