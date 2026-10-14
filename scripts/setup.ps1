param([string]$Python = 'py')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
& $Python -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 or newer is required'; import tkinter"
if ($LASTEXITCODE -ne 0) { throw 'Install Windows Python 3.11+ with Tcl/Tk, or pass -Python with a working Python executable path.' }
& $Python -m venv (Join-Path $repoRoot '.venv')
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $venvPython -m pip install -r (Join-Path $repoRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'config.json'))) {
 Copy-Item -LiteralPath (Join-Path $repoRoot 'config.example.json') -Destination (Join-Path $repoRoot 'config.json')
}
& (Join-Path $PSScriptRoot 'install-shortcuts.ps1')
Write-Host 'Setup complete. Edit config.json, then open Inference Valet from Desktop or Start.'
