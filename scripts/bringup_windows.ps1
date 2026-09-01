# Aletheia Windows bring-up: one operator command after reviewed code lands on main.
#
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/bringup_windows.ps1 | iex
#
# This is deliberately NOT a development test runner. CI owns the 1,200+ test
# suite. This script proves only the live things that can differ on the operator's
# Windows machine and keeps stale background tasks stopped while repairing them.
# It NEVER lifts a production kill switch: resume is a separate operator decision
# recorded through Aletheia's intercom so the repo and PC agree on that authority.

$ErrorActionPreference = "Stop"
$repo = "https://github.com/caleblschulte0-ux/Aletheia.git"
$dest = Join-Path $HOME "Aletheia"
$recovery = "https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/recover_operator_checkout.ps1"

function Have($name) {
  [bool](Get-Command $name -CommandType Application -ErrorAction SilentlyContinue)
}

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User")
}

function Find-AletheiaPython {
  foreach ($cand in @(@("py","-3.12"), @("py","-3.11"), @("py","-3.10"),
                      @("py"), @("python3"), @("python"))) {
    $exe = (Get-Command $cand[0] -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1).Source
    if (-not $exe) { continue }
    try {
      $flags = @($cand | Select-Object -Skip 1)
      $v = & $exe @flags -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
      if ($LASTEXITCODE -eq 0 -and [int]$v -ge 310) {
        return @{ Exe = $exe; Flags = $flags }
      }
    } catch {}
  }
  return $null
}

function Invoke-AletheiaPython {
  param([Parameter(Mandatory=$true)][string[]]$PyArgs)
  & $script:PyExe @script:PyFlags @PyArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Aletheia command failed: $($PyArgs -join ' ')"
  }
}

function Wait-ForCore([int]$Seconds = 30) {
  for ($i = 0; $i -lt $Seconds; $i++) {
    try {
      $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 "http://127.0.0.1:8777/api/status"
      if ($r.StatusCode -eq 200) { return $true }
    } catch {}
    Start-Sleep -Seconds 1
  }
  return $false
}

if ($env:OS -ne "Windows_NT") { throw "Aletheia bring-up is Windows-only." }
Write-Host "`n  ALETHEIA — SAFE WINDOWS BRING-UP" -ForegroundColor Cyan

# Containment first. A stale watchdog must not resurrect old code while the repo
# and dependencies are being repaired. Missing tasks are fine on a first install.
foreach ($name in @("AletheiaVoice", "Aletheia")) {
  Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  Disable-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
}
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match '(?i)(-m\s+aletheia\.(voice_room|supervisor|core))'
} | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

if (-not (Have git)) {
  if (-not (Have winget)) {
    throw "Git is missing and Windows Package Manager (winget) is unavailable."
  }
  Write-Host "  Installing Git ..." -ForegroundColor Yellow
  winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) { throw "Git installation failed." }
  Refresh-Path
  if (-not (Have git)) {
    throw "Git installed but is not visible yet; reopen PowerShell and rerun this command."
  }
}

$python = Find-AletheiaPython
if (-not $python) {
  if (-not (Have winget)) {
    throw "Python 3.10+ is missing and Windows Package Manager (winget) is unavailable."
  }
  Write-Host "  Installing Python 3.12 ..." -ForegroundColor Yellow
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) { throw "Python installation failed." }
  Refresh-Path
  $python = Find-AletheiaPython
  if (-not $python) {
    throw "Python installed but is not visible yet; reopen PowerShell and rerun this command."
  }
}
$script:PyExe = $python.Exe
$script:PyFlags = @($python.Flags)

