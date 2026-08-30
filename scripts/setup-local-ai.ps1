# Aletheia local AI bootstrap (Windows)
# Installs Ollama if needed, pulls the default local model, and verifies the
# loopback API. It does not modify Aletheia state, Git config, or main.

$ErrorActionPreference = "Stop"
$Model = if ($env:ALETHEIA_LOCAL_AI_MODEL) { $env:ALETHEIA_LOCAL_AI_MODEL } else { "qwen3:8b" }
$BaseUrl = if ($env:ALETHEIA_LOCAL_AI_URL) { $env:ALETHEIA_LOCAL_AI_URL } else { "http://127.0.0.1:11434" }

if ($BaseUrl -notin @("http://127.0.0.1:11434", "http://localhost:11434")) {
    throw "ALETHEIA_LOCAL_AI_URL must point to local Ollama on loopback. Got: $BaseUrl"
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama is not installed. Installing the official Windows build..."
    irm https://ollama.com/install.ps1 | iex
}

Write-Host "Pulling Aletheia local model: $Model"
ollama pull $Model
if ($LASTEXITCODE -ne 0) {
    throw "ollama pull failed for $Model"
}

Write-Host "Checking local Ollama API..."
$tags = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/tags" -TimeoutSec 15
$names = @($tags.models | ForEach-Object { $_.name })
if ($names -notcontains $Model) {
    throw "Ollama is online but $Model was not found after pull. Available: $($names -join ', ')"
}

Write-Host "Local AI is ready."
Write-Host "Test Aletheia with:"
Write-Host '  python -m aletheia.brain_router status'
Write-Host '  python -m aletheia.brain_router interpret "What needs my attention?"'
