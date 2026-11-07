# 获取当前选中对象的信息

```text
cst_connect → cst_get_selection({offset: 0, limit: 50})
```

工具读取活动 3D 项目的正式树选择和 Pick 状态，只需要 `cst_connect`，不需要 ACIS
代理。没有 SAT/STEP 导出，没有模型历史条目，不清除或修改用户当前的选择。不读取鼠标
悬停产生的临时预高亮。

## 返回格式

```json
{
  "counts": {"treeItems": 1, "faces": 0, "edges": 0, "points": 0},
  "total": 1,
  "offset": 0,
  "limit": 50,
  "nextOffset": null,
  "items": [{
    "selectionIndex": 0,
    "type": "solid",
    "source": "tree",
    "treePath": "Components\\component1\\Solid048",
    "solidName": "component1:Solid048",
    "material": "Metal01"
  }],
  "file": "C:\\path\\project.cst"
}
```

分页顺序固定为树选中项、拾取面、拾取边、拾取点。`counts` 始终给出全部类别的总数，
`total` 为它们之和。树选中的 solid 和它上面拾取的面会分别保留，不合并或去重。
`selectionIndex` 是当前选择列表的位置，不是持久实体 ID。

默认每页 50 项，最多 100 项，单次成功回复最多 32 KiB；超出限制时减小 limit。
`nextOffset=null` 表示最后一页。用户在分页期间改变选择时，应重新从第 0 页开始。

| type | 信息 |
|---|---|
| `solid` | `source="tree"`、`treePath`、`solidName`、`material` |
| `tree_item` | `source="tree"`、`treePath`；文件夹、结果节点等不冒充 solid |
| `face` | `source="pick"`、`pickIndex`、`solidName`、`cstFaceId`、`area` |
| `edge` | `source="pick"`、`pickIndex`、`solidName`、`cstEdgeId`、`cstStartVertexId` |
| `point` | `source="pick"`、`pickIndex`、`position: [x,y,z]`、`coordinateFrame="global"` |

`area` 是 CST 返回的面面积；坐标使用项目几何单位。不存在的边起点 ID 返回 null。
拾取点可以是自由空间中的点，不一定是 BRep vertex，因此不虚构 vertex ID 或所属 solid。

`cstFaceId`、`cstEdgeId`、`cstStartVertexId` 是 **CST 原生数字 pick ID**，不是
`cst_get_entity` 接受的 BRep 不透明字符串 ID。本工具目前只提供所选对象的信息，不做
两套 ID 的映射。`solidName` 与 `cstFaceId` 可直接对应现有 `cst_local_modify` 的
`shape` / `faceId`；修改后应重新查询，不缓存旧 pick ID。

## 实现

控制宏使用 `GetNumberOfSelectedTreeItems`、`GetSelectedTreeItem`、
`GetNextSelectedTreeItem` 枚举树选择。`GetGlobalNameFromTreeName` 返回带 `solid$`
类型前缀的名字；去掉前缀并用 `Solid.DoesExist` 核实后，才将条目标记为 solid。

Pick 使用 `GetNumberOfPickedFaces/Edges/Points` 和 `GetPickedFaceByIndex`、
`GetPickedFaceAreaByIndex`、`GetPickedEdgeByIndex`、`GetPickpointCoordinatesByIndex`。
清单通过内存命名管道回传，字符串以 UTF-16 十六进制编码，保留 Unicode 名称。

```powershell
npm run test:selection
# 在已打开项目上只读获取；保存的是小型选择信息 JSON。
py -3.12 scripts/check_selection.py --port 8765 --output out/selection.json
# 仅空的、可丢弃的隔离测试项目；此选项会创建并选择测试几何。
py -3.12 scripts/check_selection.py --port 8770 --fixture
```

测试检查多类别信息、Unicode、分页、重复读取不改变选择，以及空页/无效返回的处理。
