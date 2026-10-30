// Feature-replay commands for cst_acis_agent.cpp (included right before RunRequest).
// Entities are addressed by index in api_get_faces / api_get_edges order of the
// current body; `dump` writes those indices with bounding boxes so the caller can
// match them geometrically and send indices back. Indices go stale after any
// command that changes the body.
//
//   dump faces|edges <file>             -> one line per entity: index box(6)
//   rmfaces <i>...                      -> api_remove_faces (neighbours grow to heal)
//   taper <px py pz> <nx ny nz> <deg> <i>...
//                                       -> api_taper_faces about the plane (p, n)
//   blend <r> <i>...                    -> api_blend_edges on edges i
//   chamfer <d1> <d2> <i>...            -> api_chamfer_edges on edges i
//   prism new|add|cut <z0> <h> <draftDeg> <file>
//                                       -> sweep closed loops from <file> along +Z;
//                                          first loop outer, the rest islands
//                                          (lines "L x1 y1 x2 y2", "A x1 y1 xm ym x2 y2",
//                                          "LOOP" between loops)
//   newbody                             -> forget the current body (next prism new)
//   snap / undo                         -> keep a copy of the body / go back to it
//   mass                                -> volume of the body (api_body_mass_props)
//   offset <d> [vent]                   -> api_offset_body: every face moves d along its normal
//                                          (outward > 0); vent = lop_options vent_type_id, how
//                                          the gaps at convex edges are filled
//   swap                                -> exchange the main body and the aux body
//   bool add|cut|int                    -> unite / subtract / intersect the aux body into the main one

#include <vector>

typedef outcome_slot(__cdecl* pfn_remove_faces)(int, FACE**, const SPAposition*, const SPAposition*, void*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_taper_faces)(int, FACE**, const SPAposition*, const SPAposition* /*unit vector*/,
                                               const double*, const SPAposition*, const SPAposition*, void*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_blend_edges)(const void*, double, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_chamfer_edges)(const void*, double, double, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_get_edges)(ENTITY*, void*, int, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_curve_line)(const SPAposition*, const SPAposition*, EDGE**, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_curve_arc_3pt)(const SPAposition*, const SPAposition*, const SPAposition*, int, EDGE**, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_make_ewire)(int, EDGE**, BODY**, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_sweep_vec)(ENTITY*, const SPAposition* /*SPAvector*/, void*, BODY**, AcisOptions*);
typedef void (__cdecl* pfn_sweep_set_d)(void*, double);
typedef void (__cdecl* pfn_sweep_set_i)(void*, int);
typedef outcome_slot(__cdecl* pfn_bool)(BODY*, BODY*, AcisOptions*);
typedef int (__cdecl* pfn_list_add)(void*, ENTITY*, int);
typedef outcome_slot(__cdecl* pfn_copy_body)(BODY*, BODY**, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_del_entity)(ENTITY*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_mass_props)(BODY*, void*, void*, AcisOptions*);
typedef double (__cdecl* pfn_get_volume)(const void*);
typedef void (__cdecl* pfn_set_vent)(void*, int);
typedef outcome_slot(__cdecl* pfn_offset_body)(BODY*, double, const SPAposition*, const SPAposition*, void*, AcisOptions*);

struct Ops {
    bool tried, ok;
    pfn_remove_faces remove_faces;
    pfn_taper_faces taper_faces;
    pfn_blend_edges blend_edges;
    pfn_chamfer_edges chamfer_edges;
    pfn_get_edges get_edges;
    pfn_curve_line curve_line;
    pfn_curve_arc_3pt curve_arc_3pt;
    pfn_make_ewire make_ewire;
    pfn_sweep_vec sweep;
    pfn_obj_ctor sweep_ctor, sweep_dtor;
    pfn_sweep_set_d sweep_draft;
    pfn_sweep_set_i sweep_solid;
    pfn_bool subtract, unite, intersect;
    pfn_list_add list_add;
    pfn_copy_body copy_body;
    pfn_del_entity del_entity;
    pfn_mass_props mass_props;
    pfn_obj_ctor mp_ctor, mp_dtor;
    pfn_get_volume mp_volume;
    pfn_offset_body offset_body;
    pfn_obj_ctor lop_ctor, lop_dtor;
    pfn_set_vent set_vent;
};
static BODY* g_snap;
static BODY* g_aux;     // second body: tool/fill bodies are built here, then combined with the main one
static Ops g_ops;

