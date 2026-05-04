# One-time local setup: Ollama + model for EduMind (Windows PowerShell).
# Run from repo root:  powershell -ExecutionPolicy Bypass -File scripts\setup-ollama-dev.ps1

$ErrorActionPreference = "Stop"
Write-Host "EduMind — Ollama dev setup" -ForegroundColor Cyan

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "Ollama is not in PATH. Install from https://ollama.com then re-run this script." -ForegroundColor Yellow
    exit 1
}

$model = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "llama3.2" }
Write-Host "Pulling model: $model (first time may take a few minutes)..." -ForegroundColor Gray
& ollama pull $model

Write-Host "OK. Start the Flask app with FLASK_ENV=development (default in .env.example)." -ForegroundColor Green
Write-Host "The app will call Ollama at http://127.0.0.1:11434 unless you set OLLAMA_BASE_URL= empty in .env" -ForegroundColor Gray
Write-Host "Smoke test after `python run.py`:  open http://127.0.0.1:5000/ai/test" -ForegroundColor Gray
