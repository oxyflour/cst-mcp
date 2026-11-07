// Live BRep snapshot. CST's shape queries supply the live BODY*; pointers are
// traversed only during that call, never retained for use by a later request.
#include "acis_brep.h"
#include <array>
#include <unordered_map>
#include <stdexcept>
#include <sstream>
#include <iomanip>
#include <locale>

typedef void* (__cdecl* BrepNode)(const void*);
typedef void* (__cdecl* BrepNext)(const void*, int);
typedef int (__cdecl* BrepInt)(const void*);
typedef outcome_slot(__cdecl* BrepCollect)(void*, void*, int, AcisOptions*);
// Explicit hidden outcome return buffer: do NOT copy our 256-byte shim into a
// CST caller's much smaller real outcome object. Its caller owns/destructs it.
typedef void* (__cdecl* BrepBodyQuery)(void*, const SPAposition*, BODY*, int*, int, AcisOptions*);
enum BrepKind { BLump, BShell, BFace, BLoop, BCoedge, BEdge, BVertex, BWire, BKindCount };
static const char* kBrepNames[] = {"lumps","shells","faces","loops","coedges","edges","vertices","wires"};

struct BrepApi {
    bool ready = false;
    std::array<BrepCollect, BKindCount> collect;
    BrepNode bodyLump, bodyWire, lumpShell, shellLump, shellFace, shellWire;
    BrepNode faceShell, faceLoop, faceGeom, loopFace, loopStart;
    BrepNode ceEdge, ceLoop, ceWire, ceNext, cePrev, cePartner;
    BrepNode edgeStart, edgeEnd, edgeCe, edgeGeom, vertexGeom, bodyTransform, transformValue, wireShell, wireCe;
    BrepNext lumpNext, shellNext, faceNext, loopNext, wireNext;
    BrepInt faceSense, ceSense, edgeSense;
    const SPAposition* (__cdecl* coords)(const void*);
    SPAposition (__cdecl* transformPoint)(const SPAposition*, const void*);
    std::array<BrepInt, 8> geomIs;
};
static BrepApi g_brep;
static BrepBodyQuery g_brepOriginal;
static unsigned char* g_brepTarget;
static unsigned char* g_brepTrampoline;
static unsigned char g_brepSaved[19];
static bool g_brepCapturing;
static thread_local bool g_brepInHook;
static ULONGLONG g_brepDeadline;
static std::vector<std::string> g_brepCaptured;
static std::string g_brepError;
static size_t g_brepEntityCount, g_brepBytes;
static const size_t kBrepMaxEntities = 200000, kBrepMaxBytes = 64 * 1024 * 1024;

