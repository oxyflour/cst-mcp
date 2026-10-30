# PLAN — 从 `models/cnc-bottom.sat` 反求特征树并重建（路线 B）

> 状态（2026-10-30）：**已按自研路线跑完一轮，结果见 [docs/feature-tree-cnc-bottom.md](docs/feature-tree-cnc-bottom.md)。**
> 特征树与整体重建可用（CST 重建体积 −0.55%）；圆角/倒角重放成功率约 1/4，拔模可重放但大多去不掉。
> 下文是开工前的计划，保留作背景；S3 之后的实际做法以报告为准。
>
> 旧状态（2026-10-29）：S3 小件自测已跑，Defeature 无授权（`errno=5000 UNAUTHORIZED_FUNCTIONALITY`，见 §1.5）。
> 本文只写可执行的东西：已证实的事实、已有资产、逐步验收。

---

## 0. 目标与完成判据

**输入**：`models/cnc-bottom.sat`（8 459 349 B，SAT 头 `3100 0 1 0`，注释行 `ACIS 31.0.1 NT 24`，1 个 body）

**目标**：把一个无历史的 BRep 拆成"基体 + 特征序列"，并能在 ACIS 里按这个序列重建出来，得到可编辑的特征树（JSON），而不是一堆孤立的面。

**完成判据**（缺一不可，都要量化）：

| 判据 | 阈值 | 怎么量 |
|---|---|---|
| 识别覆盖 | 识别出的特征面占"可分类面"的 ≥ 90% | `dft` 报告的面数 / body 面数 |
| 去除可行性 | 每个特征 `remove` 成功，或明确记为 failed | 二次 `dft`（关闭 pause）后的 `get_num_failed_features` |
| 几何等价 | 重建体与原体体积差 < 0.1%，质心偏差 < 0.01 mm | `api_body_mass_props` |
| 拓扑等价 | 面数差 ≤ 5%，无自由边 | `api_get_faces` + 自由边扫描 |
| 可编辑 | 每个特征的参数能从几何反求出来（孔径/深度/半径/方向） | 特征 JSON 里无 `null` 参数 |

---

## 1. 已证实的事实（都是本机实测，不是推测）

### 1.1 独立宿主不可行 —— 授权绑 CST 进程

自己 `LoadLibrary` 加载 `ACIS\NT_VC15_64_DLL\code\bin\SpaACIS.dll`（20211.0.1.21112）后：

```
api_start_modeller(0)      -> ok=1 errno=0
api_get_default_history    -> ok=0 errno=5000
api_save_entity_list(空表)  -> ok=0 errno=5000
api_solid_block            -> ok=0 errno=5000
```

装完 `api_initialize_kernel / constructors / booleans / query / generic_attributes /
persistent_id / blending / healing / local_ops` 九个组件后仍然全部 `errno=5000`。
→ **结论：ACIS 只能跑在 CST 的 `modeler_AMD64.exe` 里**（和 `docs/acis-injection.md` §4 一致）。

### 1.2 `modeler_AMD64.exe` 不能直接起

直接 `Start-Process` 会弹 "找不到 SpaACIS.dll" —— 它按 PATH 找 DLL，只有 CST 启动器才把
`ACIS\...\code\bin` 加进去。而且那个进程是非管理员 `OpenProcess` 拿不到的（error 5）。
→ **结论：不要自己起 CST 组件；走 `py -3.12 tools\cstmcp.py up --isolated` 这一条路。**

### 1.3 运行时符号已经核对过（按导出表，不是文档）

| DLL | 数量 | 与本任务相关的导出 |
|---|---|---|
| `SpaACIS.dll` | 50 832 | `api_detect_protrusion` / `api_detect_depression` / `api_detect_blends` / `api_detect_chamfers`；`api_note_state` / `api_get_default_history` / `api_change_to_state`；`api_remove_face` / `api_simplify_body` |
| `SPADefeature.dll` | 2 781 | `api_find_and_remove_features`（`BODY*` 与 `ENTITY_LIST&` 两个重载）、`api_initialize_defeature`、`defeature_options` 全套（`set_recognize_holes/chamfers/blends`、`set_pause_after_recognize`、`keep_face`、`get_num_features`、`get_feature`、`get_num_failed_features`、`get_failed_feature`） |

