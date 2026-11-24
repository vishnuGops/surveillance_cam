<#
.SYNOPSIS
    Configures persistent, tailnet-only HTTPS access for EYEz via `tailscale serve`.
.DESCRIPTION
    Publishes EYEz (http://127.0.0.1:8000) privately inside your Tailscale tailnet
    on dedicated HTTPS port 8443 so it never conflicts with port 443 services or
    Tailscale Funnel. Persists across reboots and recovers automatically whenever
    Tailscale reconnects (e.g., after Surfshark disconnects).
#>

[CmdletBinding()]
param(
    [int]$HttpsPort = 8443,
    [string]$LocalTarget = "http://127.0.0.1:8000",
    [switch]$Disable
)

$ErrorActionPreference = "Stop"

$Tailscale = (Get-Command tailscale -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
if (-not $Tailscale -and (Test-Path "C:\Program Files\Tailscale\tailscale.exe")) {
    $Tailscale = "C:\Program Files\Tailscale\tailscale.exe"
}
if (-not $Tailscale) {
    throw "Tailscale CLI not found. Install Tailscale from https://tailscale.com/download"
}

if ($Disable) {
    & $Tailscale serve --https=$HttpsPort off
    Write-Host "Disabled Tailscale Serve on HTTPS port $HttpsPort." -ForegroundColor Yellow
    exit 0
}

& $Tailscale serve --bg --https=$HttpsPort $LocalTarget

$StatusJson = & $Tailscale status --json | ConvertFrom-Json
$DnsName = ($StatusJson.Self.DNSName).TrimEnd(".")
$Url = if ($HttpsPort -eq 443) { "https://$DnsName" } else { "https://${DnsName}:${HttpsPort}" }

Write-Host "`nEYEz is live on your private Tailscale tailnet:" -ForegroundColor Green
Write-Host "  URL : $Url" -ForegroundColor Cyan
Write-Host "  Mode: Tailnet-only HTTPS (Funnel disabled)"
