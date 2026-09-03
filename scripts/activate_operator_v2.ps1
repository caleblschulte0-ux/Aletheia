# Aletheia full operator-mode activation for Windows (v2 hotfix).
# Safe entrypoint:
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/activate_operator_v2.ps1 | iex
#
# This version deliberately never binds a parameter named $Args. PowerShell
# reserves $args as an automatic variable; the original activation helper used
# that name and could silently launch bare Python instead of `python -m ...`.

$ErrorActionPreference = "Stop"
$repoUrl = "https://github.com/caleblschulte0-ux/Aletheia.git"
$dest = Join-Path $HOME "Aletheia"

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
  if (-not $PyArgs -or $PyArgs.Count -eq 0) {
    throw "Internal activation error: refusing to launch Python with an empty argument list."
  }
  & $script:pyExe @script:pyFlags @PyArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Python command failed: $($PyArgs -join ' ')"
  }
}

function Test-GitHubCliAuth {
  # `gh auth status` intentionally exits non-zero and writes to stderr when the
  # operator has not signed in yet. Windows PowerShell 5 can promote that stderr
  # to a terminating NativeCommandError under ErrorActionPreference=Stop, which
  # used to abort activation before the intended web-login fallback ran.
  $oldPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & gh auth status --hostname github.com 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
  } finally {
    $ErrorActionPreference = $oldPreference
  }
}

function Test-ChatGPTSession {
  # Readiness is a probe, not a failure: exit 1 simply means the one-time headed
  # sign-in flow needs to run. Keep that expected state out of the fatal path.
  $oldPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & $script:pyExe @script:pyFlags -m aletheia.chatgpt_session *> $null
    return ($LASTEXITCODE -eq 0)
  } finally {
    $ErrorActionPreference = $oldPreference
  }
}

if ($env:OS -ne "Windows_NT") {
  throw "Aletheia operator activation is Windows-only."
}

Write-Host "`n  ALETHEIA OPERATOR MODE" -ForegroundColor Cyan
Write-Host "  PC control + subscription reasoning + reviewed project loop." -ForegroundColor DarkGray

if (-not (Have winget)) {
  throw "Windows Package Manager (winget) is required for one-command setup."
}
if (-not (Have git)) {
  Write-Host "  Installing Git ..." -ForegroundColor Yellow
  winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) { throw "Git installation failed." }
  Refresh-Path
}

$python = Find-AletheiaPython
if (-not $python) {
  Write-Host "  Installing Python 3.12 ..." -ForegroundColor Yellow
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) { throw "Python installation failed." }
  Refresh-Path
  $python = Find-AletheiaPython
  if (-not $python) {
    throw "Python installed but is not visible yet; open a new PowerShell and rerun this command."
  }
}
$script:pyExe = $python.Exe
$script:pyFlags = @($python.Flags)

# ---- do not race the always-on Core, and do not destroy unpushed work ------
# `git checkout -f -B main origin/main` below discards EVERY uncommitted change
# and EVERY local commit that is not on origin/main. Two things made that
# dangerous on a machine where Aletheia actually runs (2026-09-01 Windows
# lifecycle review):
#
#   * The Core writes state continuously and checkpoint-commits it. Resetting
#     the tree underneath a running Core destroys whatever it had written but
#     not yet committed, and can leave it half-updated mid-beat.
#   * Checkpoint commits that could not be pushed (network out) live only here.
#     A reset deletes the only copy.
#
# So: stop the always-on tasks first, and refuse to discard unpushed commits
# unless the operator explicitly asks. state/private/ is gitignored and is
# never touched by any of this - grants, keys and secrets survive a reset.
function Stop-AletheiaTasks {
  foreach ($name in @("Aletheia", "AletheiaVoice", "AletheiaProjects")) {
    Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue |
      Stop-ScheduledTask -ErrorAction SilentlyContinue
  }
  # The supervisor relaunches the Core, so it goes first; give both a moment
  # to close their files before the tree moves under them.
  Start-Sleep -Seconds 2
}

function Assert-NothingUnpushed($repo) {
  $ahead = (git -C $repo rev-list --count "origin/main..HEAD" 2>$null)
  if ($LASTEXITCODE -eq 0 -and $ahead -and [int]$ahead -gt 0) {
    if ($env:ALETHEIA_DISCARD_LOCAL_COMMITS -eq "1") {
      Write-Host "  Discarding $ahead local commit(s) as instructed." -ForegroundColor Yellow
      return
    }
    throw ("This checkout has $ahead local commit(s) that are not on origin/main - " +
           "most likely Core state checkpoints that never pushed. Resetting would " +
           "delete the only copy. Push them (git -C $repo push origin main), or " +
           "rerun with ALETHEIA_DISCARD_LOCAL_COMMITS=1 to discard them on purpose.")
  }
}

