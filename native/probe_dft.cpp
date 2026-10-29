// Route B probe, step 2: load a SAT file standalone, run Defeature recognition
// (recognition only, no removal) and dump the feature inventory.
//
//   probe_sat.exe <file.sat> [holes|all]
//
// Prints one line per feature:  F <i> type=<raw enum> faces=<n> bbox=...
// and a summary at the end. Everything goes to stdout so the caller can parse.

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

typedef void(__cdecl *pfn_ctor)(void *);
typedef int(__cdecl *pfn_elist_count)(const void *);
typedef ENTITY *(__cdecl *pfn_elist_first)(const void *);
typedef ENTITY *(__cdecl *pfn_elist_next)(const void *);
typedef int(__cdecl *pfn_is_body)(const ENTITY *);

typedef outcome_slot(__cdecl *pfn_restore)(const char *, void *);
typedef outcome_slot(__cdecl *pfn_get_faces)(ENTITY *, void *, int, AcisOptions *);
typedef outcome_slot(__cdecl *pfn_entity_box)(const void *, SPAposition *, SPAposition *, const void *);

typedef outcome_slot(__cdecl *pfn_dft_init)();
typedef outcome_slot(__cdecl *pfn_dft_run)(BODY *, void *, AcisOptions *);
typedef outcome_slot(__cdecl *pfn_dft_set_pause)(void *, int);
typedef outcome_slot(__cdecl *pfn_dft_set_flag)(void *, int);
typedef int(__cdecl *pfn_dft_num)(const void *);
typedef outcome_slot(__cdecl *pfn_dft_get_feature)(const void *, int, void *, int *);

static pfn_ok o_ok;
static pfn_errno o_errno;
static pfn_dtor o_dtor;

static void *Sym(HMODULE h, const char *name) {
    void *p = (void *)GetProcAddress(h, name);
    if (!p) printf("  [missing] %s\n", name);
    return p;
}
static int Ok(const outcome_slot *o) { return o_ok(o); }
static int Err(const outcome_slot *o) { return o_errno(o); }

// ENTITY_LIST / defeature_options are opaque; their own ctors initialise
// storage we allocate. Sizes are guessed generously.
struct Elist {
    alignas(16) unsigned char b[1024];
};

