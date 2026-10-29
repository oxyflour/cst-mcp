# CST Studio Suite 2022 的 MCP：架构建议

> 结论先行：**不要为了"能控制 CST"去注入 DLL，也不要试图把 Node 塞进 CST 进程。**
> CST 2022 已经自带两条官方自动化通道（COM 和随安装包分发的 Python 库），其中 Python 库支持**附着到你已经打开的 GUI 会话**。
> 推荐做法是：Node 进程做 MCP/HTTP 层，Python 适配器做 CST 层，两者用行分隔 JSON 通信；注入只在"自动化对象模型够不着的 UI 级需求"上才有意义，且那时 DLL 也只做代理，Node 仍在进程外。

本文所有"事实"都标注了来源：`[实测]` 表示本机跑过，`[注册表]`/`[安装目录]` 表示从文件系统或注册表读出，`[文档]` 表示来自 CST 自带帮助，`[待验证]` 表示尚未验证、需要你确认。

---

## 1. 先厘清问题

"注入 DLL 开一个 Node HTTP MCP 服务器"这个方案里，其实混了三件互不相关的事：

| 需求 | 真正的技术问题 | 注入能解决吗 |
|---|---|---|
| LLM 能驱动 CST 建模/求解/取结果 | **用什么接口操作 CST 对象模型** | 不能，答案在 COM/VBA/Python |
| 服务器要能附着到用户已打开的会话 | 跨进程附着 | 能，但 `cst.interface` 已经能做 |
| 要一个 HTTP MCP 端点 | MCP 传输层怎么写 | 完全无关，独立进程即可 |

注入解决的是"进入进程"，而 MCP 需要的是"操作 CST 的对象模型"。进入进程之后你**依然**只有那套 COM/VBA 对象模型可用——CST 没有公开 C++ SDK/ABI，也没有公开的进程内插件接口（`Plugins\` 下只有 Filter2D 独立程序和 SolidWorks 加载项，不是 CST 的进程内扩展点）。也就是说：注入带来的能力增量 ≈ 0，带来的工程风险却很大（见 §5）。

唯一真实且无法替代的收益是：**附着到那个已经打开的 GUI 进程本身**——省一份 license、不打断用户现场、能碰 UI（截图、对话框、进度条）。而这第一项，CST 自带的 Python 库已经提供了。

---

## 2. 本机事实核对

### 2.1 COM 自动化服务器（已注册）

```
HKLM\SOFTWARE\Classes\CSTStudio.Application\CLSID = {8EBCF4DB-32F7-4228-9EBD-5D080CB4D6DF}
  \CLSID\{8EBCF4DB-...}\LocalServer32 = "C:\Programs\CST Studio Suite 2022\AMD64\CST DESIGN ENVIRONMENT_AMD64.exe" -activex
  \CLSID\{8EBCF4DB-...}\ProgID        = CST DESIGN ENVIRONMENT_AMD64.Application.2022
  \CLSID\{8EBCF4DB-...}\TypeLib       = {EDD3E836-F537-4C6F-BE7D-6014C155CC7B}
