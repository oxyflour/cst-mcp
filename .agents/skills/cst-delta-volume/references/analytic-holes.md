# 圆柱孔、倒角与解析空域路线

用于孔壁/倒角支撑面明确、能重建原孔空域的平移需求。不是任意失败面的兜底算法。
先在新鲜副本上试完整特征的 LocalModification；失败时保留错误、核实原体未变。
若失败与新孔接触外壁/邻面有关，解析刀具体可以表达这个拓扑变化。
向用户说明会发生的贯通或合并，沿用已授权的位移；无法确定其特征范围时再澄清。

## 1. 从原始数据重建原孔 H0

读取孔壁的轴线、半径、有限 Z 范围、倒角锥面和开口面。
同一圆柱可能由两个半面表示，轴向参数原点不一定是孔底；不能用曲面 `point.z` 当高度。
从实际裁剪边界得到接合高度和两端开口位置。

轴平行 Z 时，锥面的半径函数可由 SAT 解析参数计算：

```text
slope_z = (sine / cosine) * axis.z
r(z) = reference_radius + slope_z * (z - reference_point.z)
```

检查轴平行度、`cosine` 非零及有效参数范围。
任意方向的孔需在其轴坐标系下处理；不要把倾斜孔强行套用 Z 轴公式。
45° 倒角的 `abs(slope_z)=1`，但该值来自实测，不能对所有孔硬编码。

H0 是需要填回的**原孔内部**，两端截至原孔的真实开口面。
不能为了布尔容差把填充体延伸进孔外空气，否则会无意增加凸台/薄片。
验证 H0 与原体材料不重叠，壁面/倒角匹配，端面确实是原开口。
可用原孔截面和实体内外分类补充，记录边界/未知样本。

## 2. 构造移位后的刀具体 H1 和目标 T

H1 保持圆柱半径、轴向和倒角锥度，轴线按用户向量平移。
刀具体两端可以伸入已确认的空气，确保切穿新位置的真实外表面；
它与严格有限、只用于填回的 H0 可以有不同的端部范围。
尤其新位置接触弧面时，不要把 H1 截在原平面高度，留下意外孔盖。
伸长的锥体须保持同一支撑锥面，端部半径由半径函数计算，不能简单复制原端半径。

在 scratch 目标上构造：

```text
T = (O ∪ H0) − H1
```

O 是原实体。另存 `old_void.sat`、`new_void.sat`、`modified.sat`，检查 T 闭合、
孔轴/孔径/倒角正确，额外贯通属于此次移动的局部效果。

Z 轴孔可用 CST 的 `Cylinder`、`Cone` 构造。关键宏设置为：

```vb
With Cylinder
    .Reset
    .Name cylinderName
    .Component componentName
    .Material targetMaterial
    .Axis "z"
    .Outerradius radius
    .Innerradius "0"
    .Xcenter cx
    .Ycenter cy
    .Zrange zJoin, zEnd
    .Segments "0"
    .Create
End With
With Cone
    .Reset
    .Name chamferName
    .Component componentName
    .Material targetMaterial
    .Axis "z"
    .Bottomradius rBottom
    .Topradius rTop
    .Xcenter cx
    .Ycenter cy
    .Zrange zStart, zJoin
    .Segments "0"
    .Create
End With
Solid.Add cylinderFullName, chamferFullName
```

`Cone` 使用 `Topradius` / `Bottomradius`，不是 Cylinder 的 `Outerradius`。
几何实际参数、名称和组件来自本次项目；先检查名字是否可用，不覆盖既有对象。
建模需全局 WCS，结束时恢复原 WCS/quiet 状态。

## 3. 避免对相近复杂实体反复求差

若 `O∩R` 和 `T∩R` 的差报 `BAD_CONTAINMENT`，可直接使用已构造的 H0、H1：

```text
D_remove = O ∩ H1
F_add    = H0 − H1
(O − D_remove) ∪ F_add = (O ∪ H0) − H1 = T
```

这个回放恒等式不依赖总体积近似。H0 与 O 不重叠时，F_add 才是严格的纯增料体；
若二者重叠，它仍是并入工具，但不能将其体积全部计为新增材料。
孔移动路线本身仍应验证 H0 确实重建了原空域。
通过实际交集与共同采样检查材料重叠；不能仅凭体积加减的积分残差宣称重叠。
例如 `F_add ∩ O` 实测为空时，分别保留这个结果及体积残差，不能改称已发现薄层重叠。

在已独占的原生管道上运行：

```powershell
py -3.12 .agents/skills/cst-delta-volume/scripts/void_delta.py `
  --modeler-pid <modeler> --original <original.sat> `
  --old-void <old_void.sat> --new-void <new_void.sat> --out <new-dir> --dry-run
```

核对后去掉 `--dry-run`。脚本只编辑 ACIS 的临时体，输出非空 `remove.sat`、`add.sat`
和 `manifest.json`；不会自动填孔、导入项目、改历史或验证 H0/H1。
管道、路径、单 BODY、超时和 owner 恢复规则与 `local_delta.py` 相同。
失败后停止应用，保留日志；不能把缺失的输出当作空体。

## 4. 验证后才写正式历史

在另一份原体副本中导入 D_remove/F_add 并回放；测量、导出并检查真实几何。
至少核对孔轴横向位移、半径、锥面半径函数、有限裁剪边界和闭合性。
两个半圆柱面合并成一个完整面是可能的结果；从曲面和新边界取得新的 CST ID。

发生贯通或曲面合并时，补充以下采样：

- 全局比较 O/T/回放，编辑区域外不应出现无法解释的分类差异。
- 局部密采样 T/回放，应一致；将边界/未知分类单列。
- 对 O/H0/H1/T 在相同网格核对 `inside(T) = (inside(O) or inside(H0)) and not inside(H1)`，
  同时统计 H0 与 O 的材料重叠。

它们是几何检查的补充，不是形式上的等价证明。
回放通过后再写正式 delta 导入/布尔历史；保留 SAT 依赖和实测记录。
