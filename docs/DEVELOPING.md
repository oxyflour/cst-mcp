# DEVELOPING.md — 改这个仓库之前先读这里

给要**改代码**的 agent/人。只想"用"MCP 的话看 [AGENTS.md](../AGENTS.md) 就够了。

## 30 秒上手

```powershell
cd C:\Projects\cst-mcp
npm install                                  # 只改了 JS 时不需要重装
py -3.12 tools\cstmcp.py up --isolated
```

改了 `src/*.mjs` 或 `bridge/*.py` → 重启服务器即可：

```powershell
py -3.12 tools\cstmcp.py down ; py -3.12 tools\cstmcp.py up -WithCst
```

改了 `native/*.cpp` → 必须重新编译并**重启 modeler**（DLL 不能卸载，见下文）。

## 代码地图

| 文件 | 职责 | 改它的时候注意 |
|---|---|---|
| `src/server.mjs` | MCP 传输层 + 15 个工具注册 + HTTP/stdio 两个入口 | 工具只是薄壳；业务逻辑往桥/代理里放 |
| `src/acis.mjs` | 命名管道客户端、`findModelerPid()`、`satImportCode()` | 行协议：一条命令一行，回 `OK ...` / `ERR ...` |
| `bridge/cst_bridge.py` | CST 适配器，跑在 **CST 自带 python 3.6** | 只能用 3.6 语法；只 import 标准库 + `cst.*` |
| `native/cst_acis_agent.cpp` | 常驻代理（管道服务 + UI 线程调度 + ACIS 调用） | 崩溃半径是整个 CST 会话 |
| `native/acis_shim.h` | `outcome_slot`、`SPAposition`、符号常量 | 所有 ABI 假设都在这里 |
| `native/acis_direct.h` | 直接建模子集的函数指针类型 | 含回引的函数标了 `INFERRED` |
| `tools/cstmcp.py inject` | 注入器（`CreateRemoteThread(LoadLibraryW)`） | 换 DLL 名不会重跑 `DllMain`，要用新文件名 |
| `native/build.bat` | MSVC 构建 | **`/MD` 不能去掉** |
| `scripts/*.py` `tools/cstmcp.py` | 符号扫描、反汇编、ABI 探测、导入测试 | 都是只读诊断工具 |

三个入口的关系：

```
MCP client ──stdio 或 HTTP──► src/server.mjs
                               ├─ 行 JSON over stdio ─► bridge/cst_bridge.py ─► cst.interface ─► CST DE
                               └─ 命名管道 ──────────► cst_acis_agent.dll ─► ACIS ─► modeler_AMD64.exe
```

## 加一个工具的三种情形

### 1. 只是包一层已有桥方法（最常见）

`src/server.mjs` 里：

```js
server.registerTool(
  "cst_foo",
  {
    title: "…",
    description: "…告诉模型什么时候用它、有什么副作用…",
    inputSchema: { bar: z.number().default(1) },
  },
  async ({ bar }) => {
    try {
      return text(await bridge.call("foo.do", { bar }));
    } catch (err) {
      return fail(err);
    }
  },
);
```

再去 `bridge/cst_bridge.py` 加方法并登记到 `METHODS`：

```python
def m_foo_do(params):
    de = de_require()
    return {"ok": True}

METHODS = {..., "foo.do": m_foo_do}
```

返回 `dict`，异常会被包成 `{"ok": false, "error": {...}}` 传给 Node。

### 2. 要调进程内 ACIS

在 `native/cst_acis_agent.cpp` 的 `RunRequest()` 里加一条命令（行协议）：

```cpp
if (strncmp(line, "foo ", 4) == 0) { ...; Reply("OK ..."); return; }
```

- **所有 ACIS 调用必须在 UI 线程**——`RunRequest` 已经跑在主线程，别自己起线程。
- 新符号：`Res<...>(g_api.h, "?api_xxx@@...")`，先用 `py -3.12 tools/cstmcp.py symbols` 验证能解析。
- 返回体的大小/对齐见 `acis_shim.h` 的 `outcome_slot`。

然后在 `src/acis.mjs` 或 `server.mjs` 里加对应工具，发一行命令。

### 3. 要用一个还没接的 ACIS API

1. 从 `out/SpaACIS.full.exports.txt` 找修饰名（这个文件由 `scripts/pe_exports_full.py` 生成，
   注意 pefile 在 >8192 个名字时会截断）。