```
`[注册表]`

含义：这是个 **out-of-proc 的 LocalServer32**，客户端 `CreateObject("CSTStudio.Application")` 会让 SCM 拉起一个新的 DE 进程（带 `-activex`），占用一份 license。当前没有 DE 运行时 `GetActiveObject` 返回 `MK_E_UNAVAILABLE` `[实测]`，符合预期。

> `[待验证]` 已有一个 `-activex` 实例在跑时，`GetActiveObject` 能否拿到它；以及一个**用户手动启动**（无 `-activex`）的 GUI 是否在 ROT 里。这决定了"COM 能否附着手开会话"。

### 2.2 CST 自带 Python 运行时与库（关键资产）

```
AMD64\python\python.exe                       Python 3.6.0                 [实测]
AMD64\python_cst_libraries\cst\                cst.interface / cst.results  [安装目录]
AMD64\_cst_interface.cp36-win_amd64.pyd        cp36..cp39 四个版本           [安装目录]
AMD64\python\Lib\site-packages\python_cst_libraries.pth
```
用自带解释器实测：

```
$ "C:\Programs\CST Studio Suite 2022\AMD64\python\python.exe" -c "import cst.interface as i; print(i.running_design_environments())"
[]
```
`[实测]` —— 库可用，且能在**没有 DE** 的情况下枚举运行中的 DE。

### 2.3 `cst.interface` 的能力面（这就是你的 API）

`[文档]`（`Online Help\Python\source\cst.interface.html`）：

| 对象 | 方法 | 用途 |
|---|---|---|
| `DesignEnvironment` | `connect_to_any()`, `connect(pid)`, `connect_to_any_or_new()`, `new(options=...)` | 附着到已运行 DE / 新开 DE |
| | `active_project()`, `get_open_projects()`, `list_open_projects()`, `has_active_project()` | 项目枚举 |
| | `set_quiet_mode(True)` | 抑制消息框（脚本化必备） |
| `Project` | `filename()`, `folder()`, `activate()`, `close()` | 项目生命周期 |
| | `.modeler` / `.schematic` / `.pcbs` | 各应用接口 |
| `Modeler` | **`add_to_history(header, vba_code, timeout)`** | 执行任意 VBA —— 万能入口 |
| | `run_solver()`, `start_solver()`, `abort_solver()`, `is_solver_running()`, `get_active_solver_name()` | 求解控制 |
| | `full_history_rebuild(timeout)` | 历史重建 |
| `Schematic` | `execute_vba_code(vba_code)` | 原理图侧执行 |
| `cst.results` | `ProjectFile(path, allow_interactive=...)` | **不占 license** 直接读盘上的 0D/1D 结果 |

底层是 `CST::Bus` 的 **TCP + JSON** 私有协议（`_cst_interface.pyd` 里有 `TCPClientSocket`、`CST::Bus::CommunicationCodec::messageToWire`、`GetExternalBusAddress` 等符号）`[实测字符串]`。**不要去逆向这个协议**——用现成的 `cst` 包就行。

### 2.4 进程与环境

- GUI 主进程：`AMD64\CST DESIGN ENVIRONMENT_AMD64.exe`，19.9 MB，x64 Qt 应用（存在 `platforms\`、`styles\`、`imageformats\` 插件目录与 `coin4a.dll`），版本 2022.4.0.0 `[实测]`。
- 根目录 `CST DESIGN ENVIRONMENT.exe` 是 186 KB 的启动器 `[实测]`。
- 本机有 Node 24.14 / pnpm 10.32 / Python 3.12（`C:\Python312`），**没有 MSVC、Windows SDK、cmake** `[实测]` → 现在这条路连编译都过不去。

---

## 3. 三条路线

| | A 外挂式（推荐） | B 混合式 | C 全内嵌 |
|---|---|---|---|
| 形态 | Node MCP ⇄ Python 适配器 ⇄ CST | 注入薄 DLL ⇄ 管道 ⇄ Node MCP | DLL 里跑 Node |
| 能附着手开 GUI | ✅ `connect_to_any` | ✅ | ✅ |
| 需要 MSVC | ❌ | ✅ | ✅✅（还要自己 build Node） |
| AV/EDR 风险 | 无 | 高 | 高 |
| 崩溃半径 | 只挂自己的进程 | 用户整个 CST 会话 | 同 B |
| 版本耦合 | 低（官方 API） | 中（COM/UI 细节） | 高 |
| 工作量 | 1–2 天出可用版 | 1–2 周且不稳 | 基本不可行 |
| 能碰 UI/对话框 | ❌ | ✅ | ✅ |

### 方案 A：Node + Python 适配器（推荐）

```
┌──────────────┐   HTTP/JSON-RPC    ┌─────────────────┐  行分隔 JSON   ┌──────────────────┐
│ MCP client   │ ─────────────────► │ Node cst-mcp    │ ─────────────► │ cst_bridge.py    │
│ (LLM host)   │   POST /mcp        │ StreamableHTTP  │   stdin/stdout │ (CST python 3.6) │
└──────────────┘                    └─────────────────┘                └────────┬─────────┘
                                                                                │ cst.interface / COM
                                                                       ┌────────▼─────────┐
                                                                       │ CST DESIGN ENV   │
                                                                       │ (已打开的 GUI)    │
                                                                       └──────────────────┘
