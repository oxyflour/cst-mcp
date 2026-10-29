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
    [switch] $WithCst
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

# safety net: whoever is listening on the port
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host "port $Port released (pid $($conn.OwningProcess))"
}

if ($WithCst) {
    $cst = Get-Process -Name 'CST DESIGN*' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cst) {
        $python = 'C:\Programs\CST Studio Suite 2022\AMD64\python\python.exe'
        & $python -c "import cst.interface as ci; de=ci.DesignEnvironment.connect($($cst.Id)); de.set_quiet_mode(True); de.close()" 2>$null
        Write-Host "CST closed (pid $($cst.Id))"
    }
}
