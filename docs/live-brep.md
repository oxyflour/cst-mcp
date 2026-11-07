# 按 entity ID 查询运行中模型的 BRep

接口直接读取活动 CST 项目中的 solid。先列出 ID，随后只用 entity ID 查询。
客户端不创建、不保存、不传入 snapshot ID。MCP 返回 JSON，不导出 SAT/STEP，不创建
模型历史条目，不改变选择或几何。

```text
cst_connect → acis_connect → cst_list_solids
    → cst_list_entities(type="face") → cst_get_entity
    → cst_get_adjacency(relation="loops") → cst_get_loop_boundary
```

## 六个接口

| 工具 | 必需参数 | 可选参数 | 返回内容 |
|---|---|---|---|
| `cst_list_solids` | 无 | `offset=0, limit=50` | `items: [{id,name,material,counts}]` |
| `cst_list_entities` | `solidId, type` | `geometryType, offset=0, limit=50` | 指定类型的 `ids` |
| `cst_get_entity` | `id` | 无 | 一个 entity 的属性及直接连接 ID |
| `cst_get_entities` | `ids` | 无 | 按输入顺序返回至多 20 个 entity，任何一个失效则整批报错 |
| `cst_get_adjacency` | `id, relation` | `offset=0, limit=50` | 包含/邻接关系的目标 `ids` |
| `cst_get_loop_boundary` | `loopId` | `offset=0, limit=20` | 按环方向排列的半边段及其端点 ID |

`type` 为单数：`lump / shell / face / loop / coedge / edge / vertex / wire`。
`geometryType` 只适用于 face/edge，可用 `plane / cone / sphere / torus / spline /
straight / ellipse / intcurve / other / none`。圆柱面在 ACIS 中属于 `cone`。

列表/邻接每页最多 200 项；环边界每页最多 50 项；批量详情最多 20 项。
所有 BRep 工具的成功回复限制为 **32 KiB UTF-8 JSON**。没有任何工具自动展开整个
solid 的拓扑；超过回复限制时返回 `RESPONSE_TOO_LARGE`，需要减小请求量，不会截断。

## Entity ID 的含义与生命周期

- ID 为不透明字符串，带 `solid:`、`face:`、`edge:` 等类型前缀；应原样传回，不解析、不拼接。
- ID 不包含 native 地址，不是数组下标，也不是 CST 的数字 pick ID。
- solid ID 对应当前项目中的完整 solid 名称，改几何但保留名称时仍可继续查询它。
- 子实体 ID 绑定该 solid 的完整拓扑/顶点坐标指纹。后续查询重新读取对应 solid；
  检测到变化会返回 `STALE_ENTITY_ID`，避免把旧下标对应到新实体。
- 修改一个 solid 后，应重新列举它的子实体；其他未变化 solid 的 ID 保持可用。
  名称改变或 solid 删除后，旧 solid ID 不会自动指向另一个名称。
- 切换项目或 modeler、服务器重启后重新列举 ID。ID 不用于跨会话持久引用。
- 只保存名称到 solid ID 的索引和 ID 校验密钥，不保存可被后续请求解引用的 BRep 指针。

没有额外的模型版本参数或 snapshot ID 需要客户端管理。

## 分页格式

`cst_list_solids` 的列表字段是 `items`；entity 和邻接查询的列表字段是 `ids`：

```json
{
  "solidId": "solid:<opaque-id>",
  "type": "face",
  "total": 1443,
  "offset": 0,
  "limit": 20,
  "nextOffset": 20,
  "ids": ["face:<opaque-id>"]
}
```

以上为字段示意，真实 ID 由工具返回。`nextOffset=null` 表示最后一页；`total` 为过滤后
的总数。模型不变时分页和 ID 保持一致，模型变化后重新从列表开始。

## 单实体详情

`cst_get_entity` 只返回常数规模的直接连接；大型集合通过邻接接口分页查询。
所有非 solid 详情都有 `id`、`type`、`solidId`。不存在的连接为 `null`。

| entity | 属性与连接 |
|---|---|
| solid | `name, material, counts, firstLumpId, firstWireId` |
| lump | `firstShellId, nextId` |
| shell | `lumpId, firstFaceId, firstWireId, nextId` |
| face | `shellId, firstLoopId, nextId, sense, surfaceType` |
| loop | `faceId, firstCoedgeId, nextId` |
| coedge | `edgeId, loopId, wireId, nextId, previousId, partnerId, sense` |
| edge | `startVertexId, endVertexId, firstCoedgeId, sense, curveType` |
| vertex | `position, localPosition, coordinateFrame="global"` |
| wire | `shellId, firstCoedgeId, nextId` |