```

**为什么 Node 和 Python 分居两侧而不是二选一：**
- CST 侧只有 Python 包能"附着已运行实例 + 暴露完整对象模型 + 官方维护"，这是硬约束；
- Node 侧是 MCP SDK 最成熟、HTTP 传输/鉴权/工具编排最省事的地方，也是你团队的技术栈；
- 中间只是一个 stdio 管道，延迟亚毫秒，不是瓶颈。

**已在本仓库实现并跑通骨架**（见 §7 实测记录）：

```
src/server.mjs          MCP server（Streamable HTTP，stateless，7 个工具）
bridge/cst_bridge.py    CST 适配器（跑在 CST 自带 python 3.6 上）
scripts/probe_cst.py    attach 诊断脚本，不占 license
docs/architecture.md    本文
```

**关键工程点：**

1. **串行化**：CST 是单会话，所有调用必须排队（`Bridge.#chain`）。并发调用会互相打断 VBA 执行。
2. **长任务不阻塞**：`cst_solve` 只调 `start_solver()` 立刻返回，客户端轮询 `cst_solver_state`。把 `run_solver()` 放进 tool call 会撞上 60s 的客户端超时。
3. **静默模式**：连接后第一件事 `set_quiet_mode(True)`，否则任何消息框都会把服务卡死（对话框无法被脚本关闭）。
4. **结果读取走免 license 通道**：`cst.results.ProjectFile` 直接读盘，求解器还在写的时候不要读。
5. **安全**：`cst_vba` 等价于在用户机器上执行任意代码。默认只绑 `127.0.0.1`，加 `CST_MCP_TOKEN` Bearer 校验，记录每次 VBA 的完整文本。

### 方案 B：注入薄代理 DLL + 进程外 Node

只有在需要 UI 级能力时才做：接管模态对话框、读取 3D 视图像素、监听求解进度窗口、绕过某个自动化 API 的缺陷。

核心原则：**DLL 里只放代理，不放 Node**（理由见 §6）。DLL 提供 `\\.\pipe\cst-mcp-<pid>`，Node 进程连它——和方案 A 的 Node 侧代码几乎一样，只把"spawn python"换成"net.connect pipe"。

施工要点见 §5。

### 方案 C：DLL 里跑 Node

不可行/成本极高，见 §6。

---

## 4. 工具面怎么切

不要一上来就给 LLM 一个 `run_anything`。两层：

**第一层：结构化小工具**（模型能稳定调用、能校验、能回滚）
- `cst_status` / `cst_connect`：会话状态与附着
- `cst_open_project`：项目
- `cst_solver`（start/state/abort）
- `cst_export`（Touchstone/CSV，内部走 VBA `ASCIIExport`）
- `cst_screenshot`（方案 B 才有价值）

**第二层：`cst_vba` 逃生口**
- 真正的建模能力全在这里（`Brick`/`Cylinder`/`Material`/`Port`/`Monitor`/`Solver`/`ResultTemplate` 都是 VBA 对象，见 `Online Help\vba\`）。
- 约定：每次调用写成一个独立的 history block（header 用 `mcp:<task>`），失败时可以用 `history.rebuild` 回到干净状态。
- 提示词里明确要求"先生成 VBA 草稿，确认后再执行"——这是唯一能防住 LLM 把项目改烂的地方。

**上下文预算**：`get_result_tree()` 对大项目能返回几千个节点。桥里已经截断到 3 层（`_tree`），进一步应该只返回"用户问到的那条曲线"。

---

## 5. 如果确实要注入：施工图（方案 B）

### 5.1 注入器

```
1. 找进程：CST DESIGN ENVIRONMENT_AMD64.exe（x64，架构必须匹配）
2. OpenProcess(PROCESS_CREATE_THREAD|PROCESS_VM_OPERATION|PROCESS_VM_WRITE|PROCESS_QUERY_INFORMATION)
3. VirtualAllocEx + WriteProcessMemory 写入 DLL 全路径（UTF-16）
4. CreateRemoteThread(hProc, NULL, 0, (LPTHREAD_START_ROUTINE)GetProcAddress(kernel32,"LoadLibraryW"), remoteMem, 0, NULL)
5. WaitForSingleObject + GetExitCodeThread 判断加载是否成功
```
更稳的变体：`CreateProcess(CREATE_SUSPENDED)` 起 CST，注入后再 `ResumeThread`（避开"注入正在跑的业务进程"的时序问题）。
注入器本身要签名，否则会被 AV 直接拦。

### 5.2 DLL 骨架

```cpp
BOOL APIENTRY DllMain(HMODULE h, DWORD reason, LPVOID) {
  if (reason == DLL_PROCESS_ATTACH) {
    DisableThreadLibraryCalls(h);              // DllMain 里不做任何重活
    CreateThread(nullptr, 0, Worker, nullptr, 0, nullptr);
  }
  return TRUE;
}

