# AGENTS.md — 给其他 agent 的接入说明

> **要改这个仓库的代码，先看 [docs/DEVELOPING.md](docs/DEVELOPING.md)**：代码地图、构建命令（`/MD` 硬规则）、
> 加工具的三种套路、验证回路、调试入口。本文件只讲"怎么用"。

这是一个 **MCP 服务器**，让 agent 操作 CST Studio Suite 2022：建模、求解、读结果、直接改几何。
编排全部在 `tools/cstmcp.py`（纯 Python + ctypes，无第三方依赖），不再有 PowerShell 脚本。

## 接入（三选一）

**A. stdio，共享**（客户端自己拉起进程；多个客户端共用一个所有者、一套 CST）

```json
{ "mcpServers": { "cst": {
    "command": "node",
    "args": ["C:/Projects/cst-mcp/src/server.mjs", "--stdio"] } } }
```

**A'. stdio，私有栈**（每个客户端一个新 DE + 自己的 modeler；互不干扰）

```json
{ "mcpServers": { "cst": { "command": "node",
    "args": ["C:/Projects/cst-mcp/src/server.mjs", "--stdio", "--isolated"] } } }
```

> ⚠️ **这一条尚未验证通过。** 代码路径已改为调用 `tools/cstmcp.py isolate`（原先调用的 PowerShell 脚本已删除），
> 但实测中 `isolate` 在一次运行里卡在 `DesignEnvironment.new()` 超过 150 秒，没有返回。原因待查
> （可能是新开 DE 时遇到模态对话框或实例数限制）。**目前请用 B（HTTP `up --isolated`）来获得私有栈**，
> 它已经端到端跑通。

**B. HTTP**（跨进程、远程）

```powershell
py -3.12 C:\Projects\cst-mcp\tools\cstmcp.py up --isolated
# {"pid":..., "port":8770, "url":"http://127.0.0.1:8770/mcp", "dePid":..., "modelerPid":...}
```

端口以命令输出为准（共享模式 8765，`--isolated` 从 8770 起自动挑空位）。

## 多个 agent 共用

**每个 agent 用自己的一套栈**：`up --isolated` 新开一个 Design Environment、它自己的 `modeler_AMD64.exe`，
ACIS 代理只注入到那个 modeler。进程、命名管道、VBA 历史全部独立，不排队也不互相踩。
代价：每套栈占一份 CST license，首次约 25 秒。

```powershell
py -3.12 tools\cstmcp.py up --isolated     # 私有栈 + 所有者
py -3.12 tools\cstmcp.py status            # 谁在跑；栈已死会标出来
py -3.12 tools\cstmcp.py down --with-cst   # 停所有者并关掉它自己的 DE
```

已有栈、只重启服务器（不重建 CST）：

```powershell
py -3.12 tools\cstmcp.py up --de-pid <DE> --modeler-pid <modeler>
```

## 前置条件

| 项 | 说明 |
|---|---|
| CST 2022 | 装在 `C:\Programs\CST Studio Suite 2022`（路径写死在 `bridge/cst_bridge.py`、`CONFIG.python`、`tools/cstmcp.py`） |
| Node ≥ 20 | 缺 `node_modules` 时 `up` 会自动跑 `npm install` |
| Python ≥ 3.8 | `py -3.12 tools\cstmcp.py`（只用标准库 + ctypes） |
| ACIS 代理 | **不用手动注入**：首次 `acis_connect` 自动把最新的 `native/cst_acis_agent*.dll` 注入到 modeler。注入前会等 modeler 把 SpaACIS 加载完并 settle，否则会把它弄崩 |
| CST 3D 项目 | ACIS 工具要求 `modeler_AMD64.exe` 在跑（CST 里打开一个 3D 项目） |

## 工具（15 个）

**VBA 层**（走 `cst.interface`，先 `cst_connect`）

| 工具 | 作用 |
|---|---|
| `cst_status` | 运行中的 DE、连接状态、活动项目 |
| `cst_connect` | 附着到已运行的 DE（`mode=any`/`pid`），不新开实例 |
| `cst_open_project` | 打开 `.cst` |
| `cst_vba` | 在活动项目里执行任意 VBA（万能口，也是最大风险） |
| `cst_solve` / `cst_solver_state` / `cst_abort_solver` | 求解器控制（启动异步，需轮询） |
| `cst_import_step` | 读 `.stp/.step` |
| `cst_export_sat` | 整个模型导出成 SAT（`SAT.WriteAll`） |
| `cst_local_modify` | 按面 ID 推拉（沿法向 offset / 按向量移动），CST 自动保持闭合 |

