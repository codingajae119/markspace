<#
.SYNOPSIS
    Stop the backend and frontend servers started by start.ps1.

.DESCRIPTION
    Reads the PIDs from scripts/.run/*.pid and terminates each process TREE
    (taskkill /T) so children (uv -> python, npm -> node/vite) are killed too
    and no port stays bound. Safe to run when nothing is running (idempotent).

    NOTE: ASCII-only on purpose. Windows PowerShell 5.1 reads BOM-less .ps1
    files with the system ANSI codepage, so non-ASCII text can break parsing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
#>

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunDir    = Join-Path $ScriptDir ".run"

$targets = @(
    @{ Name = "backend";  PidFile = (Join-Path $RunDir "backend.pid") },
    @{ Name = "frontend"; PidFile = (Join-Path $RunDir "frontend.pid") }
)

# --- Kill a PID tree; children terminate with the parent ---
function Stop-Tree([string]$Name, [string]$PidFile) {
    if (-not (Test-Path $PidFile)) {
        Write-Host "[stop] $Name : no PID file (skip)" -ForegroundColor DarkGray
        return
    }

    $processId = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $processId) {
        Write-Host "[stop] $Name : empty PID (skip)" -ForegroundColor DarkGray
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return
    }

    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
        Write-Host "[stop] $Name : killing PID=$processId tree ..." -ForegroundColor Cyan
        # /T = include children, /F = force. Ignore exit code (child may be gone).
        & taskkill /PID $processId /T /F 2>&1 | Out-Null
    }
    else {
        Write-Host "[stop] $Name : PID=$processId already stopped" -ForegroundColor DarkGray
    }

    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

foreach ($t in $targets) {
    Stop-Tree $t.Name $t.PidFile
}

Write-Host ""
Write-Host "[stop] Done. backend and frontend servers are stopped." -ForegroundColor Green
