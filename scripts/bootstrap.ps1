# Aletheia — one-command setup for Windows.
#
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/bootstrap.ps1 | iex
#
# Installs nothing behind your back: it checks for git and Python, clones
# (or updates) the repo in your home folder, starts the local Core, and
# opens the Command Center. Ctrl+C in this window stops Aletheia.

$ErrorActionPreference = "Stop"
$repo = "https://github.com/caleblschulte0-ux/Aletheia.git"
$dest = Join-Path $HOME "Aletheia"

function Need($name, $url) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    Write-Host "`n  Missing: $name" -ForegroundColor Red
    Write-Host "  Install it, then run this again:  $url`n"
    exit 1
  }
}

Write-Host "`n  ALETHEIA setup" -ForegroundColor Cyan
Need git "https://git-scm.com/download/win"
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" }
      elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" }
      else { $null }
if (-not $py) {
  Write-Host "`n  Missing: Python 3.11+" -ForegroundColor Red
  Write-Host "  Install from https://www.python.org/downloads/ " -NoNewline
  Write-Host "(tick 'Add python.exe to PATH'), then run this again.`n"
  exit 1
}

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
Write-Host "`n  Starting Aletheia Core — leave this window open." -ForegroundColor Green
Write-Host "  Wall:           http://127.0.0.1:8777/"
Write-Host "  Command Center: http://127.0.0.1:8777/command.html"
Write-Host "  Stop with Ctrl+C`n"
Start-Process "http://127.0.0.1:8777/command.html"
& $py -m aletheia.core
