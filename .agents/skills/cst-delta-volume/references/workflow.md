# CST 接口与局部 delta 的操作细节

## 连接和数据导出

从 `tools/cstmcp.py status` 获得真实 DE/modeler/端口，调用 `cst_connect(mode="pid")`。
项目切换后重新读取选择，不缓存上一项目或上一轮编辑的选择。
查询前先读 `docs/selection.md`；需要在线 BRep 时再读 `docs/live-brep.md`。

MCP 工具不提供任意管道命令。只读查询可以复用 `bridge/live_brep.py` 的
`execute_control_macro(project, code)`，在 **CST 自带 Python 3.6** 中通过
`cst.interface.DesignEnvironment.connect(de_pid)` 附着；与 owner 的操作串行执行，
不建立第二个服务器。控制宏的结果通过命名管道返回，不把查询写进历史。
该函数要求宏向 `PIPE_NAME` 输出以 `BEGIN` 加制表符开头、以 `END` 结尾的行协议。
接口等待超时后，只有完整返回数据加上后续实测才足以确认执行结果。
可直接使用本 skill 的 `scripts/control.py`，例如：

```powershell
& 'C:/Programs/CST Studio Suite 2022/AMD64/python/python.exe' `
  .agents/skills/cst-delta-volume/scripts/control.py --de-pid <de> `
  --project <actual-project.cst> --code <scratch.bas> --output <new-result.json>
```

`scratch.bas` 只放 Sub Main 内的语句，可用 `fh` 输出 `Print #fh, ...`；不要重复包 Sub Main。
结果为 `lines`、`macro_error`、`interface_timed_out`。出现错误后仍须读取真实几何状态。

导出/测量使用已安装的 CST VBA 文档定义的方法：

```vb
unitName = Units.GetGeometryUnit
unitToSI = Units.GetGeometryUnitToSI
volume = Solid.GetVolume(shape)
materialName = Solid.GetMaterialNameForShape(shape)
With SAT
    .Reset
    .FileName satPath
    .ExportFromActiveCoordinateSystem False
    .Write shape
End With
```

如需面三角网格，`Pick.ExportFaceTriangles filename, maxlen, surftol` 导出当前拾取面，
坐标和精度按项目单位。它不能替代精确 BRep。
VBA 字符串中的双引号要加倍，拒绝把带换行的名称直接拼入宏。

## SAT 分析与选面扩展

`tools/feat/sat.py` 提供 `Model(path)`、`surface(face)`、`face_box(face)`、
`loops(face)`、`coedges(loop)`、`partner_face(coedge)` 等读取方法。
它是特征分析所需的最小解析器，不是通用 ACIS 几何验证器；遇到不支持的记录/曲面时改用在线 BRep
或已验证的几何内核，不按猜测补齐属性。

CST 导出 SAT 的 face 属性链中，`integer_attrib-name_attrib-gen-attrib` 的 `pid`
可对应原生 CST face ID。遍历 face 的第 0 个指针指向的属性，再沿属性第 2 个指针前进：

```python
def cst_face_id(model, face):
    attr = model.rec(face.ptr(0))
    seen = set()
    while attr is not None and attr.index not in seen:
        seen.add(attr.index)
        if "pid" in attr.f:
            return int(attr.f[-1])
        attr = model.rec(attr.ptr(2))
    return None
```

仅在属性存在且几何吻合时使用此映射；ACIS 面列表序号不是这个 ID。
从选中面沿 coedge partner 读取邻面，寻找共同构成可移动边界的曲面。
例如两个圆角面夹着一个斜平面，通常应将中间面一并移动，避免扭曲该特征；
这不表示可以无界地扩展到整个相切连通分量。
另外两种已用过的补面规则：圆角锥槽需补齐同一槽的另一半锥面、上下圆角和封底面；
圆柱孔的两个半面需连同相接倒角一起移动。以上都由邻接和支撑曲面确认，不能只按面类型补选。
若用户选面数量与读取结果不符，先完成选择澄清，再进行副本移动。

## 临时副本与目标编辑

零向量 Transform 可以复制实体。下面是已验证的设置组合；执行前核实自动副本名称未被占用：

