<#
.SYNOPSIS
    Displays EYEz 24/7 Scheduled Task state, active processes, live health, and recent logs.
#>

[CmdletBinding()]
param(
    [string]$TaskName = "EYEz Surveillance",
    [string]$Url = "http://127.0.0.1:8000",
    [string]$LogPath = "C:\SurveillanceData\logs\eyez.log"
)

Write-Host "=== EYEz 24/7 STATUS ===" -ForegroundColor Cyan

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    $Info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host ("Task        : {0} ({1})" -f $Task.TaskName, $Task.State)
    Write-Host ("Last Run    : {0} (Result: {1})" -f $Info.LastRunTime, $Info.LastTaskResult)
    Write-Host ("Next Check  : {0}" -f $Info.NextRunTime)
} else {
    Write-Host "Task        : NOT INSTALLED (run .\scripts\install_autostart.ps1)" -ForegroundColor Yellow
}

$Procs = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -match '^pythonw?\.exe$') -and ($_.CommandLine -like "*eyez_service.py*" -or $_.CommandLine -like "*surveillance_cam*app.py*")
}
Write-Host ("Processes   : {0} running" -f ($Procs | Measure-Object).Count)
foreach ($p in $Procs) {
    Write-Host ("  - PID {0} ({1})" -f $p.ProcessId, $p.Name)
}

try {
    $Status = Invoke-RestMethod "$Url/api/status" -TimeoutSec 3
    Write-Host ("Live API    : ONLINE ({0}/{1} cams online, {2} recording)" -f $Status.cameras_online, $Status.cameras_total, $Status.cameras_recording) -ForegroundColor Green
} catch {
    Write-Host "Live API    : UNREACHABLE ($Url)" -ForegroundColor Red
}

$Tailscale = (Get-Command tailscale -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
if (-not $Tailscale -and (Test-Path "C:\Program Files\Tailscale\tailscale.exe")) {
    $Tailscale = "C:\Program Files\Tailscale\tailscale.exe"
}
if ($Tailscale) {
    try {
        $TsJson = & $Tailscale status --json 2>$null | ConvertFrom-Json
        $DnsName = ($TsJson.Self.DNSName).TrimEnd(".")
        $TsOnline = $TsJson.Self.Online
        Write-Host ("Tailscale   : {0} (https://{1}:8443)" -f ($(if ($TsOnline) { "ONLINE" } else { "OFFLINE" }), $DnsName)) -ForegroundColor $(if ($TsOnline) { "Cyan" } else { "Yellow" })
    } catch {
        Write-Host "Tailscale   : UNAVAILABLE (Surfshark or VPN active?)" -ForegroundColor Yellow
    }
}

if (Test-Path $LogPath) {
    Write-Host "`n--- Recent Log ($LogPath) ---" -ForegroundColor DarkGray
    Get-Content $LogPath -Tail 12
}
