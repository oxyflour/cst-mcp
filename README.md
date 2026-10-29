# cst-mcp

CST Studio Suite 2022 的 MCP 服务器（Streamable HTTP）。设计取舍与"要不要注入 DLL"的分析见 [docs/architecture.md](docs/architecture.md)。

## 给其他 agent 用

客户端配置（仓库里的 `.mcp.json` 就是这段），**客户端启动时自己拉起进程，不需要预先开任何东西**：

```json
{ "mcpServers": { "cst": { "type": "stdio", "command": "node", "args": ["C:/Projects/cst-mcp/src/server.mjs", "--stdio"] } } }
```

ACIS 代理也不用手动注入：第一次调 `acis_connect` 时，服务器自己找最新的 `native/cst_acis_agent*.dll` 注入到 `modeler_AMD64.exe`。

完整接入说明、工具清单、已知坑见 [AGENTS.md](AGENTS.md)。

## 快速启动（HTTP 模式）

**一条命令**，开服务器 + 开 CST + 注入 ACIS 代理：

```powershell
py -3.12 tools\cstmcp.py up --isolated
```

输出：

```
server started: pid 91380
opening a CST project...
agent injected: cst_acis_agent12.dll -> modeler 39412

MCP endpoint : http://127.0.0.1:8765/mcp
```

| 命令 | 作用 |
|---|---|
| `py -3.12 tools\cstmcp.py up` | 只开 MCP 服务器（VBA 层工具可用，ACIS 工具会报"未连接代理"） |
| `py -3.12 tools\cstmcp.py up -WithCst` | 再打开 CST + 新项目 + 注入 ACIS 代理 |
| `py -3.12 tools\cstmcp.py up -WithCst -Build` | 若代理 DLL 还没编译，先编再注 |
| `py -3.12 tools\cstmcp.py up -Port 8766` | 换端口 |
| `py -3.12 tools\cstmcp.py down` | 停服务器 |
| `py -3.12 tools\cstmcp.py down --with-cst` | 连 CST 一起关 |

脚本是幂等的：服务器已在跑就直接复用，不会起第二个。

客户端配置：

```json
{ "mcpServers": { "cst": { "type": "http", "url": "http://127.0.0.1:8765/mcp" } } }
```

带鉴权（强烈建议，`cst_vba` 等价于任意代码执行）：

```powershell
$env:CST_MCP_TOKEN = "换成一个长随机串"
py -3.12 tools\cstmcp.py up --isolated
# 客户端 header: Authorization: Bearer <token>
```

> **换了会话用不了，通常是服务器进程没了。** MCP 是常驻进程，关掉终端/重启机器后要重新 `tools/cstmcp.py up`。
> 判断方法：`curl http://127.0.0.1:8765/health`，返回 `{"ok":true,...}` 才是在跑。

## 先验证能不能附着

开一个 CST、打开一个项目，然后：

```powershell
& "C:\Programs\CST Studio Suite 2022\AMD64\python\python.exe" scripts\probe_cst.py
```

必须用 CST **自带**的 python 3.6，因为 `_cst_interface.pyd` 只有 cp36..cp39 的构建。

## 结构

```
src/server.mjs        MCP server：传输层 + 7 个工具，不含任何 CST 细节
bridge/cst_bridge.py  CST 适配器：跑在自带 python 上，包一层 cst.interface
scripts/probe_cst.py  attach 诊断（不占 license）
docs/architecture.md  为什么这么分层、注入方案怎么施工
```

```
MCP client --HTTP--> server.mjs --stdin/stdout JSON--> cst_bridge.py --> CST DE
```

## 工具（15 个）

**VBA 层**（`cst.interface`，先 `cst_connect`）

