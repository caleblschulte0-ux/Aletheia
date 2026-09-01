# Aletheia Windows bootstrap compatibility entrypoint.
#
#   irm https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/bootstrap.ps1 | iex
#
# The old bootstrap made the operator's PC run the entire 1,200+ development
# test suite before it would start the Core. That was both slow and incorrect:
# an intentional production HALT was visible to those tests and made a healthy
# checkout look broken. Full tests now belong in CI (including Windows CI).
#
# Keep the familiar URL, but hand the work to the bounded live bring-up script.
# That script stops stale watchdogs first, refreshes main, validates live
# registries, smoke-gates local AI, and proves Core + voice on this machine. It
# verifies the operator's existing authority but never resumes production or
# grants unattended ChatGPT browser reasoning.

$ErrorActionPreference = "Stop"
$bringup = "https://raw.githubusercontent.com/caleblschulte0-ux/Aletheia/main/scripts/bringup_windows.ps1"
Write-Host "`n  ALETHEIA bootstrap -> safe Windows bring-up" -ForegroundColor Cyan
Invoke-RestMethod $bringup | Invoke-Expression
