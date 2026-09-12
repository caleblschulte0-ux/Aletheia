# Recover the operator's Aletheia checkout after an interrupted plain `git pull`.
# This is intentionally narrow: it never hard-resets, never deletes local commits,
# and refuses to rebase if non-Aletheia working files are dirty.
# Safe entrypoint:
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/recover_operator_checkout.ps1 | iex

$ErrorActionPreference = "Stop"
$dest = Join-Path $HOME "Aletheia"
$taskNames = @("Aletheia", "AletheiaVoice", "AletheiaProjects", "AletheiaApply")
$ownedPrefixes = @("state/", "exchange/commands/", "exchange/receipts/", "cache/")
$legacyJournal = "state/journal/journal.jsonl"
# The branch the Core is deployed on and reads its state from. It moved from
# main to live on 2026-09-08 and this script did not move with it, so on
# 2026-09-11 the operator's own "start her up" command stopped Aletheia, threw
# "checkout is on 'live', not main", and left her dead. Kept in step with
# DEPLOY_BRANCH in tests/test_ci_writes_where_she_reads.py.
$deployBranch = "live"
# Everything this script stopped comes back EXCEPT the microphone, which is
# a button he presses and never a thing a repair script switches on (his
# ruling, 2026-09-07). $coreTask is the one whose door can also be opened
# directly, because it is the one he notices missing.
$coreTask = "Aletheia"
$restartTasks = @("Aletheia", "AletheiaProjects", "AletheiaApply")

function Resume-AletheiaCore {
  # A repair that leaves her dead is worse than the fault it repaired. The
  # scheduled task is the normal door, and it is a NO-OP when the task is
  # disabled or missing - which is exactly the state bringup_windows.ps1
  # puts it in before calling this script. So prove she answers, and launch
  # the supervisor the way the task would when she does not.
  foreach ($name in $restartTasks) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($task -and $task.State -ne "Disabled") {
      Start-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    }
  }
  for ($i = 0; $i -lt 20; $i++) {
    try {
      if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 `
            "http://127.0.0.1:8777/api/status").StatusCode -eq 200) { return $true }
    } catch {}
    if ($i -eq 4) {
      $pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
      if (-not $pythonw) {
        $guess = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\pythonw.exe"
        if (Test-Path $guess) { $pythonw = $guess }
      }
      if ($pythonw) {
        Write-Host "  Bringing the Core back directly ..." -ForegroundColor Yellow
        Start-Process -FilePath $pythonw -ArgumentList '-m','aletheia.supervisor' `
                      -WorkingDirectory $dest -WindowStyle Hidden
      }
    }
    Start-Sleep -Seconds 1
  }
  Write-Warning "Aletheia is NOT answering on 127.0.0.1:8777. Start her with: pythonw -m aletheia.supervisor"
  return $false
}

function Invoke-GitCapture {
  param([Parameter(Mandatory=$true)][string[]]$GitArgs)
  # Windows PowerShell 5 turns harmless native stderr (including Git's
  # "Applied autostash") into an ErrorRecord when ErrorActionPreference is
  # Stop. Capture it under Continue and make the native exit code authoritative.
  $oldPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    $lines = @(& git -C $dest @GitArgs 2>&1)
    $code = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $oldPreference
  }
  return @{
    Code = $code
    Lines = @($lines | ForEach-Object { "$_" })
    Text = (@($lines | ForEach-Object { "$_" }) -join "`n")
  }
}

function Invoke-Git {
  param([Parameter(Mandatory=$true)][string[]]$GitArgs,
        [switch]$ShowOutput)
  $result = Invoke-GitCapture -GitArgs $GitArgs
  if ($ShowOutput -and $result.Text) { Write-Host $result.Text }
  if ($result.Code -ne 0) {
    throw "git failed: $($GitArgs -join ' ')"
  }
  return $result
}

function Rebase-In-Progress {
  $gitDir = Join-Path $dest ".git"
  return ((Test-Path (Join-Path $gitDir "REBASE_HEAD")) -or
          (Test-Path (Join-Path $gitDir "rebase-merge")) -or
          (Test-Path (Join-Path $gitDir "rebase-apply")))
}

