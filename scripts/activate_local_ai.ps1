# Smoke-test and activate Aletheia's local reasoning pool on Windows.
# Run only after the reviewed local-AI integration has landed on main:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\activate_local_ai.ps1

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
  throw "activate_local_ai.ps1 is Windows-only."
}

$branch = (git -C $repoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw "could not read the Aletheia git branch" }
if ($branch -ne "main") {
  throw "refusing to activate local AI from branch '$branch'; run this only after the reviewed integration lands on main."
}

$python = Find-AletheiaPython
if (-not $python) {
  throw "Python 3.10+ was not found. Re-run scripts/bootstrap.ps1 first."
}
$pyExe = $python.Exe
$pyFlags = @($python.Flags)

Write-Host "`n  ALETHEIA LOCAL AI ACTIVATION" -ForegroundColor Cyan
Write-Host "  Testing the fast route and checking both configured Ollama model tags ..." -ForegroundColor Yellow
& $pyExe @pyFlags -m aletheia.local_ai activate
if ($LASTEXITCODE -ne 0) {
  $activationCode = $LASTEXITCODE
  Write-Host "  Local model smoke test failed; local routing remains disabled." -ForegroundColor Red
  Write-Host "  Read the JSON diagnostic above; no routing change was made." -ForegroundColor Red
  exit $activationCode
}

Write-Host "`n  Local reasoning is active. Background 27B shadowing remains OFF." -ForegroundColor Green
Write-Host "  Check any time: python -m aletheia.local_ai status" -ForegroundColor Green
Write-Host "  Instant rollback: python -m aletheia.local_ai deactivate`n" -ForegroundColor Green