template<class T> static T BrepResolve(const char* symbol) {
    T value = Res<T>(g_api.h, symbol);
    if (!value) throw std::runtime_error(std::string("missing BRep symbol: ") + symbol);
    return value;
}
static void BrepResolveAll() {
    if (g_brep.ready) return;
    const char* queries[] = {BREP_LUMPS, BREP_SHELLS, ACIS_SYM_GET_FACES, BREP_LOOPS,
                             BREP_COEDGES, BREP_EDGES, BREP_VERTICES, BREP_WIRES};
    for (int i=0; i<BKindCount; ++i) g_brep.collect[i] = BrepResolve<BrepCollect>(queries[i]);
#define BREP_NODE(field, sym) g_brep.field = BrepResolve<BrepNode>(sym)
#define BREP_NEXT(field, sym) g_brep.field = BrepResolve<BrepNext>(sym)
#define BREP_INT(field, sym) g_brep.field = BrepResolve<BrepInt>(sym)
    BREP_NODE(bodyLump,BREP_BODY_LUMP); BREP_NODE(bodyWire,BREP_BODY_WIRE);
    BREP_NODE(lumpShell,BREP_LUMP_SHELL); BREP_NEXT(lumpNext,BREP_LUMP_NEXT);
    BREP_NODE(shellLump,BREP_SHELL_LUMP); BREP_NODE(shellFace,BREP_SHELL_FACE);
    BREP_NODE(shellWire,BREP_SHELL_WIRE); BREP_NEXT(shellNext,BREP_SHELL_NEXT);
    BREP_NODE(faceShell,BREP_FACE_SHELL); BREP_NODE(faceLoop,BREP_FACE_LOOP);
    BREP_NODE(faceGeom,BREP_FACE_GEOM); BREP_NEXT(faceNext,BREP_FACE_NEXT); BREP_INT(faceSense,BREP_FACE_SENSE);
    BREP_NODE(loopFace,BREP_LOOP_FACE); BREP_NODE(loopStart,BREP_LOOP_START); BREP_NEXT(loopNext,BREP_LOOP_NEXT);
    BREP_NODE(ceEdge,BREP_CE_EDGE); BREP_NODE(ceLoop,BREP_CE_LOOP); BREP_NODE(ceWire,BREP_CE_WIRE);
    BREP_NODE(ceNext,BREP_CE_NEXT); BREP_NODE(cePrev,BREP_CE_PREV); BREP_NODE(cePartner,BREP_CE_PARTNER);
    BREP_INT(ceSense,BREP_CE_SENSE);
    BREP_NODE(edgeStart,BREP_EDGE_START); BREP_NODE(edgeEnd,BREP_EDGE_END); BREP_NODE(edgeCe,BREP_EDGE_CE);
    BREP_NODE(edgeGeom,BREP_EDGE_GEOM); BREP_INT(edgeSense,BREP_EDGE_SENSE);
    BREP_NODE(vertexGeom,BREP_VERTEX_GEOM); BREP_NODE(bodyTransform,BREP_BODY_TRANSFORM);
    BREP_NODE(transformValue,BREP_TRANSFORM_VALUE);
    BREP_NODE(wireShell,BREP_WIRE_SHELL); BREP_NODE(wireCe,BREP_WIRE_CE); BREP_NEXT(wireNext,BREP_WIRE_NEXT);
#undef BREP_NODE
#undef BREP_NEXT
#undef BREP_INT
    g_brep.coords = BrepResolve<decltype(g_brep.coords)>(BREP_POINT_COORDS);
    g_brep.transformPoint = BrepResolve<decltype(g_brep.transformPoint)>(BREP_TRANSFORM_POINT);
    const char* types[] = {BREP_IS_PLANE,BREP_IS_CONE,BREP_IS_SPHERE,BREP_IS_TORUS,
                           BREP_IS_SPLINE,BREP_IS_STRAIGHT,BREP_IS_ELLIPSE,BREP_IS_INTCURVE};
    for (int i=0; i<8; ++i) g_brep.geomIs[i] = BrepResolve<BrepInt>(types[i]);
    g_brep.ready = true;
}

