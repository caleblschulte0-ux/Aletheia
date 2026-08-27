param()
$ErrorActionPreference = 'Stop'

Write-Host 'Aletheia Phase 11 audio acceptance probe'
Write-Host 'READ-ONLY: this script inventories endpoints and changes no audio settings.'

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$python = $null
foreach ($candidate in @('python','py')) {
    try {
        $cmd = Get-Command $candidate -CommandType Application -ErrorAction Stop
        $python = $cmd.Source
        break
    } catch {}
}
if (-not $python) {
    Write-Error 'Python launcher not found.'
}

& $python -m aletheia.audio_cli inventory
if ($LASTEXITCODE -ne 0) {
    Write-Error 'Audio inventory failed. Install optional voice/audio dependencies first.'
}

Write-Host ''
Write-Host 'Interpretation:'
Write-Host '- At least one input + one output must exist.'
Write-Host '- Phone V0 also needs reviewed virtual audio endpoints (VB-CABLE/VoiceMeeter or equivalent).'
Write-Host '- This probe does NOT prove routing. Promotion requires a reviewed Windows backend plus a live route/observe/stop round trip.'
Write-Host '- Do not expose Core port 8777 or bypass the approval gates to make the test easier.'