```vb
With Transform
    .Reset
    .Name shape
    .Vector "0", "0", "0"
    .UsePickedPoints False
    .InvertPickedPoints False
    .MultipleObjects True
    .GroupObjects False
    .Repetitions 1
    .MultipleSelection False
    .Transform "Shape", "Translate"
End With
```

随后核实复制体确实存在、体积和几何与原体吻合，再 `Solid.Rename` 为本次唯一 scratch 名称。
不要假设所有模型上副本都一定叫 `solid_1`，更不能覆盖已有同名实体。
可靠做法是复制前后枚举 solid 名单，以新增名称识别副本，再重命名为本次独有名称。
已有 `Solid048_1` 或 `default:import_1` 可能是用户对象，不能当作本次临时体删除。
用制表符包围名称进行清单查找时，已验证的 CST Basic 写法是
`InStr(names, vbTab & name & vbTab)`；本环境的四参数 VBA 版本曾报 `Expecting ')'`。
保存 `WCS.IsWCSActive`，全局位移前 `WCS.ActivateWCS "global"`，结束时恢复原模式。

清除当前 picks 后，在同一个副本上按已核实的 ID 拾取完整移动面集，再一次执行：

```vb
With LocalModification
    .Reset
    .Name candidateShape
    .EnableInvertedFaceRemoval False
    .SetConsiderBlends False
    .MoveSelectedFaces dx, dy, dz
End With
```

沿法向推拉改用 `.OffsetSelectedFaces distance`。
平面沿自身切向移动不会改变其无限支撑平面；若意图是移动有限特征，需结合邻接确定完整面集。
`SetConsiderBlends True` 会拆除并重建邻接圆角，应按用户的几何意图选择，不作为无条件重试开关。

临时创建/编辑可在串行控制宏中执行，不进入最终历史；出错时停止并读取实际模型状态。
原项目仍存在 scratch 时，不能宣称整个项目历史已经可复现。最终要清理本次 scratch 并只记录正式 delta 操作。
对完整孔壁与倒角仍报几何内核错误的情况，先检查新位置是否与外壁、邻孔或曲面相交；
不要仅靠切换 `EnableInvertedFaceRemoval` 或重复原宏重试。
若孔空域可从解析曲面完整重建，转到 [analytic-holes.md](analytic-holes.md)。

## 原生管道、局部求差和空体

`src/acis.mjs` 的 `AcisPipe` 连接一直占有管道；同一代理虽然声明多个实例，服务循环实际一次只处理一个连接。
直接脚本报管道忙/`Invalid argument` 时，不要反复打开管道，也不要重注入 DLL。
记录当前端口与 PID，确认 owner 空闲后可暂时释放它：

```powershell
py -3.12 tools/cstmcp.py down --port <port>
# 执行 local_delta.py；不关闭 CST，也不注入新 DLL。
py -3.12 tools/cstmcp.py up --port <port> --de-pid <de> --modeler-pid <modeler>
```

在 finally 路径恢复 owner，并重新 `cst_connect`、`acis_connect`。
服务器桥重启后的 `connected:false` 是正常初始状态。

### dsh 等执行器的沙箱分支

执行器可能能访问 HTTP 和项目文件，却看不到宿主 CST 进程，表现为
`running_design_environments()=[]`、`No Process found`、命名管道 `PermissionError` 或启动桥时 `spawn EPERM`。
若宿主启动的固定 owner 仍能通过 HTTP 附着正确 DE，说明这是接入能力差异，不是几何失败。
不要仅因沙箱内进程枚举为空而重启 owner，也不要在该沙箱内先停止正常 owner 再启动替代实例。

保留宿主 owner，所有 CST 请求发往已指定端口：

- 使用 `cst_status` / `cst_connect(mode="pid", pid=...)` 核对目标；不能连到任意其他 DE。
- 隔离验证项目可用 `cst_vba` 执行 Solid 查询并向本次输出文件写结果；它会记录历史。
  临时体的创建、查询、删除应保持历史顺序可重建，保存其 SAT 依赖，正式 delta 块仍须独立于已删除的临时体。
- 用 `Brick` 的 `Xrange` / `Yrange` / `Zrange` 建裁剪盒，配合 `Solid.Intersect`、
  `Solid.Subtract`、`Solid.Add` 完成同样的局部或解析孔布尔。
  导入前后枚举名称，并检查 `Solid.DoesExist`、体积和导出的拓扑。错误不能直接解释为空体。
