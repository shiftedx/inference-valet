$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName 'AI Profiles - Idle Reload' -Confirm:$false -ErrorAction SilentlyContinue
Write-Host 'Sign-in task removed. Exit the tray app separately; model servers and saved settings are preserved.'