static bool ResolveOps() {
    if (g_ops.tried) return g_ops.ok;
    g_ops.tried = true;
    HMODULE h = g_api.h;
    g_ops.remove_faces = Res<pfn_remove_faces>(h, "?api_remove_faces@@YA?AVoutcome@@HQEAPEAVFACE@@AEBVSPAposition@@1PEAVlop_options@@PEAVAcisOptions@@@Z");
    g_ops.taper_faces = Res<pfn_taper_faces>(h, "?api_taper_faces@@YA?AVoutcome@@HQEAPEAVFACE@@AEBVSPAposition@@AEBVSPAunit_vector@@AEBN11PEAVlop_options@@PEAVAcisOptions@@@Z");
    g_ops.blend_edges = Res<pfn_blend_edges>(h, "?api_blend_edges@@YA?AVoutcome@@AEBVENTITY_LIST@@NPEAVAcisOptions@@@Z");
    g_ops.chamfer_edges = Res<pfn_chamfer_edges>(h, "?api_chamfer_edges@@YA?AVoutcome@@AEBVENTITY_LIST@@NNPEAVAcisOptions@@@Z");
    g_ops.get_edges = Res<pfn_get_edges>(h, "?api_get_edges@@YA?AVoutcome@@PEAVENTITY@@AEAVENTITY_LIST@@W4PAT_NEXT_TYPE@@PEAVAcisOptions@@@Z");
    g_ops.curve_line = Res<pfn_curve_line>(h, "?api_curve_line@@YA?AVoutcome@@AEBVSPAposition@@0AEAPEAVEDGE@@PEAVAcisOptions@@@Z");
    g_ops.curve_arc_3pt = Res<pfn_curve_arc_3pt>(h, "?api_curve_arc_3pt@@YA?AVoutcome@@AEBVSPAposition@@00HAEAPEAVEDGE@@PEAVAcisOptions@@@Z");
    g_ops.make_ewire = Res<pfn_make_ewire>(h, "?api_make_ewire@@YA?AVoutcome@@HQEAPEAVEDGE@@AEAPEAVBODY@@PEAVAcisOptions@@@Z");
    g_ops.sweep = Res<pfn_sweep_vec>(h, "?api_sweep_with_options@@YA?AVoutcome@@PEAVENTITY@@AEBVSPAvector@@PEAVsweep_options@@AEAPEAVBODY@@PEAVAcisOptions@@@Z");
    g_ops.sweep_ctor = Res<pfn_obj_ctor>(h, "??0sweep_options@@QEAA@XZ");
    g_ops.sweep_dtor = Res<pfn_obj_ctor>(h, "??1sweep_options@@QEAA@XZ");
    g_ops.sweep_draft = Res<pfn_sweep_set_d>(h, "?set_draft_angle@sweep_options@@QEAAXN@Z");
    g_ops.sweep_solid = Res<pfn_sweep_set_i>(h, "?set_solid@sweep_options@@QEAAXH@Z");
    g_ops.subtract = Res<pfn_bool>(h, "?api_subtract@@YA?AVoutcome@@PEAVBODY@@0PEAVAcisOptions@@@Z");
    g_ops.unite = Res<pfn_bool>(h, "?api_unite@@YA?AVoutcome@@PEAVBODY@@0PEAVAcisOptions@@@Z");
    g_ops.intersect = Res<pfn_bool>(h, "?api_intersect@@YA?AVoutcome@@PEAVBODY@@0PEAVAcisOptions@@@Z");
    g_ops.list_add = Res<pfn_list_add>(h, "?add@ENTITY_LIST@@QEAAHPEAVENTITY@@H@Z");
    g_ops.copy_body = Res<pfn_copy_body>(h, "?api_copy_body@@YA?AVoutcome@@PEAVBODY@@AEAPEAV2@PEAVAcisOptions@@@Z");
    g_ops.del_entity = Res<pfn_del_entity>(h, "?api_del_entity@@YA?AVoutcome@@PEAVENTITY@@PEAVAcisOptions@@@Z");
    g_ops.mass_props = Res<pfn_mass_props>(h, "?api_body_mass_props@@YA?AVoutcome@@PEAVBODY@@AEAVmass_props@@PEAVmass_props_options@@PEAVAcisOptions@@@Z");
    g_ops.mp_ctor = Res<pfn_obj_ctor>(h, "??0mass_props@@QEAA@XZ");
    g_ops.mp_dtor = Res<pfn_obj_ctor>(h, "??1mass_props@@QEAA@XZ");
    g_ops.mp_volume = Res<pfn_get_volume>(h, "?get_volume@mass_props@@QEBANXZ");
    g_ops.lop_ctor = Res<pfn_obj_ctor>(h, "??0lop_options@@QEAA@XZ");
    g_ops.lop_dtor = Res<pfn_obj_ctor>(h, "??1lop_options@@QEAA@XZ");
    g_ops.set_vent = Res<pfn_set_vent>(h, "?set_vent_type@lop_options@@QEAAXW4vent_type_id@@@Z");
    g_ops.offset_body = Res<pfn_offset_body>(h, "?api_offset_body@@YA?AVoutcome@@PEAVBODY@@NAEBVSPAposition@@1PEAVlop_options@@PEAVAcisOptions@@@Z");

    const char* inits[] = {"?api_initialize_local_ops@@YA?AVoutcome@@XZ", "?api_initialize_face_removal@@YA?AVoutcome@@XZ",
                           "?api_initialize_blending@@YA?AVoutcome@@XZ", "?api_initialize_sweeping@@YA?AVoutcome@@XZ",
                           "?api_initialize_booleans@@YA?AVoutcome@@XZ"};
    for (const char* sym : inits) {
        pfn_init fn = Res<pfn_init>(h, sym);
        if (!fn) { Log("init %s missing", sym); continue; }
        outcome_slot o = fn();
        int err = 0;
        bool ok = Outcome(g_api, o, &err);
        Log("%s ok=%d errno=%d", sym, ok, err);
    }
    g_ops.ok = g_ops.remove_faces && g_ops.taper_faces && g_ops.blend_edges && g_ops.chamfer_edges &&
               g_ops.get_edges && g_ops.curve_line && g_ops.curve_arc_3pt && g_ops.make_ewire && g_ops.sweep &&
               g_ops.sweep_ctor && g_ops.sweep_dtor && g_ops.sweep_draft && g_ops.sweep_solid &&
               g_ops.subtract && g_ops.unite && g_ops.list_add && g_ops.copy_body && g_ops.del_entity &&
               g_ops.mass_props && g_ops.mp_ctor && g_ops.mp_dtor && g_ops.mp_volume;
    Log("ops resolved=%d", g_ops.ok);
    return g_ops.ok;
}