- 可在 CST 宏内以 `Solid.IsPointInsideShape` 对同一网格做分类，向本次文件输出；
  不必为采样强求原生 `pgrid`。限制批量大小，保存网格与边界/错误统计。

这里仅使用已授权的 CST 建模与查询接口；不要用 VBA Shell、进程启动或系统设置变更绕开执行器沙箱。
若固定 owner 也失效，由宿主恢复该验证栈，再继续执行；不转向用户正在编辑的栈。

代理中的 `restore` / `prism` / `bool` / `save` 操作的是脱离 CST 项目树的临时体；
不能向其传入 live BRep 捕获的 BODY 指针。`swap` 交换 main 和 aux，`bool cut`
计算 **main − aux** 并消耗 aux；`bool int` 类似。

为避免上一轮 aux 干扰，脚本在独立阶段先发送 `newbody → swap → newbody` 清空两个临时槽。
矩形 profile 的四条 `L x1 y1 x2 y2` 边定义 XY 截面，
`prism new zmin (zmax-zmin) 0 <profile>` 生成裁剪盒。原生命令按空白分词 profile 路径，
当前脚本因此要求 ASCII、无空白路径。

对每个原体/目标体：`restore → swap → prism new → bool int` 得到局部体。
分别装载 main=A、aux=B 求 remove，main=B、aux=A 求 add。
每次检查 `faces`；零面体不导出、不导入。不用体积接近 0 来替代空体判断。
脚本超时不等于内核已取消；不能立刻再发送修改命令或重启用户的 CST。

`mass` 的默认精度在复杂体上可能与 CST `Solid.GetVolume` 不同。
日志中的原生质量属性只作诊断，定量结果应使用 CST 中对原体、delta、回放体的测量。
原生 `bbox` 的文本坐标只打印两位小数；精细检查用 SAT/BRep 中的坐标。
带裁剪曲线、样条和容差实体的 SAT 包围盒也可能偏松；不能把包围盒超出裁剪盒单独当作材质越界证据。
必须检查实际边界、关键曲面及区域外的实体内外分类，不得忽略无法解释的区域外差异。

## 回放、正式历史和最终核对

先在原体副本回放两个非空 delta。SAT 导入采用全局坐标、保持源单位的明确设置：

```vb
With SAT
    .Reset
    .FileName deltaPath
    .Id uniqueImportId
    .Version "9.0"
    .ScaleToUnit False
    .ImportToActiveCoordinateSystem False
    .Curves False
    .Read
End With
```

导入前后枚举 `Solid.GetNameOfShapeFromIndex` 获取新增名称，不按文件名猜 solid 名称。
核实新增数量与 delta 的实际 body/lump 情况一致。若是多 body delta，逐个核实、应用全部新增体；
不得只取第一个。原生 `restore` 当前只把文件中第一个 entity 放入 main，
所以局部求差脚本只接受单 BODY 输入，不能把多实体 SAT 当作完整原体处理。

`Solid.Subtract target, removeName` 消耗减料体；`Solid.Add target, addName` 消耗增料体。
增料体先设成目标的材质，应用后核实目标名称与材质。
回放通过后，清理临时实体，以不同于试验导入的唯一 `SAT.Id` 写正式历史块。
使用 `cst_vba` 时，当前 CST 2022 环境中省略可选 `timeout`；
桥传第三个 `add_to_history` 参数曾报 `Expecting 2 arguments, given were: 3`。
即使返回成功也要重新测量，不能把该返回当作验证。

验证应按模型特点选择：目标曲面的位移/偏置、轴线/半径、裁剪边界、
闭合共边、实体/壳数量、增减料体空间范围、盒外曲面、其他对象的体积/几何。
检查边界 coedge 的 partner，但不要求锥尖处的零长度退化边一定配对。
导入合面后曾出现这样的边：起终点为同一 vertex、curve 为空、边盒退化成一点，
该点与锥面由 `r=0` 计算的锥尖吻合。只有这些几何条件均确认时，才单列为退化锥尖；
闭合圆弧也可能起终点相同，不能仅据这一点放行。
可复用 `scripts/topology.py` 的 `boundary_report`；其余无配对边仍需解释或修复。
该检查不等于证明无自交或全局等价。
必要时使用差集或区域采样补充。`pgrid` 的参数格式为：

