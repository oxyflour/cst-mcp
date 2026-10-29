# Start CST's modeler kernel with the ACIS directory on PATH (so it can find
# SpaACIS.dll), inject the existing agent and see whether ACIS actually works
# outside a Design Environment. Cleans up after itself.
$ErrorActionPreference = 'Continue'

$cst       = 'C:\Programs\CST Studio Suite 2022'
$acisBin   = "$cst\ACIS\NT_VC15_64_DLL\code\bin"
$exe       = "$cst\AMD64\modeler_AMD64.exe"
$dll       = 'C:\Projects\cst-mcp\native\cst_acis_agent.dll'
$inj       = 'C:\Projects\cst-mcp\native\inject.ps1'

$env:PATH = "$acisBin;$cst\AMD64;$env:PATH"
Write-Output "PATH head: $($env:PATH.Substring(0,120))"

$p = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden
Start-Sleep -Milliseconds 2500
$p.Refresh()
Write-Output "launched pid=$($p.Id) alive=$(-not $p.HasExited) title='$($p.MainWindowTitle)'"
if ($p.HasExited) { Write-Output "exited with $($p.ExitCode)"; exit 1 }

# Can we even open it for writing?
Add-Type -Namespace W -Name N -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32", SetLastError=true)]
public static extern System.IntPtr OpenProcess(uint access, bool inherit, int pid);
[System.Runtime.InteropServices.DllImport("kernel32")]
public static extern bool CloseHandle(System.IntPtr h);
'@
$h = [W.N]::OpenProcess(0x1F0FFF, $false, $p.Id)
Write-Output ("OpenProcess(ALL_ACCESS) -> {0} err={1}" -f $h, [Runtime.InteropServices.Marshal]::GetLastWin32Error())
if ($h -ne [IntPtr]::Zero) { [W.N]::CloseHandle($h) | Out-Null }

Write-Output '--- inject ---'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $inj -Dll $dll -ProcessId $p.Id 2>&1 | Select-Object -Last 5

function Send-Line($pipeName, $line, $timeoutMs = 4000) {
    $pipe = New-Object System.IO.Pipes.NamedPipeClientStream('.', $pipeName, [System.IO.Pipes.PipeDirection]::InOut)
    try { $pipe.Connect($timeoutMs) } catch { return "CONNECT-FAIL" }
    $sw = New-Object System.IO.StreamWriter($pipe); $sw.AutoFlush = $true
    $sr = New-Object System.IO.StreamReader($pipe)
    $sw.WriteLine($line)
    return $sr.ReadLine()
}

Start-Sleep -Milliseconds 600
$pipeName = "cst-acis-$($p.Id)"
Write-Output ("ping  -> " + (Send-Line $pipeName 'ping'))
Write-Output ("block -> " + (Send-Line $pipeName 'block 0 0 0 10 10 10'))
Write-Output ("faces -> " + (Send-Line $pipeName 'faces'))

$p.Refresh()
Write-Output "alive=$(-not $p.HasExited)"
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
Write-Output 'cleaned up'