// RAII-free ENTITY_LIST holder: storage from VirtualAlloc, real ctor/dtor.
struct EList {
    void* p;
    EList() { p = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE); g_api.list_ctor(p); }
    ~EList() { g_api.list_dtor(p); VirtualFree(p, 0, MEM_RELEASE); }
    int count() const { return g_api.list_count(p); }
    ENTITY* at(int i) const { return g_api.list_at(p, i); }
};

static bool Collect(bool edges, EList& out) {
    outcome_slot o = edges ? g_ops.get_edges((ENTITY*)g_body, out.p, 0, nullptr)
                           : g_api.get_faces((ENTITY*)g_body, (ENTITY_LIST*)out.p, 0, nullptr);
    int err = 0;
    return Outcome(g_api, o, &err);
}

static void ReplyErr(const char* what, int err) {
    Reply("ERR %s errno=%d %s: %s", what, err, g_api.err_ident ? g_api.err_ident(err) : "?",
          g_api.err_mess ? g_api.err_mess(err) : "?");
}

// parses trailing integer indices into entities of `all`; "@path" reads them from a file
// (long lists do not fit the 1 KB request line)
static bool Pick(const char* s, const EList& all, std::vector<ENTITY*>& out) {
    int n = all.count();
    while (*s == ' ') s++;
    if (*s == '@') {
        char path[512] = {0};
        sscanf_s(s + 1, "%511s", path, (unsigned)sizeof(path));
        FILE* f = _fsopen(path, "r", _SH_DENYNO);
        if (!f) return false;
        long i;
        while (fscanf_s(f, "%ld", &i) == 1) {
            if (i < 0 || i >= n) { fclose(f); return false; }
            out.push_back(all.at((int)i));
        }
        fclose(f);
        return !out.empty();
    }
    while (*s) {
        while (*s == ' ') s++;
        if (!*s) break;
        char* end = nullptr;
        long i = strtol(s, &end, 10);
        if (end == s || i < 0 || i >= n) return false;
        out.push_back(all.at((int)i));
        s = end;
    }
    return !out.empty();
}

