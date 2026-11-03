# Run using Windows PowerShell or PowerShell 7. Nothing is pushed to GitHub.
$ErrorActionPreference = "Stop"
$repo = "https://github.com/Cacacarlos1221/global-market-radar.git"
$branch = "experiment/market-analysis-agent-v0"
$desktop = [Environment]::GetFolderPath("Desktop")
$parent = Join-Path $desktop "学习"
$project = Join-Path $parent "global-market-radar-agent"
New-Item -ItemType Directory -Path $parent -Force | Out-Null
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "Git not found. Install Git for Windows and run this script again."
}
if (Test-Path $project) {
  if (-not (Test-Path (Join-Path $project ".git"))) {
    throw "Target directory already exists and is not a Git repository: $project"
  }
  Write-Host "Existing project preserved, no automatic git pull or reset: $project"
} else {
  git clone --single-branch --branch $branch $repo $project
  if ($LASTEXITCODE -ne 0) { throw "Git clone failed" }
}
Set-Location $project
$venv = Join-Path $project ".venv"
if (-not (Test-Path $venv)) {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m venv $venv
  } elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python -m venv $venv
  } else {
    throw "Python 3.11+ is required. Install Python and run again."
  }
  if ($LASTEXITCODE -ne 0) { throw "Failed to create Python virtual environment" }
}
$python = Join-Path $venv "Scripts\python.exe"
$envTarget = Join-Path $project "agent\.env"
if (-not (Test-Path $envTarget)) {
  Copy-Item (Join-Path $project "agent\.env.example") $envTarget
}
Write-Host ""
Write-Host "[1/3] Run offline unit tests" -ForegroundColor Cyan
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Offline tests failed" }
Write-Host ""
Write-Host "[2/3] Check local model configuration" -ForegroundColor Cyan
& $python -m agent.main doctor
if ($LASTEXITCODE -ne 0) { throw "Doctor failed" }
Write-Host ""
Write-Host "[3/3] Run offline preview on existing 2026-11-03 snapshot" -ForegroundColor Cyan
$preview = Join-Path $project "agent\output\2026-11-03\audit.json"
if (-not (Test-Path $preview)) {
  & $python -m agent.main flow --date 2026-11-03 --offline
  if ($LASTEXITCODE -ne 0) { throw "Offline flow failed" }
} else {
  Write-Host "Existing preview preserved (not overwritten)"
}
Write-Host ""
Write-Host "READY. Project: $project" -ForegroundColor Green
Write-Host "API key configuration: $envTarget"
Write-Host ("Open with Notepad: notepad " + $envTarget)
Write-Host ("After setting real API credentials: & " + $python + " -m agent.main smoke-model")
Write-Host ("For today's official-source news: & " + $python + " -m agent.main research")
Write-Host ("Preview: " + (Join-Path $project "agent\output\2026-11-03\report.preview.html"))
