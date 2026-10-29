// Round-trip test: can the standalone kernel write and read its own SAT file?
// Distinguishes "our restore pipeline is wrong" from "this .sat dialect/version
// is not readable by the 2021.1 SpaACIS.dll that ships in the ACIS folder".

#include <windows.h>
#include <stdio.h>
#include <string.h>

#include "acis_shim.h"

static const char *kAcisBin =
    "C:\\Programs\\CST Studio Suite 2022\\ACIS\\NT_VC15_64_DLL\\code\\bin";

typedef outcome_slot(__cdecl *pfn_start)(int);
typedef outcome_slot(__cdecl *pfn_stop)();
typedef int(__cdecl *pfn_ok)(const outcome_slot *);
typedef int(__cdecl *pfn_errno)(const outcome_slot *);
typedef void(__cdecl *pfn_dtor)(outcome_slot *);
typedef void(__cdecl *pfn_ctor)(void *);
typedef int(__cdecl *pfn_elist_count)(const void *);
typedef outcome_slot(__cdecl *pfn_block)(const SPAposition *, const SPAposition *, BODY **, AcisOptions *);
typedef outcome_slot(__cdecl *pfn_save)(FILE *, int, const void *, AcisOptions *);
typedef outcome_slot(__cdecl *pfn_restore)(const char *, void *);

static pfn_ok o_ok;
static pfn_errno o_errno;
static pfn_dtor o_dtor;
static int Ok(const outcome_slot *o) { return o_ok(o); }
static int Err(const outcome_slot *o) { return o_errno(o); }

int main(int argc, char **argv) {
    const char *out = argc > 1 ? argv[1] : "rt_box.sat";
    SetDllDirectoryA(kAcisBin);
    char dll[MAX_PATH];
    _snprintf_s(dll, sizeof dll, _TRUNCATE, "%s\\SpaACIS.dll", kAcisBin);
    HMODULE h = LoadLibraryExA(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!h) { printf("load failed %lu\n", GetLastError()); return 3; }

    pfn_start start = (pfn_start)GetProcAddress(h, "?api_start_modeller@@YA?AVoutcome@@H@Z");
    pfn_stop stop = (pfn_stop)GetProcAddress(h, "?api_stop_modeller@@YA?AVoutcome@@XZ");
    o_ok = (pfn_ok)GetProcAddress(h, "?ok@outcome@@QEBAHXZ");
    o_errno = (pfn_errno)GetProcAddress(h, "?error_number@outcome@@QEBAHXZ");
    o_dtor = (pfn_dtor)GetProcAddress(h, "??1outcome@@QEAA@XZ");
    pfn_ctor el_ctor = (pfn_ctor)GetProcAddress(h, "??0ENTITY_LIST@@QEAA@XZ");
    pfn_elist_count el_count = (pfn_elist_count)GetProcAddress(h, "?count@ENTITY_LIST@@QEBAHXZ");
    pfn_block block = (pfn_block)GetProcAddress(
        h, "?api_solid_block@@YA?AVoutcome@@AEBVSPAposition@@0AEAPEAVBODY@@PEAVAcisOptions@@@Z");
    pfn_save save = (pfn_save)GetProcAddress(
        h, "?api_save_entity_list@@YA?AVoutcome@@PEAU_iobuf@@HAEBVENTITY_LIST@@PEAVAcisOptions@@@Z");
    pfn_restore restore = (pfn_restore)GetProcAddress(
        h, "?restore@@YA?AVoutcome@@PEBDAEAVENTITY_LIST@@@Z");

    outcome_slot r = start(0);
    printf("start ok=%d\n", Ok(&r));
    o_dtor(&r);

    SPAposition a(0, 0, 0), b(10, 20, 30);
    BODY *body = NULL;
    outcome_slot rb = block(&a, &b, &body, NULL);
    printf("solid_block ok=%d errno=%d body=%p\n", Ok(&rb), Ok(&rb) ? 0 : Err(&rb), (void *)body);
    o_dtor(&rb);

    alignas(16) unsigned char list[1024] = {0};
    el_ctor(list);
    typedef int(__cdecl *pfn_add)(void *, ENTITY *, int);
    pfn_add add = (pfn_add)GetProcAddress(h, "?add@ENTITY_LIST@@QEAAHPEAVENTITY@@H@Z");
    add(list, (ENTITY *)body, 0);
    printf("list count=%d\n", el_count(list));

    FILE *f = NULL;
    fopen_s(&f, out, "wb");
    outcome_slot rs = save(f, 0, list, NULL);
    printf("save ok=%d errno=%d\n", Ok(&rs), Ok(&rs) ? 0 : Err(&rs));
    o_dtor(&rs);
    fclose(f);

    alignas(16) unsigned char list2[1024] = {0};
    el_ctor(list2);
    outcome_slot rr = restore(out, list2);
    printf("restore ok=%d errno=%d entities=%d\n", Ok(&rr), Ok(&rr) ? 0 : Err(&rr),
           Ok(&rr) ? el_count(list2) : -1);
    o_dtor(&rr);

    outcome_slot rstop = stop();
    o_dtor(&rstop);
    return 0;
}