| 工具 | 作用 |
|---|---|
| `cst_status` | 列出运行中的 DE、连接状态、活动项目 |
| `cst_connect` | 附着到已运行 DE（`any` 或 `pid`），不新开实例 |
| `cst_open_project` | 打开 `.cst` |
| `cst_vba` | 在活动项目的 history 里执行一段 VBA |
| `cst_solve` / `cst_solver_state` / `cst_abort_solver` | 求解器控制（启动是异步的，要轮询） |
| `cst_import_step` | 读 `.stp/.step` |
| `cst_export_sat` | 整个模型导出成 SAT |
| `cst_local_modify` | 按面 ID 推拉（沿法向 offset / 按向量移动），CST 自动保持闭合 |

**ACIS 层**（进程内直调，需要 `modeler_AMD64.exe`）

| 工具 | 作用 |
|---|---|
| `acis_connect` | 连到 `\\.\pipe\cst-acis-<pid>`，未注入时**自动注入**；可重复调用 |
| `acis_block` | 用 ACIS 建长方体 |
| `acis_offset_face` | 偏置当前体的某个面，返回新体面数 |
| `acis_export_sat` | 把体写成 `.sat`（`which=main` 原体 / `last` 偏置结果） |
| `acis_import_sat` | 走 CST 的 `SAT.Read` 把文件读进项目 |

桥里另有备用方法（`history.rebuild`、`solver.run`、`results.tree`、`project.activate`），需要时加一层 tool 包装即可。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `CST_MCP_HOST` | `127.0.0.1` | **不要改成 0.0.0.0** |
| `CST_MCP_PORT` | `8765` | |
| `CST_MCP_TOKEN` | 空 | 设置后要求 `Authorization: Bearer` |
| `CST_PYTHON` | CST 自带 python 3.6 | 适配器解释器 |
| `CST_CALL_TIMEOUT_MS` | `600000` | 单次桥调用超时 |

## 手工验证

```powershell
$h = @{ 'content-type'='application/json'; 'accept'='application/json, text/event-stream' }
# 列工具
Invoke-RestMethod -Uri http://127.0.0.1:8765/mcp -Method Post -Headers $h -Body `
  '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
# 调一次（把 name/arguments 换掉即可）
Invoke-RestMethod -Uri http://127.0.0.1:8765/mcp -Method Post -Headers $h -Body `
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"cst_status","arguments":{}}}'
```

服务器是 stateless 模式：每个 POST 现建一个 transport，不发 `Mcp-Session-Id`，也不支持 `GET /mcp` 的 SSE 流（返回 405）。

## 多 agent 共存

每个 agent 用自己的一套栈，互不干扰：

```powershell
py -3.12 tools\cstmcp.py up --isolated     # 新 DE + 它的 modeler + 只注入到那个 modeler
py -3.12 tools\cstmcp.py status            # DE/modeler/agent 的对应关系
py -3.12 tools\cstmcp.py down --with-cst   # 停所有者并关掉它自己的 DE
```

隔离是**进程级**的：不同 agent 的 DE、modeler、命名管道、VBA 历史全部分开，不会排队也不会互相踩。
代价是每套栈占一份 CST license，首次启动约 25 秒。

复用已有栈（只重启服务器）：

```powershell
py -3.12 tools\cstmcp.py up --de-pid <DE-pid> --modeler-pid <modeler-pid>
```

stdio 默认连共享所有者（8765）；要私有栈在客户端 args 里加 `--isolated`。
## ACIS 模式（进程内直调）

除了 VBA 层，还有一组工具直连 `modeler_AMD64.exe` 里的 ACIS 内核，能做 VBA 表达不了的直接建模（偏置面、推壳、变半径倒圆……）。

代理**不需要手动注入**：第一次调 `acis_connect` 时，服务器会挑编号最大的 `native/cst_acis_agent*.dll` 注入到 modeler（首次约 30 秒，含注入等待）。

已跑通的完整链路（全部通过 MCP 调用）：

```
acis_connect → acis_block(10,10,10) [faces=6]
→ acis_offset_face(0, 2.0) [新体 faces=1]
→ acis_export_sat(main) [2474 bytes]
→ cst_connect → acis_import_sat → 3D 视图出现方块
```

截图见 `docs/img/mcp-acis.png`。