DWORD WINAPI Worker(LPVOID) {
  CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
  // 1) 拿到 app 对象（见 5.3）
  // 2) 起命名管道服务（见 5.4）
  // 3) 管道线程只入队，不直接调 CST
}
```

### 5.3 进程内怎么拿到对象模型（这是整个方案最不确定的一环）

- **首选**：`GetActiveObject(CLSID_CSTStudio, nullptr, &app)`。DE 作为 COM 本地服务器一定注册了 class factory；是否把 **object** 注册进 ROT 是应用自己的选择。`[待验证]`
- **备选**：枚举 ROT 找 CST 的 moniker：
  ```cpp
  CComPtr<IRunningObjectTable> rot; GetRunningObjectTable(0, &rot);
  // EnumRunning -> moniker->GetDisplayName -> 匹配 "CSTStudio" / "!CST..." -> rot->GetObject
  ```
- **再备选**：拿不到就说明进程内也没有额外能力，**这个方案直接作废**（这是很重要的止损点）。

拿到之后跨线程用 GIT 或 `CoMarshalInterThreadInterfaceInStream` 送给自己线程——STA 到 STA 的调用由 COM 通过目标线程的消息泵编组，所以**必须在有消息循环的线程上调用**（GUI 主线程满足）。

**如果目标能力是 UI 级**（对话框、截图、进度），还需要把代码送回 UI 线程执行：
```cpp
// 在 UI 线程上跑一次，建一个属于该线程的隐藏窗口
SetWindowsHookExW(WH_CALLWNDPROC, HookProc, hDll, uiThreadId);  // HookProc 在该线程上下文里被调用
// HookProc 里：CreateWindowEx(..., L"cstmcp.job", ...) 然后 UnhookWindowsHookEx
// 之后 PostMessage(hiddenHwnd, WM_APP+1, jobId, 0) 就能让 UI 线程执行任务
```
Qt 窗口（`Qt5QWindowIcon`）不要直接 `SetWindowLongPtr` 替换 WndProc——Qt 会自己改回去，用上面的隐藏窗口/钩子方案。

### 5.4 管道与协议

```cpp
// 只允许当前用户访问，避免本机其他账户连进来
ConvertStringSecurityDescriptorToSecurityDescriptorW(L"D:(A;;GA;;;SY)(A;;GA;;;<当前用户SID>)", ...);
CreateNamedPipeW(L"\\\\.\\pipe\\cst-mcp-<pid>", PIPE_ACCESS_DUPLEX, PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE, ...);
```
协议沿用方案 A 的行分隔 JSON，Node 侧只改 transport：

```js
const sock = net.connect(`\\\\.\\pipe\\cst-mcp-${pid}`);
```
唯一要注意：管道 server 每个连接一个线程，任务入队后由 UI 线程执行，结果通过 `SetEvent` + 共享缓冲回传，**绝不能让管道线程自己调 CST**（跨套间 + 非线程安全的 VBA 引擎 = 随机死锁）。

### 5.5 生命周期

DLL 无法安全卸载（CST 内部可能还持有你的回调指针）→ 设计成"跟随进程生命周期"：收到 `shutdown` 只停服务，不 `FreeLibrary`。CST 退出时随进程一起消失，这是可接受的。

---

## 6. 为什么不要在 DLL 里跑 Node

1. **Windows 官方发行版没有 libnode**。`node.exe` 旁边的 `node.lib` 只是给 native addon 用的导入库；嵌入 API `node::Start` 的实现在 exe 里。要"把 Node 当库"，得自己用 `vcbuild` 的 shared/dll 配置编译一份 Node——本机连 MSVC 都没有。
2. **初始化冲突**。Node 每个进程只能初始化一次、有自己的线程/TLS/信号处理；而 CST 是 Qt + STA COM + 自带 Python 3.6（`boost_python36`）的多运行时进程。V8 与 Qt/CRT 的堆、TLS 槽位、`setlocale`、异常模型都容易打架，崩了是崩在客户的 CST 里。
3. **收益为零**。把 Node 放进进程唯一省掉的是"一次本地 IPC"，那是微秒级；代价是调试（不能单独重启）、部署（DLL 依赖 node 版本）、崩溃半径。
4. **安全面**。一个能开 HTTP 端口的 Node + 一个能注入进程的 DLL 组合在一起，就是教科书级的 RCE 载荷。企业 EDR 基本必然告警。

正解是"进程内只放最小代理，Node 永远在外面"——方案 B 的形态。

---

## 7. 已实现的部分与实测记录

```powershell
cd C:\Projects\cst-mcp
npm install
npm start                        # 监听 http://127.0.0.1:8765/mcp
```

实测（本机，无 CST 运行）：

```
POST /mcp  initialize   → 200, serverInfo={name:"cst-mcp",version:"0.1.0"}
POST /mcp  tools/list   → 7 个工具：cst_status / cst_connect / cst_open_project /
                          cst_vba / cst_solve / cst_solver_state / cst_abort_solver