**没有** `api_polyhedral_make_segmented_body` → CGM Polyhedra 的网格分割这条路在这台机器上不存在。

### 1.4 文档给出的边界（`C:\Projects\2017_acisiop_docs`）

- Defeature 只认 **孔 / 倒角 / 圆角**（含变半径、blend chain）；`pause_after_recognize` 可只识别不删除。
- Feature Detection 只给"连通的凸台/凹槽面集"，**明确不分类**，分类留给应用。
- 没有任何 API 输出"这个槽是哪张草图拉出来的"——参数、顺序、父子依赖都得自己反求。
- 混合凸凹、被分割的圆角面、非流形体会识别/去除失败。

### 1.5 Defeature 在 CST 进程里也没有授权（2026-10-29 实测）

私有栈（`up --isolated`，agent15）里，在 CST 导出的 40×30×10 方块 + 两个通孔（8 面，`out/dft_holes_only.sat`）上：

```
api_initialize_defeature            -> ok=1 errno=0
dft ... holes                       -> ERR api_find_and_remove_features errno=5000
dft ... all                         -> ERR 同上
errmsg 5000                         -> UNAUTHORIZED_FUNCTIONALITY: Not authorized to use this functionality
```

同一进程里 `api_solid_block` / `api_restore_entity_list` 正常 → CST 的 ACIS 授权只放行它自己用的组件，
**SPADefeature 不在其中**。→ 风险 1 成立，S3 改走自研识别（见 §3 S3'）。

### 1.7 Feature Detection（`api_detect_*`）**有授权**（2026-10-29 实测，agent16 `detect` 命令）

测试件 `out/detect_test.sat`：40×30×10 方块 + 2 通孔 + 1 条 R2 圆角（倒角那步在 CST 里静默失败，共 9 面）。
`detect <kind> <face>` 对 9 个面逐个种子：

| 调用（种子 = 第 i 个面，`api_get_faces` 顺序） | 结果（成功面数 / 9） | 返回的面集 |
|---|---|---|
| `api_detect_blends` | 1 / 9（只有面 0） | `[0]`：面 0 就是那条圆角，识别对了 |
| `api_detect_chamfers` | 0 / 9，全部 `59000 API_FAILED` | 件上没有倒角，**授权已放行但识别能力未验证** |
| `api_detect_depression` | 9 / 9 | 多数只返回种子面本身；面 2、5（圆角两侧的面）返回 `[种子, 0]` |
| `api_detect_protrusion` | 9 / 9 | 每次都返回全部 9 面，在这个件上没有区分度 |
| `depression/protrusion` 以 BODY 为种子 | 失败，`59000` | 种子必须是面 |

没有一次 `5000` → **Feature Detection 组件已授权**。含义：
- 圆角可以直接用 `api_detect_blends` 识别，不用自己写判据；
- 倒角要再做一个真有倒角的件验证（CST 里 `ChamferEdge` 的 faceID 参数要换，或直接用 ACIS 建）；
- 孔、凸台、凹槽靠 `dep/prot` 的面集还不够：通孔只返回 1 个面，和普通平面没法区分 → 仍要加面几何类型（圆柱/圆锥 + 凹凸）判断。
- `elemType` 参数（`blend_element_type` / `chamfer_element_type` 枚举）目前固定传 0，其他值未试。

### 1.6 代理之前的错误检查全部是空的（已修，agent14 起）

`cst_acis_agent.cpp` 里所有调用都写成 `ZeroMemory(&oc); g_api.f(...); Outcome(oc)`：返回的 `outcome`
被丢弃，检查的是全零的 slot，`ok()` 恒为 1、`errno` 恒为 0。改成 `oc = g_api.f(...)`（26 处）。
修之前 `dft` 会把 5000 报成 `OK features=0`。**agent13 及更早版本报的 `OK` 都不可信。**

---

## 2. 仓库里已经有的东西

