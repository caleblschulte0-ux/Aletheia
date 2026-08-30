# Finish Aletheia operator activation after GitHub + ChatGPT session checks already pass.
# Safe entrypoint:
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/finish_operator.ps1 | iex

$ErrorActionPreference = "Stop"
$dest = Join-Path $HOME "Aletheia"

if ($env:OS -ne "Windows_NT") { throw "Aletheia operator finish is Windows-only." }
if (-not (Test-Path $dest)) { throw "Aletheia checkout not found at $dest." }
if (-not (Get-Command py -CommandType Application -ErrorAction SilentlyContinue)) {
  throw "Python launcher 'py' is not available."
}

Set-Location $dest

function Invoke-AletheiaPython {
  param([Parameter(Mandatory=$true)][string[]]$PyArgs)
  if (-not $PyArgs -or $PyArgs.Count -eq 0) {
    throw "Internal finish error: refusing empty Python arguments."
  }
  & py -3.12 @PyArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Python command failed: py -3.12 $($PyArgs -join ' ')"
  }
}

Write-Host "`n  ALETHEIA OPERATOR MODE — FINISH" -ForegroundColor Cyan
Write-Host "  Skipping the full test/install pass; verifying prerequisites first." -ForegroundColor DarkGray

# These must already be working before standing authority is enabled.
Invoke-AletheiaPython -PyArgs @("-m","aletheia.github_auth","status")
Invoke-AletheiaPython -PyArgs @("-m","aletheia.chatgpt_session")

Write-Host "  Repairing/upgrading room voice ..." -ForegroundColor Yellow
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dest "scripts\voice_repair.ps1")
if ($LASTEXITCODE -ne 0) { throw "Voice repair failed; operator mode was not enabled." }

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
Write-Host "  Claude is preferred; signed-in ChatGPT.com is the fallback." -ForegroundColor Green
Write-Host "  Code work remains reviewed branch/PR only; no autonomous merge to main." -ForegroundColor Green
Write-Host "`n  Next acceptance test: tell ChatGPT 'Open Notepad on my computer.'`n" -ForegroundColor Cyan
