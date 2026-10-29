<#
.SYNOPSIS
    Layer 1 smoke test: load SpaACIS.dll and resolve every symbol the probe uses.
    No ACIS call is made, so no licence is touched and no CST process is involved.
#>
[CmdletBinding()]
param(
    [string] $SpaAcis = 'C:\Programs\CST Studio Suite 2022\ACIS\NT_VC15_64_DLL\code\bin\SpaACIS.dll',
    [string] $Native
)

if (-not $Native) { $Native = Join-Path $PSScriptRoot '..\native' }

$ErrorActionPreference = 'Stop'

$source = @'
using System;
using System.Runtime.InteropServices;
public static class Sym {
    [DllImport("kernel32", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr LoadLibraryW(string path);
    [DllImport("kernel32", CharSet = CharSet.Ansi, SetLastError = true)]
    public static extern IntPtr GetProcAddress(IntPtr module, string name);
    [DllImport("kernel32", SetLastError = true)]
    public static extern bool FreeLibrary(IntPtr module);
}
'@
if (-not ('Sym' -as [type])) { Add-Type -TypeDefinition $source }

$consts = @{}
Get-ChildItem (Resolve-Path $Native) -Filter 'acis_*.h' | ForEach-Object {
    Select-String -Path $_.FullName -Pattern '^#define\s+(\w+)\s+"(\?.+?)"' -AllMatches |
        ForEach-Object { $_.Matches } |
        ForEach-Object { $consts[$_.Groups[1].Value] = $_.Groups[2].Value }
}

Write-Host ("SpaACIS : {0}" -f $SpaAcis)
if (-not (Test-Path $SpaAcis)) { throw "not found: $SpaAcis" }
Write-Host ("symbols : {0} from acis_*.h" -f $consts.Count)

$h = [Sym]::LoadLibraryW($SpaAcis)
if ($h -eq [IntPtr]::Zero) {
    throw ("LoadLibrary failed: {0}" -f [Runtime.InteropServices.Marshal]::GetLastWin32Error())
}

$miss = 0
try {
    foreach ($name in ($consts.Keys | Sort-Object)) {
        $p = [Sym]::GetProcAddress($h, $consts[$name])
        if ($p -eq [IntPtr]::Zero) {
            Write-Host ("  MISS  {0,-24} {1}" -f $name, $consts[$name]) -ForegroundColor Red
            $miss++
        }
        else {
            Write-Host ("  ok    {0,-24} 0x{1:X}" -f $name, $p.ToInt64())
        }
    }
}
finally {
    [void][Sym]::FreeLibrary($h)
}

if ($miss) { Write-Host ("FAILED: {0} symbol(s) missing" -f $miss); exit 1 }
Write-Host "PASS: every symbol resolves"