POST /mcp  tools/call cst_status
           → {"connected": false, "running": []}
```
最后一条证明整条链路是通的：HTTP → MCP → Node → CST 自带 python 3.6 → `cst.interface` → 返回"当前没有 DE"。

**尚未验证**（需要真的开一个 CST）：
- `connect_to_any()` 附着到用户手动打开的 GUI 是否成功；
- `add_to_history()` 在附着会话里执行 VBA；
- 许可证占用规则（每 DE 一份？附着是否额外计费）。

跑 `scripts\probe_cst.py`（用自带 python）就是为这一步准备的：

```powershell
& "C:\Programs\CST Studio Suite 2022\AMD64\python\python.exe" scripts\probe_cst.py
```

---

## 8. 里程碑

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0（半天） | `probe_cst.py` 附着到已开 DE，读项目名与求解器状态 | 打印出 pid / 项目路径 |
| P1（1 天） | 方案 A 骨架 + 7 个工具 | 已验证：`tools/list` 与 `cst_status` |
| P2（1–2 天） | 真实建模 + 求解 + 结果导出；加 `cst_export`、`cst_result_curve` | 端到端跑一个天线模型 |
| P3（按需） | 截图/对话框需求出现 → 评估方案 B | 注入器 + 管道代理跑通 |

---

## 9. 风险与合规

- **CST EULA**：多数商业 CAE 许可禁止逆向工程与修改可执行进程；`[待确认]` 注入前请让法务/采购看一眼。
- **license**：`CreateObject` 新开 DE 会占一份 license；附着已开实例通常不额外占，但规则以你持有的 license 条款为准。
- **版本锁定**：Python 包是 `cp36..cp39`，CST 2022 自带 3.6。升级到 2023+ 后 `.pyd` 与 API 都可能变，桥里所有调用都要包一层版本探测。
- **Python 3.6 已 EOL**：不要在这个解释器里装第三方包，只跑标准库 + CST 自带库。
- **LLM 误操作**：`cst_vba` 能删几何、改求解器设置。至少做到：每次 VBA 落盘审计 + 执行前 `full_history_rebuild` 可回滚 + 生产项目只读挂载。
