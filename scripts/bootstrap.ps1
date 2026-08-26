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
    if (-not (Have $cand[0])) { continue }
    try {
      $v = & $cand[0] @($cand | Select-Object -Skip 1) -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
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
$pyFlags = @($py | Select-Object -Skip 1)
$pyv = & $py[0] @pyFlags -c "import sys; print(sys.version.split()[0])"
Write-Host "  Using Python $pyv ($($py -join ' '))" -ForegroundColor Green

function Py { & $py[0] @pyFlags @args; return $LASTEXITCODE }

# ---- the repo --------------------------------------------------------------
if (Test-Path $dest) {
  Write-Host "  Updating $dest ..."
  git -C $dest pull --ff-only
} else {
  Write-Host "  Cloning into $dest ..."
  git clone $repo $dest
}
Set-Location $dest

# ---- OPTIONAL: browser control — a failure here NEVER stops the setup ------
if (-not (Test-Path (Join-Path $dest ".browser-installed"))) {
  $answer = Read-Host "  Enable browser control? Downloads Chromium (~150MB) [Y/n]"
  if ($answer -eq "" -or $answer -match "^[Yy]") {
    try {
      [void](Py -m pip install --quiet --upgrade pip)
      if ((Py -m pip install --quiet --only-binary=":all:" -r requirements-optional.txt) -ne 0) {
        throw "pip could not install playwright from wheels"
      }
      if ((Py -m playwright install chromium) -ne 0) { throw "chromium download failed" }
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
if ((Py -m unittest discover -s tests -q) -ne 0) {
  throw "Aletheia checks failed on this machine. The Core was not started - send Claude the output above."
}

$auto = Read-Host "  Start Aletheia automatically at every logon? [Y/n]"
if ($auto -eq "" -or $auto -match "^[Yy]") {
  [void](Py -m aletheia.supervisor install)
}

Write-Host "`n  Aletheia is starting — leave this window open, or close it" -ForegroundColor Green
Write-Host "  and it returns at next logon (if you said Y above)."
Write-Host "  Wall:           http://127.0.0.1:8777/"
Write-Host "  Command Center: http://127.0.0.1:8777/command.html"
Write-Host "  Stop with Ctrl+C`n"
Start-Process "http://127.0.0.1:8777/"
[void](Py -m aletheia.supervisor)
