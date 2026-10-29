// cst_acis_agent.dll -- resident in-process ACIS agent for modeler_AMD64.exe.
//
// Differences from cst_acis_probe.dll: it does not run once and exit. It opens
//   \\.\pipe\cst-acis-<pid>
// and serves line commands, each executed on the modeler's UI thread (the ACIS
// entity manager is thread-affine, so nothing may run anywhere else).
//
//   ping                     -> OK pong
//   block <lx> <ly> <lz>     -> OK body=<ptr> faces=<n>
//   faces                    -> OK faces=<n>
//   offset <faceIndex> <d>   -> OK body=<ptr> faces=<n>
//   save <path>              -> OK bytes=<n>
//   quit                     -> OK bye
//
// Commands are one line each; responses are one line each ("OK ..." / "ERR ...").
#include <windows.h>
#include <tlhelp32.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <share.h>
#include "acis_direct.h"

static HMODULE g_self;
static FILE* g_log;
static HANDLE g_done;
static HHOOK g_hook;
static volatile LONG g_ran;
static DWORD g_uiTid;
static DWORD g_pid;

static void Log(const char* fmt, ...) {
    if (!g_log) return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
}

// ---------------------------------------------------------------- job queue

static CRITICAL_SECTION g_lock;
static char g_request[1024];
static char g_response[4096];
static HANDLE g_jobDone;
static volatile LONG g_jobPending;

// ---------------------------------------------------------------- ACIS api

typedef void (__cdecl* pfn_list_ctor)(void*);
typedef void (__cdecl* pfn_list_dtor)(void*);
typedef void (__cdecl* pfn_list_ctor_one)(void*, ENTITY*);
typedef int  (__cdecl* pfn_list_count)(const void*);
typedef ENTITY* (__cdecl* pfn_list_at)(const void*, int);
typedef outcome_slot(__cdecl* pfn_restore_list)(void*, int, void*, AcisOptions*);
// api_tweak_faces(int, FACE**, SURFACE**, int*, SPAposition /*by value*/, void* /*back-ref, scalar*/, AcisOptions*)
typedef outcome_slot(__cdecl* pfn_api_tweak_faces)(int, FACE**, SURFACE**, int*, SPAposition, void*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_get_box)(const void*, SPAposition*, SPAposition*, void*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_tweak2)(int, FACE**, SURFACE**, int*, const SPAposition*, void*, void*, AcisOptions*);
typedef void (__cdecl* pfn_obj_ctor)(void*);
typedef outcome_slot(__cdecl* pfn_tweak_init)(int, FACE**, SURFACE**, int*, void*, const SPAposition*, void*, void*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_move_faces)(int, FACE**, const void*, const SPAposition*, const void*, void*, AcisOptions*);
typedef void (__cdecl* pfn_transf_ctor)(void*);
typedef outcome_slot(__cdecl* pfn_init)(void);
typedef void (__cdecl* pfn_vec3)(void*, double, double, double);
typedef void (__cdecl* pfn_mat3)(void*, const void*, const void*, const void*);
typedef void (__cdecl* pfn_transf6)(void*, const void*, const void*, double, int, int, int);

