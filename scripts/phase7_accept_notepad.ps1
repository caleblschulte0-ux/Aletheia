# Codex-owned, unapproved Phase 7 local acceptance harness.
# Run only from branch codex/phase7-windows-control-v0.
# It does not install packages, alter the registry/Core, merge code, save a
# document, or close Notepad. A result is written under gitignored cache/.

$ErrorActionPreference = "Stop"
# Originally locked to the isolated Codex review branch; the module has
# since been reviewed and merged, so main (or a claude/* branch) is fine.
$allowedBranches = @("main", "codex/phase7-windows-control-v0")
$plan = "examples/computer/notepad-acceptance.json"

if ($env:OS -ne "Windows_NT") {
  throw "Phase 7 acceptance must run on the operator's Windows PC."
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "git is required to verify the isolated review branch."
}

$branch = (git branch --show-current).Trim()
if (($allowedBranches -notcontains $branch) -and ($branch -notlike "claude/*")) {
  throw "Refusing to run from '$branch'. Check out main (or a claude/* review branch)."
}

$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" }
      elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" }
      else { throw "Python was not found." }

if (-not (Test-Path $plan)) {
  throw "Acceptance plan not found: $plan"
}

# The plan opens THIS file, so window matching can never reach a document
# the operator already has open (the first live run attached to his real
# Notepad session - a near-miss the redesign forbids by construction).
New-Item -ItemType Directory -Force "cache" | Out-Null
Set-Content -Path "cache\aletheia-acceptance.txt" -Value "" -Encoding ascii

& $py -m aletheia.computer status
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "Windows UI Automation is not ready. No changes were made." -ForegroundColor Yellow
  Write-Host "Review before installing the optional adapter:"
  Write-Host "  $py -m pip install pywinauto"
  exit 2
}

& $py -m aletheia.computer plan $plan
if ($LASTEXITCODE -ne 0) {
  throw "The acceptance plan failed validation; no desktop action was attempted."
}

$approvalId = "phase7-notepad-" + (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
& $py -m aletheia.computer request $plan --approval-id $approvalId
if ($LASTEXITCODE -ne 0) {
  throw "Could not create the durable approval request."
}

Write-Host ""
Write-Host "Approval required" -ForegroundColor Yellow
Write-Host "Action: Open Notepad and enter one harmless sentence."
Write-Host "Consequence: a Notepad tab named aletheia-acceptance.txt (Aletheia's own scratch file) shows one sentence. Your documents are untouchable by construction."
Write-Host "Approval ID: $approvalId"
$answer = Read-Host "Type APPROVE exactly to continue"

if ($answer -cne "APPROVE") {
  & $py -m aletheia.policy decide $approvalId DENIED --because "local acceptance was not explicitly approved"
  Write-Host "Denied. No desktop action was attempted."
  exit 3
}

& $py -m aletheia.policy decide $approvalId APPROVED --because "operator typed APPROVE in the local acceptance harness"
if ($LASTEXITCODE -ne 0) {
  throw "Approval decision failed; no desktop action was attempted."
}

& $py -m aletheia.computer run $plan --approval $approvalId
$executionExit = $LASTEXITCODE

$visible = "no"
if ($executionExit -eq 0) {
  $visible = Read-Host "Did Notepad open and show the exact acceptance sentence? [y/N]"
}
$passed = ($executionExit -eq 0 -and $visible -match "^[Yy]")

$receiptDir = Join-Path "cache" "phase7-acceptance"
New-Item -ItemType Directory -Path $receiptDir -Force | Out-Null
$receiptPath = Join-Path $receiptDir ("result-" + $approvalId + ".json")
[ordered]@{
  schema = 1
  branch = $branch
  approval_id = $approvalId
  executed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
  command_exit_code = $executionExit
  operator_confirmed_visible_text = $passed
  outcome = if ($passed) { "PASSED_LOCAL_ACCEPTANCE" } else { "FAILED_OR_UNVERIFIED" }
  note = "Local-only evidence. Does not promote the capability or merge the draft."
} | ConvertTo-Json | Set-Content -Path $receiptPath -Encoding utf8

if (-not $passed) {
  Write-Host "Acceptance was not verified. Capability remains NOT_BUILT." -ForegroundColor Red
  Write-Host "Receipt: $receiptPath"
  exit 4
}

Write-Host "Local acceptance passed. Capability still remains NOT_BUILT pending review." -ForegroundColor Green
Write-Host "Receipt: $receiptPath"
