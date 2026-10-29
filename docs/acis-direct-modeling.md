# ACIS 直接建模（direct modelling）接口清单

从 `SpaACIS.dll` 的 50 832 个导出里筛出来的、对应"直接改 B-rep"而不是"从草图重建"的 1307 个 `api_*`。
按能力分类，附组件依赖和签名可信度。**`✓` = 修饰名里没有回引、签名可完全确定；`~` = 含 `AEAPEAV2@` 这类回引，出参按语义填。**

## 0. 前置条件（每次都要）

1. 注入 `modeler_AMD64.exe`，在 **modeler 主线程**执行（见 `docs/acis-injection.md` §4）。
2. 组件初始化：ACIS 的功能是分包编译的，用之前必须 `api_initialize_<component>()`。幂等，重复调不报错，返回 `outcome` 可检查。
3. 拿到活体 `BODY*` / `FACE*`：`api_get_faces(ENTITY*, ENTITY_LIST&, PAT_NEXT_TYPE, AcisOptions*)`、`api_get_edges(...)`，或从 CST 现有的 shape 容器里取。

## 1. 能力 → 接口

| 想做的事 | 接口 | 组件 | 签名 |
|---|---|---|---|
| 单面偏置（推拉面成新体） | `api_offset_face` | offsetting | ~ |
| 多面偏置 | `api_offset_faces` | offsetting | ~ |
| 整体偏置 / 加厚 | `api_offset_body` | offsetting | ~ |
| 抽壳 | `api_hollow_body`、`api_shell_external` | shelling | ~ |
| 推拉面到指定位置 | `api_tweak_faces`、`api_tweak_replace_face` | local_ops / lopt_ops | ~ |
| 修边（延伸/收紧边） | `api_tweak_extend_faces`、`api_tweak_fix_edge`、`api_tweak_tighten_edge` | lopt_ops | ~ |
| 删面（自动补面） | `api_remove_face` ✓、`api_remove_faces` ~ | face_removal | ✓/~ |
| 开面 / 封面 | `api_uncover_face`、`api_cover_wire(s)`、`api_cover_planar_edges` | covering | ~ |
| 拔模角 | `api_taper_faces` ~、`api_shadow_taper_faces`、`api_edge_taper_faces` | lopt_ops | ~ |
| 面简化（识别平面/柱面/锥面） | `api_simplify_face` ✓、`api_simplify_body` ✓、`api_hh_simplify_auto` | healing | ✓ |
| 自动修复 | `api_hh_auto_heal` ✓、`api_hh_stitch_auto`、`api_clean_body` ✓ | healing/stitching | ✓ |
| 缝合 | `api_stitch` ✓、`api_stitch_nonmanifold` | stitching | ✓ |
| 布尔（并/交/差） | `api_boolean` ~、`api_boolean_glue` ~、`api_boolean_chop_body` | booleans | ~ |
| 等距倒角 | `api_chamfer_edges` ✓、`api_set_const_chamfers` ✓ | blending | ✓ |
| 变半径倒圆 | `api_blend_edges_pos_rad` ~、`api_abh_vblend`、`api_blend_holdline`（保持线圆角） | advanced_blending | ~ |
| 面分割 / 印记 | `api_split_face` ✓、`api_imprint` ✓、`api_imprint_stitch` | kernel | ✓ |
| 多壳分离成体 | `api_separate_body` ~ | kernel | ~ |
| 扫掠 | `api_sweep_with_options`、`api_rsw_face_path`、`api_rsw_face_vec` | sweeping | ~ |
| 放样 / 蒙皮 | `api_loft_faces`、`api_loft_coedges`、`api_skin_wires`、`api_net_wires` | skinning | ~ |
| 面/边查询 | `api_get_faces` ✓、`api_get_edges` ✓、`api_get_coedges` | kernel | ✓ |
| 极值点 | `api_entity_extrema` ✓ | kernel | ✓ |
| 质量属性 | `api_body_mass_props` ✓（但 `mass_props` 布局未知）、`api_body_mass_pr`（全标量出参） | kernel | ✓/~ |

## 2. 签名已确认（可直接照抄）