坐标单位为项目几何单位。`position` 已应用 BODY 变换，`localPosition` 为 BODY 局部坐标。
`sense` 保留 ACIS 标志：0 forward，1 reversed。返回几何类型，不展开完整 NURBS 参数。
`nextId` 的语义依 entity 类型而定：face/loop/shell/lump/wire 是同级链表，coedge 是环内后继。

## 包含关系与邻接关系

`cst_get_adjacency` 返回 `id, relation, targetType, ordered` 以及分页字段和 `ids`。

| 源 entity | 支持的 relation |
|---|---|
| solid | `lumps, shells, faces, loops, coedges, edges, vertices, wires` |
| lump | `shells, faces, edges, vertices` |
| shell | `faces, wires` |
| face | `loops, coedges, edges, vertices, adjacent_faces` |
| loop | `coedges, edges, vertices` |
| edge | `vertices, coedges, faces` |
| vertex | `edges, faces` |
| wire | `coedges, edges, vertices` |
| coedge | 直接连接由 `cst_get_entity` 提供 |

`face.adjacent_faces` 通过共享边寻找所有使用面，排除自身并去重，支持非流形边的多面
扇区，不假定 `partner` 只有互逆的一对。其他无序集合也去重。

`loop/wire.coedges` 与 `loop/wire.edges` 按边界顺序返回，`ordered=true`；缝合边可能出现
两次，不能去重。`edge.vertices` 按 start/end 返回，闭合边的两端可为同一个 ID。
face 的多个 loop 分别由自己的有序边界描述，不能把 face 的所有边当成单一有序环。

## 环的有序边界

`cst_get_loop_boundary` 从 `firstCoedgeId` 开始沿 next 方向绕行。每个 item 包含：

```json
{
  "coedgeId": "coedge:<opaque-id>",
  "edgeId": "edge:<opaque-id>",
  "startVertexId": "vertex:<opaque-id>",
  "endVertexId": "vertex:<opaque-id>",
  "sense": 0,
  "partnerId": null
}
```

这里的端点已按 **coedge 方向** 调整，和 edge 自身的固定 start/end 不同。分页连续覆盖
环，不自动重复首段来表示闭合；`closed` 表明闭合情况。下一段的 start 应等于上一段的
end；最后一段的 end 应等于首段的 start。端点退化/不存在时允许 `null`。

## 错误

工具错误使用 `isError=true` 和如下 JSON：

```json
{"error":{"code":"STALE_ENTITY_ID","message":"solid topology or coordinates changed; list its entities again"}}
```

常见 code：`INVALID_ENTITY_ID`（未知/错误项目/过期会话）、`STALE_ENTITY_ID`、
`ENTITY_NOT_FOUND`、`INVALID_ENTITY_TYPE`、`INVALID_FILTER`、`UNSUPPORTED_RELATION`、
`PROJECT_CHANGED`、`RESPONSE_TOO_LARGE`。错误不会返回一半结果。

## 内部实现与验证

模型没有放入 ACIS 的全局 PART 列表。桥使用控制宏枚举 CST 的 solid 名称，仅对目标
名称或指定页调用 `Solid.IsPointInsideShape`；代理在其调用期间取得真实 `BODY*` 并读取
拓扑，返回后不保留指针。名称清单通过内存命名管道返回，不写几何文件。

现阶段内部仍读取每个目标 solid 的完整 BRep，再在服务器上生成 ID 和裁剪结果；减少
上下文并不等于内核计算量与单个 entity 大小相等。一次查询只读取所需的 solid，不读取
其他 solid 的拓扑。内部捕获上限为 200000 个拓扑实体和 64 MiB，超过时明确报错。

捕获代码适配本机 CST 2022 / ACIS 2021，核验完整函数序言后临时拦截
`api_point_in_body`，在 finally/断开时恢复。求解时拒绝查询；各 BRep/桥/ACIS 工具串行化。
老代理须支持 `brep_begin` / `brep_end`，不需要为这些分页接口重启已经加载该代理的项目。

```powershell
node --test tests/brep.test.mjs
py -3.12 tools/cstmcp.py symbols
py -3.12 tools/cstmcp.py up --isolated
# 仅空的可丢弃项目：会建两个方块、推拉并删除一个，用于测试 ID 失效。
py -3.12 scripts/check_live_brep.py --port 8770 --fixture
# 仅只读查询已有项目；output 保存小型查询报告，不是整份 BRep。
py -3.12 scripts/check_live_brep.py --port 8765 --output out/brep-queries.json
```

单元测试使用真实 CST 方块及通孔拓扑，覆盖分页、混合批量、ID 校验、内外环、相邻面、
有序端点和周期缝合边。端到端检查六个工具、Unicode、重复连接、推拉后旧 ID 失效、
删除 solid、无关 solid 的 ID 不变以及回复大小。
