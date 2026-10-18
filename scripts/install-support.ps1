# Shared ownership checks; no operations occur when this file is dot-sourced.
function Get-ValetCanonicalPath([string]$Path) {
 if ([string]::IsNullOrWhiteSpace($Path) -or $Path -notmatch '^(?:[a-zA-Z]:[\\/]|\\\\)') { throw 'An absolute Windows path is required.' }
 if (-not ('ValetInstall.NativePaths' -as [type])) {
  Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
using System.Text;
namespace ValetInstall {
 public static class NativePaths {
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern uint GetLongPathName(string path, StringBuilder output, uint capacity);
 }
}
'@
 }
 $full = [IO.Path]::GetFullPath($Path)
 # Missing executables/scripts are valid when removing an older installation.
 # Expand the nearest existing ancestor, then retain exact missing components.
 $ancestor = $full
 $suffix = @()
 while (-not (Test-Path -LiteralPath $ancestor)) {
  $parent = [IO.Path]::GetDirectoryName($ancestor)
  if ([string]::IsNullOrEmpty($parent) -or $parent -eq $ancestor) { throw 'Cannot establish the path ancestor.' }
  $suffix = @([IO.Path]::GetFileName($ancestor)) + $suffix
  $ancestor = $parent
 }
 $buffer = New-Object Text.StringBuilder 32768
 $length = [ValetInstall.NativePaths]::GetLongPathName($ancestor, $buffer, $buffer.Capacity)
 if ($length -eq 0 -or $length -ge $buffer.Capacity) { throw 'Cannot expand the path identity.' }
 $canonical = $buffer.ToString()
 foreach ($component in $suffix) { $canonical = [IO.Path]::Combine($canonical, $component) }
 return $canonical.TrimEnd('\')
}
function Test-ValetPath($Actual, $Expected) {
 if ([string]::IsNullOrWhiteSpace([string]$Actual)) { return $false }
 try { return (Get-ValetCanonicalPath $Actual).Equals((Get-ValetCanonicalPath $Expected), [StringComparison]::OrdinalIgnoreCase) } catch { return $false }
}
function Test-ValetAction($Action, $Root, [switch]$Startup) {
 # Accept only one exact launcher path and the optional expected tray flag.
 # Parse the restricted generated argument format; never evaluate command text.
 if ([string]$Action.Arguments -notmatch '^\s*(?:"([^"\r\n]+)"|([^"\s]+))(?:\s+(--tray))?\s*$') { return $false }
 $script = $Matches[1]
 if (-not $script) { $script = $Matches[2] }
 $tray = $Matches[3]
 if (($Startup -and $tray -cne '--tray') -or (-not $Startup -and $tray)) { return $false }
 return (Test-ValetPath $Action.Execute (Join-Path $Root '.venv\Scripts\pythonw.exe')) -and (Test-ValetPath $script (Join-Path $Root 'ai-launcher.py')) -and (Test-ValetPath $Action.WorkingDirectory $Root)
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
