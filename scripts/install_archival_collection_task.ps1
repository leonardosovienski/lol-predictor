param([switch]$Verify)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\run_archival_collection.py"
if (!(Test-Path $python) -or !(Test-Path $script)) { throw "archival collection entrypoint incomplete" }
$action = New-ScheduledTaskAction -Execute $python -Argument ('-X utf8 "' + $script + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 03:15
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "lol-archival-collection" -Action $action -Trigger $trigger -Settings $settings -Description "LoL COLLECTION_ONLY archival sports data" -Force | Out-Null
Get-ScheduledTask -TaskName "lol-archival-collection" | Select-Object TaskName,State
