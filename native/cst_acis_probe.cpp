// cst_acis_probe.dll -- closes the loop: create a body, enumerate its faces,
// offset one face, report what ACIS says.
//
// Everything is resolved by mangled name; no ACIS headers, no import library.
// ENTITY_LIST is driven through its own exported ctor/dtor/count/operator[],
// so its layout never has to be known either.
//
// Log: %TEMP%\cst_acis_probe.<pid>.log
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

static void Log(const char* fmt, ...) {
    if (!g_log) return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
}

// ---------------------------------------------------------------- resolved API

typedef void (__cdecl* pfn_list_ctor)(void*);
typedef void (__cdecl* pfn_list_dtor)(void*);
typedef int  (__cdecl* pfn_list_count)(const void*);
typedef ENTITY* (__cdecl* pfn_list_at)(const void*, int);
typedef void (__cdecl* pfn_list_ctor_one)(void*, ENTITY*);
typedef outcome_slot(__cdecl* pfn_init)(void);

#define SYM_LIST_CTOR "??0ENTITY_LIST@@QEAA@XZ"
#define SYM_LIST_DTOR "??1ENTITY_LIST@@QEAA@XZ"
#define SYM_LIST_COUNT "?count@ENTITY_LIST@@QEBAHXZ"
#define SYM_LIST_AT "??AENTITY_LIST@@QEBAPEAVENTITY@@H@Z"
#define SYM_LIST_CTOR_ONE "??0ENTITY_LIST@@QEAA@PEAVENTITY@@@Z"

struct Api {
    HMODULE h;
    pfn_outcome_ok ok;
    pfn_outcome_error_number errno_;
    pfn_outcome_dtor dtor;
    pfn_api_solid_block solid_block;
    pfn_api_get_faces get_faces;
    pfn_api_offset_face offset_face;
    pfn_api_entity_extrema extrema;
    pfn_init init_offsetting;
    pfn_list_ctor list_ctor;
    pfn_list_dtor list_dtor;
    pfn_list_count list_count;
    pfn_list_at list_at;
    pfn_list_ctor_one list_ctor_one;
    pfn_api_save_entity_list save_list;
};

template <typename T>
static T Resolve(HMODULE h, const char* name, const char* what) {
    T fn = (T)GetProcAddress(h, name);
    if (!fn) Log("  [miss] %s", what);
    return fn;
}

static bool ResolveAll(Api& a) {
    a.h = GetModuleHandleW(L"SpaACIS.dll");
    if (!a.h) { Log("SpaACIS.dll not loaded -- wrong process"); return false; }
    Log("SpaACIS base=%p", (void*)a.h);

    a.ok = Resolve<pfn_outcome_ok>(a.h, ACIS_SYM_OUTCOME_OK, "outcome::ok");
    a.errno_ = Resolve<pfn_outcome_error_number>(a.h, ACIS_SYM_OUTCOME_ERRNO, "outcome::error_number");
    a.dtor = Resolve<pfn_outcome_dtor>(a.h, ACIS_SYM_OUTCOME_DTOR, "~outcome");
    a.solid_block = Resolve<pfn_api_solid_block>(a.h, ACIS_SYM_SOLID_BLOCK, "api_solid_block");
    a.get_faces = Resolve<pfn_api_get_faces>(a.h, ACIS_SYM_GET_FACES, "api_get_faces");
    a.offset_face = Resolve<pfn_api_offset_face>(a.h, ACIS_SYM_OFFSET_FACE, "api_offset_face");
    a.extrema = Resolve<pfn_api_entity_extrema>(a.h, ACIS_SYM_ENTITY_EXTREMA, "api_entity_extrema");
    a.init_offsetting = Resolve<pfn_init>(a.h, ACIS_SYM_INIT_OFFSET, "api_initialize_offsetting");
    a.list_ctor = Resolve<pfn_list_ctor>(a.h, SYM_LIST_CTOR, "ENTITY_LIST::ENTITY_LIST");
    a.list_dtor = Resolve<pfn_list_dtor>(a.h, SYM_LIST_DTOR, "ENTITY_LIST::~ENTITY_LIST");
    a.list_count = Resolve<pfn_list_count>(a.h, SYM_LIST_COUNT, "ENTITY_LIST::count");
    a.list_at = Resolve<pfn_list_at>(a.h, SYM_LIST_AT, "ENTITY_LIST::operator[]");
    a.list_ctor_one = Resolve<pfn_list_ctor_one>(a.h, SYM_LIST_CTOR_ONE, "ENTITY_LIST(ENTITY*)");
    a.save_list = Resolve<pfn_api_save_entity_list>(a.h, ACIS_SYM_SAVE_ENTITY_LIST, "api_save_entity_list");

    return a.ok && a.dtor && a.solid_block && a.get_faces &&
           a.list_ctor && a.list_dtor && a.list_count && a.list_at;
}

