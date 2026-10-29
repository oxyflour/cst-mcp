@echo off
REM Build the probe DLL. Needs an x64 MSVC toolchain:
REM   "x64 Native Tools Command Prompt for VS 2022"
REM No ACIS headers or import libraries are used - every ACIS entry point is
REM resolved at runtime with GetProcAddress(mangled_name).
setlocal
if not defined VSCMD_ARG_TGT_ARCH (
  echo [!] Run this from "x64 Native Tools Command Prompt for VS 2022".
  exit /b 1
)
REM /MD is mandatory: with the static CRT (/MT default) every FILE* handed to
REM ACIS comes from a private CRT and SpaACIS fail-fasts inside ucrtbase.
cl /nologo /LD /MD /O2 /EHsc /std:c++17 /W4 ^
   cst_acis_probe.cpp ^
   /Fe:cst_acis_probe.dll ^
   /link /DLL /MACHINE:X64 user32.lib
if errorlevel 1 exit /b 1
echo.
echo built: %CD%\cst_acis_probe.dll

