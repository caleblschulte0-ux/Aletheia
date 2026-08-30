# Aletheia local AI bootstrap (Windows)
# Installs Ollama if needed, pulls a chosen local model, saves that choice in
# machine-local config, and verifies the loopback API. Nothing touches main.
param(
    [string]$Model = ""
)

$ErrorActionPreference = "Stop"
$BaseUrl = if ($env:ALETHEIA_LOCAL_AI_URL) { $env:ALETHEIA_LOCAL_AI_URL } else { "http://127.0.0.1:11434" }

if ($BaseUrl -notin @("http://127.0.0.1:11434", "http://localhost:11434")) {
    throw "ALETHEIA_LOCAL_AI_URL must point to local Ollama on loopback. Got: $BaseUrl"
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama is not installed. Installing the official Windows build..."
    irm https://ollama.com/install.ps1 | iex
}

if (-not $Model) {
    if ($env:ALETHEIA_LOCAL_AI_MODEL) {
        $Model = $env:ALETHEIA_LOCAL_AI_MODEL
    } else {
        $resolved = python -m aletheia.model_config show | ConvertFrom-Json
        $Model = $resolved.model
    }
}

Write-Host "Pulling Aletheia local model: $Model"
ollama pull $Model
if ($LASTEXITCODE -ne 0) {
    throw "ollama pull failed for $Model"
}

# Save the selection outside Git. Future swaps are the same one-line command.
python -m aletheia.model_config set $Model
if ($LASTEXITCODE -ne 0) {
    throw "Could not save Aletheia local model selection"
}

Write-Host "Checking local Ollama API..."
$tags = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/tags" -TimeoutSec 15
$names = @($tags.models | ForEach-Object { $_.name })
if ($names -notcontains $Model) {
    throw "Ollama is online but $Model was not found after pull. Available: $($names -join ', ')"
}

Write-Host "Local AI is ready: $Model"
Write-Host "Change models later with: python -m aletheia.model_config set <ollama-model>"
Write-Host "Training capture is ON by default and remains local to this PC."
Write-Host "Check with: python -m aletheia.training_cli status"
Write-Host "Test Aletheia with:"
Write-Host '  python -m aletheia.brain_router status'
Write-Host '  python -m aletheia.brain_router interpret "What needs my attention?"'
