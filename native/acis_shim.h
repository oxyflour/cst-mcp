// Minimal hand-written ACIS 2021 shim: no Spatial headers required.
//
// Everything here was derived from the real export table of
//   C:\Programs\CST Studio Suite 2022\ACIS\NT_VC15_64_DLL\code\bin\SpaACIS.dll
// and from CST's own call sites (see docs/acis-injection.md).
//
// ABI rules verified against CST's machine code:
//   * `outcome` is returned through a caller-provided buffer, pointer in RCX.
//     (AcisTools_AMD64.dll: `lea rcx, [rbp+0x1f]` right before the call.)
//   * `const SPAposition&` is just a pointer; SPAposition is { double x,y,z; }.
//   * `AcisOptions* = nullptr` is fine for every call we make.
#pragma once

#include <windows.h>
#include <stdint.h>

// Opaque ACIS handles. We never dereference them.
struct ENTITY;
struct BODY;
struct AcisOptions;
struct ENTITY_LIST;

// ACIS's world position. Layout is x,y,z -- stable across ACIS releases.
struct SPAposition {
    double x, y, z;
    SPAposition() : x(0), y(0), z(0) {}
    SPAposition(double a, double b, double c) : x(a), y(b), z(c) {}
};

// Opaque return slot for `outcome`. Must be:
//   * larger than 16 bytes, so MSVC passes its address in RCX like CST does;
//   * 16-byte aligned, because the class may hold 16-byte members.
// 256 bytes is well past any observed layout; the real ctor is executed by the
// callee into this storage, and the real dtor is called explicitly afterwards.
struct outcome_slot {
    alignas(16) unsigned char storage[256];
};

typedef outcome_slot(__cdecl* pfn_api_ret_outcome)();

// Function pointers we resolve by mangled name. Signatures mirror the ones the
// mangled names encode; keep them in sync with the strings below.
typedef outcome_slot(__cdecl* pfn_api_solid_block)(
    const SPAposition*, const SPAposition*, BODY**, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_solid_cylinder_cone)(
    const SPAposition*, const SPAposition*, double, double, double,
    const SPAposition*, BODY**, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_solid_sphere)(
    const SPAposition*, double, BODY**, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_body_mass_props)(
    BODY*, void* /*mass_props*/, void* /*mass_props_options*/, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_save_entity_list)(
    void* /*FILE**/, int, const ENTITY_LIST*, AcisOptions*);

typedef int(__cdecl* pfn_outcome_ok)(const outcome_slot*);
typedef int(__cdecl* pfn_outcome_error_number)(const outcome_slot*);
typedef void(__cdecl* pfn_outcome_dtor)(outcome_slot*);

#define ACIS_SYM_START_MODELLER  "?api_start_modeller@@YA?AVoutcome@@H@Z"
#define ACIS_SYM_STOP_MODELLER   "?api_stop_modeller@@YA?AVoutcome@@XZ"
#define ACIS_SYM_SOLID_BLOCK     "?api_solid_block@@YA?AVoutcome@@AEBVSPAposition@@0AEAPEAVBODY@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_SOLID_SPHERE    "?api_solid_sphere@@YA?AVoutcome@@AEBVSPAposition@@NAEAPEAVBODY@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_SOLID_CYL       "?api_solid_cylinder_cone@@YA?AVoutcome@@AEBVSPAposition@@0NNNPEBV2@AEAPEAVBODY@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_BODY_MASS_PROPS "?api_body_mass_props@@YA?AVoutcome@@PEAVBODY@@AEAVmass_props@@PEAVmass_props_options@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_SAVE_ENTITY_LIST "?api_save_entity_list@@YA?AVoutcome@@PEAU_iobuf@@HAEBVENTITY_LIST@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_OUTCOME_OK      "?ok@outcome@@QEBAHXZ"
#define ACIS_SYM_OUTCOME_ERRNO   "?error_number@outcome@@QEBAHXZ"
#define ACIS_SYM_OUTCOME_DTOR    "??1outcome@@QEAA@XZ"