struct BrepTable {
    std::vector<void*> nodes;
    std::unordered_map<const void*, int> ids;
    void read(BODY* body, int kind) {
        EList list;
        outcome_slot o = g_brep.collect[kind](body,list.p,0,nullptr);
        int err=0;
        if (!Outcome(g_api,o,&err)) throw std::runtime_error(std::string("cannot enumerate ")+kBrepNames[kind]+" errno="+std::to_string(err));
        int n=list.count();
        if (n<0 || g_brepEntityCount+(size_t)n>kBrepMaxEntities) throw std::runtime_error("BRep snapshot exceeds 200000 entities");
        g_brepEntityCount += n;
        for (int i=0;i<n;++i) {
            void* p=list.at(i);
            if (!p || !ids.emplace(p,i).second) throw std::runtime_error("null or duplicate topology entity");
            nodes.push_back(p);
        }
    }
    std::string ref(const void* p) const {
        if (!p) return "null";
        auto at=ids.find(p);
        if (at==ids.end()) throw std::runtime_error("topology relation points outside its body");
        return std::to_string(at->second);
    }
};
static const char* BrepGeomType(void* p) {
    if (!p) return "none";
    const char* names[]={"plane","cone","sphere","torus","spline","straight","ellipse","intcurve"};
    for (int i=0;i<8;++i) if (g_brep.geomIs[i](p)) return names[i];
    return "other";
}
static std::string BrepSnapshot(BODY* body) {
    std::array<BrepTable,BKindCount> t;
    for (int k=0;k<BKindCount;++k) t[k].read(body,k);
    std::ostringstream out;
    out.imbue(std::locale::classic()); out << std::setprecision(17);
    void* transform=g_brep.bodyTransform(body);
    if (transform) transform=g_brep.transformValue(transform);
    out << "{\"counts\":{";
    for (int k=0;k<BKindCount;++k) { if(k)out<<',';out<<'"'<<kBrepNames[k]<<"\":"<<t[k].nodes.size(); }
    out << "},\"firstLump\":" << t[BLump].ref(g_brep.bodyLump(body))
        << ",\"firstWire\":" << t[BWire].ref(g_brep.bodyWire(body));
    for (int k=0;k<BKindCount;++k) {
        out << ",\""<<kBrepNames[k]<<"\":[";
        for (size_t i=0;i<t[k].nodes.size();++i) {
            if(i)out<<',';
            void* p=t[k].nodes[i]; out<<"{\"id\":"<<i;
            auto ref=[&](const char* name,int kind,void* node) {out<<",\""<<name<<"\":"<<t[kind].ref(node);};
            switch(k) {
            case BLump:
                ref("firstShell",BShell,g_brep.lumpShell(p)); ref("next",BLump,g_brep.lumpNext(p,0)); break;
            case BShell:
                ref("lump",BLump,g_brep.shellLump(p));ref("firstFace",BFace,g_brep.shellFace(p));
                ref("firstWire",BWire,g_brep.shellWire(p));ref("next",BShell,g_brep.shellNext(p,0));break;
            case BFace:
                ref("shell",BShell,g_brep.faceShell(p));ref("firstLoop",BLoop,g_brep.faceLoop(p));
                ref("next",BFace,g_brep.faceNext(p,0));
                out<<",\"sense\":"<<g_brep.faceSense(p)<<",\"surfaceType\":\""<<BrepGeomType(g_brep.faceGeom(p))<<'"';break;
            case BLoop:
                ref("face",BFace,g_brep.loopFace(p));ref("firstCoedge",BCoedge,g_brep.loopStart(p));ref("next",BLoop,g_brep.loopNext(p,0));break;
            case BCoedge:
                ref("edge",BEdge,g_brep.ceEdge(p));ref("loop",BLoop,g_brep.ceLoop(p));ref("wire",BWire,g_brep.ceWire(p));
                ref("next",BCoedge,g_brep.ceNext(p));ref("previous",BCoedge,g_brep.cePrev(p));ref("partner",BCoedge,g_brep.cePartner(p));
                out<<",\"sense\":"<<g_brep.ceSense(p);break;
            case BEdge:
                ref("start",BVertex,g_brep.edgeStart(p));ref("end",BVertex,g_brep.edgeEnd(p));ref("firstCoedge",BCoedge,g_brep.edgeCe(p));
                out<<",\"sense\":"<<g_brep.edgeSense(p)<<",\"curveType\":\""<<BrepGeomType(g_brep.edgeGeom(p))<<'"';break;
            case BVertex: {
                void* geom=g_brep.vertexGeom(p);
                if(!geom)throw std::runtime_error("vertex has no point geometry");
                SPAposition local=*g_brep.coords(geom), world=local;
                if(transform)world=g_brep.transformPoint(&local,transform);
                if(!std::isfinite(world.x)||!std::isfinite(world.y)||!std::isfinite(world.z))throw std::runtime_error("non-finite vertex coordinate");
                out<<",\"position\":["<<world.x<<','<<world.y<<','<<world.z<<"],\"localPosition\":["<<local.x<<','<<local.y<<','<<local.z<<']';break;
            }
            case BWire:
                ref("shell",BShell,g_brep.wireShell(p));ref("firstCoedge",BCoedge,g_brep.wireCe(p));ref("next",BWire,g_brep.wireNext(p,0));break;
            }
            out<<'}';
        }
        out<<']';
    }
    out<<'}';
    std::string result=out.str();
    if(g_brepBytes+result.size()>kBrepMaxBytes)throw std::runtime_error("BRep snapshot exceeds 64 MiB");
    g_brepBytes+=result.size();
    return result;
}

