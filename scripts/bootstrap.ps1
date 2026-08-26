# Aletheia — one-command setup for Windows.
#
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/bootstrap.ps1 | iex
#
# Installs git and a modern Python via winget if needed, clones or updates
# the repo in your home folder, runs the tests, registers Aletheia to start
# at every logon, and starts it. Safe to re-run any time — it only fixes
# what is missing.
#
# Design rule (learned the hard way, 2026-08-26): OPTIONAL steps never
# abort the setup. A machine with Python 3.9 and no C compiler failed the
# optional browser install and the old script threw — so the REQUIRED
# Core never started. Now: required steps stop with a clear message;
# optional steps warn and continue.

$ErrorActionPreference = "Stop"
# `irm | iex` runs in the CALLER'S session: a function defined by an older
# version of this script (the recursive `Py`) survives there and would
# shadow py.exe again. Clear any such leftovers before anything runs.
Remove-Item function:\Py -ErrorAction SilentlyContinue
$repo = "https://github.com/caleblschulte0-ux/Aletheia.git"
$dest = Join-Path $HOME "Aletheia"

function Have($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User")
}

# ---- a Python Aletheia can actually run on (>= 3.10) -----------------------
function Find-Python {
  # newest-first; 310 = 3.10, the floor for this codebase (aletheia/__init__.py
  # enforces the same floor with a clear message instead of syntax errors)
  foreach ($cand in @(@("py","-3.12"), @("py","-3.11"), @("py","-3.10"),
                      @("py"), @("python3"), @("python"))) {
    # resolve to the real .exe so no session function can shadow the name
    $exe = (Get-Command $cand[0] -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1).Source
    if (-not $exe) { continue }
    try {
      $v = & $exe @($cand | Select-Object -Skip 1) -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
      if ($LASTEXITCODE -eq 0 -and [int]$v -ge 310) { return $cand }
    } catch {}
  }
  return $null
}

Write-Host "`n  ALETHEIA setup" -ForegroundColor Cyan

if (-not (Have git)) {
  if (Have winget) {
    Write-Host "  git is missing — installing with winget ..." -ForegroundColor Yellow
    winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
  }
  if (-not (Have git)) { throw "git is required: https://git-scm.com/download/win" }
}

$py = Find-Python
if (-not $py) {
  Write-Host "  Python 3.10+ not found (an older Python doesn't count) — installing 3.12 ..." -ForegroundColor Yellow
  if (-not (Have winget)) { throw "Python 3.10+ is required: https://www.python.org/downloads/" }
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  Refresh-Path
  $py = Find-Python
  if (-not $py) { throw "Python 3.12 installed but not found on PATH — open a NEW PowerShell window and re-run this command." }
}
# Resolve the interpreter to its real .exe path and call it directly
# everywhere. The previous version wrapped this in `function Py { & $py[0]
# ... }` — but PowerShell resolves the bare name "py" to the FUNCTION
# before the py.exe launcher, so the helper called itself until
# CallDepthOverflow killed the whole setup on a real machine (2026-08-26,
# third failed run). No wrapper function, no name that shadows a command.
$pyExe = (Get-Command $py[0] -CommandType Application -ErrorAction SilentlyContinue |
          Select-Object -First 1).Source
if (-not $pyExe) { throw "could not resolve $($py[0]) to an executable" }
$pyFlags = @($py | Select-Object -Skip 1)
$pyv = & $pyExe @pyFlags -c "import sys; print(sys.version.split()[0])"
Write-Host "  Using Python $pyv ($pyExe $pyFlags)" -ForegroundColor Green

# ---- the repo --------------------------------------------------------------
# This is a RECOVERY tool: it must end with the repo exactly at current
# main, whatever state the checkout is in. A plain `git pull` once aborted
# on a locally-written journal and the setup silently continued on STALE
# code. Local journal lines are salvaged into the PC's own writer file
# (journal-pc.jsonl — see aletheia/journal.py) before the hard reset;
# anything else uncommitted on the PC is run-state the fresh main replaces.
if (Test-Path $dest) {
  Write-Host "  Updating $dest ..."
  git -C $dest fetch origin main
  if ($LASTEXITCODE -ne 0) { throw "git fetch failed - is the network up?" }
  $localJournal = Join-Path $dest "state\journal\journal.jsonl"
  $salvage = ""
  if (Test-Path $localJournal) { $salvage = Get-Content $localJournal -Raw }
  git -C $dest checkout -f -B main origin/main
  if ($LASTEXITCODE -ne 0) { throw "git could not reset to origin/main" }
  if ($salvage) {
    $upstream = ""
    if (Test-Path $localJournal) { $upstream = Get-Content $localJournal -Raw }
    $pcJournal = Join-Path $dest "state\journal\journal-pc.jsonl"
    $existing = ""
    if (Test-Path $pcJournal) { $existing = Get-Content $pcJournal -Raw }
    $known = ($upstream + "`n" + $existing) -split "`r?`n"
    $new = ($salvage -split "`r?`n") | Where-Object { $_.Trim() -and ($known -notcontains $_) }
    if ($new) {
      # NOT Add-Content -Encoding utf8: Windows PowerShell writes a BOM,
      # which corrupts the first JSON line for every reader of the journal
      [System.IO.File]::AppendAllText($pcJournal, (($new -join "`n") + "`n"),
                                      [System.Text.UTF8Encoding]::new($false))
      git -C $dest add state/journal
      git -C $dest commit -m "pc: salvage locally journaled entries" | Out-Null
      Write-Host "  Salvaged $($new.Count) local journal line(s)." -ForegroundColor Yellow
    }
  }
} else {
  Write-Host "  Cloning into $dest ..."
  git clone $repo $dest
  if ($LASTEXITCODE -ne 0) { throw "git clone failed - is the network up?" }
}
Set-Location $dest