| 文件 | 状态 | 说明 |
|---|---|---|
| `native/cst_acis_agent.cpp` | **已改，已编译** | `dft <report.tsv> [all\|holes]`：载 `SPADefeature.dll` → `pause_after_recognize=1` → 只识别不删除 → 逐特征写 `index/type/faces/bbox`。新增 `errmsg <n>`（`find_err_ident/find_err_mess`），`dft` 失败时回带错误名。outcome 检查已修（§1.6）。 |
| `native/cst_acis_agent16.dll` | 当前版本 | 新增 `detect <dep\|prot\|blend\|chamfer> <faceIndex> [elemType]`，回复面集在 `api_get_faces` 里的下标。`up` 自动挑编号最大的注入；13–15 已过时 |
| `out/detect_test.sat` | 测试件 | 方块 + 2 通孔 + 1 圆角（9 面），§1.7 用 |
| `native/probe_dft.cpp` | 保留 | 独立宿主版的同一套识别/导出逻辑；作为"如果哪天有 license 就能离线跑"的参考实现 |
| `native/probe_sat/diag/rt.*`（`.cpp/.exe/.obj`）、`native/probe_dft.exe/.obj`、`native/try_modeler*.ps1`、`native/cst_acis_agent_dft.dll`（名字不带编号，永远不会被注入）、`scripts/bootstrap_de.py`、`out/open_mws.py`、`out/de_boot.log*` | **一次性诊断，待删** | 结论已经写进 §1，不必留 |
| `out/dft_holes_only.sat` | 测试件 | S3 自测用的小件（方块 + 2 通孔，8 面） |

---

## 3. 执行步骤（S3 之前不动 CST）

### S1 环境（只用 `cstmcp.py`，不手起 CST）✅
```powershell
cd C:\Projects\cst-mcp
py -3.12 tools\cstmcp.py up --isolated   # 私有 DE + modeler + 注入最新 agent，打印 JSON
py -3.12 tools\cstmcp.py status          # 核对
```
验收：输出里 `modelerPid` 非空、`agent` 是编号最大的那个。代理管道是 `\\.\pipe\cst-acis-<modelerPid>`，一行一条命令。
收尾：`py -3.12 tools\cstmcp.py down --port <port> --with-cst`（只停自己那套）。

### S2 基线（先量原模型，后面靠它判等价）
```
restore C:\Projects\cst-mcp\models\cnc-bottom.sat
faces
bbox
```
验收：`entities ≥ 1`、`body` 非空、`faces` 有数（预期数千）、`bbox` 与 SAT 头里的
`-43.12 -79.37 -3.56 → 43.12 -59.13 3.94` 一致。**这一步只读，不改几何。**

### S3 识别（两次，用来解枚举）
```
dft C:\Projects\cst-mcp\out\cnc_features_holes.tsv holes
dft C:\Projects\cst-mcp\out\cnc_features_all.tsv  all
```
验收：两次都返回 `OK features=N ...`；`holes` 那次只出现一个 `type` 值 → 该值就是 hole；
`all` 的 `type0/1/2` 分布与 `holes` 对照即可确定 `chamfer/blend` 的编号。耗时记进报告。

**结果：❌ 小件上两次都是 `errno=5000 UNAUTHORIZED_FUNCTIONALITY`（§1.5）。没有上 `cnc-bottom.sat`。**

### S3' 识别：Feature Detection + 自研补齐（替代 S3）
已授权的 `api_detect_*`（§1.7）加基础 API（`api_get_faces`、面几何类型、`api_entity_extrema`、`api_body_mass_props`）：
- 圆角：`api_detect_blends` 逐面种子，返回面集即一条圆角链（已在小件上验证）；
- 倒角：`api_detect_chamfers`，待用真有倒角的件验证；
- 孔：圆柱/圆锥面，按轴线聚类，凹（法向朝轴）判为孔；`dep` 面集只作辅助；
- 凸台/凹槽：`dep/prot` 面集 + 法向聚类，`prot` 在简单件上返回整个体，需在 `cnc-bottom.sat` 上看实际表现。
下一步先加一个 `facetype <i>` 命令（面几何类型 + 包络），否则面编号无法对应到几何。

### S4 参数反求（新代码，走 `acis_direct.h` 的子集）
- 孔：`FACE` 类型判 `face_cone/face_cylinder/face_torus`，取轴 + 半径 + 深度（`api_entity_extrema` 给轴向包络）。
- 圆角：环面主半径 = 圆角半径；`blend` 面集的首尾面确定起止边。
- 倒角：两侧支撑面夹角 + 宽度。
- 凸台/凹槽：`api_detect_depression` / `api_detect_protrusion` 用种子面拿面集，再用面法向聚类出拉伸方向和轮廓。

