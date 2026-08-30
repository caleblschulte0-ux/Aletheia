# Branch-only bootstrap for Aletheia's reviewable two-tier local AI pool.
# Does not modify main or canonical Aletheia runtime files.
param(
    [string]$FastModel = "qwen3:8b",
    [string]$DeepModel = "qwen3.6:27b"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama is missing. Installing official Windows build..."
    irm https://ollama.com/install.ps1 | iex
}

Write-Host "Pulling fast local model: $FastModel"
ollama pull $FastModel
if ($LASTEXITCODE -ne 0) { throw "Failed to pull $FastModel" }

Write-Host "Pulling deep local model: $DeepModel"
ollama pull $DeepModel
if ($LASTEXITCODE -ne 0) { throw "Failed to pull $DeepModel" }

Write-Host "Saving machine-local Aletheia model roles..."
python -m aletheia.model_pool_config set-fast $FastModel --no-think
if ($LASTEXITCODE -ne 0) { throw "Failed to save fast model profile" }
python -m aletheia.model_pool_config set-deep $DeepModel --think
if ($LASTEXITCODE -ne 0) { throw "Failed to save deep model profile" }

Write-Host "Checking Ollama + both configured roles..."
python -m aletheia.local_ai_bridge status
if ($LASTEXITCODE -ne 0) { throw "Local AI bridge status failed" }

Write-Host ""
Write-Host "Aletheia staging local AI pool is configured."
Write-Host "Fast test:"
Write-Host '  python -m aletheia.local_ai_bridge ask --mode fast "Reply with only READY."'
Write-Host "Deep test:"
Write-Host '  python -m aletheia.local_ai_bridge ask --mode deep "Analyze whether this architecture has a hidden failure mode."'
Write-Host "Auto route preview (no inference):"
Write-Host '  python -m aletheia.local_ai_bridge route "review the architecture"'