static const char* SkipTokens(const char* s, int n) {
    for (int k = 0; k < n; k++) {
        while (*s == ' ') s++;
        while (*s && *s != ' ') s++;
    }
    return s;
}

// builds one swept prism from a loop of segments at height z0
static BODY* SweepLoop(const std::vector<std::vector<double>>& segs, char* kinds, double z0, double h,
                       double draftRad, int* errOut) {
    std::vector<EDGE*> edges;
    for (size_t k = 0; k < segs.size(); k++) {
        const std::vector<double>& v = segs[k];
        EDGE* e = nullptr;
        outcome_slot o;
        if (kinds[k] == 'L') {
            SPAposition a(v[0], v[1], z0), b(v[2], v[3], z0);
            o = g_ops.curve_line(&a, &b, &e, nullptr);
        } else {
            SPAposition a(v[0], v[1], z0), m(v[2], v[3], z0), b(v[4], v[5], z0);
            o = g_ops.curve_arc_3pt(&a, &m, &b, 0, &e, nullptr);
        }
        if (!Outcome(g_api, o, errOut) || !e) return nullptr;
        edges.push_back(e);
    }
    BODY* wire = nullptr;
    outcome_slot o = g_ops.make_ewire((int)edges.size(), edges.data(), &wire, nullptr);
    if (!Outcome(g_api, o, errOut) || !wire) return nullptr;

    void* opts = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    g_ops.sweep_ctor(opts);
    g_ops.sweep_solid(opts, 1);
    if (draftRad != 0) g_ops.sweep_draft(opts, draftRad);
    SPAposition dir(0, 0, h);
    BODY* swept = nullptr;
    o = g_ops.sweep((ENTITY*)wire, &dir, opts, &swept, nullptr);
    bool ok = Outcome(g_api, o, errOut);
    g_ops.sweep_dtor(opts);
    VirtualFree(opts, 0, MEM_RELEASE);
    if (!ok) return nullptr;
    return swept ? swept : wire;   // sweeping a wire body turns that body into the solid
}

