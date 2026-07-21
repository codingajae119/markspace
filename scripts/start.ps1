<#
.SYNOPSIS
    Start backend (uvicorn) and frontend (vite) dev servers in the background.

.DESCRIPTION
    - backend : uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
    - frontend: npm run dev  (Vite, default :5173, proxies /api -> backend)
    Each process is launched hidden; its PID is written to scripts/.run/*.pid
    and stdout/stderr are redirected to scripts/.run/*.log.
    stop.ps1 reads those PID files and terminates the whole process tree.

    NOTE: ASCII-only on purpose. Windows PowerShell 5.1 reads BOM-less .ps1
    files with the system ANSI codepage, so non-ASCII text can break parsing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1
#>

$ErrorActionPreference = "Stop"

# --- Resolve repo layout from this script's location ---
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot    = Split-Path -Parent $ScriptDir
$BackendDir  = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$RunDir      = Join-Path $ScriptDir ".run"

if (-not (Test-Path $RunDir)) { New-Item -ItemType Directory -Path $RunDir | Out-Null }

$BackendPidFile  = Join-Path $RunDir "backend.pid"
$FrontendPidFile = Join-Path $RunDir "frontend.pid"

# --- Guard against a double start ---
function Test-Running([string]$PidFile) {
    if (-not (Test-Path $PidFile)) { return $false }
    $processId = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $processId) { return $false }
    return [bool](Get-Process -Id $processId -ErrorAction SilentlyContinue)
}

if ((Test-Running $BackendPidFile) -or (Test-Running $FrontendPidFile)) {
    Write-Host "[start] A server is already running. Run stop.ps1 first." -ForegroundColor Yellow
    exit 1
}

# --- Start backend ---
Write-Host "[start] backend (uvicorn :8000) ..." -ForegroundColor Cyan
$backend = Start-Process -FilePath "uv" `
    -ArgumentList @("run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
    -WorkingDirectory $BackendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $RunDir "backend.out.log") `
    -RedirectStandardError  (Join-Path $RunDir "backend.err.log") `
    -PassThru
$backend.Id | Out-File -FilePath $BackendPidFile -Encoding ascii
Write-Host ("        PID={0}  log=scripts\.run\backend.*.log" -f $backend.Id) -ForegroundColor DarkGray

# --- Start frontend (npm is npm.cmd on Windows) ---
Write-Host "[start] frontend (vite dev :5173) ..." -ForegroundColor Cyan
$frontend = Start-Process -FilePath "npm.cmd" `
    -ArgumentList @("run", "dev") `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $RunDir "frontend.out.log") `
    -RedirectStandardError  (Join-Path $RunDir "frontend.err.log") `
    -PassThru
$frontend.Id | Out-File -FilePath $FrontendPidFile -Encoding ascii
Write-Host ("        PID={0}  log=scripts\.run\frontend.*.log" -f $frontend.Id) -ForegroundColor DarkGray

Write-Host ""
Write-Host "[start] Done. Both servers are running in the background." -ForegroundColor Green
Write-Host "        backend : http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "        frontend: http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "        stop    : .\scripts\stop.ps1" -ForegroundColor Green
