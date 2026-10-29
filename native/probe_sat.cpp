// Standalone ACIS probe: can we host CST's SpaACIS.dll in our own process?
//
// Route B of the feature-tree plan needs to load a SAT file, run Defeature
// recognition and dump the feature inventory without CST Studio being open.
// Step 1 is the licence gate: api_start_modeller() either succeeds or tells us
// we have to go back to in-process injection.
//
// Build (x64 native tools prompt):
//   cl /nologo /MD /O2 /EHsc /std:c++17 /W4 probe_sat.cpp /Fe:probe_sat.exe
//
// Usage:
//   probe_sat.exe <path-to.sat> [--out report.txt]

#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acis_shim.h"

static const char *kAcisBin =
    "C:\\Programs\\CST Studio Suite 2022\\ACIS\\NT_VC15_64_DLL\\code\\bin";

typedef outcome_slot(__cdecl *pfn_start)(int);
typedef outcome_slot(__cdecl *pfn_stop)();
typedef int(__cdecl *pfn_ok)(const outcome_slot *);
typedef int(__cdecl *pfn_errno)(const outcome_slot *);
typedef void(__cdecl *pfn_dtor)(outcome_slot *);

typedef void(__cdecl *pfn_elist_ctor)(void *);
typedef void(__cdecl *pfn_elist_dtor)(void *);
typedef int(__cdecl *pfn_elist_count)(const void *);
typedef ENTITY *(__cdecl *pfn_elist_first)(const void *);
typedef ENTITY *(__cdecl *pfn_elist_next)(const void *);
typedef int(__cdecl *pfn_is_body)(const ENTITY *);

typedef outcome_slot(__cdecl *pfn_restore)(FILE *, int, void *, AcisOptions *);

static HMODULE g_h;
static pfn_ok o_ok;
static pfn_errno o_errno;
static pfn_dtor o_dtor;

static void *Sym(HMODULE h, const char *name) {
    void *p = (void *)GetProcAddress(h, name);
    if (!p) printf("  [missing] %s\n", name);
    return p;
}

static int OutcomeOk(const outcome_slot *o) { return o_ok(o); }
static int OutcomeErr(const outcome_slot *o) { return o_errno(o); }

int main(int argc, char **argv) {
    if (argc < 2) {
        printf("usage: probe_sat.exe <file.sat>\n");
        return 2;
    }
    const char *sat = argv[1];

    char dll[MAX_PATH];
    _snprintf_s(dll, sizeof dll, _TRUNCATE, "%s\\SpaACIS.dll", kAcisBin);
    SetDllDirectoryA(kAcisBin);

    g_h = LoadLibraryExA(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!g_h) {
        printf("LoadLibrary(%s) failed: %lu\n", dll, GetLastError());
        return 3;
    }
    printf("loaded %s\n", dll);

    pfn_start start = (pfn_start)Sym(g_h, "?api_start_modeller@@YA?AVoutcome@@H@Z");
    pfn_stop stop = (pfn_stop)Sym(g_h, "?api_stop_modeller@@YA?AVoutcome@@XZ");
    o_ok = (pfn_ok)Sym(g_h, "?ok@outcome@@QEBAHXZ");
    o_errno = (pfn_errno)Sym(g_h, "?error_number@outcome@@QEBAHXZ");
    o_dtor = (pfn_dtor)Sym(g_h, "??1outcome@@QEAA@XZ");
    if (!start || !stop || !o_ok || !o_errno || !o_dtor) {
        printf("core symbols missing\n");
        return 4;
    }

    printf("calling api_start_modeller(0) ...\n");
    fflush(stdout);
    outcome_slot r = start(0);
    int ok = OutcomeOk(&r);
    int err = OutcomeErr(&r);
    printf("api_start_modeller -> ok=%d errno=%d\n", ok, err);
    o_dtor(&r);
    if (!ok) {
        printf("LICENCE GATE: kernel refused to start standalone (errno=%d)\n", err);
        return 5;
    }

    // ---- restore the SAT file into an ENTITY_LIST -------------------------
    pfn_elist_ctor el_ctor = (pfn_elist_ctor)Sym(g_h, "??0ENTITY_LIST@@QEAA@XZ");
    pfn_elist_dtor el_dtor = (pfn_elist_dtor)Sym(g_h, "??1ENTITY_LIST@@QEAA@XZ");
    pfn_elist_count el_count = (pfn_elist_count)Sym(g_h, "?count@ENTITY_LIST@@QEBAHXZ");
    pfn_elist_first el_first = (pfn_elist_first)Sym(g_h, "?first@ENTITY_LIST@@QEBAPEAVENTITY@@XZ");
    pfn_elist_next el_next = (pfn_elist_next)Sym(g_h, "?next@ENTITY_LIST@@QEBAPEAVENTITY@@XZ");
    pfn_is_body is_body = (pfn_is_body)Sym(g_h, "?is_BODY@@YAHPEBVENTITY@@@Z");
    pfn_restore restore = (pfn_restore)Sym(
        g_h,
        "?api_restore_entity_list@@YA?AVoutcome@@PEAU_iobuf@@HAEAVENTITY_LIST@@PEAVAcisOptions@@@Z");

    if (!el_ctor || !el_dtor || !el_count || !el_first || !el_next || !is_body || !restore) {
        printf("restore symbols missing\n");
        stop();
        return 6;
    }

    // ENTITY_LIST is opaque to us; 1 KiB of zeroed, 16-byte aligned storage is
    // far more than the real object needs and lets its own ctor initialise it.
    alignas(16) unsigned char el_storage[1024] = {0};
    el_ctor(el_storage);

    FILE *f = NULL;
    if (fopen_s(&f, sat, "rb") != 0 || !f) {
        printf("cannot open %s\n", sat);
        stop();
        return 7;
    }

    printf("restoring ...\n");
    fflush(stdout);
    outcome_slot rr = restore(f, 0, el_storage, NULL);
    int rok = OutcomeOk(&rr);
    printf("api_restore_entity_list -> ok=%d errno=%d\n", rok, OutcomeErr(&rr));
    o_dtor(&rr);
    fclose(f);
    if (!rok) {
        el_dtor(el_storage);
        stop();
        return 8;
    }

    int n = el_count(el_storage);
    int nbodies = 0, nfaces_hint = 0;
    printf("entities in file: %d\n", n);
    for (ENTITY *e = el_first(el_storage); e; e = el_next(el_storage)) {
        if (is_body(e)) nbodies++;
    }
    printf("bodies: %d\n", nbodies);

    el_dtor(el_storage);

    outcome_slot rs = stop();
    printf("api_stop_modeller -> ok=%d\n", OutcomeOk(&rs));
    o_dtor(&rs);
    return 0;
}
