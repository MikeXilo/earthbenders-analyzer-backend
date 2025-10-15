# PowerShell script to deploy backend to GitHub repo (respecting .gitignore)
# Usage: .\scripts\deploy-backend-clean.ps1

param(
    [string]$GitHubRepo = "https://github.com/MikeXilo/earthbenders-analyzer-backend.git",
    [string]$CommitMessage = "Deploy backend updates"
)

Write-Host "Deploying backend to GitHub repository (clean version)..." -ForegroundColor Green

# Check if we're in the right directory
if (-not (Test-Path "backend")) {
    Write-Host "Error: backend folder not found. Run this script from the project root." -ForegroundColor Red
    exit 1
}

# Create temporary directory for GitHub repo
$tempDir = "temp-backend-deploy"
if (Test-Path $tempDir) {
    Remove-Item -Recurse -Force $tempDir
}

Write-Host "Creating temporary directory..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $tempDir

try {
    # Clone the GitHub repo
    Write-Host "Cloning GitHub repository..." -ForegroundColor Yellow
    git clone $GitHubRepo $tempDir
    
    # Copy only the files we want (excluding data/)
    Write-Host "Copying backend files (excluding data)..." -ForegroundColor Yellow
    
    # Copy Python files
    Copy-Item -Path "backend\*.py" -Destination "$tempDir\" -Force
    
    # Copy requirements and config files
    Copy-Item -Path "backend\requirements.txt" -Destination "$tempDir\" -Force
    Copy-Item -Path "backend\Dockerfile" -Destination "$tempDir\" -Force
    Copy-Item -Path "backend\.gitignore" -Destination "$tempDir\" -Force
    Copy-Item -Path "backend\.railwayignore" -Destination "$tempDir\" -Force
    Copy-Item -Path "backend\env.example" -Destination "$tempDir\" -Force
    Copy-Item -Path "backend\README.md" -Destination "$tempDir\" -Force
    Copy-Item -Path "backend\railway.json" -Destination "$tempDir\" -Force
    Copy-Item -Path "backend\Procfile" -Destination "$tempDir\" -Force
    
    # Copy routes directory
    Copy-Item -Path "backend\routes" -Destination "$tempDir\" -Recurse -Force
    
    # Copy services directory
    Copy-Item -Path "backend\services" -Destination "$tempDir\" -Recurse -Force
    
    # Copy utils directory
    Copy-Item -Path "backend\utils" -Destination "$tempDir\" -Recurse -Force
    
    # Create empty data directory structure
    New-Item -ItemType Directory -Path "$tempDir\data" -Force
    New-Item -ItemType Directory -Path "$tempDir\data\srtm" -Force
    New-Item -ItemType Directory -Path "$tempDir\data\polygon_sessions" -Force
    New-Item -ItemType Directory -Path "$tempDir\data\basemaps" -Force
    
    # Create .gitkeep files to maintain directory structure
    New-Item -ItemType File -Path "$tempDir\data\srtm\.gitkeep" -Force
    New-Item -ItemType File -Path "$tempDir\data\polygon_sessions\.gitkeep" -Force
    New-Item -ItemType File -Path "$tempDir\data\basemaps\.gitkeep" -Force
    
    # Navigate to the temp directory
    Set-Location $tempDir
    
    # Add all files
    Write-Host "Adding files to git..." -ForegroundColor Yellow
    git add .
    
    # Commit changes
    Write-Host "Committing changes..." -ForegroundColor Yellow
    git commit -m $CommitMessage
    
    # Push to GitHub
    Write-Host "Pushing to GitHub..." -ForegroundColor Yellow
    git push origin main
    
    Write-Host "Backend deployed successfully (clean version)!" -ForegroundColor Green
    Write-Host "Repository: $GitHubRepo" -ForegroundColor Cyan
    Write-Host "Note: Large data files excluded as per strategy" -ForegroundColor Yellow
    
} catch {
    Write-Host "Error during deployment: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    # Clean up
    Set-Location ..
    Remove-Item -Recurse -Force $tempDir
    Write-Host "Cleaned up temporary files" -ForegroundColor Yellow
}