#define SYM_LIST_CTOR "??0ENTITY_LIST@@QEAA@XZ"
#define SYM_LIST_DTOR "??1ENTITY_LIST@@QEAA@XZ"
#define SYM_LIST_CTOR_ONE "??0ENTITY_LIST@@QEAA@PEAVENTITY@@@Z"
#define SYM_LIST_COUNT "?count@ENTITY_LIST@@QEBAHXZ"
#define SYM_LIST_AT "??AENTITY_LIST@@QEBAPEAVENTITY@@H@Z"
#define SYM_RESTORE_LIST "?api_restore_entity_list@@YA?AVoutcome@@PEAU_iobuf@@HAEAVENTITY_LIST@@PEAVAcisOptions@@@Z"
#define SYM_TWEAK_FACES2 "?api_tweak_faces@@YA?AVoutcome@@HQEAPEAVFACE@@QEAPEAVSURFACE@@QEAHAEBVSPAposition@@3PEAVlop_options@@PEAVAcisOptions@@@Z"
#define SYM_VEC3 "??0SPAvector@@QEAA@NNN@Z"
#define SYM_MAT3 "??0SPAmatrix@@QEAA@AEBVSPAvector@@00@Z"
#define SYM_TRANSF6 "??0SPAtransf@@QEAA@AEBVSPAmatrix@@AEBVSPAvector@@NHHH@Z"
#define SYM_INIT_LOCAL_OPS "?api_initialize_local_ops@@YA?AVoutcome@@XZ"
#define SYM_INIT_LOPT_OPS "?api_initialize_lopt_ops@@YA?AVoutcome@@XZ"
#define SYM_MOVE_FACES "?api_move_faces@@YA?AVoutcome@@HQEAPEAVFACE@@AEBVSPAtransf@@AEBVSPAposition@@2PEAVlop_options@@PEAVAcisOptions@@@Z"
#define SYM_TRANSF_CTOR "??0SPAtransf@@QEAA@XZ"
#define SYM_TWEAK_INIT "?api_tweak_faces_init@@YA?AVoutcome@@HQEAPEAVFACE@@QEAPEAVSURFACE@@QEAHAEAVENTITY_LIST@@AEBVSPAposition@@4PEAVlop_options@@PEAVAcisOptions@@@Z"
#define SYM_LOP_CTOR "??0lop_options@@QEAA@XZ"
#define SYM_LOP_DTOR "??1lop_options@@QEAA@XZ"
#define SYM_GET_BOX "?api_get_entity_box@@YA?AVoutcome@@AEBVENTITY_LIST@@AEAVSPAposition@@1PEAVSPAboxing_options@@PEAVAcisOptions@@@Z"
#define SYM_TWEAK_FACES "?api_tweak_faces@@YA?AVoutcome@@HQEAPEAVFACE@@QEAPEAVSURFACE@@QEAHVSPAposition@@3PEAVAcisOptions@@@Z"

struct Api {
    HMODULE h;
    pfn_outcome_ok ok;
    pfn_outcome_error_number errno_;
    pfn_outcome_dtor dtor;
    pfn_api_solid_block solid_block;
    pfn_api_get_faces get_faces;
    pfn_api_offset_face offset_face;
    pfn_list_ctor list_ctor;
    pfn_list_dtor list_dtor;
    pfn_list_ctor_one list_ctor_one;
    pfn_list_count list_count;
    pfn_list_at list_at;
    pfn_restore_list restore_list;
    pfn_api_tweak_faces tweak_faces;
    pfn_get_box get_box;
    pfn_tweak2 tweak2;
    pfn_tweak_init tweak_init;
    pfn_move_faces move_faces;
    pfn_transf_ctor transf_ctor;
    pfn_init init_local_ops;
    pfn_vec3 vec3;
    pfn_mat3 mat3;
    pfn_transf6 transf6;
    pfn_init init_lopt_ops;
    pfn_obj_ctor lop_ctor;
    pfn_obj_ctor lop_dtor;
};

static Api g_api;
static BODY* g_body;
static BODY* g_lastBody;

template <typename T>
static T Res(HMODULE h, const char* name) { return (T)GetProcAddress(h, name); }

static bool ResolveAll(Api& a) {
    a.h = GetModuleHandleW(L"SpaACIS.dll");
    if (!a.h) return false;
    a.ok = Res<pfn_outcome_ok>(a.h, ACIS_SYM_OUTCOME_OK);
    a.errno_ = Res<pfn_outcome_error_number>(a.h, ACIS_SYM_OUTCOME_ERRNO);
    a.dtor = Res<pfn_outcome_dtor>(a.h, ACIS_SYM_OUTCOME_DTOR);
    a.solid_block = Res<pfn_api_solid_block>(a.h, ACIS_SYM_SOLID_BLOCK);
    a.get_faces = Res<pfn_api_get_faces>(a.h, ACIS_SYM_GET_FACES);
    a.offset_face = Res<pfn_api_offset_face>(a.h, ACIS_SYM_OFFSET_FACE);
    a.list_ctor = Res<pfn_list_ctor>(a.h, SYM_LIST_CTOR);
    a.list_dtor = Res<pfn_list_dtor>(a.h, SYM_LIST_DTOR);
    a.list_ctor_one = Res<pfn_list_ctor_one>(a.h, SYM_LIST_CTOR_ONE);
    a.list_count = Res<pfn_list_count>(a.h, SYM_LIST_COUNT);
    a.list_at = Res<pfn_list_at>(a.h, SYM_LIST_AT);
    a.restore_list = Res<pfn_restore_list>(a.h, SYM_RESTORE_LIST);
    a.tweak_faces = Res<pfn_api_tweak_faces>(a.h, SYM_TWEAK_FACES);
    a.get_box = Res<pfn_get_box>(a.h, SYM_GET_BOX);
    a.tweak2 = Res<pfn_tweak2>(a.h, SYM_TWEAK_FACES2);
    a.tweak_init = Res<pfn_tweak_init>(a.h, SYM_TWEAK_INIT);
    a.move_faces = Res<pfn_move_faces>(a.h, SYM_MOVE_FACES);
    a.transf_ctor = Res<pfn_transf_ctor>(a.h, SYM_TRANSF_CTOR);
    a.init_local_ops = Res<pfn_init>(a.h, SYM_INIT_LOCAL_OPS);
    a.vec3 = Res<pfn_vec3>(a.h, SYM_VEC3);
    a.mat3 = Res<pfn_mat3>(a.h, SYM_MAT3);
    a.transf6 = Res<pfn_transf6>(a.h, SYM_TRANSF6);
    a.init_lopt_ops = Res<pfn_init>(a.h, SYM_INIT_LOPT_OPS);
    a.lop_ctor = Res<pfn_obj_ctor>(a.h, SYM_LOP_CTOR);
    a.lop_dtor = Res<pfn_obj_ctor>(a.h, SYM_LOP_DTOR);
    return a.ok && a.dtor && a.solid_block && a.get_faces &&
           a.list_ctor && a.list_dtor && a.list_count && a.list_at;
}

