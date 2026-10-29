#include <windows.h>
#include <stdio.h>
BOOL APIENTRY DllMain(HMODULE mod, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(mod);
        char p[MAX_PATH]; GetTempPathA(MAX_PATH, p);
        char f[MAX_PATH]; _snprintf_s(f, sizeof(f), _TRUNCATE, "%sminimal_probe.log", p);
        FILE* fp = fopen(f, "a");
        if (fp) { fprintf(fp, "attach pid=%lu base=%p\n", GetCurrentProcessId(), (void*)mod); fclose(fp); }
    }
    return TRUE;
}
