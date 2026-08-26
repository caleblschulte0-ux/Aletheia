# finish-setup.ps1 — the ONE script Caleb runs to finish bringing Aletheia live.
#
#   powershell -ExecutionPolicy Bypass -File C:\Users\caleb\Aletheia\scripts\finish-setup.ps1
#
# Claude prepared everything it could from inside its session; the five steps
# below are the ones that genuinely need the operator's identity, approval, or
# keyboard. Each step is idempotent — re-running the script is always safe,
# and a failed step warns and continues so one hiccup never blocks the rest.

$ErrorActionPreference = "Stop"
$repo = "C:\Users\caleb\Aletheia"
Set-Location $repo

# The 3.12 interpreter (bare `python` on this PC is a 3.9 that Aletheia refuses)
$py = "C:\Users\caleb\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) { throw "Python 3.12 not found at $py - run the bootstrap first" }

function Step($n, $text) { Write-Host "`n=== Step ${n}: $text ===" -ForegroundColor Cyan }

# ---- 1. Merge the reviewed work onto main ---------------------------------
Step 1 "Merge the reviewed ChatGPT-integration work onto main"
git checkout main | Out-Null
$ahead = git rev-list --count main..claude/chatgpt-review-integration 2>$null
if ($LASTEXITCODE -eq 0 -and [int]$ahead -gt 0) {
  git merge --no-ff --no-edit claude/chatgpt-review-integration
  if ($LASTEXITCODE -ne 0) { throw "merge failed - tell Claude, do not force anything" }
  Write-Host "Merged $ahead commits onto main." -ForegroundColor Green
} else {
  Write-Host "Nothing to merge - main is already up to date." -ForegroundColor Green
}

# ---- 2. Sign in to GitHub once so the Core can push ------------------------
Step 2 "Push to GitHub (a sign-in window may pop up - approve it once)"
git push origin main
if ($LASTEXITCODE -eq 0) {
  Write-Host "Pushed. Credentials are stored; the Core can publish from now on." -ForegroundColor Green
} else {
  Write-Host "Push failed - the Core will keep working locally and retry each tick." -ForegroundColor Yellow
}

# ---- 3. Make Aletheia permanent (start at every logon) ---------------------
Step 3 "Install the supervisor (auto-start, self-restart, self-update)"
# stop any Core Claude left running so the supervised one takes over on main
$owners = Get-NetTCPConnection -LocalPort 8777 -State Listen -ErrorAction SilentlyContinue |
          Select-Object -ExpandProperty OwningProcess -Unique
foreach ($p in $owners) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
& $py -m aletheia.supervisor install
if ($LASTEXITCODE -ne 0) { Write-Host "supervisor install failed - tell Claude." -ForegroundColor Yellow }

# wait for the Core to answer before anything else uses it
$up = $false
foreach ($i in 1..30) {
  try {
    Invoke-RestMethod -Uri "http://127.0.0.1:8777/api/status" -TimeoutSec 2 | Out-Null
    $up = $true; break
  } catch { Start-Sleep -Seconds 1 }
}
if ($up) { Write-Host "Core is up at http://127.0.0.1:8777/" -ForegroundColor Green }
else     { Write-Host "Core did not answer within 30s - tell Claude." -ForegroundColor Yellow }

# ---- 4. Email credentials (never enter the repo) ---------------------------
Step 4 "Email - a Gmail app password (skip with Enter if not now)"
$cfgDir  = Join-Path $HOME ".aletheia"
$cfgFile = Join-Path $cfgDir "mail.json"
if (Test-Path $cfgFile) {
  Write-Host "mail.json already exists - leaving it alone." -ForegroundColor Green
} else {
  Write-Host "  Create one at https://myaccount.google.com/apppasswords (16 letters)."
  $addr = Read-Host "  Gmail address (Enter to skip)"
  if ($addr) {
    $pw = Read-Host "  App password" -AsSecureString
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
             [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))
    New-Item -ItemType Directory -Force $cfgDir | Out-Null
    @{ address = $addr; password = $plain } | ConvertTo-Json |
      Out-File -FilePath $cfgFile -Encoding ascii
    $check = & $py -c "from aletheia import mail; ok, why = mail.available(); print(why); exit(0 if ok else 1)"
    Write-Host "  $check" -ForegroundColor Green
  } else {
    Write-Host "  Skipped - email stays NEEDS_CONFIGURATION until you re-run this." -ForegroundColor Yellow
  }
}

# ---- 5. Prove computer control (Notepad acceptance) ------------------------
Step 5 "Windows computer control acceptance (you will type APPROVE)"
& $py -m pip install --quiet --only-binary=":all:" pywinauto
if ($LASTEXITCODE -ne 0) {
  Write-Host "pywinauto install failed - skipping; computer control stays EXPERIMENTAL." -ForegroundColor Yellow
} else {
  & powershell -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\phase7_accept_notepad.ps1")
  Write-Host "Result receipt is under cache\phase7-acceptance - Claude reads it and updates the registry." -ForegroundColor Cyan
}

# ---- Done ------------------------------------------------------------------
Write-Host "`n=== All steps done ===" -ForegroundColor Cyan
Write-Host "Open the wall, click the small mic dot bottom-right ONCE, then say:"
Write-Host '  "Thea, what''s going on?"' -ForegroundColor Green
Start-Process "http://127.0.0.1:8777/"
