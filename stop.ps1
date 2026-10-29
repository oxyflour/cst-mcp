<#
.SYNOPSIS
    Stop the cst-mcp server (and optionally CST).

.EXAMPLE
    .\stop.ps1
    .\stop.ps1 -WithCst
#>
[CmdletBinding()]
param(
    [int] $Port = 8765,
    [switch] $WithCst,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
$run = Join-Path $PSScriptRoot '.run'
$pidFile = Join-Path $run 'server.pid'

if (Test-Path $pidFile) {
    $serverPid = [int](Get-Content $pidFile -Raw).Trim()
    $proc = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
    if ($proc) { Stop-Process -Id $serverPid -Force; Write-Host "server stopped (pid $serverPid)" }
    else { Write-Host "server pid $serverPid is not running" }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
} else {
    Write-Host 'no pid file; nothing to stop'
}

# Safety net, but only for our own server: never kill an unrelated process that
# happens to hold the port.
$health = $null
try { $health = (Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2).Content | ConvertFrom-Json } catch { }
if ($health -and $health.app -eq 'cst-mcp') {
    Stop-Process -Id $health.pid -Force -ErrorAction SilentlyContinue
    Write-Host "port $Port released (pid $($health.pid))"
} elseif ($health -and -not $Force) {
    Write-Host "port $Port is held by '$($health.app)', refusing to kill it (use -Force)" -ForegroundColor Yellow
} elseif ($health) {
    Stop-Process -Id $health.pid -Force -ErrorAction SilentlyContinue
    Write-Host "force-released port $Port (pid $($health.pid))"
}
Remove-Item (Join-Path $run 'server.json') -ErrorAction SilentlyContinue

if ($WithCst) {
    $cst = Get-Process -Name 'CST DESIGN*' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cst) {
        $python = 'C:\Programs\CST Studio Suite 2022\AMD64\python\python.exe'
        & $python -c "import cst.interface as ci; de=ci.DesignEnvironment.connect($($cst.Id)); de.set_quiet_mode(True); de.close()" 2>$null
        Write-Host "CST closed (pid $($cst.Id))"
    }
}