2. 用 `scripts/acis_demangle.py <name>` 解出原型；**回引数字是 0-based 参数下标**
   （例：`api_get_entity_box` 里的 `1` 指第 2 个参数）。
3. 语义必须查文档，不要猜。权威来源：
   - CST 自带 VBA 文档 `Online Help\mergedProjects\VBA_3D\`（对象方法，优先用）
   - ACIS 文档 `http://www-isl.ece.arizona.edu/ACIS-docs/`（R10，函数参考在 `PDF/LOP/03FN.PDF`）
4. 先在 `py -3.12 tools/cstmcp.py symbols` 加常量、确认能 `GetProcAddress`，再写调用。

## 构建

```powershell
# 必须用 x64 Native Tools 环境
& 'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat'
cd native
cl /nologo /LD /MD /O2 /EHsc /std:c++17 cst_acis_agent.cpp /Fe:cst_acis_agent13.dll `
   /link /DLL /MACHINE:X64 user32.lib
```

三条硬规则：

- **`/MD` 不能少。** 静态 CRT（`/MT`）下，任何交给 ACIS 的 `FILE*` 都会让它 fail-fast 崩在
  `ucrtbase`（`0xC0000409`，偏移 `0x11858`）。这个坑花了很久才定位。
- **改了 DLL 就换文件名**（`agent13` → `agent14`），因为已加载的模块不会重跑 `DllMain`。
  `tools/cstmcp.py up` 自动挑编号最大的那个。
- 目标进程是 `modeler_AMD64.exe`（x64），**不是** `CST DESIGN ENVIRONMENT_AMD64.exe`。

## 验证回路

改完必须按这个顺序自证，别靠"看起来对"：

```powershell
# 1. 符号层（不开 CST、不注入）
py -3.12 tools\cstmcp.py symbols

# 2. 起环境（会自动编译/注入）
py -3.12 tools\cstmcp.py up -WithCst -Build

# 3. 走 MCP 调一次
curl -s http://127.0.0.1:8765/mcp -H "content-type: application/json" `
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"acis_block","arguments":{}}}'

# 4. 量化确认几何真的变了（截图会被视图自动缩放骗）
#    代理命令：restore <sat> -> bbox
```

`bbox` 是最可靠的判据：`block 10 10 10` 后 `mv 0 0 0 5` 必须让 `hi.z` 从 10 变成 15。
VBA 侧同理——用 `SAT.WriteAll` 导出再 `restore` 量。

## 调试入口

| 位置 | 内容 |
|---|---|
| `.run/server.out.log` / `.run/server.err.log` | MCP 服务器 stdout/stderr |
| `%TEMP%\cst_acis_agent.<pid>.log` | 代理的每条管道请求和回复 |
| `%TEMP%\cst_acis_probe.<pid>.*.log` | 一次性探针的输出 |
| 事件查看器 → Windows 日志 → 应用程序 | modeler 崩溃时看故障模块和偏移 |

服务器在 stdio 模式下**不能往 stdout 写日志**（stdout 是协议通道），只能 `process.stderr.write`。

## 不变量（改代码时别破坏）

1. `outcome` 由调用方提供返回槽（`outcome_slot`，256 B、16 字节对齐），用完必须调 `??1outcome`。
2. `ENTITY_LIST` 不要自己算布局，用它的导出成员（`??0`/`?count@`/`??A`/`??1`）。
3. **只能有一个所有者进程驱动 CST**。stdio 模式是代理（转发到 8765 的所有者），不要新增第二个所有者；`bridge` 有队列，管道服务一次处理一条。
4. 桥跑在 Python 3.6（CST 自带），不要引第三方包，不要用 3.7+ 语法。
5. `cst_vba` 是任意代码执行口，新增工具不要隐含放大它。
6. 工具描述是给模型看的：写清前置条件、副作用、单位。

## 已知缺陷 / 下一步

- `api_tweak_faces`（ACIS）尚未接：它要求调用方构造目标 `SURFACE*` 数组，不是"移动面"。
  推拉用 CST 的 `cst_local_modify`，或 ACIS 的 `api_move_faces`（代理 `mv`，已跑通）。
- `acis_*` 工具面还窄，只有建块/偏置/导出。`docs/acis-direct-modeling.md` 有清单和签名线索。
- 服务器没有自动重连：CST 重启后 `modeler` pid 变了，需要重新 `acis_connect`（会重新发现 pid）。
- `models/*.sat` 是测试数据，不入库。
