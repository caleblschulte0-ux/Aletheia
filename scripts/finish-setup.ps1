# finish-setup.ps1 — the last steps that genuinely need Caleb.
#
#   powershell -ExecutionPolicy Bypass -File C:\Users\caleb\Aletheia\scripts\finish-setup.ps1
#
# Claude already did the rest from its session (2026-08-26): merged the
# reviewed work to main, pushed it (your one-time GitHub sign-in stored the
# credentials), and installed the supervisor — Aletheia now starts at every
# logon, restarts on crash, and updates itself from main. What remains needs
# your password, your approval, or your voice. Idempotent — re-run any time.

$ErrorActionPreference = "Stop"
$repo = "C:\Users\caleb\Aletheia"
Set-Location $repo
$py = "C:\Users\caleb\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) { throw "Python 3.12 not found at $py - run the bootstrap first" }

function Step($n, $text) { Write-Host "`n=== Step ${n}: $text ===" -ForegroundColor Cyan }

# ---- 1. Email credentials (never enter the repo) ---------------------------
Step 1 "Email - a Gmail app password (Enter to skip for now)"
$cfgDir  = Join-Path $HOME ".aletheia"
$cfgFile = Join-Path $cfgDir "mail.json"
if (Test-Path $cfgFile) {
  Write-Host "mail.json already exists - leaving it alone." -ForegroundColor Green
} else {
  Write-Host "  Create one at https://myaccount.google.com/apppasswords (16 letters)."
  $addr = Read-Host "  Gmail address (Enter to skip)"
  if ($addr) {
    while ($true) {
      $plain = (Read-Host "  App password (16 letters)") -replace "\s", ""
      if ($plain.Length -ne 16) {
        Write-Host "  That's $($plain.Length) characters - an app password is exactly 16. Try again." -ForegroundColor Yellow
        continue
      }
      New-Item -ItemType Directory -Force $cfgDir | Out-Null
      @{ address = $addr; password = $plain } | ConvertTo-Json |
        Out-File -FilePath $cfgFile -Encoding ascii
      # prove it against Gmail right now - stored-but-wrong helps nobody
      & $py -c "from aletheia import mail; mail.check_unread(); print('  IMAP login OK - email is live.')"
      if ($LASTEXITCODE -eq 0) { break }
      Write-Host "  Gmail refused that password - re-copy it from myaccount.google.com/apppasswords" -ForegroundColor Yellow
      Remove-Item $cfgFile -Force
    }
  } else {
    Write-Host "  Skipped - email stays NEEDS_CONFIGURATION until you re-run this." -ForegroundColor Yellow
  }
}

# ---- 2. Prove computer control (Notepad acceptance) ------------------------
Step 2 "Windows computer control acceptance (you will type APPROVE)"
& $py -m pip install --quiet --only-binary=":all:" pywinauto pillow
if ($LASTEXITCODE -ne 0) {
  Write-Host "pywinauto install failed - skipping; computer control stays EXPERIMENTAL." -ForegroundColor Yellow
} else {
  & powershell -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\phase7_accept_notepad.ps1")
  if (Test-Path (Join-Path $repo "cache\phase7-acceptance")) {
    Write-Host "Receipt written under cache\phase7-acceptance - Claude reads it and updates the registry." -ForegroundColor Cyan
  } else {
    Write-Host "No receipt was written - the acceptance did not complete. Tell Claude what you saw." -ForegroundColor Yellow
  }
}

# ---- 3. Talk to her --------------------------------------------------------
Step 3 "The wall"
Write-Host "Click the small mic dot bottom-right ONCE (browser asks for the mic), then say:"
Write-Host '  "Thea, what''s going on?"' -ForegroundColor Green
Start-Process "http://127.0.0.1:8777/"
