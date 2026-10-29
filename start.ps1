<#
.SYNOPSIS
    Start the cst-mcp HTTP server (and optionally CST + the ACIS agent).

.DESCRIPTION
    One entry point so a fresh shell/session does not have to remember the
    individual steps. Writes .run\server.pid and .run\state.json.

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Port 8766
    .\start.ps1 -WithCst            # also open CST and inject the ACIS agent
    .\start.ps1 -WithCst -Build     # build the agent first if missing
#>
[CmdletBinding()]
param(
    [int] $Port = 8765,
    [switch] $WithCst,
    [switch] $Build,
    [string] $Token = $env:CST_MCP_TOKEN
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$run = Join-Path $root '.run'
New-Item -ItemType Directory -Force -Path $run | Out-Null

$python = 'C:\Programs\CST Studio Suite 2022\AMD64\python\python.exe'

function Wait-Health([int]$port, [int]$timeoutSec = 20) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { return $r.Content }
        } catch { }
        Start-Sleep -Milliseconds 400
    }
    return $null
}

# ---------------------------------------------------------------- server

$existing = $null
try { $existing = (Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2).Content } catch { }

if ($existing) {
    Write-Host "server already running on port $Port : $existing"
} else {
    if (-not (Test-Path (Join-Path $root 'node_modules'))) {
        Write-Host 'installing node dependencies...'
        Push-Location $root
        npm install --silent
        Pop-Location
    }

    $node = (Get-Command node -ErrorAction SilentlyContinue).Source
    if (-not $node) { throw 'node not found in PATH' }

    $env:CST_MCP_PORT = "$Port"
    if ($Token) { $env:CST_MCP_TOKEN = $Token }

    $out = Join-Path $run 'server.out.log'
    $err = Join-Path $run 'server.err.log'
    $nodePid = $null
    try {
        $p = Start-Process -FilePath $node -ArgumentList 'src/server.mjs' -WorkingDirectory $root `
                           -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
        $nodePid = $p.Id
    } catch {
        # Start-Process occasionally fails cloning the environment (duplicate
        # NO_PROXY/no_proxy keys); Win32_Process.Create is not affected.
        $cmd = "`"$node`" src/server.mjs 1>>`"$out`" 2>>`"$err`""
        $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
            CommandLine = $cmd; CurrentDirectory = $root
        }
        $nodePid = [int]$created.ProcessId
    }
    Set-Content (Join-Path $run 'server.pid') $nodePid -Encoding ASCII

    $health = Wait-Health $Port
    if (-not $health) {
        Write-Host '--- server.err.log ---' -ForegroundColor Red
        Get-Content $err -ErrorAction SilentlyContinue | Select-Object -Last 20
        throw "server did not come up on port $Port (pid $nodePid)"
    }
    Write-Host "server started: pid $nodePid"
}

# ---------------------------------------------------------------- CST + agent

$cstPid = $null
$modelerPid = $null
$agentDll = $null

if ($WithCst) {
    $cst = Get-Process -Name 'CST DESIGN*' -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cst) {
        Write-Host 'opening a CST project...'
        & $python (Join-Path $root 'scripts\start_cst_project.py') | ForEach-Object { Write-Host "  $_" }
        Start-Sleep -Seconds 4
        $cst = Get-Process -Name 'CST DESIGN*' -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($cst) { $cstPid = $cst.Id }

    $modeler = Get-Process -Name 'modeler_AMD64' -ErrorAction SilentlyContinue |
               Sort-Object StartTime -Descending | Select-Object -First 1
    if ($modeler) {
        $modelerPid = $modeler.Id

        $agentDll = Get-ChildItem (Join-Path $root 'native') -Filter 'cst_acis_agent*.dll' -ErrorAction SilentlyContinue |
                    Where-Object { $_.BaseName -match '^cst_acis_agent\d+$' } |
                    Sort-Object { [int]($_.BaseName -replace '\D', '') } |
                    Select-Object -Last 1

        if (-not $agentDll -and $Build) {
            Write-Host 'building the ACIS agent...'
            $vcvars = 'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat'
            if (-not (Test-Path $vcvars)) { throw 'MSVC not found; cannot build the agent' }
            Push-Location (Join-Path $root 'native')
            cmd /c "call `"$vcvars`" >nul && cl /nologo /LD /MD /O2 /EHsc /std:c++17 cst_acis_agent.cpp /Fe:cst_acis_agent13.dll /link /DLL /MACHINE:X64 user32.lib"
            Pop-Location
            $agentDll = Get-ChildItem (Join-Path $root 'native') -Filter 'cst_acis_agent13.dll' | Select-Object -First 1
        }

        if ($agentDll) {
            $loaded = ($modeler.Modules | Where-Object { $_.ModuleName -eq $agentDll.Name })
            if ($loaded) {
                Write-Host "agent already loaded in modeler $modelerPid"
            } else {
                powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'native\inject.ps1') `
                           -ProcessId $modelerPid -Dll $agentDll.FullName | Out-Null
                Write-Host "agent injected: $($agentDll.Name) -> modeler $modelerPid"
            }
        } else {
            Write-Host 'no built agent found; ACIS tools will be unavailable (run with -Build)' -ForegroundColor Yellow
        }
    } else {
        Write-Host 'CST is open but modeler_AMD64.exe is not running (open a 3D project)' -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------- summary

$state = [pscustomobject]@{
    port      = $Port
    url       = "http://127.0.0.1:$Port/mcp"
    startedAt = (Get-Date).ToString('o')
    cstPid    = $cstPid
    modelerPid= $modelerPid
    agent     = if ($agentDll) { $agentDll.Name } else { $null }
}
$state | ConvertTo-Json | Set-Content (Join-Path $run 'state.json') -Encoding UTF8

Write-Host ''
Write-Host "MCP endpoint : http://127.0.0.1:$Port/mcp"
if ($Token) { Write-Host "auth         : Authorization: Bearer <CST_MCP_TOKEN>" }
if ($cstPid) { Write-Host "CST          : pid $cstPid" }
if ($modelerPid) { Write-Host "modeler      : pid $modelerPid  agent=$($state.agent)" }
Write-Host ''
Write-Host 'client config:'
Write-Host ('  { "mcpServers": { "cst": { "type": "http", "url": "http://127.0.0.1:' + $Port + '/mcp" } } }')
