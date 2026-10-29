# Start CST's modeler kernel, inject the ACIS agent, and try to talk to it.
# Purpose: find out whether modeler_AMD64.exe can host ACIS outside a DE.
$ErrorActionPreference = 'Continue'
$exe = 'C:\Programs\CST Studio Suite 2022\AMD64\modeler_AMD64.exe'
$dll = 'C:\Projects\cst-mcp\native\cst_acis_agent.dll'
$inj = 'C:\Projects\cst-mcp\native\inject.ps1'

$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Milliseconds 1500
Write-Output "launched pid=$($p.Id) exited=$($p.HasExited)"

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $inj -Dll $dll -ProcessId $p.Id 2>&1 | Select-Object -Last 4

function Send-Line($pipeName, $line, $timeoutMs = 5000) {
    $pipe = New-Object System.IO.Pipes.NamedPipeClientStream('.', $pipeName, [System.IO.Pipes.PipeDirection]::InOut)
    try {
        $pipe.Connect($timeoutMs)
    } catch {
        return "CONNECT-FAIL: $($_.Exception.Message)"
    }
    $sw = New-Object System.IO.StreamWriter($pipe)
    $sw.AutoFlush = $true
    $sr = New-Object System.IO.StreamReader($pipe)
    $sw.WriteLine($line)
    if ($pipe.CanRead) { return $sr.ReadLine() } else { return 'NO-READ' }
}

Start-Sleep -Milliseconds 500
$pipeName = "cst-acis-$($p.Id)"
Write-Output ("ping -> " + (Send-Line $pipeName 'ping'))
Write-Output ("block -> " + (Send-Line $pipeName 'block 0 0 0 10 10 10'))
Write-Output ("faces -> " + (Send-Line $pipeName 'faces'))
$p.Refresh()
Write-Output "still alive: $(-not $p.HasExited)"
