<#
.SYNOPSIS
    Registers the \Power655\Refresh Windows Task Scheduler task: a Tue/Thu/Sat 20:00 draw-night
    run and a Wed/Fri/Sun 08:30 next-day retry (refresh is idempotent, so the retry is safe even
    when nothing changed).

.DESCRIPTION
    The human runs this script. Agents never execute it.

.PARAMETER PythonExe
    Absolute path to a python.exe with this project's dependencies installed. Defaults to
    `(Get-Command python).Source`. A python.exe under \WindowsApps\ (the Microsoft Store alias,
    which does not run a real interpreter) is rejected.

.PARAMETER DrawRunTime
    Local time of the draw-night run, "HH:mm". Default 20:00.

.PARAMETER RetryTime
    Local time of the next-day retry, "HH:mm". Default 08:30.

.PARAMETER Replace
    Overwrite an existing \Power655\Refresh task.

.PARAMETER Force
    Register even if the machine's local UTC offset is not +07:00 (Asia/Ho_Chi_Minh). The human
    asserts that DrawRunTime/RetryTime are already expressed in the intended local time.
#>
[CmdletBinding()]
param(
    [string]$PythonExe,
    [string]$DrawRunTime = "20:00",
    [string]$RetryTime = "08:30",
    [switch]$Replace,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $PythonExe) {
    $found = Get-Command python -ErrorAction Stop
    $PythonExe = $found.Source
}
$PythonExe = (Resolve-Path $PythonExe).Path

if ($PythonExe -match '\\WindowsApps\\') {
    throw "Refusing to register with a WindowsApps python alias ($PythonExe). Install a real " +
          "Python interpreter and pass -PythonExe <path to python.exe>."
}

Push-Location $repoRoot
try {
    & $PythonExe -c "import pandas, bs4, src.cli"
    if ($LASTEXITCODE -ne 0) {
        throw "Import check failed: '& `"$PythonExe`" -c ""import pandas, bs4, src.cli""' did not exit 0. " +
              "Install project dependencies for this interpreter first."
    }
}
finally {
    Pop-Location
}

$localOffset = (Get-TimeZone).BaseUtcOffset
$expectedOffset = New-TimeSpan -Hours 7
if ($localOffset -ne $expectedOffset -and -not $Force) {
    throw "This machine's local UTC offset is $localOffset, not +07:00 (Asia/Ho_Chi_Minh). The " +
          "schedule times ($DrawRunTime / $RetryTime) are assumed local. Pass -Force to register " +
          "anyway (you are asserting the times are correct for this machine)."
}

$taskFolder = "\Power655\"
$taskName = "Refresh"
$fullTaskName = "$taskFolder$taskName"

$existing = Get-ScheduledTask -TaskName $taskName -TaskPath $taskFolder -ErrorAction SilentlyContinue
if ($existing -and -not $Replace) {
    throw "Task $fullTaskName already exists. Pass -Replace to overwrite it."
}

$scriptPath = Join-Path $repoRoot "scripts\run_refresh.ps1"
$argumentList = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`" -PythonExe `"$PythonExe`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argumentList -WorkingDirectory $repoRoot

$drawTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday, Thursday, Saturday -At $DrawRunTime
$retryTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday, Friday, Sunday -At $RetryTime

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask `
    -TaskName $taskName `
    -TaskPath $taskFolder `
    -Action $action `
    -Trigger @($drawTrigger, $retryTrigger) `
    -Settings $settings `
    -Principal $principal `
    -Force:$Replace | Out-Null

Write-Output "Registered $fullTaskName (draw run $DrawRunTime Tue/Thu/Sat; retry $RetryTime Wed/Fri/Sun; python=$PythonExe)."
