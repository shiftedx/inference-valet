$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'install-support.ps1')
$repoRoot = Split-Path -Parent $PSScriptRoot
$task = Get-ValetTask
if ($task) {
 if (-not (Test-ValetTask $task $repoRoot)) { Write-Host 'Startup belongs to another checkout; preserved.'; return }
 Unregister-ScheduledTask -TaskName 'AI Profiles - Idle Reload' -TaskPath '\' -Confirm:$false
}
Write-Host 'Startup removed for this checkout. Model servers and settings are preserved.'