static bool RunOps(const char* line) {
    bool isOp = strncmp(line, "dump ", 5) == 0 || strncmp(line, "rmfaces ", 8) == 0 ||
                strncmp(line, "taper ", 6) == 0 || strncmp(line, "blend ", 6) == 0 ||
                strncmp(line, "chamfer ", 8) == 0 || strncmp(line, "prism ", 6) == 0 ||
                strncmp(line, "newbody", 7) == 0 || strcmp(line, "snap") == 0 || strcmp(line, "undo") == 0 ||
                strcmp(line, "mass") == 0 || strcmp(line, "swap") == 0 || strncmp(line, "bool ", 5) == 0 ||
                strncmp(line, "offset ", 7) == 0;
    if (!isOp) return false;
    if (!ResolveOps()) { Reply("ERR feature ops unresolved (see agent log)"); return true; }

    if (strncmp(line, "newbody", 7) == 0) {
        g_body = nullptr;
        g_lastBody = nullptr;
        Reply("OK");
        return true;
    }

    if (strcmp(line, "swap") == 0) {
        BODY* t = g_body;
        g_body = g_aux;
        g_aux = t;
        g_lastBody = nullptr;
        Reply("OK main=%d aux=%d", g_body ? CountFaces(g_api, g_body) : 0, g_aux ? CountFaces(g_api, g_aux) : 0);
        return true;
    }
    if (strncmp(line, "bool ", 5) == 0) {
        // bool add|cut: combines the aux body into the main one (aux is consumed)
        if (!g_body || !g_aux) { Reply("ERR need main and aux bodies"); return true; }
        int err = 0;
        pfn_bool fn = strcmp(line + 5, "add") == 0 ? g_ops.unite
                    : strcmp(line + 5, "int") == 0 ? g_ops.intersect : g_ops.subtract;
        if (!fn) { Reply("ERR boolean unresolved"); return true; }
        outcome_slot o = fn(g_aux, g_body, nullptr);
        g_aux = nullptr;
        if (!Outcome(g_api, o, &err)) { ReplyErr("bool", err); return true; }
        Reply("OK faces=%d", CountFaces(g_api, g_body));
        return true;
    }

    if (strncmp(line, "prism ", 6) == 0) {
        char op[8] = {0}, path[512] = {0};
        double z0, h, draft;
        if (sscanf_s(line + 6, "%7s %lf %lf %lf %511s", op, (unsigned)sizeof(op), &z0, &h, &draft, path,
                     (unsigned)sizeof(path)) != 5) {
            Reply("ERR usage: prism new|add|cut z0 h draftDeg file");
            return true;
        }
        FILE* f = _fsopen(path, "r", _SH_DENYNO);
        if (!f) { Reply("ERR cannot open %s", path); return true; }
        std::vector<std::vector<std::vector<double>>> loops(1);
        std::vector<std::string> kinds(1);
        char buf[512];
        while (fgets(buf, sizeof(buf), f)) {
            if (strncmp(buf, "LOOP", 4) == 0) { loops.emplace_back(); kinds.emplace_back(); continue; }
            double v[6] = {0};
            if (buf[0] == 'L' && sscanf_s(buf + 1, "%lf %lf %lf %lf", &v[0], &v[1], &v[2], &v[3]) == 4) {
                loops.back().push_back(std::vector<double>(v, v + 4));
                kinds.back().push_back('L');
            } else if (buf[0] == 'A' && sscanf_s(buf + 1, "%lf %lf %lf %lf %lf %lf", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]) == 6) {
                loops.back().push_back(std::vector<double>(v, v + 6));
                kinds.back().push_back('A');
            }
        }
        fclose(f);
        int err = 0;
        double rad = draft * 3.14159265358979323846 / 180.0;
        BODY* solid = SweepLoop(loops[0], &kinds[0][0], z0, h, rad, &err);
        if (!solid) { ReplyErr("prism outer", err); return true; }
        for (size_t k = 1; k < loops.size(); k++) {
            if (loops[k].empty()) continue;
            // islands are sweeps of their own, drafted the opposite way so walls stay parallel
            BODY* isl = SweepLoop(loops[k], &kinds[k][0], z0, h, -rad, &err);
            if (!isl) { ReplyErr("prism island", err); return true; }
            outcome_slot o = g_ops.subtract(isl, solid, nullptr);
            if (!Outcome(g_api, o, &err)) { ReplyErr("prism island subtract", err); return true; }
        }
        outcome_slot o;
        if (_stricmp(op, "new") == 0 || !g_body) {
            g_body = solid;
        } else if (_stricmp(op, "add") == 0) {
            o = g_ops.unite(solid, g_body, nullptr);
            if (!Outcome(g_api, o, &err)) { ReplyErr("prism unite", err); return true; }
        } else {
            o = g_ops.subtract(solid, g_body, nullptr);
            if (!Outcome(g_api, o, &err)) { ReplyErr("prism subtract", err); return true; }
        }
        g_lastBody = nullptr;
        Reply("OK faces=%d", CountFaces(g_api, g_body));
        return true;
    }

    if (!g_body) { Reply("ERR no body"); return true; }

    if (strcmp(line, "snap") == 0) {
        int err = 0;
        if (g_snap) { outcome_slot d = g_ops.del_entity((ENTITY*)g_snap, nullptr); Outcome(g_api, d, &err); g_snap = nullptr; }
        outcome_slot o = g_ops.copy_body(g_body, &g_snap, nullptr);
        if (!Outcome(g_api, o, &err) || !g_snap) { g_snap = nullptr; ReplyErr("api_copy_body", err); return true; }
        Reply("OK");
        return true;
    }
    if (strcmp(line, "undo") == 0) {
        if (!g_snap) { Reply("ERR nothing to undo"); return true; }
        int err = 0;
        outcome_slot d = g_ops.del_entity((ENTITY*)g_body, nullptr);
        Outcome(g_api, d, &err);
        g_body = g_snap;
        g_snap = nullptr;
        g_lastBody = nullptr;
        Reply("OK faces=%d", CountFaces(g_api, g_body));
        return true;
    }
    if (strncmp(line, "offset ", 7) == 0) {
        double d = 0;
        int vent = -1;
        if (sscanf_s(line + 7, "%lf %d", &d, &vent) < 1) { Reply("ERR usage: offset d [vent]"); return true; }
        if (!g_ops.offset_body) { Reply("ERR api_offset_body unresolved"); return true; }
        SPAposition lo(-1e4, -1e4, -1e4), hi(1e4, 1e4, 1e4);
        void* lop = nullptr;
        if (vent >= 0 && g_ops.lop_ctor && g_ops.set_vent) {
            lop = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
            g_ops.lop_ctor(lop);
            g_ops.set_vent(lop, vent);
        }
        outcome_slot o = g_ops.offset_body(g_body, d, &lo, &hi, lop, nullptr);
        if (lop) { g_ops.lop_dtor(lop); VirtualFree(lop, 0, MEM_RELEASE); }
        int err = 0;
        if (!Outcome(g_api, o, &err)) { ReplyErr("api_offset_body", err); return true; }
        Reply("OK faces=%d", CountFaces(g_api, g_body));
        return true;
    }
    if (strcmp(line, "mass") == 0) {
        void* mp = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        g_ops.mp_ctor(mp);
        outcome_slot o = g_ops.mass_props(g_body, mp, nullptr, nullptr);
        int err = 0;
        bool ok = Outcome(g_api, o, &err);
        double v = ok ? g_ops.mp_volume(mp) : 0;
        g_ops.mp_dtor(mp);
        VirtualFree(mp, 0, MEM_RELEASE);
        if (!ok) { ReplyErr("api_body_mass_props", err); return true; }
        Reply("OK volume=%.9g", v);
        return true;
    }

    if (strncmp(line, "dump ", 5) == 0) {
        char what[8] = {0}, path[512] = {0};
        if (sscanf_s(line + 5, "%7s %511s", what, (unsigned)sizeof(what), path, (unsigned)sizeof(path)) != 2) {
            Reply("ERR usage: dump faces|edges file");
            return true;
        }
        bool edges = _stricmp(what, "edges") == 0;
        EList all;
        if (!Collect(edges, all)) { Reply("ERR collect failed"); return true; }
        FILE* f = _fsopen(path, "w", _SH_DENYNO);
        if (!f) { Reply("ERR cannot write %s", path); return true; }
        for (int i = 0; i < all.count(); i++) {
            void* one = VirtualAlloc(nullptr, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
            g_api.list_ctor_one(one, all.at(i));
            SPAposition lo, hi;
            outcome_slot o = g_api.get_box(one, &lo, &hi, nullptr, nullptr);
            int err = 0;
            Outcome(g_api, o, &err);
            fprintf(f, "%d %.9g %.9g %.9g %.9g %.9g %.9g\n", i, lo.x, lo.y, lo.z, hi.x, hi.y, hi.z);
            g_api.list_dtor(one);
            VirtualFree(one, 0, MEM_RELEASE);
        }
        fclose(f);
        Reply("OK %s=%d file=%s", what, all.count(), path);
        return true;
    }

    if (strncmp(line, "rmfaces ", 8) == 0 || strncmp(line, "taper ", 6) == 0) {
        bool taper = line[0] == 't';
        EList all;
        Collect(false, all);
        std::vector<ENTITY*> picked;
        double p[3], n[3], deg = 0;
        const char* rest = line + 8;
        if (taper) {
            if (sscanf_s(line + 6, "%lf %lf %lf %lf %lf %lf %lf", &p[0], &p[1], &p[2], &n[0], &n[1], &n[2], &deg) != 7) {
                Reply("ERR usage: taper px py pz nx ny nz deg i...");
                return true;
            }
            rest = SkipTokens(line + 6, 7);
        }
        if (!Pick(rest, all, picked)) { Reply("ERR bad face indices (faces=%d)", all.count()); return true; }
        SPAposition lo(-1e4, -1e4, -1e4), hi(1e4, 1e4, 1e4);
        outcome_slot o;
        if (taper) {
            double len = sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
            SPAposition pt(p[0], p[1], p[2]), nv(n[0] / len, n[1] / len, n[2] / len);
            double ang = deg * 3.14159265358979323846 / 180.0;
            o = g_ops.taper_faces((int)picked.size(), (FACE**)picked.data(), &pt, &nv, &ang, &lo, &hi, nullptr, nullptr);
        } else {
            o = g_ops.remove_faces((int)picked.size(), (FACE**)picked.data(), &lo, &hi, nullptr, nullptr);
        }
        int err = 0;
        if (!Outcome(g_api, o, &err)) { ReplyErr(taper ? "api_taper_faces" : "api_remove_faces", err); return true; }
        Reply("OK faces=%d", CountFaces(g_api, g_body));
        return true;
    }

    if (strncmp(line, "blend ", 6) == 0 || strncmp(line, "chamfer ", 8) == 0) {
        bool blend = line[0] == 'b';
        double a = 0, b = 0;
        const char* rest;
        if (blend) {
            if (sscanf_s(line + 6, "%lf", &a) != 1) { Reply("ERR usage: blend r i..."); return true; }
            rest = SkipTokens(line + 6, 1);
        } else {
            if (sscanf_s(line + 8, "%lf %lf", &a, &b) != 2) { Reply("ERR usage: chamfer d1 d2 i..."); return true; }
            rest = SkipTokens(line + 8, 2);
        }
        EList all;
        Collect(true, all);
        std::vector<ENTITY*> picked;
        if (!Pick(rest, all, picked)) { Reply("ERR bad edge indices (edges=%d)", all.count()); return true; }
        EList sel;
        for (ENTITY* e : picked) g_ops.list_add(sel.p, e, 1);
        outcome_slot o = blend ? g_ops.blend_edges(sel.p, a, nullptr) : g_ops.chamfer_edges(sel.p, a, b, nullptr);
        int err = 0;
        if (!Outcome(g_api, o, &err)) { ReplyErr(blend ? "api_blend_edges" : "api_chamfer_edges", err); return true; }
        Reply("OK faces=%d", CountFaces(g_api, g_body));
        return true;
    }
    return false;
}
