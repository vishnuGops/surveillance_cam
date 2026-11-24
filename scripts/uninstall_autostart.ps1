<#
.SYNOPSIS
    Removes the EYEz 24/7 Scheduled Task and stops any running EYEz processes cleanly.
#>

[CmdletBinding()]
param(
    [string]$TaskName = "EYEz Surveillance"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed Scheduled Task: $TaskName" -ForegroundColor Yellow
} else {
    Write-Host "Scheduled Task '$TaskName' is not installed."
}

# Stop running eyez_service.py / app.py processes from this project
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -match '^pythonw?\.exe$') -and (
        $_.CommandLine -like "*eyez_service.py*" -or
        ($_.CommandLine -like "*app.py*" -and $_.CommandLine -like "*$RepoRoot*")
    )
}

foreach ($proc in $Targets) {
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        Write-Host "Stopped PID $($proc.ProcessId) ($($proc.Name))"
    } catch {
        Write-Warning "Could not stop PID $($proc.ProcessId): $_"
    }
}

$ShortcutPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\EYEz Dashboard.url"
if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
}

Write-Host "EYEz auto-start removed and processes stopped." -ForegroundColor Green
