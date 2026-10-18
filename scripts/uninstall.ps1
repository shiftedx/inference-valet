param([switch]$NoDesktop, [string[]]$ShortcutDirectories, [switch]$NoStartup)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'install-support.ps1')
$repoRoot = Split-Path -Parent $PSScriptRoot
# Leave source, environment and user data intact: backend hooks can reference this checkout.
if (-not $NoStartup) { & (Join-Path $PSScriptRoot 'remove-startup.ps1') }
$shell = New-Object -ComObject WScript.Shell
foreach ($location in (Get-ValetShortcutLocations $ShortcutDirectories -NoDesktop:$NoDesktop)) {
 $path = Join-Path $location 'Inference Valet.lnk'
 if (-not (Test-Path -LiteralPath $path)) { continue }
 $shortcut = $shell.CreateShortcut($path)
 if (Test-ValetShortcut $shortcut $repoRoot) { Remove-Item -LiteralPath $path }
 else { Write-Host "Shortcut belongs to another checkout; preserved: $path" }
}
Write-Host 'Shell integration removed. Exit Valet from its tray menu to stop monitoring; backend servers remain running.'
Write-Host 'Config, state, source and virtual environment preserved. See docs/SETUP.md before deleting the checkout.'
