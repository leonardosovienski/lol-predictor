param([switch]$Verify)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\run_archival_collection.py"
if (!(Test-Path $python) -or !(Test-Path $script)) { throw "archival collection entrypoint incomplete" }
$runtime = Join-Path $env:LOCALAPPDATA "predictor-tools\runtime\lol-predictor\lol-archival-collection"
$runner = Join-Path (Split-Path -Parent $root) "tools\operational_runner.py"
if (!(Test-Path $runner)) { throw "operational runner unavailable" }
$status = Join-Path $runtime "collection.status.json"
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $runner + '" --task lol-archival-collection --project lol-predictor --cwd "' + $root + '" --log "' + (Join-Path $runtime "lol-archival-collection.log") + '" --heartbeat "' + (Join-Path $runtime "lol-archival-collection.heartbeat.json") + '" --event-log "' + (Join-Path $runtime "lol-archival-collection.events.jsonl") + '" --lock "' + (Join-Path $runtime "lol-archival-collection.lock") + '" --lock-stale-after 900 --timeout 300 --provenance-mode strict --consumer-status-json "' + $status + '" -- "' + $python + '" -X utf8 "' + $script + '" --status-output "' + $status + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 03:15
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "lol-archival-collection" -Action $action -Trigger $trigger -Settings $settings -Description "LoL COLLECTION_ONLY archival sports data" -Force | Out-Null
Get-ScheduledTask -TaskName "lol-archival-collection" | Select-Object TaskName,State