if (Test-Path $dest) {
  Write-Host "  Safely updating Aletheia main ..." -ForegroundColor Yellow
  # The recovery entrypoint rebases local Aletheia state, preserves the one
  # known legacy journal conflict, and refuses foreign work.  Keeping tasks
  # stopped prevents its standalone finally block from restarting old code
  # halfway through this larger bring-up.
  $previousKeepStopped = $env:ALETHEIA_RECOVERY_KEEP_STOPPED
  try {
    $env:ALETHEIA_RECOVERY_KEEP_STOPPED = "1"
    Invoke-RestMethod $recovery | Invoke-Expression
  } finally {
    if ($null -eq $previousKeepStopped) {
      Remove-Item Env:\ALETHEIA_RECOVERY_KEEP_STOPPED -ErrorAction SilentlyContinue
    } else {
      $env:ALETHEIA_RECOVERY_KEEP_STOPPED = $previousKeepStopped
    }
  }
} else {
  Write-Host "  Cloning Aletheia ..." -ForegroundColor Yellow
  git clone $repo $dest
  if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
}
Set-Location $dest

$version = & $script:PyExe @script:PyFlags -c "import sys; print(sys.version.split()[0])"
Write-Host "  Python $version" -ForegroundColor Green

# The browser-reasoning lease is intentionally foreground-only. This bring-up
# never grants it. Always-on Aletheia must use local/Claude reasoning or degrade;
# it must never create visible ChatGPT conversations while the operator is away.
Remove-Item Env:\ALETHEIA_ALLOW_CHATGPT_BROWSER_REASONING -ErrorAction SilentlyContinue

Write-Host "  Installing required runtime data ..." -ForegroundColor Yellow
& $script:PyExe @script:PyFlags -m pip install --quiet --only-binary=":all:" tzdata
if ($LASTEXITCODE -ne 0) { throw "could not install tzdata" }

Write-Host "  Running short live preflight (not the full test suite) ..." -ForegroundColor Yellow
Invoke-AletheiaPython -PyArgs @("-m","aletheia.fleet","--validate")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.capabilities","--validate")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.suggestions","validate")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.plans","validate")
Invoke-AletheiaPython -PyArgs @("-c","from aletheia import browser_reasoner as b; assert not b.operator_lease_enabled(); print('browser reasoning: unattended fallback BLOCKED')")

Write-Host "  Activating local reasoning ..." -ForegroundColor Yellow
Invoke-AletheiaPython -PyArgs @("-m","aletheia.local_ai","activate")

# Bring the Core up without changing production authority. The Core can serve
# status while halted; nothing autonomous is authorized by this installer.
Write-Host "  Installing the Core watchdog ..." -ForegroundColor Yellow
Invoke-AletheiaPython -PyArgs @("-m","aletheia.autostart","install","--only","core")
Start-ScheduledTask -TaskName "Aletheia"
if (-not (Wait-ForCore 30)) {
  throw "Core did not answer within 30 seconds. Kill switch remains unchanged and voice remains off."
}
Write-Host "  Core: UP" -ForegroundColor Green

# Voice repair proves the local ears and neural speech stack before replacing /
# re-enabling the persistent voice task. It still grants no execution authority.
Write-Host "  Repairing and proving room voice ..." -ForegroundColor Yellow
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dest "scripts\voice_repair.ps1")
if ($LASTEXITCODE -ne 0) {
  throw "Voice did not pass readiness. Core stays up; production authority is unchanged."
}

Write-Host "  Final health checks ..." -ForegroundColor Yellow
Invoke-AletheiaPython -PyArgs @("-m","aletheia.autostart","doctor","--only","core")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.autostart","doctor","--only","voice")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.local_ai","status")

# A halt is repo truth, not an installer setting. The operator's resume must have
# been relayed separately so every copy of Aletheia sees the same authority.
& $script:PyExe @script:PyFlags -c "from aletheia import policy; h=policy.halted(); print('policy: HALTED - ' + h.get('reason','') if h else 'policy: running'); raise SystemExit(2 if h else 0)"
if ($LASTEXITCODE -ne 0) {
  throw "Aletheia is healthy but the repo kill switch is still ON. The installer will not override it."
}

Write-Host "`n  ALETHEIA IS UP." -ForegroundColor Green
Write-Host "  Core:  http://127.0.0.1:8777/" -ForegroundColor Green
Write-Host "  Voice: persistent; say a full command such as 'Thea, what needs my attention?'" -ForegroundColor Green
Write-Host "  Browser reasoning: blocked in unattended processes." -ForegroundColor Green
Write-Host "  The 1,200+ development tests stay in CI and will not run on this PC again.`n" -ForegroundColor Green