验收：每个特征至少 `type + 主轴 + 主尺寸` 三个量，且量纲和 SAT 一致（SAT 是 mm）。

### S5 排序
启发式：`基体 → 大切除（depression/protrusion）→ 孔 → 倒角 → 圆角`；同层按体积降序。
验收：每个特征有 `parents[]`，无环。

### S6 重建（独立 scratch 工程里做，不碰用户工程）
`api_solid_block` / `api_extrude` / `api_boolean(subtract)` / `api_blend_edges` / `api_chamfer_edges`
按 S5 的顺序重放；失败的特征记 `failed[]` 并继续。

### S7 比对
体积、质心、面数、最大偏差（体素或采样点距离）。不达标就回到 S4 调参数，而不是调顺序。

### S8 产出
- `out/cnc_features.tsv`（S3 原始）
- `out/cnc_feature_tree.json`（特征树，含参数与依赖）
- `out/cnc_rebuild.sat`（重建体）
- `out/cnc_compare.md`（S7 指标）

---

## 4. 命令面（MCP 工具，待加）

| 工具 | 参数 | 作用 |
|---|---|---|
| `acis_restore` | `path` | 已有能力，包一层（现在只有管道命令） |
| `acis_features` | `sat`, `mode=holes\|all`, `out` | 跑 `dft`，返回特征数/分布/报告路径 |

只做薄壳：业务逻辑留在代理和 `src/acis.mjs`，符合 `DEVELOPING.md` 的分层。

---

## 5. 风险（按会不会让计划失败排序）

1. **Defeature 授权**：`SPADefeature.dll` 在位 ≠ 有 license。S3 第一次调用就能看出（返回非 0 errno 即放行不了）。放行不了就退到"自己写孔/圆角识别"（面类型 + 轴线聚类 + 凸凹判据），工作量约 ×3。
2. **`dft` 首次运行是否会崩**：识别大模型在 UI 线程跑，崩了会带走整个 modeler。**先拿一个小模型试**（`api_solid_block` 挖两个孔再识别），不要直接上 8.4 MB 的件。
3. **枚举顺序未知**：上面 S3 用两次运行对照解决，不要写死 `type==0 是孔`。
4. **识别耗时长**：8.4 MB / 数千面，可能几分钟。代理超时已放宽到 900 s；`ExecOnUiThread` 阻塞期间 CST 是卡住的。
5. **顺序不可观测**：布尔可交换，重建顺序是启发式，不保证和原设计一致——判据只认几何等价。
6. **自由曲面不覆盖**：CNC 件如果主体是扫掠/放样面，特征级重建做不出来，只能到面级分割（而 CGM Polyhedra 这台机器没装）。

---

## 6. 明确不做

- 不动用户已有工程、不动 VBA 历史列表（`DEVELOPING.md` 坑 2）。
- 不往项目里留临时体：识别阶段 `pause_after_recognize=1`，几何本来就不变；重建在 scratch 工程里做，做完关掉。
- 不删 `models/cnc-bottom.sat`（`DEVELOPING.md`：`models/*.sat` 是测试数据，不入库）。

---

## 7. 环境残留（需要收尾）

| 残留 | 建议 |
|---|---|
| 私有栈 `:8771`（DE 68152 / modeler 57984 / agent16） | 用完 `down --port 8771 --with-cst` |
| `:8765`、`:8770` 两个 owner（`status` 标 DE/modeler gone） | 不确定是否有别的会话在用，没动；确认无人用后 `down --port <p>` |
| `%TEMP%\cst_acis_agent.<pid>.log` | 代理日志，出问题先看这个 |
| 上表 §2 的一次性诊断文件 | 直接删 |

---

## 8. 下一次开工的第一条命令

```powershell
cd C:\Projects\cst-mcp
py -3.12 tools\cstmcp.py up --isolated
# 代理管道里：restore C:\Projects\cst-mcp\out\detect_test.sat → 加 facetype 后对照 detect 结果 → 做倒角件验证 → 再上 cnc-bottom.sat
```
