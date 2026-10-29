# cst-mcp

CST Studio Suite 2022 的 MCP 服务器（Streamable HTTP）。设计取舍与"要不要注入 DLL"的分析见 [docs/architecture.md](docs/architecture.md)。

## 运行

```powershell
npm install
npm start
# [cst-mcp] listening on http://127.0.0.1:8765/mcp
```

客户端配置：

```json
{ "mcpServers": { "cst": { "type": "http", "url": "http://127.0.0.1:8765/mcp" } } }
```

带鉴权（强烈建议，`cst_vba` 等价于任意代码执行）：

```powershell
$env:CST_MCP_TOKEN = "换成一个长随机串"
npm start
# 客户端 header: Authorization: Bearer <token>
```

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

## 工具

| 工具 | 作用 |
|---|---|
| `cst_status` | 列出运行中的 DE、连接状态、活动项目 |
| `cst_connect` | 附着到已运行 DE（`any` 或 `pid`），不新开实例 |
| `cst_open_project` | 打开 `.cst` |
| `cst_vba` | 在活动项目的 history 里执行一段 VBA |
| `cst_solve` | 异步启动求解器，立即返回 |
| `cst_solver_state` | 求解器是否在跑、哪个 |
| `cst_abort_solver` | 中止 |

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
Invoke-RestMethod -Uri http://127.0.0.1:8765/mcp -Method Post -Headers $h -Body `
  '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

服务器是 stateless 模式：每个 POST 现建一个 transport，不发 `Mcp-Session-Id`，也不支持 `GET /mcp` 的 SSE 流（返回 405）。

## ACIS 模式（进程内直调）

除了 VBA 层，还有一组工具直连 `modeler_AMD64.exe` 里的 ACIS 内核，能做 VBA 表达不了的直接建模（偏置面、推壳、变半径倒圆……）。

前提：每次 CST 启动后手动注入一次代理（DLL 不能自动加载）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File native\inject.ps1 -Dll native\cst_acis_agent2.dll
```

| 工具 | 作用 |
|---|---|
| `acis_connect` | 连到 `\\.\pipe\cst-acis-<pid>`，省略 pid 自动找 modeler |
| `acis_block` | 用 ACIS 建一个长方体，返回面数 |
| `acis_offset_face` | 偏置当前体的某个面（推拉），返回新体面数 |
| `acis_export_sat` | 把体写成 `.sat`（`which=main` 原体 / `last` 偏置结果） |
| `acis_import_sat` | 走 CST 的 `SAT.Read` 把文件读进项目 |

已跑通的完整链路（全部通过 MCP 调用）：

```
acis_connect → acis_block(10,10,10) [faces=6]
→ acis_offset_face(0, 2.0) [新体 faces=1]
→ acis_export_sat(main) [2474 bytes]
→ cst_connect → acis_import_sat → 3D 视图出现方块
```

截图见 `docs/img/mcp-acis.png`。