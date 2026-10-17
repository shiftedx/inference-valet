param([switch]$NoDesktop)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$pythonw = Join-Path $repoRoot '.venv\Scripts\pythonw.exe'
$icon = Join-Path $repoRoot 'docs\assets\inference-valet.ico'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'Run scripts\setup.ps1 first.' }
if (-not (Test-Path -LiteralPath $icon)) { throw 'Inference Valet icon is missing.' }
$locations = @([Environment]::GetFolderPath('Programs'))
if (-not $NoDesktop) { $locations += [Environment]::GetFolderPath('Desktop') }
$shell = New-Object -ComObject WScript.Shell
Push-Location -LiteralPath $repoRoot
try {
 $icon = & $python -c 'from ai_branding import taskbar_icon_path; print(taskbar_icon_path())'
 if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the versioned app icon.' }
 foreach ($location in $locations) {
  $path = Join-Path $location 'Inference Valet.lnk'
  $shortcut = $shell.CreateShortcut($path)
  $shortcut.TargetPath = $pythonw
  $shortcut.Arguments = '"' + (Join-Path $repoRoot 'ai-launcher.py') + '"'
  $shortcut.WorkingDirectory = $repoRoot
  $shortcut.IconLocation = $icon + ',0'
  $shortcut.Description = 'Inference Valet: local model control and performance.'
  $shortcut.Save()
  & $python -c 'import sys; from ai_branding import set_shortcut_app_id; set_shortcut_app_id(sys.argv[1])' $path
  if ($LASTEXITCODE -ne 0) { throw "Could not set app identity on $path" }
 }
 & $python -c 'import ctypes; ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)'
} finally { Pop-Location }
Write-Host 'Inference Valet shortcuts installed with the app icon and taskbar identity.'
