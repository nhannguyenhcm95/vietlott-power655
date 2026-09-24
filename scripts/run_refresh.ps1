<#
.SYNOPSIS
    Task Scheduler action for \Power655\Refresh. Runs `python -m src.cli refresh`, tees the
    console output to a per-run log, and normalises the exit code to one of {0,10,30,40,50}.

.PARAMETER PythonExe
    Absolute path to the python.exe that has this project's dependencies installed.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe
)

Set-Location "$PSScriptRoot\.."
$env:PYTHONIOENCODING = "utf-8"

$logDir = Join-Path (Get-Location) "data\logs\scheduler"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "refresh_$timestamp.log"

# PS 5.1: with $ErrorActionPreference = 'Stop', stderr merged via 2>&1 throws a terminating
# error even on a normal non-zero exit code from a native command. Use 'Continue' around it.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $PythonExe -m src.cli refresh 2>&1 | Tee-Object -FilePath $logFile
$code = $LASTEXITCODE
$ErrorActionPreference = $previousPreference

$validCodes = @(0, 10, 30, 40, 50)
$hasResult = Select-String -Path $logFile -Pattern 'REFRESH_RESULT ' -Quiet -SimpleMatch

if (-not ($validCodes -contains $code)) {
    $code = 50
}
elseif (-not $hasResult -and $code -ne 40) {
    # every non-locked run must end with a REFRESH_RESULT line; anything else is unexplained
    $code = 50
}

# Keep only the newest 60 scheduler logs.
$oldLogs = Get-ChildItem -Path $logDir -Filter 'refresh_*.log' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 60
foreach ($old in $oldLogs) {
    Remove-Item -Path $old.FullName -Force -ErrorAction SilentlyContinue
}

exit $code
