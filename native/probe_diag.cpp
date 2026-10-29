// Diagnostic: is the standalone kernel merely "not licensed for modelling"?
// Tries a query API, an empty-list save, and a block, for start_modeller(0/1/2).

#include <windows.h>
#include <stdio.h>

#include "acis_shim.h"

static const char *kAcisBin =
    "C:\\Programs\\CST Studio Suite 2022\\ACIS\\NT_VC15_64_DLL\\code\\bin";

typedef outcome_slot(__cdecl *pfn_start)(int);
typedef outcome_slot(__cdecl *pfn_stop)();
typedef int(__cdecl *pfn_ok)(const outcome_slot *);
typedef int(__cdecl *pfn_errno)(const outcome_slot *);
typedef void(__cdecl *pfn_dtor)(outcome_slot *);
typedef void(__cdecl *pfn_ctor)(void *);
typedef outcome_slot(__cdecl *pfn_block)(const SPAposition *, const SPAposition *, BODY **, AcisOptions *);
typedef outcome_slot(__cdecl *pfn_save)(FILE *, int, const void *, AcisOptions *);
struct HISTORY_STREAM;
typedef outcome_slot(__cdecl *pfn_hist)(HISTORY_STREAM **);
typedef outcome_slot(__cdecl *pfn_names)(const void *, void *);

static pfn_ok o_ok;
static pfn_errno o_errno;
static pfn_dtor o_dtor;
static int Ok(const outcome_slot *o) { return o_ok(o); }
static int Err(const outcome_slot *o) { return o_errno(o); }

int main(int argc, char **argv) {
    int arg = argc > 1 ? atoi(argv[1]) : 0;
    SetDllDirectoryA(kAcisBin);
    char dll[MAX_PATH];
    _snprintf_s(dll, sizeof dll, _TRUNCATE, "%s\\SpaACIS.dll", kAcisBin);
    HMODULE h = LoadLibraryExA(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    o_ok = (pfn_ok)GetProcAddress(h, "?ok@outcome@@QEBAHXZ");
    o_errno = (pfn_errno)GetProcAddress(h, "?error_number@outcome@@QEBAHXZ");
    o_dtor = (pfn_dtor)GetProcAddress(h, "??1outcome@@QEAA@XZ");
    pfn_start start = (pfn_start)GetProcAddress(h, "?api_start_modeller@@YA?AVoutcome@@H@Z");
    pfn_stop stop = (pfn_stop)GetProcAddress(h, "?api_stop_modeller@@YA?AVoutcome@@XZ");
    pfn_ctor el_ctor = (pfn_ctor)GetProcAddress(h, "??0ENTITY_LIST@@QEAA@XZ");
    pfn_block block = (pfn_block)GetProcAddress(
        h, "?api_solid_block@@YA?AVoutcome@@AEBVSPAposition@@0AEAPEAVBODY@@PEAVAcisOptions@@@Z");
    pfn_save save = (pfn_save)GetProcAddress(
        h, "?api_save_entity_list@@YA?AVoutcome@@PEAU_iobuf@@HAEBVENTITY_LIST@@PEAVAcisOptions@@@Z");
    pfn_hist hist =
        (pfn_hist)GetProcAddress(h, "?api_get_default_history@@YA?AVoutcome@@AEAPEAVHISTORY_STREAM@@@Z");

    printf("=== start_modeller(%d) ===\n", arg);
    outcome_slot r = start(arg);
    printf("start ok=%d errno=%d\n", Ok(&r), Ok(&r) ? 0 : Err(&r));
    o_dtor(&r);

    // ACIS components must be initialised explicitly; uninitialised modules
    // answer every call with the same error number.
    const char *inits[] = {
        "?api_initialize_kernel@@YA?AVoutcome@@XZ",
        "?api_initialize_constructors@@YA?AVoutcome@@XZ",
        "?api_initialize_booleans@@YA?AVoutcome@@XZ",
        "?api_initialize_query@@YA?AVoutcome@@XZ",
        "?api_initialize_generic_attributes@@YA?AVoutcome@@XZ",
        "?api_initialize_persistent_id@@YA?AVoutcome@@XZ",
        "?api_initialize_blending@@YA?AVoutcome@@XZ",
        "?api_initialize_healing@@YA?AVoutcome@@XZ",
        "?api_initialize_local_ops@@YA?AVoutcome@@XZ",
    };
    for (int i = 0; i < (int)(sizeof inits / sizeof inits[0]); i++) {
        typedef outcome_slot(__cdecl * pfn_init)();
        pfn_init fn = (pfn_init)GetProcAddress(h, inits[i]);
        if (!fn) { printf("  init missing: %s\n", inits[i]); continue; }
        outcome_slot ri = fn();
        printf("  init %-24s ok=%d errno=%d\n", inits[i] + 2, Ok(&ri), Ok(&ri) ? 0 : Err(&ri));
        o_dtor(&ri);
    }

    HISTORY_STREAM *hs = NULL;
    outcome_slot rh = hist(&hs);
    printf("get_default_history ok=%d errno=%d hs=%p\n", Ok(&rh), Ok(&rh) ? 0 : Err(&rh), (void *)hs);
    o_dtor(&rh);

    alignas(16) unsigned char list[1024] = {0};
    el_ctor(list);
    FILE *f = NULL;
    fopen_s(&f, "empty_save.sat", "wb");
    outcome_slot rsa = save(f, 0, list, NULL);
    printf("save(empty) ok=%d errno=%d\n", Ok(&rsa), Ok(&rsa) ? 0 : Err(&rsa));
    o_dtor(&rsa);
    fclose(f);

    SPAposition a(0, 0, 0), b(10, 20, 30);
    BODY *body = NULL;
    outcome_slot rb = block(&a, &b, &body, NULL);
    printf("solid_block ok=%d errno=%d body=%p\n", Ok(&rb), Ok(&rb) ? 0 : Err(&rb), (void *)body);
    o_dtor(&rb);

    outcome_slot rst = stop();
    o_dtor(&rst);
    return 0;
}
