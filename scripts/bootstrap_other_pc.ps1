param(
    [switch]$SkipVerification
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python launcher `py` was not found. Install Python 3.10 or newer, then rerun.'
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -m venv .venv
}

& '.venv\Scripts\python.exe' -m pip install --upgrade pip
& '.venv\Scripts\python.exe' -m pip install -r requirements.lock.txt

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Host 'Created .env from .env.example. Add API keys there; .env is git-ignored.'
} else {
    Write-Host 'Kept the existing .env unchanged.'
}

if (-not $SkipVerification) {
    & '.venv\Scripts\python.exe' -m pytest -q
    & '.venv\Scripts\python.exe' -m evals.runner
}

Write-Host ''
Write-Host 'Bootstrap complete.'
Write-Host '1. Edit .env for optional GitHub/Groq/Gemini live access.'
Write-Host '2. Run: .venv\Scripts\python.exe scripts\preflight.py --profile live'
Write-Host '3. Run: .venv\Scripts\python.exe -m app.main'
