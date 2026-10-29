# AGENTS.md — 给其他 agent 的接入说明

> **要改这个仓库的代码，先看 [docs/DEVELOPING.md](docs/DEVELOPING.md)**：代码地图、构建命令（`/MD` 硬规则）、
> 加工具的三种套路、验证回路、调试入口。本文件只讲"怎么用"。

这是一个 **MCP 服务器**，让 agent 操作 CST Studio Suite 2022：建模、求解、读结果、直接改几何。

## 接入（二选一）

**A. stdio（推荐，客户端自己拉起进程，不需要预先启动任何东西）**

```json
{
  "mcpServers": {
    "cst": {
      "command": "node",
      "args": ["C:/Projects/cst-mcp/src/server.mjs", "--stdio"]
    }
  }
}
```

仓库根目录的 `.mcp.json` 就是这个内容，多数客户端（Claude Code 等）会直接读取。
仓库换位置时把 `args[0]` 改成新的绝对路径。

**B. HTTP（跨进程、多客户端、远程）**

```powershell
py -3.12 C:\Projects\cst-mcp\tools\cstmcp.py up --isolated
```

```
http://127.0.0.1:8765/mcp      # 客户端配置 {"type":"http","url":"..."}
```

`tools/cstmcp.py up` 幂等；`tools/cstmcp.py down` 关闭。判断是否在跑：`GET /health` 返回 `{"ok":true,"app":"cst-mcp",...}`。

## 多个 agent 共用

**每个 agent 用自己的一套栈**：`up --isolated` 会新开一个 Design Environment、它自己的 `modeler_AMD64.exe`，
并把 ACIS 代理只注入到那个 modeler。彼此的进程、命名管道、VBA 历史全部独立，互不排队。
代价：每个栈占一份 CST license，首次启动约 25 秒。

```powershell
py -3.12 tools\cstmcp.py up --isolated     # 私有栈 + 所有者，端口自动从 8770 起
py -3.12 tools\cstmcp.py status            # 谁在跑、哪个 modeler 装了 agent
py -3.12 tools\cstmcp.py down --with-cst   # 停所有者并关掉它自己的 DE
```

已经有一个栈、只想重启服务器时，不用重建 CST：

```powershell
py -3.12 tools\cstmcp.py up --de-pid <DE-pid> --modeler-pid <modeler-pid>
```

- stdio 默认是**共享**代理（连 8765 的所有者）；要私有栈就在客户端配置里加 `--isolated`。
- 不要手动 `node src/server.mjs` 起第二个所有者抢同一端口。
## 前置条件

| 项 | 说明 |
|---|---|
| CST 2022 | 装在 `C:\Programs\CST Studio Suite 2022`（路径写死在 `bridge/cst_bridge.py` 与 `CONFIG.python`） |
| Node ≥ 20 | 已 `npm install`（`tools/cstmcp.py up` 会自动补） |
| ACIS 代理 | **不需要手动注入**：首次调用 `acis_connect` 时服务器会自动找最新的 `native/cst_acis_agent*.dll` 注入到 `modeler_AMD64.exe`（首次约 30 秒，之后秒回） |
| CST 3D 项目 | ACIS 工具要求 `modeler_AMD64.exe` 在跑（CST 里打开一个 3D 项目） |

## 工具（15 个）

**VBA 层**（走 `cst.interface`，需要先 `cst_connect`）

| 工具 | 作用 |
|---|---|
| `cst_status` | 列出运行中的 Design Environment、活动项目 |
| `cst_connect` | 附着到已运行的 DE（`mode=any` 或 `pid`），不新开实例 |
| `cst_open_project` | 打开 `.cst` |
| `cst_vba` | 在活动项目里执行任意 VBA（万能口，也是最大风险） |
| `cst_solve` / `cst_solver_state` / `cst_abort_solver` | 求解器控制（启动是异步的，要轮询状态） |
| `cst_import_step` | 读 `.stp/.step` 进项目 |
| `cst_export_sat` | 整个模型导出成 SAT |
| `cst_local_modify` | **推拉面**：按面 ID 沿法向 offset 或按向量移动，CST 自动保持闭合、可处理相邻圆角 |

**ACIS 层**（进程内直调，需要 `modeler_AMD64.exe`）

| 工具 | 作用 |
|---|---|
| `acis_connect` | 连接（未注入时自动注入） |
| `acis_block` | 用 ACIS 建长方体 |
| `acis_offset_face` | 单面偏置成新体 |
| `acis_export_sat` | 当前体写成 SAT（`which=main` 原体 / `last` 偏置结果） |
| `acis_import_sat` | 走 CST 的 `SAT.Read` 把文件读进项目 |

## 典型流程

```
cst_connect → cst_status                    确认附着到哪个项目
cst_import_step  →  STEP 进模型
cst_local_modify →  推拉某个面
cst_solve        →  cst_solver_state 轮询
```

STEP → ACIS 编辑 → 回 CST 的完整闭环：

```
cst_import_step → cst_export_sat → acis_connect → acis_export_sat? 否：
实际路径：CST 导入 STEP → cst_export_sat 导出 SAT → （注入进程内）restore → 编辑 → 导出 → acis_import_sat
```

## 已知坑（踩过，别再踩）

1. **`cst_vba` 等价于任意代码执行。** 只在受信环境启用；HTTP 模式建议设 `CST_MCP_TOKEN`。
2. **CST 的 VBA 错误是静默的。** `add_to_history` 永远返回成功，命令写错也不报错——块执行失败后整个历史列表会停摆，后面所有调用都变成空转。判断命令是否生效必须**换干净项目**重试。
3. **面 ID 会变。** 一次推拉后新建的面会改编号，连续操作要重新查。
4. **`MoveSelectedFaces` 沿平面自身方向平移无效**，推拉用 `OffsetSelectedFaces`。
5. **原生 DLL 必须 `/MD` 编译。** 用静态 CRT（`/MT`）时任何传给 ACIS 的 `FILE*` 都会让它 fail-fast 崩在 `ucrtbase`。
6. **ACIS 代理 DLL 不能卸载**，重测要重启 `modeler_AMD64.exe`。
7. **不要同时跑两个服务器占同一端口**；`tools/cstmcp.py up` 会检测并复用。

## 排障

| 现象 | 原因 / 处理 |
|---|---|
| HTTP 连不上 | 进程没了，跑 `tools/cstmcp.py up`；`GET /health` 确认 |
| `acis_connect` 报找不到 modeler | CST 没开 3D 项目 |
| `acis_connect` 报 no built DLL | `native/build.bat`（或 `py -3.12 tools\cstmcp.py isolate` 会自动注入已编译的版本） |
| `cst_status` 显示 `connected:false` | 正常，先 `cst_connect` |
| 工具调用成功但模型没变 | 见坑 2，历史列表可能已停摆 |
