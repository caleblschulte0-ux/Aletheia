# Aletheia full operator-mode activation for Windows.
# Safe entrypoint from any PowerShell window:
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/activate_operator.ps1 | iex
#
# This is the one explicit local operator action that enables bounded standing
# workstation + reviewed-code grants. Human authentication remains human: if
# GitHub or ChatGPT is not signed in, their official browser flows are opened.
# No credential is printed, put in an environment variable, or committed.

$ErrorActionPreference = "Stop"
$repoUrl = "https://github.com/caleblschulte0-ux/Aletheia.git"
$dest = Join-Path $HOME "Aletheia"

function Have($name) { [bool](Get-Command $name -CommandType Application -ErrorAction SilentlyContinue) }
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
function Run-Python([string[]]$Args) {
  & $script:pyExe @script:pyFlags @Args
  if ($LASTEXITCODE -ne 0) { throw "Python command failed: $($Args -join ' ')" }
}

if ($env:OS -ne "Windows_NT") { throw "Aletheia operator activation is Windows-only." }

Write-Host "`n  ALETHEIA OPERATOR MODE" -ForegroundColor Cyan
Write-Host "  One setup: PC control + subscription reasoning + reviewed project loop." -ForegroundColor DarkGray

# ---- required base tools ---------------------------------------------------
if (-not (Have winget)) { throw "Windows Package Manager (winget) is required for one-command setup." }
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
  if (-not $python) { throw "Python installed but is not visible yet; open a new PowerShell and rerun this command." }
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

# ---- get an exact current main while preserving local journal lines --------
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
      [System.IO.File]::AppendAllText($pcJournal, (($new -join "`n") + "`n"),
                                      [System.Text.UTF8Encoding]::new($false))
      git -C $dest add state/journal
      git -C $dest commit -m "pc: salvage locally journaled entries" | Out-Null
      Write-Host "  Preserved $($new.Count) local journal line(s)." -ForegroundColor DarkYellow
    }
  }
}
Set-Location $dest

# ---- mandatory runtime dependencies for operator mode ----------------------
Write-Host "  Installing operator-mode runtime dependencies ..." -ForegroundColor Yellow
Run-Python @("-m","pip","install","--quiet","--upgrade","pip")
Run-Python @("-m","pip","install","--quiet","--only-binary=:all:","-r","requirements-optional.txt")
Run-Python @("-m","playwright","install","chromium")

Write-Host "  Running the full Aletheia test suite before activation ..." -ForegroundColor Yellow
Run-Python @("-m","unittest","discover","-s","tests","-t",".","-q")

# ---- official GitHub authentication -> DPAPI, never stdout -----------------
if (-not (Have gh)) {
  Write-Host "  Installing GitHub CLI ..." -ForegroundColor Yellow
  winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) { throw "GitHub CLI installation failed." }
  Refresh-Path
}
& gh auth status --hostname github.com *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "`n  GitHub needs its one-time web sign-in." -ForegroundColor Cyan
  & gh auth login --hostname github.com --web --git-protocol https
  if ($LASTEXITCODE -ne 0) { throw "GitHub sign-in did not complete." }
}
Run-Python @("-m","aletheia.github_auth","import-cli")

# ---- ChatGPT subscription browser profile ----------------------------------
& $script:pyExe @script:pyFlags -m aletheia.chatgpt_session *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "`n  ChatGPT needs its one-time normal browser sign-in." -ForegroundColor Cyan
  & $script:pyExe @script:pyFlags -m aletheia.browse login https://chatgpt.com/
  if ($LASTEXITCODE -ne 0) { throw "ChatGPT browser sign-in did not complete." }
}
Run-Python @("-m","aletheia.chatgpt_session")

# ---- voice quality, standing grants, and persistent tasks ------------------
Write-Host "  Repairing/upgrading room voice ..." -ForegroundColor Yellow
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dest "scripts\voice_repair.ps1")
if ($LASTEXITCODE -ne 0) { throw "Voice repair failed; operator mode was not declared ready." }

Run-Python @("-m","aletheia.work_trust","on","--days","30","--hours","8","--actions","250")
Run-Python @("-m","aletheia.code_trust","on","--days","30","--prs","25")
Run-Python @("-m","aletheia.autostart","install","--only","core")
Run-Python @("-m","aletheia.project_autostart","install")

# Start the Core and one project cycle now. Voice repair already restarted voice.
Start-ScheduledTask -TaskName "Aletheia" -ErrorAction SilentlyContinue
Run-Python @("-m","aletheia.project_autostart","start")

# ---- final evidence checks -------------------------------------------------
Write-Host "`n  Verifying operator mode ..." -ForegroundColor Yellow
Run-Python @("-m","aletheia.github_auth","status")
Run-Python @("-m","aletheia.chatgpt_session")
Run-Python @("-m","aletheia.work_trust","status")
Run-Python @("-m","aletheia.code_trust","status")
Run-Python @("-m","aletheia.autostart","doctor","--only","core")
Run-Python @("-m","aletheia.autostart","doctor","--only","voice")
Run-Python @("-m","aletheia.project_autostart","status")

Write-Host "`n  OPERATOR MODE IS CONFIGURED." -ForegroundColor Green
Write-Host "  - Core + voice survive logon/restarts." -ForegroundColor Green
Write-Host "  - Routine PC/browser work may auto-open bounded Work Sessions." -ForegroundColor Green
Write-Host "  - GitHub auth is held locally in Windows DPAPI." -ForegroundColor Green
Write-Host "  - Claude subscription is preferred; ChatGPT.com is the signed-in fallback." -ForegroundColor Green
Write-Host "  - Every 30 minutes Thea scans projects and may prepare one reviewed public-repo PR." -ForegroundColor Green
Write-Host "  - She still cannot auto-merge, edit protected safety/auth paths, or export private repo code." -ForegroundColor Green
Write-Host "`n  Next acceptance test in ChatGPT: tell me 'Open Notepad on my computer.'`n" -ForegroundColor Cyan
