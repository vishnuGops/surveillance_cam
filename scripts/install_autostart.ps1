<#
.SYNOPSIS
    Installs EYEz 24/7 auto-start and crash/close auto-revive via Windows Task Scheduler.
.DESCRIPTION
    Registers an interactive-session Scheduled Task ("EYEz Surveillance") that:
    - Auto-launches EYEz silently into the Windows System Tray on PC boot/logon.
    - Runs a lightweight 1-minute watchdog trigger: if EYEz is already running, the
      single-instance Mutex exits in <10ms; if EYEz was closed or killed, it revives
      automatically within 60 seconds and resumes surveillance & loop recording.
    - Runs in your interactive user session so Windows Camera Privacy and DirectShow
      USB webcams work reliably (avoiding Windows Session 0 camera blocks).
#>

[CmdletBinding()]
param(
    [string]$TaskName = "EYEz Surveillance",
    [string]$DataDir = "C:\SurveillanceData",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonW = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
$ServiceScript = Join-Path $RepoRoot "eyez_service.py"

if (-not (Test-Path $PythonW)) {
    throw "Virtual environment pythonw.exe not found at: $PythonW"
}
if (-not (Test-Path $ServiceScript)) {
    throw "eyez_service.py not found at: $ServiceScript"
}

New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "logs") | Out-Null

$CurrentUser = "$env:USERDOMAIN\$env:USERNAME"
$Arguments = "`"$ServiceScript`" --host $BindHost --port $Port --data-dir `"$DataDir`""

$Action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument $Arguments `
    -WorkingDirectory $RepoRoot

$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$TriggerWatchdog = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances Parallel `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited

# Replace existing task if present
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger @($TriggerLogon, $TriggerWatchdog) `
    -Settings $Settings `
    -Principal $Principal `
    -Description "EYEz 24/7 Home Surveillance System Tray & Watchdog (auto-starts on logon and revives if closed)." | Out-Null

# Create Start Menu web dashboard shortcut
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$ShortcutPath = Join-Path $StartMenuDir "EYEz Dashboard.url"
@(
    "[InternetShortcut]"
    "URL=http://${BindHost}:${Port}"
) | Set-Content -Path $ShortcutPath -Encoding ASCII

Write-Host "Registered Scheduled Task: $TaskName" -ForegroundColor Green
Write-Host "  User      : $CurrentUser (Interactive session - full USB webcam access)"
Write-Host "  Triggers  : At Logon + 1-minute auto-revive watchdog"
Write-Host "  Dashboard : http://${BindHost}:${Port}"
Write-Host "  Logs      : $(Join-Path $DataDir 'logs\eyez.log')"

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started '$TaskName' in the Windows System Tray." -ForegroundColor Cyan
}