static void* __cdecl BrepBodyQueryHook(void* result,const SPAposition* point,BODY* body,int* containment,int boxes,AcisOptions* options) {
    // The original function and its outcome retain exactly their normal ownership.
    if(g_brepInHook)return g_brepOriginal(result,point,body,containment,boxes,options);
    g_brepInHook=true;
    void* ret=g_brepOriginal(result,point,body,containment,boxes,options);
    if(g_brepCapturing && GetCurrentThreadId()==g_uiTid && g_brepError.empty()) {
        try {
            if(GetTickCount64()>g_brepDeadline)throw std::runtime_error("BRep capture expired");
            g_brepCaptured.push_back(BrepSnapshot(body));
        } catch(const std::exception& e) {g_brepError=e.what();}
          catch(...) {g_brepError="BRep query failed";}
    }
    g_brepInHook=false;
    return ret;
}

static bool BrepSetHook(bool enable) {
    // CST calls this export through cached addresses, not the ordinary IAT.
    // The CST 2022 / ACIS 2021 prologue consists of six complete instructions,
    // without branches or RIP-relative operands. Reject any other binary.
    static const unsigned char prologue[19] = {0x48,0x8b,0xc4,0x48,0x89,0x48,0x08,0x57,
        0x41,0x56,0x41,0x57,0x48,0x81,0xec,0x20,0x01,0x00,0x00};
    if(!g_brepTarget) {
        auto target=(unsigned char*)g_api.point_in_body;
        if(!target || memcmp(target,prologue,sizeof(prologue)))return false;
        auto trampoline=(unsigned char*)VirtualAlloc(nullptr,64,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
        if(!trampoline)return false;
        memcpy(trampoline,prologue,19);
        trampoline[19]=0xff;trampoline[20]=0x25;memset(trampoline+21,0,4);
        void* resume=target+19;memcpy(trampoline+25,&resume,sizeof(resume));
        DWORD old=0;
        if(!VirtualProtect(trampoline,64,PAGE_EXECUTE_READ,&old)) {VirtualFree(trampoline,0,MEM_RELEASE);return false;}
        FlushInstructionCache(GetCurrentProcess(),trampoline,64);
        memcpy(g_brepSaved,prologue,19);g_brepTarget=target;g_brepTrampoline=trampoline;
        g_brepOriginal=(BrepBodyQuery)trampoline;
    }
    unsigned char patch[19]={0xff,0x25,0,0,0,0};
    void* hook=(void*)&BrepBodyQueryHook;memcpy(patch+6,&hook,sizeof(hook));memset(patch+14,0x90,5);
    const unsigned char* expected=enable?g_brepSaved:patch;
    if(memcmp(g_brepTarget,expected,19)) {
        if(!enable && !memcmp(g_brepTarget,g_brepSaved,19)) {g_brepCapturing=false;return true;}
        return false;
    }
    DWORD old=0,ignored=0;
    if(!VirtualProtect(g_brepTarget,19,PAGE_EXECUTE_READWRITE,&old))return false;
    memcpy(g_brepTarget,enable?patch:g_brepSaved,19);
    FlushInstructionCache(GetCurrentProcess(),g_brepTarget,19);
    VirtualProtect(g_brepTarget,19,old,&ignored);
    g_brepCapturing=enable;
    return true;
}

static bool RunBrepRequest(const char* line) {
    if(strcmp(line,"brep_begin")==0) {
        if(g_brepCapturing) {Reply("ERR BRep capture already active");return true;}
        try {
            BrepResolveAll();g_brepCaptured.clear();g_brepError.clear();g_brepEntityCount=0;g_brepBytes=0;
            g_brepDeadline=GetTickCount64()+300000;
            if(!BrepSetHook(true))throw std::runtime_error("unsupported CST/ACIS query prologue or active instrumentation");
            Reply("OK capturing");
        } catch(const std::exception& e) {Reply("ERR %s",e.what());}
        return true;
    }
    if(strcmp(line,"brep_end")==0 || strcmp(line,"brep_cancel")==0) {
        if(!BrepSetHook(false)) {Reply("ERR cannot restore CST solid query imports");return true;}
        if(strcmp(line,"brep_cancel")==0) {g_brepCaptured.clear();Reply("OK cancelled");return true;}
        if(!g_brepError.empty()) {Reply("ERR %s",g_brepError.c_str());g_brepCaptured.clear();return true;}
        g_response="OK [";
        for(size_t i=0;i<g_brepCaptured.size();++i) {if(i)g_response+=',';g_response+=g_brepCaptured[i];}
        g_response+=']';g_brepCaptured.clear();return true;
    }
    return false;
}