static bool Outcome(Api& a, outcome_slot& oc, int* errOut) {
    int ok = a.ok(&oc);
    if (errOut) *errOut = a.errno_ ? a.errno_(&oc) : -1;
    a.dtor(&oc);
    return ok == 1;
}

static int CountFaces(Api& a, BODY* body) {
    void* list = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!list) return -1;
    a.list_ctor(list);
    outcome_slot oc;
    ZeroMemory(&oc, sizeof(oc));
    a.get_faces((ENTITY*)body, (ENTITY_LIST*)list, 0, nullptr);
    int ok = a.ok(&oc);
    a.dtor(&oc);
    int n = ok ? a.list_count(list) : -1;
    a.list_dtor(list);
    VirtualFree(list, 0, MEM_RELEASE);
    return n;
}

// --- SAT writer (CST's own, proven path) -----------------------------------

#pragma pack(push, 8)
struct Str32 {
    union { char buf[16]; char* ptr; } u;
    size_t len;
    size_t cap;
};
#pragma pack(pop)

static void Str32Init(Str32* s, const char* text) {
    size_t n = strlen(text);
    if (n <= 15) { memcpy(s->u.buf, text, n + 1); s->len = n; s->cap = 15; }
    else {
        s->u.ptr = (char*)malloc(n + 1);
        if (s->u.ptr) memcpy(s->u.ptr, text, n + 1);
        s->len = n; s->cap = n;
    }
}
static void Str32Free(Str32* s) { if (s->cap > 15 && s->u.ptr) free(s->u.ptr); }

typedef void (__cdecl* pfn_mif_ctor)(void*);
typedef void (__cdecl* pfn_mif_dtor)(void*);
typedef void (__cdecl* pfn_mif_add)(void*, ENTITY*, const Str32*, const Str32*);
typedef bool (__cdecl* pfn_mif_write)(const void*, const Str32*, double);

static long WriteSat(void* entity, const char* path) {
    WCHAR exe[MAX_PATH];
    GetModuleFileNameW(nullptr, exe, MAX_PATH);
    WCHAR* slash = wcsrchr(exe, L'\\');
    if (!slash) return -1;
    *slash = 0;
    wcscat_s(exe, MAX_PATH, L"\\SatMifInterface_AMD64.dll");

    HMODULE m = LoadLibraryW(exe);
    if (!m) return -2;
    auto ctor = Res<pfn_mif_ctor>(m, "??0SatMifInterface@0@QEAA@XZ");
    auto dtor = Res<pfn_mif_dtor>(m, "??1SatMifInterface@0@QEAA@XZ");
    auto add = Res<pfn_mif_add>(m, "?add_entity@SatMifInterface@1@QEAAXPEAVENTITY@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@1@Z");
    auto write = Res<pfn_mif_write>(m, "?write_sat_file_only@SatMifInterface@1@QEBA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@N@Z");
    if (!ctor || !dtor || !add || !write) return -3;

    alignas(16) unsigned char obj[512];
    ZeroMemory(obj, sizeof(obj));
    ctor(obj);

    Str32 name, mat, file;
    Str32Init(&name, "mcp_agent");
    Str32Init(&mat, "Vacuum");
    Str32Init(&file, path);

    add(obj, (ENTITY*)entity, &name, &mat);
    bool ok = write(obj, &file, 1.0);

    dtor(obj);
    Str32Free(&name);
    Str32Free(&mat);
    Str32Free(&file);

    if (!ok) return -4;
    FILE* f = _fsopen(path, "rb", _SH_DENYNO);
    long size = -1;
    if (f) { fseek(f, 0, SEEK_END); size = ftell(f); fclose(f); }
    return size;
}

