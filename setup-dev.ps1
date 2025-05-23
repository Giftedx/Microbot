# Microbot Development Environment Setup Script (PowerShell)

Write-Host "🤖 Setting up Microbot development environment..." -ForegroundColor Green

# Check if Docker is available
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Docker is not installed. Please install Docker Desktop first." -ForegroundColor Red
    exit 1
}

# Build the development container
Write-Host "🐳 Building development container..." -ForegroundColor Cyan
docker build -t microbot-dev .

# Set up Python environment locally (if not using container)
if (Get-Command python -ErrorAction SilentlyContinue) {
    Write-Host "🐍 Setting up Python environment..." -ForegroundColor Yellow
    Set-Location python_agent
    if (-not (Test-Path "venv")) {
        python -m venv venv
    }
    & "venv\Scripts\Activate.ps1"
    pip install -r requirements.txt
    Set-Location ..
}

# Build Java components
if (Get-Command mvn -ErrorAction SilentlyContinue) {
    Write-Host "☕ Building Java components..." -ForegroundColor Magenta
    mvn clean compile
}

Write-Host "✅ Development environment setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To start developing:" -ForegroundColor Cyan
Write-Host "  1. For Python agent: cd python_agent && .\venv\Scripts\Activate.ps1"
Write-Host "  2. For Java: Use your IDE or mvn commands"
Write-Host "  3. For container development: Use the Cursor dev container features" 