# ---- REQUIRED: timezone database ------------------------------------------
# Windows Python ships no tz database; without the tzdata wheel every
# timezone-aware capability (schedules, calendar availability) fails with
# ZoneInfoNotFoundError. Tiny, pure-python, wheels-only.
& $pyExe @pyFlags -m pip install --quiet --only-binary=":all:" tzdata
if ($LASTEXITCODE -ne 0) { throw "pip could not install tzdata (required for schedules/calendar)" }

# ---- OPTIONAL: browser control — a failure here NEVER stops the setup ------
if (-not (Test-Path (Join-Path $dest ".browser-installed"))) {
  $answer = Read-Host "  Enable browser control? Downloads Chromium (~150MB) [Y/n]"
  if ($answer -eq "" -or $answer -match "^[Yy]") {
    try {
      & $pyExe @pyFlags -m pip install --quiet --upgrade pip
      & $pyExe @pyFlags -m pip install --quiet --only-binary=":all:" -r requirements-optional.txt
      if ($LASTEXITCODE -ne 0) { throw "pip could not install playwright from wheels" }
      & $pyExe @pyFlags -m playwright install chromium
      if ($LASTEXITCODE -ne 0) { throw "chromium download failed" }
      New-Item -ItemType File -Path (Join-Path $dest ".browser-installed") -Force | Out-Null
      Write-Host "  Browser control ready." -ForegroundColor Green
    } catch {
      Write-Host "  Browser control install FAILED — continuing without it." -ForegroundColor Yellow
      Write-Host "  ($_)" -ForegroundColor DarkYellow
      Write-Host "  Everything else works; re-run this script later to retry." -ForegroundColor Yellow
    }
  } else {
    Write-Host "  Browser control skipped (re-run this script to add it later)." -ForegroundColor Yellow
  }
}

# ---- REQUIRED: the checks, then Aletheia itself ----------------------------
Write-Host "  Running checks ..."
& $pyExe @pyFlags -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) {
  throw "Aletheia checks failed on this machine. The Core was not started - send Claude the output above."
}

$auto = Read-Host "  Start Aletheia automatically at every logon? [Y/n]"
if ($auto -eq "" -or $auto -match "^[Yy]") {
  & $pyExe @pyFlags -m aletheia.supervisor install
}

function Wait-ForCore($seconds) {
  for ($i = 0; $i -lt $seconds; $i++) {
    try {
      Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 "http://127.0.0.1:8777/api/status" | Out-Null
      return $true
    } catch { Start-Sleep 1 }
  }
  return $false
}

if ($auto -eq "" -or $auto -match "^[Yy]") {
  # installed AND started as a background task — wait for it, open the
  # wall, and this window is free to close
  Write-Host "`n  Waiting for Aletheia to come up ..." -ForegroundColor Green
  if (Wait-ForCore 30) {
    Start-Process "http://127.0.0.1:8777/"
    Write-Host "  Aletheia is UP and runs in the background — at every logon, forever." -ForegroundColor Green
    Write-Host "  Wall: http://127.0.0.1:8777/   (click the mic dot, say `"Thea, what's going on?`")"
    Write-Host "  You can close this window.`n"
  } else {
    Write-Host "  The background task did not come up in 30s — starting here instead." -ForegroundColor Yellow
    Start-Process "http://127.0.0.1:8777/"
    & $pyExe @pyFlags -m aletheia.supervisor
  }
} else {
  Write-Host "`n  Aletheia is starting — leave this window open (Ctrl+C stops it)." -ForegroundColor Green
  Write-Host "  Wall: http://127.0.0.1:8777/  — refresh it if it loads before the Core.`n"
  Start-Process "http://127.0.0.1:8777/"
  & $pyExe @pyFlags -m aletheia.supervisor
}
