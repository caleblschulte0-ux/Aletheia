# Aletheia — one-command setup for Windows.
#
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/bootstrap.ps1 | iex
#
# Installs git and Python via winget if they are missing (announced, not
# silent), clones or updates the repo in your home folder, runs the tests,
# starts the local Core, and opens the Command Center.
# Ctrl+C in this window stops Aletheia.

$ErrorActionPreference = "Stop"
$repo = "https://github.com/caleblschulte0-ux/Aletheia.git"
$dest = Join-Path $HOME "Aletheia"

function Have($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User")
}

function Ensure($name, $wingetId, $manualUrl) {
  if (Have $name) { return $true }
  if (Have winget) {
    Write-Host "  $name is missing — installing it with winget ..." -ForegroundColor Yellow
    winget install --id $wingetId -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (Have $name) { Write-Host "  $name installed." -ForegroundColor Green; return $true }
  }
  Write-Host "`n  Could not install $name automatically." -ForegroundColor Red
  Write-Host "  Install it here, then run this command again:  $manualUrl`n"
  return $false
}

Write-Host "`n  ALETHEIA setup" -ForegroundColor Cyan

if (-not (Ensure git "Git.Git" "https://git-scm.com/download/win")) { exit 1 }
if (-not ((Have py) -or (Have python))) {
  if (-not (Ensure python "Python.Python.3.12" "https://www.python.org/downloads/")) { exit 1 }
}
$py = if (Have py) { "py" } else { "python" }

if (Test-Path $dest) {
  Write-Host "  Updating $dest ..."
  git -C $dest pull --ff-only
} else {
  Write-Host "  Cloning into $dest ..."
  git clone $repo $dest
}

Set-Location $dest
Write-Host "  Running checks ..."
& $py -m unittest discover -s tests -q

# Optional: browser control (Playbook Phase 8). Chromium is ~150MB, so ask.
if (-not (Test-Path (Join-Path $dest ".browser-installed"))) {
  $answer = Read-Host "  Enable browser control? Downloads Chromium (~150MB) [Y/n]"
  if ($answer -eq "" -or $answer -match "^[Yy]") {
    & $py -m pip install --quiet -r requirements-optional.txt
    & $py -m playwright install chromium
    New-Item -ItemType File -Path (Join-Path $dest ".browser-installed") -Force | Out-Null
    Write-Host "  Browser control ready. Sign into a site once with:" -ForegroundColor Green
    Write-Host "    $py -m aletheia.browse login https://example.com"
  }
}

Write-Host "`n  Aletheia Core is starting — leave this window open." -ForegroundColor Green
Write-Host "  Wall:           http://127.0.0.1:8777/"
Write-Host "  Command Center: http://127.0.0.1:8777/command.html"
Write-Host "  Stop with Ctrl+C`n"
Start-Process "http://127.0.0.1:8777/command.html"
& $py -m aletheia.core