// outcome handling: log the verdict, then release whatever the outcome holds.
static bool Verdict(Api& a, outcome_slot& oc, const char* what) {
    if (!a.ok || !a.dtor) return false;
    int ok = a.ok(&oc);
    int err = a.errno_ ? a.errno_(&oc) : -1;
    Log("  %-28s ok=%d errno=%d", what, ok, err);
    a.dtor(&oc);
    return ok == 1;
}

// ---------------------------------------------------------- UI thread hop

static void DoAcisWork(void);

static LRESULT CALLBACK GetMsgProc(int code, WPARAM w, LPARAM l) {
    if (code == HC_ACTION && InterlockedExchange(&g_ran, 1) == 0) {
        DoAcisWork();
        SetEvent(g_done);
    }
    return CallNextHookEx(g_hook, code, w, l);
}

// Write one ACIS entity to a SAT file so CST can import it through VBA.
static void SaveSat(Api& a, void* entity, const char* tag) {
    if (!a.save_list || !a.list_ctor_one || !entity) return;

    WCHAR tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    char dir[MAX_PATH];
    WideCharToMultiByte(CP_ACP, 0, tmp, -1, dir, MAX_PATH, nullptr, nullptr);

    char path[MAX_PATH];
    _snprintf_s(path, sizeof(path), _TRUNCATE, "%scst_acis_%s.sat", dir, tag);

    FILE* f = _fsopen(path, "w", _SH_DENYNO);
    if (!f) { Log("  sat[%s]: open failed", tag); return; }

    // ENTITY_LIST's real size is not known. A 256-byte stack buffer produced
    // 0xC0000409 (STATUS_STACK_BUFFER_OVERRUN) inside ucrtbase, so give the
    // object a generous heap block instead.
    void* list = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!list) { fclose(f); return; }

    a.list_ctor_one(list, (ENTITY*)entity);
    Log("  sat[%s]: list=%p entity=%p file=%p -- calling save", tag, list, entity, (void*)f);

    outcome_slot oc;
    ZeroMemory(&oc, sizeof(oc));
    a.save_list(f, 1, (ENTITY_LIST*)list, nullptr);
    Log("  sat[%s]: save returned", tag);
    bool ok = Verdict(a, oc, "api_save_entity_list");
    a.list_dtor(list);
    VirtualFree(list, 0, MEM_RELEASE);
    Log("  sat[%s]: list destroyed", tag);

    fflush(f);
    fclose(f);
    Log("  sat[%s]: file closed", tag);

    long size = 0;
    FILE* g = _fsopen(path, "rb", _SH_DENYNO);
    if (g) { fseek(g, 0, SEEK_END); size = ftell(g); fclose(g); }
    Log("  sat[%s]: ok=%d %s (%ld bytes)", tag, ok ? 1 : 0, path, size);
}

// --- CST's own SAT writer: SatMifInterface::write_sat_file_only ---------------
// It takes a std::string path, so no CRT file handle crosses a module boundary
// (handing our FILE* to SpaACIS's api_save_entity_list made it fail-fast inside
// ucrtbase). The object layout is unknown, so it gets an oversized buffer plus
// its own exported ctor/dtor.
#pragma pack(push, 8)
struct Str32 {
    union { char buf[16]; char* ptr; } u;
    size_t len;
    size_t cap;
};
#pragma pack(pop)

static void Str32Init(Str32* s, const char* text) {
    size_t n = strlen(text);
    if (n <= 15) {
        memcpy(s->u.buf, text, n + 1);
        s->len = n;
        s->cap = 15;
    } else {
        s->u.ptr = (char*)malloc(n + 1);
        if (s->u.ptr) memcpy(s->u.ptr, text, n + 1);
        s->len = n;
        s->cap = n;
    }
}

static void Str32Free(Str32* s) {
    if (s->cap > 15 && s->u.ptr) free(s->u.ptr);
}

typedef void (__cdecl* pfn_mif_ctor)(void*);
typedef void (__cdecl* pfn_mif_dtor)(void*);
typedef void (__cdecl* pfn_mif_add)(void*, ENTITY*, const Str32*, const Str32*);
typedef bool (__cdecl* pfn_mif_write)(const void*, const Str32*, double);

