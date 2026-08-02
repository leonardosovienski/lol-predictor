param([switch]$Verify)

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

if ($Verify) {
    $probeTask = "$taskName-probe"
    $probeScript = Join-Path $projectRoot "scripts\scheduler_probe.py"
    $probeOutput = Join-Path $projectRoot "data\scheduler_probe_attestation.json"
    if (-not (Test-Path -LiteralPath $probeScript -PathType Leaf)) {
        throw "Scheduler probe not found: $probeScript"
    }
    Remove-Item -LiteralPath $probeOutput -Force -ErrorAction SilentlyContinue
    $probeAction = New-ScheduledTaskAction `
        -Execute $pythonExe `
        -Argument ('-X utf8 "' + $probeScript + '" --output "' + $probeOutput + '"') `
        -WorkingDirectory $projectRoot
    $probeTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5)
    try {
        Register-ScheduledTask `
            -TaskName $probeTask `
            -Action $probeAction `
            -Trigger $probeTrigger `
            -Settings $settings `
            -Principal $principal `
            -Description "Harmless LoL Scheduler execution probe" `
            -Force | Out-Null
        Start-ScheduledTask -TaskName $probeTask
        $deadline = (Get-Date).AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 250
            $probeInfo = Get-ScheduledTaskInfo -TaskName $probeTask
            $probeState = (Get-ScheduledTask -TaskName $probeTask).State
        } while ((-not (Test-Path -LiteralPath $probeOutput) -or
                  $probeState -eq "Running") -and (Get-Date) -lt $deadline)
        if (-not (Test-Path -LiteralPath $probeOutput)) {
            throw "Scheduler probe did not produce its artifact"
        }
        $probe = Get-Content -LiteralPath $probeOutput -Raw | ConvertFrom-Json
        if ($probeInfo.LastTaskResult -ne 0 -or $probe.status -ne "SUCCEEDED") {
            throw "Scheduler probe failed: result=$($probeInfo.LastTaskResult) status=$($probe.status)"
        }
        $probe
    } finally {
        Unregister-ScheduledTask -TaskName $probeTask -Confirm:$false `
            -ErrorAction SilentlyContinue
    }
}
