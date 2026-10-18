# Shared ownership checks; no operations occur when this file is dot-sourced.
function Test-ValetPath($Actual, $Expected) {
 if ([string]::IsNullOrWhiteSpace([string]$Actual)) { return $false }
 try { return [IO.Path]::GetFullPath($Actual).TrimEnd('\').Equals([IO.Path]::GetFullPath($Expected).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase) } catch { return $false }
}
function Test-ValetAction($Action, $Root, [switch]$Startup) {
 $expectedArgs = '"' + (Join-Path $Root 'ai-launcher.py') + '"'
 if ($Startup) { $expectedArgs += ' --tray' }
 return (Test-ValetPath $Action.Execute (Join-Path $Root '.venv\Scripts\pythonw.exe')) -and ($Action.Arguments -eq $expectedArgs) -and (Test-ValetPath $Action.WorkingDirectory $Root)
}
function Get-ValetTask {
 # Do not hide permission or provider failures as a missing task.
 return Get-ScheduledTask | Where-Object { $_.TaskName -eq 'AI Profiles - Idle Reload' -and $_.TaskPath -eq '\' }
}
function Test-ValetTask($Task, $Root) {
 return @($Task.Actions).Count -eq 1 -and (Test-ValetAction $Task.Actions[0] $Root -Startup)
}
function Test-ValetShortcut($Shortcut, $Root) {
 $action = [pscustomobject]@{Execute=$Shortcut.TargetPath;Arguments=$Shortcut.Arguments;WorkingDirectory=$Shortcut.WorkingDirectory}
 return Test-ValetAction $action $Root
}
function Get-ValetShortcutLocations([string[]]$ShortcutDirectories, [switch]$NoDesktop) {
 if ($ShortcutDirectories) { return $ShortcutDirectories }
 $locations = @([Environment]::GetFolderPath('Programs'))
 if (-not $NoDesktop) { $locations += [Environment]::GetFolderPath('Desktop') }
 return $locations
}
