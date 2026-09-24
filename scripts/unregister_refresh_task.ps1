<#
.SYNOPSIS
    Removes the \Power655\Refresh Windows Task Scheduler task. Idempotent: prints "not
    registered" and exits 0 if the task does not exist.

.DESCRIPTION
    The human runs this script. Agents never execute it.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$taskFolder = "\Power655\"
$taskName = "Refresh"

$existing = Get-ScheduledTask -TaskName $taskName -TaskPath $taskFolder -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Output "not registered"
    exit 0
}

Unregister-ScheduledTask -TaskName $taskName -TaskPath $taskFolder -Confirm:$false
Write-Output "Unregistered \Power655\Refresh."