// ------------------------------------------------------------- dispatch

static void Reply(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(g_response, sizeof(g_response), fmt, ap);
    va_end(ap);
}

static void RunRequest(const char* line) {
    if (strncmp(line, "ping", 4) == 0) { Reply("OK pong"); return; }

    if (strncmp(line, "block ", 6) == 0) {
        double lx = 10, ly = 10, lz = 10;
        sscanf_s(line + 6, "%lf %lf %lf", &lx, &ly, &lz);
        SPAposition lo(0, 0, 0), hi(lx, ly, lz);
        BODY* body = nullptr;
        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        g_api.solid_block(&lo, &hi, &body, nullptr);
        int err = 0;
        bool ok = Outcome(g_api, oc, &err);
        if (!ok || !body) { Reply("ERR api_solid_block errno=%d", err); return; }
        g_body = body;
        g_lastBody = nullptr;
        Reply("OK body=%p faces=%d", (void*)body, CountFaces(g_api, body));
        return;
    }

    if (strncmp(line, "faces", 5) == 0) {
        if (!g_body) { Reply("ERR no body; run block first"); return; }
        Reply("OK faces=%d", CountFaces(g_api, g_body));
        return;
    }

    if (strncmp(line, "offset ", 7) == 0) {
        if (!g_body) { Reply("ERR no body; run block first"); return; }
        int index = 0;
        double dist = 2.0;
        sscanf_s(line + 7, "%d %lf", &index, &dist);

        void* list = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!list) { Reply("ERR out of memory"); return; }
        g_api.list_ctor(list);
        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        g_api.get_faces((ENTITY*)g_body, (ENTITY_LIST*)list, 0, nullptr);
        int err = 0;
        bool ok = Outcome(g_api, oc, &err);
        int n = ok ? g_api.list_count(list) : 0;
        if (!ok || index < 0 || index >= n) {
            Reply("ERR bad face index %d (faces=%d errno=%d)", index, n, err);
            g_api.list_dtor(list);
            VirtualFree(list, 0, MEM_RELEASE);
            return;
        }
        ENTITY* face = g_api.list_at(list, index);

        BODY* out = nullptr;
        outcome_slot oc2;
        ZeroMemory(&oc2, sizeof(oc2));
        g_api.offset_face((FACE*)face, dist, &out, nullptr);
        bool ok2 = Outcome(g_api, oc2, &err);
        g_api.list_dtor(list);
        VirtualFree(list, 0, MEM_RELEASE);
        if (!ok2 || !out) { Reply("ERR api_offset_face errno=%d", err); return; }
        g_lastBody = out;
        Reply("OK body=%p faces=%d", (void*)out, CountFaces(g_api, out));
        return;
    }

    if (strncmp(line, "save ", 5) == 0) {
        // "save main <path>" exports the original body, plain "save <path>" the
        // most recent offset result.
        BODY* target = g_lastBody ? g_lastBody : g_body;
        const char* path = line + 5;
        if (strncmp(path, "main ", 5) == 0) { target = g_body; path += 5; }
        if (!target) { Reply("ERR no body; run block first"); return; }
        long size = WriteSat((void*)target, path);
        if (size < 0) { Reply("ERR write_sat_file_only code=%ld", size); return; }
        Reply("OK bytes=%ld path=%s", size, path);
        return;
    }

    if (strncmp(line, "initlop", 7) == 0) {
        int r1 = -1, r2 = -1;
        if (g_api.init_local_ops) { outcome_slot o; ZeroMemory(&o, sizeof(o)); g_api.init_local_ops(); r1 = g_api.ok(&o); g_api.dtor(&o); }
        if (g_api.init_lopt_ops) { outcome_slot o; ZeroMemory(&o, sizeof(o)); g_api.init_lopt_ops(); r2 = g_api.ok(&o); g_api.dtor(&o); }
        Reply("OK local_ops=%d lopt_ops=%d", r1, r2);
        return;
    }
    if (strncmp(line, "mv ", 3) == 0) {
        if (!g_body || !g_api.move_faces || !g_api.vec3 || !g_api.mat3 || !g_api.transf6) {
            Reply("ERR mv unavailable"); return;
        }
        int index = 0; double dx = 0, dy = 0, dz = 0;
        sscanf_s(line + 3, "%d %lf %lf %lf", &index, &dx, &dy, &dz);

        void* flist = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!flist) { Reply("ERR oom"); return; }
        g_api.list_ctor(flist);
        outcome_slot oc; ZeroMemory(&oc, sizeof(oc));
        g_api.get_faces((ENTITY*)g_body, (ENTITY_LIST*)flist, 0, nullptr);
        int err = 0; bool ok = Outcome(g_api, oc, &err);
        int n = ok ? g_api.list_count(flist) : 0;
        if (!ok || index < 0 || index >= n) { Reply("ERR bad face index %d (n=%d)", index, n); return; }
        FACE* faces[1] = { (FACE*)g_api.list_at(flist, index) };

        // identity basis + translation vector -> a real translation transform
        void* v1 = VirtualAlloc(nullptr, 64, MEM_COMMIT|MEM_RESERVE, PAGE_READWRITE);
        void* v2 = VirtualAlloc(nullptr, 64, MEM_COMMIT|MEM_RESERVE, PAGE_READWRITE);
        void* v3 = VirtualAlloc(nullptr, 64, MEM_COMMIT|MEM_RESERVE, PAGE_READWRITE);
        void* tv = VirtualAlloc(nullptr, 64, MEM_COMMIT|MEM_RESERVE, PAGE_READWRITE);
        void* mat = VirtualAlloc(nullptr, 512, MEM_COMMIT|MEM_RESERVE, PAGE_READWRITE);
        void* tr = VirtualAlloc(nullptr, 1024, MEM_COMMIT|MEM_RESERVE, PAGE_READWRITE);
        g_api.vec3(v1, 1, 0, 0);
        g_api.vec3(v2, 0, 1, 0);
        g_api.vec3(v3, 0, 0, 1);
        g_api.vec3(tv, dx, dy, dz);
        g_api.mat3(mat, v1, v2, v3);
        g_api.transf6(tr, mat, tv, 1.0, 0, 0, 0);

        SPAposition lo(-1e4, -1e4, -1e4), hi(1e4, 1e4, 1e4);
        outcome_slot oc2; ZeroMemory(&oc2, sizeof(oc2));
        g_api.move_faces(1, faces, tr, &lo, &hi, &hi, nullptr);
        bool ok2 = Outcome(g_api, oc2, &err);
        Reply(ok2 ? "OK faces=%d" : "ERR api_move_faces errno=%d faces=%d",
              ok2 ? CountFaces(g_api, g_body) : err, ok2 ? 0 : CountFaces(g_api, g_body));
        return;
    }
    if (strncmp(line, "move ", 5) == 0) {
        if (!g_body || !g_api.move_faces || !g_api.transf_ctor) { Reply("ERR move_faces unavailable"); return; }
        int index = 0;
        double dx = 0, dy = 0, dz = 0;
        sscanf_s(line + 5, "%d %lf %lf %lf", &index, &dx, &dy, &dz);

        void* flist = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!flist) { Reply("ERR out of memory"); return; }
        g_api.list_ctor(flist);
        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        g_api.get_faces((ENTITY*)g_body, (ENTITY_LIST*)flist, 0, nullptr);
        int err = 0;
        bool ok = Outcome(g_api, oc, &err);
        int n = ok ? g_api.list_count(flist) : 0;
        if (!ok || index < 0 || index >= n) { Reply("ERR bad face index %d (faces=%d)", index, n); return; }
        FACE* faces[1] = { (FACE*)g_api.list_at(flist, index) };

        void* transf = VirtualAlloc(nullptr, 512, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        g_api.transf_ctor(transf);
        SPAposition from(0, 0, 0), to(dx, dy, dz);
        SPAposition zero(0, 0, 0);

        outcome_slot oc2;
        ZeroMemory(&oc2, sizeof(oc2));
        g_api.move_faces(1, faces, transf, &from, &to, &zero, nullptr);
        bool ok2 = Outcome(g_api, oc2, &err);
        Reply(ok2 ? "OK faces=%d" : "ERR api_move_faces errno=%d faces=%d",
              ok2 ? CountFaces(g_api, g_body) : err, ok2 ? 0 : CountFaces(g_api, g_body));
        return;
    }
    if (strncmp(line, "tweak3 ", 7) == 0) {
        if (!g_body || !g_api.tweak_init) { Reply("ERR tweak_init unavailable"); return; }
        int index = 0;
        double dx = 0, dy = 0, dz = 0;
        sscanf_s(line + 7, "%d %lf %lf %lf", &index, &dx, &dy, &dz);

        void* flist = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        void* inList = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        void* outList = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!flist || !inList || !outList) { Reply("ERR out of memory"); return; }
        g_api.list_ctor(flist);
        g_api.list_ctor(inList);
        g_api.list_ctor(outList);

        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        g_api.get_faces((ENTITY*)g_body, (ENTITY_LIST*)flist, 0, nullptr);
        int err = 0;
        bool ok = Outcome(g_api, oc, &err);
        int n = ok ? g_api.list_count(flist) : 0;
        if (!ok || index < 0 || index >= n) {
            Reply("ERR bad face index %d (faces=%d)", index, n);
            return;
        }
        FACE* faces[1] = { (FACE*)g_api.list_at(flist, index) };

        SPAposition delta(dx, dy, dz);
        outcome_slot oc2;
        ZeroMemory(&oc2, sizeof(oc2));
        g_api.tweak_init(1, faces, nullptr, nullptr, inList, &delta, outList, nullptr, nullptr);
        bool ok2 = Outcome(g_api, oc2, &err);
        int affected = g_api.list_count(outList);
        Reply(ok2 ? "OK affected=%d faces=%d" : "ERR api_tweak_faces_init errno=%d",
              ok2 ? affected : err, ok2 ? CountFaces(g_api, g_body) : 0);
        return;
    }
    if (strncmp(line, "tweak2 ", 7) == 0) {
        if (!g_body || !g_api.tweak2 || !g_api.lop_ctor) { Reply("ERR tweak2 unavailable"); return; }
        int index = 0;
        double dx = 0, dy = 0, dz = 0;
        sscanf_s(line + 7, "%d %lf %lf %lf", &index, &dx, &dy, &dz);

        void* list = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!list) { Reply("ERR out of memory"); return; }
        g_api.list_ctor(list);
        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        g_api.get_faces((ENTITY*)g_body, (ENTITY_LIST*)list, 0, nullptr);
        int err = 0;
        bool ok = Outcome(g_api, oc, &err);
        int n = ok ? g_api.list_count(list) : 0;
        if (!ok || index < 0 || index >= n) {
            Reply("ERR bad face index %d (faces=%d)", index, n);
            g_api.list_dtor(list);
            VirtualFree(list, 0, MEM_RELEASE);
            return;
        }
        FACE* faces[1] = { (FACE*)g_api.list_at(list, index) };
        g_api.list_dtor(list);
        VirtualFree(list, 0, MEM_RELEASE);

        void* lop = VirtualAlloc(nullptr, 1024, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        SPAposition delta(dx, dy, dz);
        outcome_slot oc2;
        ZeroMemory(&oc2, sizeof(oc2));
        g_api.lop_ctor(lop);
        g_api.tweak2(1, faces, nullptr, nullptr, &delta, nullptr, lop, nullptr);
        bool ok2 = Outcome(g_api, oc2, &err);
        if (g_api.lop_dtor) g_api.lop_dtor(lop);
        VirtualFree(lop, 0, MEM_RELEASE);
        Reply(ok2 ? "OK faces=%d" : "ERR api_tweak_faces(lop) errno=%d", ok2 ? CountFaces(g_api, g_body) : err);
        return;
    }
    if (strncmp(line, "bbox", 4) == 0) {
        if (!g_body || !g_api.get_box) { Reply("ERR no body or no api_get_entity_box"); return; }
        void* list = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!list) { Reply("ERR out of memory"); return; }
        g_api.list_ctor(list);
        g_api.list_ctor_one(list, (ENTITY*)g_body);
        SPAposition lo, hi;
        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        g_api.get_box((const void*)list, &lo, &hi, nullptr, nullptr);
        int err = 0;
        bool ok = Outcome(g_api, oc, &err);
        g_api.list_dtor(list);
        VirtualFree(list, 0, MEM_RELEASE);
        if (!ok) { Reply("ERR api_get_entity_box errno=%d", err); return; }
        Reply("OK lo=(%.2f %.2f %.2f) hi=(%.2f %.2f %.2f)", lo.x, lo.y, lo.z, hi.x, hi.y, hi.z);
        return;
    }
    if (strncmp(line, "tweak ", 6) == 0) {
        if (!g_body) { Reply("ERR no body"); return; }
        if (!g_api.tweak_faces) { Reply("ERR api_tweak_faces missing"); return; }
        int index = 0;
        double dx = 0, dy = 0, dz = 0;
        sscanf_s(line + 6, "%d %lf %lf %lf", &index, &dx, &dy, &dz);

        void* list = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!list) { Reply("ERR out of memory"); return; }
        g_api.list_ctor(list);
        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        g_api.get_faces((ENTITY*)g_body, (ENTITY_LIST*)list, 0, nullptr);
        int err = 0;
        bool ok = Outcome(g_api, oc, &err);
        int n = ok ? g_api.list_count(list) : 0;
        if (!ok || index < 0 || index >= n) {
            Reply("ERR bad face index %d (faces=%d)", index, n);
            g_api.list_dtor(list);
            VirtualFree(list, 0, MEM_RELEASE);
            return;
        }
        FACE* faces[1] = { (FACE*)g_api.list_at(list, index) };
        g_api.list_dtor(list);
        VirtualFree(list, 0, MEM_RELEASE);

        SPAposition delta(dx, dy, dz);
        outcome_slot oc2;
        ZeroMemory(&oc2, sizeof(oc2));
        g_api.tweak_faces(1, faces, nullptr, nullptr, delta, nullptr, nullptr);
        bool ok2 = Outcome(g_api, oc2, &err);
        int after = CountFaces(g_api, g_body);
        Reply(ok2 ? "OK faces=%d" : "ERR api_tweak_faces errno=%d faces=%d", ok2 ? after : err, ok2 ? 0 : after);
        return;
    }
    if (strncmp(line, "restore ", 8) == 0) {
        if (!g_api.restore_list) { Reply("ERR api_restore_entity_list missing"); return; }
        const char* path = line + 8;
        FILE* f = _fsopen(path, "r", _SH_DENYNO);
        if (!f) { Reply("ERR cannot open %s", path); return; }
        void* list = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!list) { fclose(f); Reply("ERR out of memory"); return; }
        g_api.list_ctor(list);
        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        g_api.restore_list(f, 1, list, nullptr);
        int err = 0;
        bool ok = Outcome(g_api, oc, &err);
        int n = ok ? g_api.list_count(list) : -1;
        fclose(f);
        if (ok && n > 0) {
            // make the restored geometry the current body so faces/offset work on it
            g_body = (BODY*)g_api.list_at(list, 0);
            g_lastBody = nullptr;
            Reply("OK entities=%d body=%p faces=%d", n, (void*)g_body, CountFaces(g_api, g_body));
        }
        else {
            Reply("ERR api_restore_entity_list errno=%d", err);
        }
        return;
    }
    if (strncmp(line, "quit", 4) == 0) { Reply("OK bye"); return; }

    Reply("ERR unknown command: %.60s", line);
}