```
outcome api_remove_face(FACE*, AcisOptions*)
outcome api_simplify_face(FACE*, int, AcisOptions*)          // int = 简化选项位
outcome api_simplify_body(BODY*, AcisOptions*)
outcome api_hh_auto_heal(BODY*, AcisOptions*)
outcome api_clean_body(BODY*, AcisOptions*)
outcome api_split_face(FACE*, int, int, double, AcisOptions*) // 按 u/v 分割
outcome api_imprint(BODY*, BODY*, AcisOptions*)
outcome api_stitch(BODY*, BODY*, int, AcisOptions*)
outcome api_stitch(BODY*, ENTITY_LIST&, stitch_options*, AcisOptions*)
outcome api_chamfer_edges(const ENTITY_LIST&, double, double, AcisOptions*)
outcome api_set_const_chamfers(const ENTITY_LIST&, double,double,double,double,double,double,
                               int, int, double, double, AcisOptions*)
outcome api_get_faces(ENTITY*, ENTITY_LIST&, PAT_NEXT_TYPE, AcisOptions*)
outcome api_get_edges(ENTITY*, ENTITY_LIST&, PAT_NEXT_TYPE, AcisOptions*)
outcome api_entity_extrema(ENTITY*, int, SPAvector*, SPAposition&, param_info&, AcisOptions*)
```

## 3. 含回引、需要语义确认的

这些修饰名里出现 `AEAPEAV2@` / `?1` 这类回引（指向前面已出现的类型）。从用法看 `AEAPEAV2@` 在各种"产生新体"的 API 里都是**结果 `BODY*&`**：

```
api_offset_face   (FACE*, double, BODY*&, AcisOptions*)
api_offset_body   (BODY*, double, const SPAposition&, BODY*&, lop_options*, AcisOptions*)
api_boolean       (BODY*, BODY*, BOOL_TYPE, NDBOOL_KEEP, BODY*&, AcisOptions*)
api_separate_body (BODY*, int&, BODY**&, AcisOptions*)
api_hollow_body   (BODY*, int, const FACE**, double, const SPAposition&, ...)
api_tweak_faces   (int, const FACE**, const SURFACE**, const int*, ...)   // 3 个重载
api_taper_faces   (int, const FACE**, const SPAposition&, const SPAunit_vector&, const double&, ...)
```

写原型前拿 ACIS 2021 的 C API 参考对一遍 `?1`/`?2` 到底指向哪个参数——这里只能确认到"同类"。

## 4. 组件初始化清单

`SpaACIS.dll` 里 33 个组件，直接建模用得到的是：

```
kernel, constructors, booleans, blending, advanced_blending,
offsetting, offset_surface, shelling, local_ops, lopt_ops,
face_removal, covering, healing, stitching, sweeping, skinning,
spline, faceter, warp, part_manager, query
```

`api_initialize_<name>()` 无参数，返回 `outcome`。CST 自己必然初始化过 kernel/blending/booleans/faceter；`shelling`、`warp`、`face_removal` 这类 CST 不一定用，先探测再调。

## 5. 先把"查询"打通再动刀

任何改 B-rep 的操作都需要一个 `FACE*`/`BODY*` 入口。最小闭环：

```
api_get_faces(body, faces, PAT_NEXT_TYPE(...), nullptr)   // 枚举面
api_entity_extrema(face, ..., extrema, ...)               // 确认拿到的是哪个面
api_offset_face(face, 2.0, newbody, nullptr)              // 第一次真正改几何
```

跑到 `api_offset_face` 返回 `ok=1` 且 `newbody != nullptr`，就说明整条链路（注入 / 线程 / ABI / 组件初始化 / 实体指针）全部成立，后面只是加函数。

> **已本机跑通**：方块 `api_get_faces` 返回 6 个面，`api_offset_face` 返回新体且新体有 1 个面（单面偏置得到片体，符合 ACIS 语义）。日志见 `docs/acis-injection.md` §6。

---

生成方式：`scripts/acis_direct_survey.py`（分类）、`scripts/acis_demangle.py`（解修饰名）。
完整符号表：`out/SpaACIS.full.exports.txt`。
