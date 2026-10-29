<#
.SYNOPSIS
    Inject a DLL into a running process (x64, same-user, no service).

.EXAMPLE
    .\inject.ps1 -Dll .\cst_acis_probe.dll
    .\inject.ps1 -Dll .\cst_acis_probe.dll -ProcessId 1234
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $Dll,
    [int] $ProcessId = 0,
    [string] $ProcessName = 'modeler_AMD64'
)

$ErrorActionPreference = 'Stop'

$source = @'
using System;
using System.Runtime.InteropServices;

public static class Injector
{
    [DllImport("kernel32", SetLastError = true)]
    public static extern IntPtr OpenProcess(uint access, bool inherit, int pid);

    [DllImport("kernel32", SetLastError = true)]
    public static extern IntPtr VirtualAllocEx(IntPtr proc, IntPtr addr, UIntPtr size, uint type, uint protect);

    [DllImport("kernel32", SetLastError = true)]
    public static extern bool VirtualFreeEx(IntPtr proc, IntPtr addr, UIntPtr size, uint type);

    [DllImport("kernel32", SetLastError = true)]
    public static extern bool WriteProcessMemory(IntPtr proc, IntPtr addr, byte[] buf, UIntPtr size, out UIntPtr written);

    [DllImport("kernel32", SetLastError = true)]
    public static extern IntPtr CreateRemoteThread(IntPtr proc, IntPtr attrs, UIntPtr stack, IntPtr start, IntPtr arg, uint flags, out uint tid);

    [DllImport("kernel32", SetLastError = true)]
    public static extern uint WaitForSingleObject(IntPtr handle, uint ms);

    [DllImport("kernel32", SetLastError = true)]
    public static extern bool GetExitCodeThread(IntPtr thread, out uint code);

    [DllImport("kernel32", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32", SetLastError = true)]
    public static extern IntPtr GetModuleHandle(string name);

    [DllImport("kernel32", SetLastError = true, CharSet = CharSet.Ansi)]
    public static extern IntPtr GetProcAddress(IntPtr module, string name);
}
'@

if (-not ('Injector' -as [type])) { Add-Type -TypeDefinition $source }

if (-not $ProcessId) {
    $proc = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
            Sort-Object StartTime -Descending | Select-Object -First 1
    if (-not $proc) { throw "process '$ProcessName' is not running (open a 3D project in CST first)" }
    $ProcessId = $proc.Id
}

$dllPath = (Resolve-Path $Dll).Path
if (-not (Test-Path $dllPath)) { throw "DLL not found: $Dll" }

$target = Get-Process -Id $ProcessId
Write-Host ("target: {0} (pid {1})" -f $target.ProcessName, $ProcessId)
Write-Host ("payload: {0} ({1:N0} bytes)" -f $dllPath, (Get-Item $dllPath).Length)

$PROCESS_ALL_ACCESS = 0x1F0FFF
$MEM_COMMIT_RESERVE = 0x3000
$PAGE_READWRITE = 0x04
$MEM_RELEASE = 0x8000

$hProc = [Injector]::OpenProcess($PROCESS_ALL_ACCESS, $false, $ProcessId)
if ($hProc -eq [IntPtr]::Zero) {
    throw ("OpenProcess failed: {0} (run elevated, or inject into a process you own)" -f [Runtime.InteropServices.Marshal]::GetLastWin32Error())
}

try {
    $bytes = [Text.Encoding]::Unicode.GetBytes($dllPath + [char]0)
    $size = [UIntPtr]::new([uint64]$bytes.Length)

    $remote = [Injector]::VirtualAllocEx($hProc, [IntPtr]::Zero, $size, $MEM_COMMIT_RESERVE, $PAGE_READWRITE)
    if ($remote -eq [IntPtr]::Zero) { throw "VirtualAllocEx failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }

    $written = [UIntPtr]::Zero
    if (-not [Injector]::WriteProcessMemory($hProc, $remote, $bytes, $size, [ref]$written)) {
        throw "WriteProcessMemory failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }

    $kernel32 = [Injector]::GetModuleHandle('kernel32.dll')
    $loadLibrary = [Injector]::GetProcAddress($kernel32, 'LoadLibraryW')

    $tid = 0
    $hThread = [Injector]::CreateRemoteThread($hProc, [IntPtr]::Zero, [UIntPtr]::Zero, $loadLibrary, $remote, 0, [ref]$tid)
    if ($hThread -eq [IntPtr]::Zero) { throw "CreateRemoteThread failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }

    [void][Injector]::WaitForSingleObject($hThread, 10000)
    $exit = 0
    [void][Injector]::GetExitCodeThread($hThread, [ref]$exit)
    [void][Injector]::CloseHandle($hThread)
    [void][Injector]::VirtualFreeEx($hProc, $remote, [UIntPtr]::Zero, $MEM_RELEASE)

    if ($exit -eq 0) { throw "LoadLibraryW returned NULL - the DLL did not load (check bitness and dependencies)" }
    Write-Host ("injected: module base 0x{0:X}" -f $exit)
    Write-Host ("log: {0}cst_acis_probe.{1}.log" -f $env:TEMP, $ProcessId)
}
finally {
    [void][Injector]::CloseHandle($hProc)
}