// ------------------------------------------------------------- ui thread

static LRESULT CALLBACK GetMsgProc(int code, WPARAM w, LPARAM l) {
    if (code == HC_ACTION && InterlockedCompareExchange(&g_jobPending, 1, 1) == 1) {
        RunRequest(g_request);
        InterlockedExchange(&g_jobPending, 0);
        SetEvent(g_jobDone);
    }
    return CallNextHookEx(g_hook, code, w, l);
}

static BOOL CALLBACK EnumWndProc(HWND hwnd, LPARAM p) {
    DWORD pid = (DWORD)p;
    DWORD owner = 0;
    GetWindowThreadProcessId(hwnd, &owner);
    if (owner == pid && IsWindowVisible(hwnd)) return FALSE;
    return TRUE;
}

static DWORD FindUiThread(DWORD pid) {
    struct Ctx { DWORD pid, tid; } c = {pid, 0};
    EnumWindows([](HWND hwnd, LPARAM p) -> BOOL {
        auto* c = (Ctx*)p;
        DWORD owner = 0;
        DWORD tid = GetWindowThreadProcessId(hwnd, &owner);
        if (owner == c->pid && IsWindowVisible(hwnd)) { c->tid = tid; return FALSE; }
        return TRUE;
    }, (LPARAM)&c);
    if (c.tid) return c.tid;

    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snap != INVALID_HANDLE_VALUE) {
        THREADENTRY32 te;
        te.dwSize = sizeof(te);
        if (Thread32First(snap, &te)) {
            do {
                if (te.th32OwnerProcessID == pid) { c.tid = te.th32ThreadID; break; }
            } while (Thread32Next(snap, &te));
        }
        CloseHandle(snap);
    }
    return c.tid;
}

