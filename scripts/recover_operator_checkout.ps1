# Recover the operator's Aletheia checkout after an interrupted plain `git pull`.
# This is intentionally narrow: it never hard-resets, never deletes local commits,
# and refuses to rebase if non-Aletheia working files are dirty.
# Safe entrypoint:
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/recover_operator_checkout.ps1 | iex

$ErrorActionPreference = "Stop"
$dest = Join-Path $HOME "Aletheia"
$taskNames = @("Aletheia", "AletheiaVoice", "AletheiaProjects")
$ownedPrefixes = @("state/", "exchange/commands/", "exchange/receipts/", "cache/")

function Invoke-Git {
  param([Parameter(Mandatory=$true)][string[]]$GitArgs)
  & git -C $dest @GitArgs
  if ($LASTEXITCODE -ne 0) {
    throw "git failed: $($GitArgs -join ' ')"
  }
}

function Foreign-Working-Paths {
  $lines = @(& git -C $dest status --porcelain -uall)
  if ($LASTEXITCODE -ne 0) { throw "Could not inspect the Aletheia working tree." }
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
    Invoke-Git -GitArgs @("merge", "--abort")
  }
  if ((Test-Path (Join-Path $gitDir "REBASE_HEAD")) -or
      (Test-Path (Join-Path $gitDir "rebase-merge")) -or
      (Test-Path (Join-Path $gitDir "rebase-apply")) -or
      (Test-Path (Join-Path $gitDir "CHERRY_PICK_HEAD")) -or
      (Test-Path (Join-Path $gitDir "REVERT_HEAD"))) {
    throw "A non-merge Git operation is active. Refusing to stomp somebody's work."
  }

  $branch = (& git -C $dest rev-parse --abbrev-ref HEAD).Trim()
  if ($LASTEXITCODE -ne 0 -or $branch -ne "main") {
    throw "Aletheia checkout is on '$branch', not main. Refusing to rewrite another branch."
  }

  $foreign = @(Foreign-Working-Paths)
  if ($foreign.Count -gt 0) {
    $shown = ($foreign | Select-Object -First 4) -join ", "
    throw "Uncommitted non-Aletheia work exists ($shown). Refusing to autostash it."
  }

  # Future accidental `git pull` uses rebase and therefore never asks Vim for
  # a synthetic merge-commit message on this stateful checkout.
  Invoke-Git -GitArgs @("config", "pull.rebase", "true")
  Invoke-Git -GitArgs @("config", "rebase.autoStash", "true")

  Write-Host "  Fetching reviewed main and rebasing local Aletheia state ..." -ForegroundColor Yellow
  Invoke-Git -GitArgs @("fetch", "origin", "main")
  & git -C $dest rebase --autostash origin/main
  if ($LASTEXITCODE -ne 0) {
    & git -C $dest rebase --abort 2>$null | Out-Null
    throw "Rebase conflicted and was aborted. No local commit was deleted."
  }

  & git -C $dest merge-base --is-ancestor origin/main HEAD
  if ($LASTEXITCODE -ne 0) {
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
