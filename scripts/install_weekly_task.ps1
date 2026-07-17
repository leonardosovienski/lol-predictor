$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $projectRoot "scripts\atualiza_semanal.py"
$taskName = "lol-ratings-semanal"

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Python executable not found: $pythonExe"
}
if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
    throw "Weekly entrypoint not found: $entrypoint"
}

$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument ('-X utf8 "' + $entrypoint + '"') `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday `
    -At 08:30
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Weekly observable LoL ratings refresh" `
    -Force | Out-Null

Get-ScheduledTask -TaskName $taskName |
    Select-Object TaskName, State, TaskPath
Get-ScheduledTaskInfo -TaskName $taskName |
    Select-Object LastRunTime, LastTaskResult, NextRunTime, NumberOfMissedRuns