int main(int argc, char **argv) {
    if (argc < 2) {
        printf("usage: probe_sat.exe <file.sat> [holes|all]\n");
        return 2;
    }
    const char *sat = argv[1];
    const int holes_only = (argc > 2 && _stricmp(argv[2], "holes") == 0);

    SetDllDirectoryA(kAcisBin);
    char dll[MAX_PATH];
    _snprintf_s(dll, sizeof dll, _TRUNCATE, "%s\\SpaACIS.dll", kAcisBin);
    HMODULE h = LoadLibraryExA(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!h) { printf("load SpaACIS failed %lu\n", GetLastError()); return 3; }

    pfn_start start = (pfn_start)Sym(h, "?api_start_modeller@@YA?AVoutcome@@H@Z");
    pfn_stop stop = (pfn_stop)Sym(h, "?api_stop_modeller@@YA?AVoutcome@@XZ");
    o_ok = (pfn_ok)Sym(h, "?ok@outcome@@QEBAHXZ");
    o_errno = (pfn_errno)Sym(h, "?error_number@outcome@@QEBAHXZ");
    o_dtor = (pfn_dtor)Sym(h, "??1outcome@@QEAA@XZ");
    pfn_ctor el_ctor = (pfn_ctor)Sym(h, "??0ENTITY_LIST@@QEAA@XZ");
    pfn_ctor el_dtor = (pfn_ctor)Sym(h, "??1ENTITY_LIST@@QEAA@XZ");
    pfn_elist_count el_count = (pfn_elist_count)Sym(h, "?count@ENTITY_LIST@@QEBAHXZ");
    pfn_elist_first el_first = (pfn_elist_first)Sym(h, "?first@ENTITY_LIST@@QEBAPEAVENTITY@@XZ");
    pfn_elist_next el_next = (pfn_elist_next)Sym(h, "?next@ENTITY_LIST@@QEBAPEAVENTITY@@XZ");
    pfn_is_body is_body = (pfn_is_body)Sym(h, "?is_BODY@@YAHPEBVENTITY@@@Z");
    pfn_restore restore = (pfn_restore)Sym(h, "?restore@@YA?AVoutcome@@PEBDAEAVENTITY_LIST@@@Z");
    pfn_get_faces get_faces =
        (pfn_get_faces)Sym(h, "?api_get_faces@@YA?AVoutcome@@PEAVENTITY@@AEAVENTITY_LIST@@W4PAT_NEXT_TYPE@@PEAVAcisOptions@@@Z");
    pfn_entity_box get_box =
        (pfn_entity_box)Sym(h, "?get_entity_box@@YA?AVoutcome@@AEBVENTITY_LIST@@AEAVSPAposition@@1PEBVSPAboxing_options@@@Z");

    if (!start || !stop || !o_ok || !o_errno || !o_dtor || !el_ctor || !el_dtor ||
        !el_count || !el_first || !el_next || !is_body || !restore || !get_faces || !get_box) {
        printf("core symbols missing\n");
        return 4;
    }

    outcome_slot r = start(0);
    if (!Ok(&r)) { printf("start_modeller failed errno=%d\n", Err(&r)); return 5; }
    o_dtor(&r);
    printf("OK kernel started\n");
    fflush(stdout);

    Elist ents;
    memset(&ents, 0, sizeof ents);
    el_ctor(&ents);

    DWORD t0 = GetTickCount();
    outcome_slot rr = restore(sat, &ents);
    if (!Ok(&rr)) {
        printf("restore failed errno=%d\n", Err(&rr));
        typedef void(__cdecl *pfn_debug)(const outcome_slot *, FILE *);
        pfn_debug dbg = (pfn_debug)Sym(h, "?debug@outcome@@QEBAXPEAU_iobuf@@@Z");
        if (dbg) { printf("--- outcome debug ---\n"); dbg(&rr, stdout); printf("--- end ---\n"); }
        o_dtor(&rr);
        return 6;
    }
    o_dtor(&rr);
    printf("OK restored in %lu ms\n", GetTickCount() - t0);

    int n = el_count(&ents);
    int nbodies = 0;
    BODY *body = NULL;
    for (ENTITY *e = el_first(&ents); e; e = el_next(&ents)) {
        if (is_body(e)) { nbodies++; if (!body) body = (BODY *)e; }
    }
    printf("OK entities=%d bodies=%d\n", n, nbodies);
    if (!body) { printf("no body\n"); return 7; }
    fflush(stdout);

    Elist faces;
    memset(&faces, 0, sizeof faces);
    el_ctor(&faces);
    outcome_slot gf = get_faces((ENTITY *)body, &faces, 0, NULL);
    int nfaces = Ok(&gf) ? el_count(&faces) : -1;
    if (!Ok(&gf)) printf("get_faces errno=%d\n", Err(&gf));
    o_dtor(&gf);
    el_dtor(&faces);
    printf("OK body=%p faces=%d\n", (void *)body, nfaces);
    fflush(stdout);

    // ---------------- Defeature recognition -------------------------------
    char dfe[MAX_PATH];
    _snprintf_s(dfe, sizeof dfe, _TRUNCATE, "%s\\SPADefeature.dll", kAcisBin);
    HMODULE hd = LoadLibraryExA(dfe, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!hd) { printf("load SPADefeature failed %lu\n", GetLastError()); return 8; }

    pfn_dft_init dft_init = (pfn_dft_init)Sym(hd, "?api_initialize_defeature@@YA?AVoutcome@@XZ");
    pfn_dft_run dft_run = (pfn_dft_run)Sym(
        hd, "?api_find_and_remove_features@@YA?AVoutcome@@PEAVBODY@@PEAVdefeature_options@@PEAVAcisOptions@@@Z");
    pfn_dft_set_pause dft_pause =
        (pfn_dft_set_pause)Sym(hd, "?set_pause_after_recognize@defeature_options@@QEAA?AVoutcome@@H@Z");
    pfn_dft_set_flag dft_holes =
        (pfn_dft_set_flag)Sym(hd, "?set_recognize_holes@defeature_options@@QEAA?AVoutcome@@H@Z");
    pfn_dft_set_flag dft_chamf =
        (pfn_dft_set_flag)Sym(hd, "?set_recognize_chamfers@defeature_options@@QEAA?AVoutcome@@H@Z");
    pfn_dft_set_flag dft_blends =
        (pfn_dft_set_flag)Sym(hd, "?set_recognize_blends@defeature_options@@QEAA?AVoutcome@@H@Z");
    pfn_dft_num dft_num = (pfn_dft_num)Sym(hd, "?get_num_features@defeature_options@@QEBAHXZ");
    pfn_dft_get_feature dft_get = (pfn_dft_get_feature)Sym(
        hd, "?get_feature@defeature_options@@QEBA?AVoutcome@@HAEAVENTITY_LIST@@AEAW4defeature_feature_type@@@Z");
    if (!dft_run || !dft_pause || !dft_holes || !dft_num || !dft_get) {
        printf("defeature symbols missing\n");
        return 9;
    }

    if (dft_init) {
        outcome_slot oi = dft_init();
        printf("api_initialize_defeature ok=%d errno=%d\n", Ok(&oi), Ok(&oi) ? 0 : Err(&oi));
        o_dtor(&oi);
    }

    alignas(16) unsigned char opts[4096] = {0};
    ((pfn_ctor)Sym(hd, "??0defeature_options@@QEAA@XZ"))(opts);

    int e;
    outcome_slot so;
    so = dft_pause(opts, 1); e = Ok(&so) ? 0 : Err(&so); o_dtor(&so);
    printf("set_pause_after_recognize -> %d\n", e);
    so = dft_holes(opts, 1); e = Ok(&so) ? 0 : Err(&so); o_dtor(&so);
    printf("set_recognize_holes(1) -> %d\n", e);
    if (holes_only) {
        if (dft_chamf) { so = dft_chamf(opts, 0); o_dtor(&so); }
        if (dft_blends) { so = dft_blends(opts, 0); o_dtor(&so); }
        printf("mode: holes only\n");
    } else {
        printf("mode: all features\n");
    }
    fflush(stdout);

    t0 = GetTickCount();
    outcome_slot rd = dft_run(body, opts, NULL);
    int rok = Ok(&rd), rerr = rok ? 0 : Err(&rd);
    o_dtor(&rd);
    printf("api_find_and_remove_features -> ok=%d errno=%d in %lu ms\n", rok, rerr,
           GetTickCount() - t0);
    if (!rok) { printf("recognition failed\n"); return 10; }
    fflush(stdout);

    int nf = dft_num(opts);
    printf("features=%d\n", nf);

    int counts[64] = {0};
    for (int i = 0; i < nf; i++) {
        Elist ff;
        memset(&ff, 0, sizeof ff);
        el_ctor(&ff);
        int type = -1;
        outcome_slot og = dft_get(opts, i, &ff, &type);
        if (!Ok(&og)) {
            printf("F %d get_feature failed errno=%d\n", i, Err(&og));
            o_dtor(&og);
            el_dtor(&ff);
            continue;
        }
        o_dtor(&og);
        int fc = el_count(&ff);
        SPAposition lo, hi;
        const char *box = "n/a";
        char boxbuf[96];
        outcome_slot ob = get_box(&ff, &lo, &hi, NULL);
        if (Ok(&ob)) {
            _snprintf_s(boxbuf, sizeof boxbuf, _TRUNCATE, "(%.2f %.2f %.2f)-(%.2f %.2f %.2f)",
                        lo.x, lo.y, lo.z, hi.x, hi.y, hi.z);
            box = boxbuf;
        }
        o_dtor(&ob);
        printf("F %d type=%d faces=%d bbox=%s\n", i, type, fc, box);
        if (type >= 0 && type < 64) counts[type]++;
        el_dtor(&ff);
    }

    printf("SUMMARY faces_before=%d features=%d", nfaces, nf);
    for (int t = 0; t < 64; t++)
        if (counts[t]) printf(" type%d=%d", t, counts[t]);
    printf("\n");
    fflush(stdout);

    outcome_slot rs = stop();
    o_dtor(&rs);
    return 0;
}