# Recovery/update path. Keep current repo exactly on reviewed origin/main while
# preserving any local journal lines that the always-on PC wrote before reset.
if (-not (Test-Path $dest)) {
  Write-Host "  Cloning Aletheia ..." -ForegroundColor Yellow
  git clone $repoUrl $dest
  if ($LASTEXITCODE -ne 0) { throw "Aletheia clone failed." }
} else {
  Write-Host "  Updating Aletheia main ..." -ForegroundColor Yellow
  git -C $dest fetch origin main
  if ($LASTEXITCODE -ne 0) { throw "Aletheia fetch failed." }

  $localJournal = Join-Path $dest "state\journal\journal.jsonl"
  $salvage = ""
  if (Test-Path $localJournal) { $salvage = Get-Content $localJournal -Raw }

  Stop-AletheiaTasks
  Assert-NothingUnpushed $dest
  git -C $dest checkout -f -B main origin/main
  if ($LASTEXITCODE -ne 0) { throw "Could not reset local checkout to current main." }

  if ($salvage) {
    $upstream = ""
    if (Test-Path $localJournal) { $upstream = Get-Content $localJournal -Raw }
    $pcJournal = Join-Path $dest "state\journal\journal-pc.jsonl"
    $existing = ""
    if (Test-Path $pcJournal) { $existing = Get-Content $pcJournal -Raw }
    $known = ($upstream + "`n" + $existing) -split "`r?`n"
    $new = @($salvage -split "`r?`n" | Where-Object { $_.Trim() -and ($known -notcontains $_) })
    if ($new.Count -gt 0) {
      [System.IO.File]::AppendAllText(
        $pcJournal,
        (($new -join "`n") + "`n"),
        [System.Text.UTF8Encoding]::new($false)
      )
      git -C $dest add state/journal
      git -C $dest commit -m "pc: salvage locally journaled entries" | Out-Null
      Write-Host "  Preserved $($new.Count) local journal line(s)." -ForegroundColor DarkYellow
    }
  }
}
Set-Location $dest

Write-Host "  Installing operator-mode runtime dependencies ..." -ForegroundColor Yellow
Invoke-AletheiaPython -PyArgs @("-m","pip","install","--quiet","--upgrade","pip")
Invoke-AletheiaPython -PyArgs @("-m","pip","install","--quiet","--only-binary=:all:","-r","requirements-optional.txt")
Invoke-AletheiaPython -PyArgs @("-m","playwright","install","chromium")

Write-Host "  Running the full Aletheia test suite before activation ..." -ForegroundColor Yellow
Invoke-AletheiaPython -PyArgs @("-m","unittest","discover","-s","tests","-t",".","-q")

# GitHub authentication: official gh web flow -> local DPAPI vault.
if (-not (Have gh)) {
  Write-Host "  Installing GitHub CLI ..." -ForegroundColor Yellow
  winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) { throw "GitHub CLI installation failed." }
  Refresh-Path
}
if (-not (Test-GitHubCliAuth)) {
  Write-Host "`n  GitHub needs its one-time web sign-in." -ForegroundColor Cyan
  & gh auth login --hostname github.com --web --git-protocol https
  if ($LASTEXITCODE -ne 0) { throw "GitHub sign-in did not complete." }
}
Invoke-AletheiaPython -PyArgs @("-m","aletheia.github_auth","import-cli")

# ChatGPT subscription: normal dedicated browser-profile sign-in; no API key.
if (-not (Test-ChatGPTSession)) {
  Write-Host "`n  ChatGPT needs its one-time normal browser sign-in." -ForegroundColor Cyan
  & $script:pyExe @script:pyFlags -m aletheia.browse login https://chatgpt.com/
  if ($LASTEXITCODE -ne 0) { throw "ChatGPT browser sign-in did not complete." }
}
Invoke-AletheiaPython -PyArgs @("-m","aletheia.chatgpt_session")

Write-Host "  Repairing/upgrading room voice ..." -ForegroundColor Yellow
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dest "scripts\voice_repair.ps1")
if ($LASTEXITCODE -ne 0) {
  throw "Voice repair failed; operator mode was not declared ready."
}

Invoke-AletheiaPython -PyArgs @("-m","aletheia.work_trust","on","--days","30","--hours","8","--actions","250")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.code_trust","on","--days","30","--prs","25")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.autostart","install","--only","core")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.project_autostart","install")

Start-ScheduledTask -TaskName "Aletheia" -ErrorAction SilentlyContinue
Invoke-AletheiaPython -PyArgs @("-m","aletheia.project_autostart","start")

Write-Host "`n  Verifying operator mode ..." -ForegroundColor Yellow
Invoke-AletheiaPython -PyArgs @("-m","aletheia.github_auth","status")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.chatgpt_session")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.work_trust","status")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.code_trust","status")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.autostart","doctor","--only","core")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.autostart","doctor","--only","voice")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.project_autostart","status")

Write-Host "`n  OPERATOR MODE IS CONFIGURED." -ForegroundColor Green
Write-Host "  Core + voice are persistent; project repair runs every 30 minutes." -ForegroundColor Green
Write-Host "  Claude subscription is preferred; signed-in ChatGPT.com is the fallback." -ForegroundColor Green
Write-Host "  Code work remains reviewed branch/PR only; no autonomous merge to main." -ForegroundColor Green
Write-Host "`n  Next acceptance test: tell ChatGPT 'Open Notepad on my computer.'`n" -ForegroundColor Cyan