// Execute one request on the UI thread and copy the reply out.
static bool ExecOnUiThread(const char* line) {
    EnterCriticalSection(&g_lock);
    strncpy_s(g_request, sizeof(g_request), line, _TRUNCATE);
    g_response[0] = 0;
    ResetEvent(g_jobDone);
    InterlockedExchange(&g_jobPending, 1);
    PostThreadMessageW(g_uiTid, WM_NULL, 0, 0);
    BOOL ok = WaitForSingleObject(g_jobDone, 20000) == WAIT_OBJECT_0;
    LeaveCriticalSection(&g_lock);
    return ok == TRUE;
}

// ------------------------------------------------------------- pipe server

static DWORD WINAPI PipeServer(LPVOID) {
    char pipeName[128];
    _snprintf_s(pipeName, sizeof(pipeName), _TRUNCATE, "\\\\.\\pipe\\cst-acis-%lu", g_pid);

    for (;;) {
        HANDLE pipe = CreateNamedPipeA(pipeName, PIPE_ACCESS_DUPLEX,
                                       PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
                                       PIPE_UNLIMITED_INSTANCES, 8192, 8192, 0, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) { Log("CreateNamedPipe failed %lu", GetLastError()); return 1; }

        if (!ConnectNamedPipe(pipe, nullptr) && GetLastError() != ERROR_PIPE_CONNECTED) {
            CloseHandle(pipe);
            continue;
        }

        char buf[1024];
        DWORD read = 0;
        while (ReadFile(pipe, buf, sizeof(buf) - 1, &read, nullptr) && read > 0) {
            buf[read] = 0;
            while (read > 0 && (buf[read - 1] == '\n' || buf[read - 1] == '\r')) buf[--read] = 0;
            if (!buf[0]) continue;

            Log("[pipe] <- %s", buf);
            bool ok = ExecOnUiThread(buf);
            if (!ok) Reply("ERR timeout waiting for the UI thread");

            DWORD wrote = 0;
            char out[4200];
            _snprintf_s(out, sizeof(out), _TRUNCATE, "%s\n", g_response);
            WriteFile(pipe, out, (DWORD)strlen(out), &wrote, nullptr);
            Log("[pipe] -> %s", g_response);

            if (strncmp(buf, "quit", 4) == 0) { DisconnectNamedPipe(pipe); CloseHandle(pipe); return 0; }
        }
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
    }
}