static bool SaveViaSatMif(void* entity, const char* path, const char* tag) {
    WCHAR exe[MAX_PATH];
    GetModuleFileNameW(nullptr, exe, MAX_PATH);
    WCHAR* slash = wcsrchr(exe, L'\\');
    if (!slash) return false;
    *slash = 0;
    wcscat_s(exe, MAX_PATH, L"\\SatMifInterface_AMD64.dll");

    HMODULE m = LoadLibraryW(exe);
    if (!m) { Log("  mif[%s]: LoadLibrary failed %lu", tag, GetLastError()); return false; }

    auto ctor = (pfn_mif_ctor)GetProcAddress(m, "??0SatMifInterface@0@QEAA@XZ");
    auto dtor = (pfn_mif_dtor)GetProcAddress(m, "??1SatMifInterface@0@QEAA@XZ");
    auto add = (pfn_mif_add)GetProcAddress(
        m, "?add_entity@SatMifInterface@1@QEAAXPEAVENTITY@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@1@Z");
    auto write = (pfn_mif_write)GetProcAddress(
        m, "?write_sat_file_only@SatMifInterface@1@QEBA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@N@Z");

    Log("  mif[%s]: ctor=%p add=%p write=%p", tag, (void*)ctor, (void*)add, (void*)write);
    if (!ctor || !dtor || !add || !write) return false;

    alignas(16) unsigned char obj[512];
    ZeroMemory(obj, sizeof(obj));
    ctor(obj);

    Str32 name, mat, file;
    Str32Init(&name, "mcp_probe");
    Str32Init(&mat, "Vacuum");
    Str32Init(&file, path);

    add(obj, (ENTITY*)entity, &name, &mat);
    bool ok = write(obj, &file, 1.0);
    Log("  mif[%s]: write_sat_file_only -> %d (%s)", tag, ok ? 1 : 0, path);

    dtor(obj);
    Str32Free(&name);
    Str32Free(&mat);
    Str32Free(&file);
    return ok;
}

typedef struct { DWORD pid; DWORD tid; } FIND_CTX;

static BOOL CALLBACK EnumWndProc(HWND hwnd, LPARAM p) {
    FIND_CTX* c = (FIND_CTX*)p;
    DWORD owner = 0;
    DWORD tid = GetWindowThreadProcessId(hwnd, &owner);
    if (owner == c->pid && IsWindowVisible(hwnd)) { c->tid = tid; return FALSE; }
    return TRUE;
}