```text
pgrid x0 y0 z0 dx dy dz nx ny nz output.bin
```

每点输出一个字节，X 最外层、Z 最内层；1 为内部、2 为边界、3 为外部，0/4 及调用错误须单列。
网格原点错开模型上的整齐坐标，分块限制单次工作量。
比较原体/目标体的全局样本应只在编辑区域内不同；局部密采样比较目标/回放应一致。
不要把边界或未知分类强行归到内部/外部。采样点数是报告数据，不是等价性的形式证明。
不要为例行核对对用户整个项目强制 full rebuild。

CAD 文件重新导入后 PID 可能变化。把原 SAT 的 face `pid` 作为输入定位线索，
用几何支撑及边界建立新项目的映射；可使用 `Pick.GetFaceIdFromPoint` 取得实际 ID。
取点须确实位于该裁剪面内部：不要对曲面用包围盒中心直接猜 ID。
映射后用 `cst_get_selection` 核对面积/所属实体，确认后再编辑。
SAT 重新导入可能修复或合并面，体积积分也可能随表示变化。
独立回归用本次导入后实测的原体作基线，并保留输入文件哈希；
不能仅凭它与历史体积不同就断言输入快照不同，也不要求导入后的面数与源文件一致。

## 数值、状态与回归

圆柱轴线比较应去除沿轴方向的参数原点自由度；平面用法向和平面方程比较。
布尔合并前后样条可能从内联几何改为 `ref`，周期曲线的缝点也可能移动；
不能仅据顶点集合、字符串、face PID 集合不同判定几何已改变。
反过来，只比较半径、顶点或面数也不能证明等价。

在这些复杂导入体上，CST 单独测量原体、增减料体和目标体的数值积分可能不完全可加。
曾出现目标/回放约 `1.03e-5 mm³` 的差异，而曲面参数、闭合性及局部 CSG 采样均一致。
记录实际绝对/相对误差及所用公差，用进一步几何证据判定；
不得把这些示例误差变成通用默认公差，或只放宽数值检查来掩盖错误。
体积不可加的残差本身不能证明材料重叠、薄层丢失或端面越界。
若实际交集为空且参数/边界与采样一致，应分别报告这些证据和积分残差，
不要用未经几何验证的重叠猜测解释差值。

独立复现应从每次操作前的原始 SAT 开始，只给新执行者选面线索、位移、skill 和隔离栈。
要求重新构造目标/delta、在 CST 历史应用，并产出模型和机器可读报告，不能复制旧的成功结果。
用 dsh 时，`dsh headless --json -` 从 stdin 读取任务，事件日志保留 session ID 与执行证据。
只允许它操作为验证创建的 DE/modeler/端口；原有用户栈保持不动。
成功退出、声称 PASS、仅跑格式校验都不足以证明 case 完成，必须核对新生成的几何产物和实测数据。
`MISSING_CREDENTIAL` 表示执行者尚未调用模型，不是几何 case 失败或成功。
记录该预检阻碍，使用用户已有的凭据/profile，或请用户在 dsh 环境中完成配置；
不要求把 API key 贴进聊天，也不把密钥写入 skill、任务文本或回归报告。

## 已验证案例（回归线索）

2026-11-07 的一次操作：`component1:Solid048` 上面 294、1427，补选连接面 295，
沿全局 X 移动 −1 mm。两个圆柱面的半径分别为 0.16845、0.2246 mm。
局部盒为 `[-25.6, -77.6, 1.25]` 至 `[-23.6, -76.3, 1.95]` mm。
得到一个 10 面减料体，增料体为空；最终仍是单实体、单壳、1452 面。
体积 `1398.07160715004 → 1397.64262057247 mm³`，减料约 `0.42898658 mm³`。

这些数值只用于已知案例回归，不能成为其他模型的默认值或通用断言。
原始临时产物如仍在本机，可在 `out/delta_move_x_20261107/` 查到；该目录不入库，
本 skill 不依赖它的存在，也不把这些实体或 PID 写入脚本默认参数。