**ACIS 层**（进程内直调，需要 `modeler_AMD64.exe`）

| 工具 | 作用 |
|---|---|
| `acis_connect` | 连 `\\.\pipe\cst-acis-<pid>`，未注入时自动注入；**可重复调用** |
| `acis_block` | 用 ACIS 建长方体 |
| `acis_offset_face` | 单面偏置成新体 |
| `acis_export_sat` | 当前体写成 SAT（`which=main` 原体 / `last` 偏置结果） |
| `acis_import_sat` | 走 CST 的 `SAT.Read` 读进项目 |

## 典型流程

```
cst_connect → cst_status            确认附着到哪个项目
cst_import_step                      STEP 进模型
cst_local_modify                     推拉面
cst_solve → cst_solver_state         求解并轮询
```

ACIS → CST 的交接（已跑通）：

```
acis_connect → acis_block(10,10,10) → acis_offset_face(0,2.0)
→ acis_export_sat(which=main) → cst_connect → acis_import_sat
```

反方向（CST 模型 → ACIS 编辑）**还不是工具**：代理有 `restore`/`bbox`/`mv` 命令，但没包装成 MCP 工具，
目前只能通过管道直接下发（见 `docs/DEVELOPING.md`）。

## 已知坑

1. **`cst_vba` 等价于任意代码执行。** 只在受信环境启用；HTTP 模式建议设 `CST_MCP_TOKEN`。
2. **CST 的 VBA 错误是静默的。** `add_to_history` 永远返回成功；某个块失败后整个历史列表会停摆，
   后续调用全部空转。判断命令是否生效必须换干净项目重试。
3. **面 ID 会变。** 一次推拉后新建的面会改编号，连续操作前重新查。
4. **`MoveSelectedFaces` 沿平面自身方向平移无效**，推拉用 `OffsetSelectedFaces`。
5. **原生 DLL 必须 `/MD` 编译。** 静态 CRT（`/MT`）下任何交给 ACIS 的 `FILE*` 都会 fail-fast 崩在 `ucrtbase`。
6. **ACIS 代理 DLL 不能卸载**，重测要重启 `modeler_AMD64.exe`（换新栈最快）。
7. **不要在 modeler 刚启动时注入**，注入器已内置等待；自己写注入时也要等。
8. **不要起第二个所有者抢同一端口**；`up` 会检测并复用。

## 排障

| 现象 | 原因 / 处理 |
|---|---|
| HTTP 连不上 | 进程没了：`py -3.12 tools\cstmcp.py up`；`GET /health` 确认 |
| `status` 标 `<-- DE/modeler gone` | 栈已死但所有者还在：`down` 再 `up --isolated` |
| `acis_connect` 报找不到 modeler | CST 没开 3D 项目 |
| `acis_connect` 报 no built DLL | `native\build.bat`，或用 `py -3.12 tools\cstmcp.py up --isolated`（会注入已编译版本） |
| `cst_status` 显示 `connected:false` | 正常，先 `cst_connect` |
| 工具调用成功但模型没变 | 见坑 2，历史列表可能已停摆 |
| 注入后 modeler 消失 | 注入时机太早或 DLL 不是 `/MD`；看事件日志的 `0xC0000005` |

## 命令速查（`py -3.12 tools\cstmcp.py ...`）

| 命令 | 作用 |
|---|---|
| `status` | owner / DE / modeler / agent 对应关系，栈死活 |
| `symbols` | 校验 `native/*.h` 里全部符号能否在 SpaACIS 里解析 |
| `inject <pid> [--dll X]` | 注入代理（ctypes，无需 PowerShell） |
| `isolate` | 新开 DE + 它的 modeler + 只注入那个，打印 JSON |
| `up [--isolated] [--port N] [--de-pid D --modeler-pid M]` | 起/复用所有者 |
| `down [--with-cst]` | 停所有者，可选关掉它自己的 DE |
