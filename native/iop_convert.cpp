// iop_convert.exe -- drive Spatial InterOp's C API standalone (no CST process).
//
//   iop_convert <input.stp> <output.sat>
//
// Only the high-level SPAIInteropC entry points are used; every symbol is
// resolved at runtime so no Spatial headers are needed.
#include <windows.h>
#include <stdio.h>

typedef int  (__cdecl* pfn_init)(void);
typedef int  (__cdecl* pfn_shutdown)(void);
typedef void (__cdecl* pfn_conv_create)(void**);
typedef long (__cdecl* pfn_conv_convert)(void*, void*, void*);
typedef void (__cdecl* pfn_file_create_a)(void**, const char*);
typedef long (__cdecl* pfn_register)(const wchar_t*, const wchar_t*, int, const wchar_t*);

#define BIN L"C:\\Programs\\CST Studio Suite 2022\\ACIS_interop\\NT_VC16_64_DLL\\code\\bin"

static void Step(const char* what, long hr) {
    printf("  %-34s hr=0x%08lX\n", what, (unsigned long)hr);
}

int wmain(int argc, wchar_t** argv) {
    if (argc < 3) {
        printf("usage: iop_convert <in.stp> <out.sat>\n");
        return 2;
    }

    // Let the InterOp DLLs find their siblings and resources.
    if (!SetDllDirectoryW(BIN)) {
        printf("SetDllDirectory failed: %lu\n", GetLastError());
    }
    SetCurrentDirectoryW(BIN);

    WCHAR path[MAX_PATH];
    wcscpy_s(path, BIN);
    wcscat_s(path, L"\\SPAIInteropC.dll");
    HMODULE ipc = LoadLibraryW(path);
    if (!ipc) { printf("LoadLibrary(SPAIInteropC) failed: %lu\n", GetLastError()); return 1; }
    printf("SPAIInteropC at %p\n", (void*)ipc);

    auto init = (pfn_init)GetProcAddress(ipc, "?SPAICSystem_Initialize@@YAHXZ");
    auto shutdown = (pfn_shutdown)GetProcAddress(ipc, "?SPAICSystem_Shutdown@@YAHXZ");
    auto create = (pfn_conv_create)GetProcAddress(ipc, "?SPAICConverter_Create@@YAXPEAPEAX@Z");
    auto convert = (pfn_conv_convert)GetProcAddress(ipc, "?SPAICConverter_Convert@@YAJPEAX00@Z");
    auto mkFileA = (pfn_file_create_a)GetProcAddress(ipc, "?SPAICFile_Create@@YAXPEAPEAXPEBD@Z");
    auto reg = (pfn_register)GetProcAddress(ipc, "?SPAICConverter_RegisterComponent@@YAJPEB_W0H0@Z");

    printf("symbols: init=%p shutdown=%p create=%p convert=%p file=%p register=%p\n",
           (void*)init, (void*)shutdown, (void*)create, (void*)convert, (void*)mkFileA, (void*)reg);
    if (!init || !create || !convert || !mkFileA) return 1;

    int ok = init();
    printf("SPAICSystem_Initialize -> %d\n", ok);
    if (!ok) printf("  (returned 0 -- trying anyway, 0 may mean success)\n");

    if (reg) {
        const wchar_t* comps[] = { L"STEP", L"IGES", L"ACIS", L"Parasolid" };
        for (const wchar_t* c : comps) {
            long hr = reg(c, c, 1, nullptr);
            printf("  RegisterComponent(%-10ls) hr=0x%08lX\n", c, (unsigned long)hr);
        }
    }

    void* conv = nullptr;
    create(&conv);
    printf("converter = %p\n", conv);
    if (!conv) return 1;

    char inA[MAX_PATH], outA[MAX_PATH];
    WideCharToMultiByte(CP_ACP, 0, argv[1], -1, inA, MAX_PATH, nullptr, nullptr);
    WideCharToMultiByte(CP_ACP, 0, argv[2], -1, outA, MAX_PATH, nullptr, nullptr);

    void* inFile = nullptr;
    void* outFile = nullptr;
    mkFileA(&inFile, inA);
    mkFileA(&outFile, outA);
    printf("inFile=%p outFile=%p\n", inFile, outFile);

    long hr = convert(conv, inFile, outFile);
    Step("Convert", hr);

    WIN32_FILE_ATTRIBUTE_DATA fad;
    if (GetFileAttributesExW(argv[2], GetFileExInfoStandard, &fad))
        printf("output size: %llu bytes\n", ((unsigned long long)fad.nFileSizeHigh << 32) | fad.nFileSizeLow);
    else
        printf("no output file (err %lu)\n", GetLastError());

    if (shutdown) shutdown();
    return 0;
}