static DWORD FindUiThread(DWORD pid) {
    FIND_CTX c = {pid, 0};
    EnumWindows(EnumWndProc, (LPARAM)&c);
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

static BOOL RunOnUiThread(DWORD tid) {
    g_done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    g_ran = 0;
    g_hook = SetWindowsHookExW(WH_GETMESSAGE, GetMsgProc, g_self, tid);
    if (!g_hook) { Log("SetWindowsHookEx failed: %lu", GetLastError()); return FALSE; }
    PostThreadMessageW(tid, WM_NULL, 0, 0);
    BOOL ok = WaitForSingleObject(g_done, 20000) == WAIT_OBJECT_0;
    UnhookWindowsHookEx(g_hook);
    g_hook = nullptr;
    if (!ok) Log("timed out waiting for the UI thread");
    return ok;
}

// ------------------------------------------------------------- the loop

static void DoAcisWork(void) {
    Log("[work] tid=%lu", GetCurrentThreadId());

    Api a;
    if (!ResolveAll(a)) { Log("[work] missing symbols, abort"); return; }

    // 0. the offsetting component may never have been initialised by CST.
    if (a.init_offsetting) {
        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        a.init_offsetting();
        Verdict(a, oc, "api_initialize_offsetting");
    }

    // 1. a body to work on: a 10 x 10 x 10 block at the origin.
    SPAposition lo(0, 0, 0), hi(10, 10, 10);
    BODY* body = nullptr;
    {
        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        a.solid_block(&lo, &hi, &body, nullptr);
        if (!Verdict(a, oc, "api_solid_block") || !body) {
            Log("[work] no body -- stop here");
            return;
        }
    }
    Log("[work] body=%p", (void*)body);

    // 2. enumerate faces. PAT_NEXT_TYPE is an enum we do not have; probe 0..3.
    ENTITY* face = nullptr;
    for (int pat = 0; pat < 4 && !face; ++pat) {
        alignas(16) unsigned char storage[256];
        ZeroMemory(storage, sizeof(storage));
        a.list_ctor(storage);

        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        a.get_faces((ENTITY*)body, (ENTITY_LIST*)storage, pat, nullptr);
        int ok = a.ok(&oc);
        int err = a.errno_ ? a.errno_(&oc) : -1;
        a.dtor(&oc);

        int n = a.list_count(storage);
        Log("[work] api_get_faces(pat=%d) ok=%d errno=%d count=%d", pat, ok, err, n);

        if (ok == 1 && n > 0) face = a.list_at(storage, 0);
        a.list_dtor(storage);
    }

    if (!face) { Log("[work] no face obtained -- stop here"); return; }
    Log("[work] first face=%p", (void*)face);

    // 3. where is that face?
    if (a.extrema) {
        SPAposition pos(0, 0, 0);
        SPAvector vec;
        ZeroMemory(&vec, sizeof(vec));
        alignas(16) unsigned char pinfo[256];
        ZeroMemory(pinfo, sizeof(pinfo));

        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        a.extrema(face, 0, &vec, &pos, (param_info*)pinfo, nullptr);
        if (Verdict(a, oc, "api_entity_extrema"))
            Log("[work] extremum at (%.3f, %.3f, %.3f)", pos.x, pos.y, pos.z);
    }

    // 4. offset that face by 2.0 -> a new body.
    if (a.offset_face) {
        BODY* offsetBody = nullptr;
        outcome_slot oc;
        ZeroMemory(&oc, sizeof(oc));
        a.offset_face((FACE*)face, 2.0, &offsetBody, nullptr);
        bool ok = Verdict(a, oc, "api_offset_face");
        Log("[work] offset body=%p", (void*)offsetBody);

        // 5. prove the returned BODY* is real geometry, not a stale pointer.
        if (ok && offsetBody) {
            alignas(16) unsigned char s2[256];
            ZeroMemory(s2, sizeof(s2));
            a.list_ctor(s2);
            outcome_slot oc2;
            ZeroMemory(&oc2, sizeof(oc2));
            a.get_faces((ENTITY*)offsetBody, (ENTITY_LIST*)s2, 0, nullptr);
            int ok2 = a.ok(&oc2);
            int err2 = a.errno_ ? a.errno_(&oc2) : -1;
            a.dtor(&oc2);
            int n2 = a.list_count(s2);
            Log("  new body faces              ok=%d errno=%d count=%d", ok2, err2, n2);
            a.list_dtor(s2);
            if (ok2 == 1 && n2 > 0)
                Log("[work] SUCCESS: inject + thread + ABI + component init + entity handle all work");
            else
                Log("[work] offset returned a body but no faces -- suspect the ABI");

            // 6. hand both bodies over as SAT, the only format CST imports through VBA.
            // 6a. raw ACIS writer (FILE* path) -- testing the buffer-size theory
            SaveSat(a, (void*)body, "raw");

            char tmpA[MAX_PATH], satPath[MAX_PATH];
            WCHAR tmpW[MAX_PATH];
            GetTempPathW(MAX_PATH, tmpW);
            WideCharToMultiByte(CP_ACP, 0, tmpW, -1, tmpA, MAX_PATH, nullptr, nullptr);
            _snprintf_s(satPath, sizeof(satPath), _TRUNCATE, "%scst_acis_block.sat", tmpA);
            SaveViaSatMif((void*)body, satPath, "block");
            _snprintf_s(satPath, sizeof(satPath), _TRUNCATE, "%scst_acis_sheet.sat", tmpA);
            SaveViaSatMif((void*)offsetBody, satPath, "sheet");
        }
        else {
            Log("[work] offset failed -- read errno; usually a missing component init");
        }
    }
}

// ------------------------------------------------------------------ entry

static DWORD WINAPI Worker(LPVOID) {
    WCHAR tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    char dir[MAX_PATH];
    WideCharToMultiByte(CP_ACP, 0, tmp, -1, dir, MAX_PATH, nullptr, nullptr);

    char path[MAX_PATH];
    _snprintf_s(path, sizeof(path), _TRUNCATE, "%scst_acis_probe.%lu.%lu.log", dir, GetCurrentProcessId(), GetTickCount());
    g_log = _fsopen(path, "w", _SH_DENYNO);
    if (!g_log) return 1;

    Log("pid=%lu self=%p", GetCurrentProcessId(), (void*)g_self);

    HMODULE h = GetModuleHandleW(L"SpaACIS.dll");
    if (!h) { Log("SpaACIS.dll not loaded -- injected into the wrong process?"); return 1; }

    g_uiTid = FindUiThread(GetCurrentProcessId());
    Log("ui thread id=%lu", g_uiTid);
    if (g_uiTid) RunOnUiThread(g_uiTid);

    Log("done -> %s", path);
    if (g_log) { fflush(g_log); fclose(g_log); g_log = nullptr; }
    return 0;
}

BOOL APIENTRY DllMain(HMODULE mod, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_self = mod;
        DisableThreadLibraryCalls(mod);
        HANDLE t = CreateThread(nullptr, 0, Worker, nullptr, 0, nullptr);
        if (t) CloseHandle(t);
    }
    return TRUE;
}







