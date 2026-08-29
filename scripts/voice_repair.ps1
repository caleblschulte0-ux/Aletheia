# Aletheia room-voice repair / quality upgrade for Windows.
#
# Run from the repo after this voice stack has landed:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\voice_repair.ps1
#
# This is deliberately operator-invoked. It may download the improved local
# Vosk model plus optional Piper/faster-whisper packages/models, then it
# replaces the AletheiaVoice Scheduled Task so the already-running old Python
# process cannot keep stale voice code loaded indefinitely.

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

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

if ($env:OS -ne "Windows_NT") {
  throw "voice_repair.ps1 is Windows-only."
}

$python = Find-AletheiaPython
if (-not $python) {
  throw "Python 3.10+ was not found. Re-run scripts/bootstrap.ps1 first."
}
$pyExe = $python.Exe
$pyFlags = @($python.Flags)

Write-Host "`n  ALETHEIA VOICE REPAIR" -ForegroundColor Cyan
Write-Host "  Repo: $repoRoot"
Write-Host "  Python: $pyExe $pyFlags" -ForegroundColor DarkGray

# A dirty/non-main checkout is a review/development state. Do not restart the
# operator's always-on voice task into code that has not landed on main.
$branch = (git -C $repoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw "could not read the git branch" }
if ($branch -ne "main") {
  throw "refusing to restart always-on voice from branch '$branch'; run this only after Claude merges the reviewed fix to main."
}

Write-Host "`n  1/4 Preparing improved local ears + neural voice ..." -ForegroundColor Yellow
& $pyExe @pyFlags -m aletheia.voice_room --setup
if ($LASTEXITCODE -ne 0) {
  throw "required room recognizer setup failed; the current listener was left untouched."
}

Write-Host "`n  2/4 Re-registering the voice watchdog with current Python ..." -ForegroundColor Yellow
& $pyExe @pyFlags -m aletheia.autostart install --only voice
if ($LASTEXITCODE -ne 0) { throw "could not register the AletheiaVoice task" }

Write-Host "`n  3/4 Replacing any stale running listener ..." -ForegroundColor Yellow
$task = Get-ScheduledTask -TaskName "AletheiaVoice" -ErrorAction SilentlyContinue
if (-not $task) { throw "AletheiaVoice task is not registered after install" }

# Stop-ScheduledTask may report success before pythonw has fully exited. Wait
# briefly for Task Scheduler's state rather than starting a competing listener.
Stop-ScheduledTask -TaskName "AletheiaVoice" -ErrorAction SilentlyContinue
$deadline = (Get-Date).AddSeconds(15)
do {
  Start-Sleep -Milliseconds 250
  $task = Get-ScheduledTask -TaskName "AletheiaVoice" -ErrorAction SilentlyContinue
} while ($task -and $task.State -eq "Running" -and (Get-Date) -lt $deadline)
if ($task -and $task.State -eq "Running") {
  throw "old AletheiaVoice listener did not stop within 15 seconds; refusing to start a second listener."
}

Start-ScheduledTask -TaskName "AletheiaVoice"
Start-Sleep -Seconds 3
$task = Get-ScheduledTask -TaskName "AletheiaVoice"
if ($task.State -ne "Running") {
  $info = Get-ScheduledTaskInfo -TaskName "AletheiaVoice"
  throw "AletheiaVoice did not stay running (state=$($task.State), last result=$($info.LastTaskResult))."
}

Write-Host "`n  4/4 Checking the live voice dependencies ..." -ForegroundColor Yellow
& $pyExe @pyFlags -m aletheia.voice_room --check
if ($LASTEXITCODE -ne 0) {
  throw "voice task restarted, but readiness check found a problem. Read the lines above."
}

Write-Host "`n  Voice stack restarted on current main." -ForegroundColor Green
Write-Host "  Hands-free test: say 'Thea, what is going on?' once." -ForegroundColor Green
Write-Host "  Silence test: talk normally without saying Thea; she should say nothing." -ForegroundColor Green
Write-Host "  Browser fallback: click its mic and speak WITHOUT saying Thea." -ForegroundColor Green
Write-Host ""
