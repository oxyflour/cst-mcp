// Direct-modelling subset of the ACIS C API, resolved by mangled name.
//
// Types are opaque: only pointer size matters at the ABI level. Signatures
// marked INFERRED contain MSVC back-references in the mangled name; the out
// parameter was deduced from how CST and ACIS use these calls (always the new
// BODY). Confirm against the ACIS 2021 C API reference before relying on it.
#pragma once

#include "acis_shim.h"

struct FACE;
struct EDGE;
struct VERTEX;
struct CURVE;
struct SURFACE;
struct COEDGE;
struct WIRE;
struct LUMP;
struct SHELL;
struct APOINT;
struct BoolOptions;
struct lop_options;
struct offset_options;
struct stitch_options;
struct mass_props;
struct param_info;
struct SPAvector { double x, y, z; };
struct SPAunit_vector { double x, y, z; };

// PAT_NEXT_TYPE: pass 0 for the common "all" traversal.
typedef int PAT_NEXT_TYPE;
// BOOL_TYPE / NDBOOL_KEEP: ACIS enums, int-sized.
typedef int BOOL_TYPE;
typedef int NDBOOL_KEEP;

// ---------------------------------------------------------------- confirmed

typedef outcome_slot(__cdecl* pfn_api_remove_face)(FACE*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_simplify_face)(FACE*, int, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_simplify_body)(BODY*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_hh_auto_heal)(BODY*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_clean_body)(BODY*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_split_face)(FACE*, int, int, double, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_imprint)(BODY*, BODY*, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_stitch_bodies)(BODY*, BODY*, int, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_chamfer_edges)(const ENTITY_LIST*, double, double, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_get_faces)(ENTITY*, ENTITY_LIST*, PAT_NEXT_TYPE, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_get_edges)(ENTITY*, ENTITY_LIST*, PAT_NEXT_TYPE, AcisOptions*);
typedef outcome_slot(__cdecl* pfn_api_entity_extrema)(
    ENTITY*, int, SPAvector*, SPAposition*, param_info*, AcisOptions*);

// ---------------------------------------------------------------- inferred

typedef outcome_slot(__cdecl* pfn_api_offset_face)(
    FACE*, double, BODY**, AcisOptions*);                       // INFERRED: BODY*&
typedef outcome_slot(__cdecl* pfn_api_offset_body)(
    BODY*, double, const SPAposition*, BODY**, lop_options*, AcisOptions*);  // INFERRED
typedef outcome_slot(__cdecl* pfn_api_boolean)(
    BODY*, BODY*, BOOL_TYPE, NDBOOL_KEEP, BODY**, AcisOptions*);             // INFERRED
typedef outcome_slot(__cdecl* pfn_api_separate_body)(
    BODY*, int*, BODY***, AcisOptions*);                        // INFERRED: BODY**&

// ------------------------------------------------------------------ symbols

#define ACIS_SYM_OFFSET_FACE    "?api_offset_face@@YA?AVoutcome@@PEAVFACE@@NAEAPEAV2@PEAVAcisOptions@@@Z"
#define ACIS_SYM_OFFSET_BODY    "?api_offset_body@@YA?AVoutcome@@PEAVBODY@@NVSPAposition@@1PEAVAcisOptions@@@Z"
#define ACIS_SYM_BOOLEAN        "?api_boolean@@YA?AVoutcome@@PEAVBODY@@0W4BOOL_TYPE@@W4NDBOOL_KEEP@@AEAPEAV2@PEAVAcisOptions@@@Z"
#define ACIS_SYM_SEPARATE_BODY  "?api_separate_body@@YA?AVoutcome@@PEAVBODY@@AEAHAEAPEAPEAV2@PEAVAcisOptions@@@Z"
#define ACIS_SYM_REMOVE_FACE    "?api_remove_face@@YA?AVoutcome@@PEAVFACE@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_SIMPLIFY_FACE  "?api_simplify_face@@YA?AVoutcome@@PEAVFACE@@HPEAVAcisOptions@@@Z"
#define ACIS_SYM_SIMPLIFY_BODY  "?api_simplify_body@@YA?AVoutcome@@PEAVBODY@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_AUTO_HEAL      "?api_hh_auto_heal@@YA?AVoutcome@@PEAVBODY@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_CLEAN_BODY     "?api_clean_body@@YA?AVoutcome@@PEAVBODY@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_SPLIT_FACE     "?api_split_face@@YA?AVoutcome@@PEAVFACE@@HHNPEAVAcisOptions@@@Z"
#define ACIS_SYM_IMPRINT        "?api_imprint@@YA?AVoutcome@@PEAVBODY@@0PEAVAcisOptions@@@Z"
#define ACIS_SYM_STITCH_BODIES  "?api_stitch@@YA?AVoutcome@@PEAVBODY@@0HPEAVAcisOptions@@@Z"
#define ACIS_SYM_CHAMFER_EDGES  "?api_chamfer_edges@@YA?AVoutcome@@AEBVENTITY_LIST@@NNPEAVAcisOptions@@@Z"
#define ACIS_SYM_GET_FACES      "?api_get_faces@@YA?AVoutcome@@PEAVENTITY@@AEAVENTITY_LIST@@W4PAT_NEXT_TYPE@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_GET_EDGES      "?api_get_edges@@YA?AVoutcome@@PEAVENTITY@@AEAVENTITY_LIST@@W4PAT_NEXT_TYPE@@PEAVAcisOptions@@@Z"
#define ACIS_SYM_ENTITY_EXTREMA "?api_entity_extrema@@YA?AVoutcome@@PEAVENTITY@@HPEAVSPAvector@@AEAVSPAposition@@AEAVparam_info@@PEAVAcisOptions@@@Z"

// Component initialisers. Kernel is already up inside CST; the rest may not be.
#define ACIS_SYM_INIT_HEALING   "?api_initialize_healing@@YA?AVoutcome@@XZ"
#define ACIS_SYM_INIT_OFFSET    "?api_initialize_offsetting@@YA?AVoutcome@@XZ"
#define ACIS_SYM_INIT_SHELLING  "?api_initialize_shelling@@YA?AVoutcome@@XZ"
#define ACIS_SYM_INIT_STITCHING "?api_initialize_stitching@@YA?AVoutcome@@XZ"
#define ACIS_SYM_INIT_BLENDING  "?api_initialize_blending@@YA?AVoutcome@@XZ"
#define ACIS_SYM_INIT_BOOLEANS  "?api_initialize_booleans@@YA?AVoutcome@@XZ"