// ------------------------------------------------------------------ entry

static DWORD WINAPI Worker(LPVOID) {
    WCHAR tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    char dir[MAX_PATH];
    WideCharToMultiByte(CP_ACP, 0, tmp, -1, dir, MAX_PATH, nullptr, nullptr);
    char path[MAX_PATH];
    _snprintf_s(path, sizeof(path), _TRUNCATE, "%scst_acis_agent.%lu.log", dir, g_pid);
    g_log = _fsopen(path, "w", _SH_DENYNO);
    Log("pid=%lu self=%p", g_pid, (void*)g_self);

    if (!ResolveAll(g_api)) { Log("SpaACIS not ready; wrong process?"); return 1; }

    g_uiTid = FindUiThread(g_pid);
    Log("ui thread=%lu", g_uiTid);
    if (!g_uiTid) return 1;

    g_jobDone = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    InitializeCriticalSection(&g_lock);
    g_hook = SetWindowsHookExW(WH_GETMESSAGE, GetMsgProc, g_self, g_uiTid);
    if (!g_hook) { Log("SetWindowsHookEx failed %lu", GetLastError()); return 1; }

    PostThreadMessageW(g_uiTid, WM_NULL, 0, 0);   // let the hook go live
    Log("ready, pipe=\\\\.\\pipe\\cst-acis-%lu", g_pid);
    return PipeServer(nullptr);
}

BOOL APIENTRY DllMain(HMODULE mod, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_self = mod;
        g_pid = GetCurrentProcessId();
        DisableThreadLibraryCalls(mod);
        HANDLE t = CreateThread(nullptr, 0, Worker, nullptr, 0, nullptr);
        if (t) CloseHandle(t);
    }
    return TRUE;
}