function Resolve-Legacy-Journal-Rebase {
  # Old PC builds wrote to the cloud journal. Current builds use
  # journal-pc.jsonl, but one old state checkpoint can still collide while it
  # is replayed. Resolve only that exact append-only legacy case. Any other
  # commit or conflicted path remains a hard stop for a person to inspect.
  for ($attempt = 0; $attempt -lt 20 -and (Rebase-In-Progress); $attempt++) {
    $conflictsResult = Invoke-GitCapture -GitArgs @(
      "diff", "--name-only", "--diff-filter=U"
    )
    if ($conflictsResult.Code -ne 0) { return $false }
    $conflicts = @($conflictsResult.Lines | Where-Object { $_.Trim() })
    if ($conflicts.Count -ne 1 -or $conflicts[0].Trim() -ne $legacyJournal) {
      return $false
    }

    $subject = Invoke-GitCapture -GitArgs @("show", "-s", "--format=%s", "REBASE_HEAD")
    if ($subject.Code -ne 0 -or $subject.Text.Trim() -ne "core: state checkpoint") {
      return $false
    }

    Write-Host "  Preserving the legacy PC journal checkpoint ..." -ForegroundColor Yellow
    $stages = Invoke-GitCapture -GitArgs @(
      "checkout-index", "--stage=all", "--temp", "--", $legacyJournal
    )
    if ($stages.Code -ne 0 -or -not $stages.Lines) { return $false }
    $parts = @((($stages.Lines[-1]).Trim()) -split "\s+")
    if ($parts.Count -lt 3) { return $false }
    $temporary = @($parts[0], $parts[1], $parts[2])

    try {
      # checkout-index returns stage 1/base, 2/current upstream, 3/old PC
      # files. Git's union merge preserves both append-only tails without
      # conflict markers or text re-encoding.
      $union = Invoke-GitCapture -GitArgs @(
        "merge-file", "--union", $temporary[1], $temporary[0], $temporary[2]
      )
      if ($union.Code -gt 1) { return $false }
      Copy-Item -LiteralPath (Join-Path $dest $temporary[1]) `
                -Destination (Join-Path $dest $legacyJournal) -Force
    } finally {
      foreach ($name in $temporary) {
        Remove-Item -LiteralPath (Join-Path $dest $name) -Force -ErrorAction SilentlyContinue
      }
    }

    $null = Invoke-Git -GitArgs @("add", "--", $legacyJournal)
    $staged = Invoke-GitCapture -GitArgs @("diff", "--cached", "--quiet")
    if ($staged.Code -eq 0) {
      $continued = Invoke-GitCapture -GitArgs @("rebase", "--skip")
    } else {
      $continued = Invoke-GitCapture -GitArgs @(
        "-c", "core.editor=true", "rebase", "--continue"
      )
    }
    if ($continued.Code -ne 0 -and -not (Rebase-In-Progress)) { return $false }
  }
  return (-not (Rebase-In-Progress))
}

function Foreign-Working-Paths {
  $status = Invoke-GitCapture -GitArgs @("status", "--porcelain", "-uall")
  if ($status.Code -ne 0) { throw "Could not inspect the Aletheia working tree." }
  $lines = @($status.Lines)
  $foreign = @()
  foreach ($line in $lines) {
    if (-not $line -or $line.Length -lt 4) { continue }
    $path = $line.Substring(3).Trim().Trim('"')
    if ($path -like "* -> *") { $path = ($path -split " -> ", 2)[1] }
    $normalized = $path.Replace('\','/')
    $owned = $false
    foreach ($prefix in $ownedPrefixes) {
      if ($normalized.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        $owned = $true
        break
      }
    }
    if (-not $owned) { $foreign += $normalized }
  }
  return @($foreign)
}

if (-not (Test-Path (Join-Path $dest ".git"))) {
  throw "Aletheia checkout not found at $dest"
}

Write-Host "`n  ALETHEIA CHECKOUT RECOVERY" -ForegroundColor Cyan
Write-Host "  Stopping Aletheia briefly so Git state cannot move during repair ..." -ForegroundColor DarkGray
foreach ($name in $taskNames) {
  Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
}

try {
  $gitDir = Join-Path $dest ".git"
  if (Test-Path (Join-Path $gitDir "MERGE_HEAD")) {
    Write-Host "  Aborting the unfinished editor-only merge ..." -ForegroundColor Yellow
    $null = Invoke-Git -GitArgs @("merge", "--abort")
  }
  if ((Test-Path (Join-Path $gitDir "CHERRY_PICK_HEAD")) -or
      (Test-Path (Join-Path $gitDir "REVERT_HEAD"))) {
    throw "A non-merge Git operation is active. Refusing to stomp somebody's work."
  }
  if ((Rebase-In-Progress) -and -not (Resolve-Legacy-Journal-Rebase)) {
    throw "A non-legacy rebase is active. Refusing to stomp somebody's work."
  }

  $branchResult = Invoke-GitCapture -GitArgs @("rev-parse", "--abbrev-ref", "HEAD")
  $branch = $branchResult.Text.Trim()
  # The deploy branch first, main second: a checkout on either is a checkout
  # this script owns. Anything else (a claude/* working branch) is somebody's
  # work and is still refused.
  if ($branchResult.Code -ne 0 -or $branch -notin @($deployBranch, "main")) {
    throw "Aletheia checkout is on '$branch', not '$deployBranch' or main. Refusing to rewrite another branch."
  }

  $foreign = @(Foreign-Working-Paths)
  if ($foreign.Count -gt 0) {
    $shown = ($foreign | Select-Object -First 4) -join ", "
    throw "Uncommitted non-Aletheia work exists ($shown). Refusing to autostash it."
  }

  # Future accidental `git pull` uses rebase and therefore never asks Vim for
  # a synthetic merge-commit message on this stateful checkout.
  $null = Invoke-Git -GitArgs @("config", "pull.rebase", "true")
  $null = Invoke-Git -GitArgs @("config", "rebase.autoStash", "true")

  # The branch it is ON is the branch it is brought up to date with. Fetching
  # main onto a live checkout is how the 2026-09-08 stale-state defect happened
  # one layer up, in the workflows.
  Write-Host "  Fetching reviewed '$branch' and rebasing local Aletheia state ..." -ForegroundColor Yellow
  $null = Invoke-Git -GitArgs @("fetch", "origin", $branch) -ShowOutput
  $rebase = Invoke-GitCapture -GitArgs @("rebase", "--autostash", "origin/$branch")
  if ($rebase.Code -ne 0 -and -not (Resolve-Legacy-Journal-Rebase)) {
    $null = Invoke-GitCapture -GitArgs @("rebase", "--abort")
    throw "Rebase conflicted and was aborted. No local commit was deleted."
  }

  $ancestor = Invoke-GitCapture -GitArgs @(
    "merge-base", "--is-ancestor", "origin/$branch", "HEAD"
  )
  if ($ancestor.Code -ne 0) {
    throw "Recovery finished Git operations but current HEAD does not contain origin/$branch."
  }

  Write-Host "  Checkout recovered and current '$branch' is present." -ForegroundColor Green
} finally {
  # Never leave on a throw. The old version called Start-ScheduledTask on
  # tasks the caller had just DISABLED, so the net caught nothing and she
  # stayed down; and it started the voice task, which his ruling says is a
  # button he presses.
  if ($env:ALETHEIA_RECOVERY_KEEP_STOPPED -ne "1") {
    $null = Resume-AletheiaCore
  }
}

if ($env:ALETHEIA_RECOVERY_KEEP_STOPPED -eq "1") {
  Write-Host "  Checkout recovered; tasks remain stopped for the calling repair.`n" -ForegroundColor Green
} else {
  Write-Host "  Aletheia tasks restarted. Future plain pulls are configured to rebase.`n" -ForegroundColor Green
}
