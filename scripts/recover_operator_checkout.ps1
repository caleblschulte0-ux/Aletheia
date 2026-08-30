# Recover the operator's Aletheia checkout after an interrupted plain `git pull`.
# This is intentionally narrow: it never hard-resets, never deletes local commits,
# and refuses to rebase if non-Aletheia working files are dirty.
# Safe entrypoint:
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/recover_operator_checkout.ps1 | iex

$ErrorActionPreference = "Stop"
$dest = Join-Path $HOME "Aletheia"
$taskNames = @("Aletheia", "AletheiaVoice", "AletheiaProjects")
$ownedPrefixes = @("state/", "exchange/commands/", "exchange/receipts/", "cache/")
$legacyJournal = "state/journal/journal.jsonl"

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
  if ($branchResult.Code -ne 0 -or $branch -ne "main") {
    throw "Aletheia checkout is on '$branch', not main. Refusing to rewrite another branch."
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

  Write-Host "  Fetching reviewed main and rebasing local Aletheia state ..." -ForegroundColor Yellow
  $null = Invoke-Git -GitArgs @("fetch", "origin", "main") -ShowOutput
  $rebase = Invoke-GitCapture -GitArgs @("rebase", "--autostash", "origin/main")
  if ($rebase.Code -ne 0 -and -not (Resolve-Legacy-Journal-Rebase)) {
    $null = Invoke-GitCapture -GitArgs @("rebase", "--abort")
    throw "Rebase conflicted and was aborted. No local commit was deleted."
  }

  $ancestor = Invoke-GitCapture -GitArgs @(
    "merge-base", "--is-ancestor", "origin/main", "HEAD"
  )
  if ($ancestor.Code -ne 0) {
    throw "Recovery finished Git operations but current HEAD does not contain origin/main."
  }

  Write-Host "  Checkout recovered and current main is present." -ForegroundColor Green
} finally {
  foreach ($name in $taskNames) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
      Start-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    }
  }
}

Write-Host "  Aletheia tasks restarted. Future plain pulls are configured to rebase.`n" -ForegroundColor Green
