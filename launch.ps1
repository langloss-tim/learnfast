# Learnfast Dashboard Launcher
# Right-click and "Run with PowerShell" or run from PowerShell

$ErrorActionPreference = "Stop"

# Change to script directory
Set-Location $PSScriptRoot
Write-Host "Working directory: $PWD" -ForegroundColor Cyan

# Check if venv exists
if (-not (Test-Path "venv\Scripts\activate.ps1")) {
    Write-Host "Virtual environment not found. Creating..." -ForegroundColor Yellow
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to create venv. Make sure Python is installed." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# Activate venv
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
& "venv\Scripts\Activate.ps1"

# Check if streamlit is installed
$streamlitPath = "venv\Scripts\streamlit.exe"
if (-not (Test-Path $streamlitPath)) {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to install dependencies." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# Set PYTHONPATH so imports work
$env:PYTHONPATH = $PWD

Write-Host ""
Write-Host "==================================" -ForegroundColor Green
Write-Host "  Starting Learnfast Dashboard" -ForegroundColor Green
Write-Host "==================================" -ForegroundColor Green
Write-Host ""
Write-Host "Dashboard will open at: http://localhost:8501" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Launch streamlit
& "venv\Scripts\streamlit.exe" run "src\web\dashboard.py" --server.headless true

Read-Host "Press Enter to exit"
