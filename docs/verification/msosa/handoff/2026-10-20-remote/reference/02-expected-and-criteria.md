# reference/02 · 期望值、判定标准、高风险构造

---

## 1. 这份文本是什么

`inputs/golden-coaxial-power-chain.sysml`（sha256 `bb64cc2c…`）是一份**冻结**的 SysML v2 文本模型，包名 `CoaxialOctoRotor`，共 213 行、9766 字符。

它由我们的建模智能体从 IR JSON 确定性生成，已经通过：

- 我们自己的 IR 校验（L0，0 error / 0 warning）；
- **OMG SysML v2 Pilot Implementation 官方解析器**（L1，0 条诊断）；
- 追溯性检查（L2，4 行矩阵，0 gap）。

> 也就是说：**如果这份文本在对方工具里报语法错误，那不是"我们文本不合法"的孤证**——它是另一个实现对 SysML v2 文本子集的覆盖差异。这正是我们要的差分证据。

---

## 2. 期望的元素账本（34 个声明元素）

按种类：

| 种类 | 数量 | 说明 |
| --- | ---: | --- |
| `part def`（PartDefinition） | 7 | BatteryPack / ElectronicSpeedController / BrushlessMotor / PowerChain / LowerRotor / UpperRotor / CoaxialOctoRotorSystem |
| `part`（PartUsage） | 8 | x8System / powerChain / batteryPack / escUnit / upperMotor / lowerMotor / upperPropeller / lowerPropeller |
| `requirement def` | 4 | MissionEndurance / CruiseEndurance / RotorSpeedRatioBand / CruisePowerBudget |
| `attribute` | 9 | batteryCapacityWh / usableEnergyFraction / escEfficiency / motorEfficiency / propellerEfficiency / cruisePowerW / enduranceHours / cruiseSpeed / speedRatioEta |
| `action def` | 2 | OnlinePowerOptimization / EnduranceSimulationRun |
| `state def` | 1 | FlightModeStates |
| `constraint def` | 1 | EnduranceBudget |
| `connect`（连接用法） | 2 | batteryToEsc / upperMotorToPropeller |
| **合计** | **34** | 逐行见 `ledgers/elements.csv` |

**抽查点名（6 个）**：`BatteryPack`、`PowerChain`、`CruiseEndurance`、`FlightModeStates`、`EnduranceBudget`、`batteryToEsc`。

### 关于"20 条关系"

`ledgers/relations.csv` 有 20 行，但：

- **只有 2 条**以真正的 `connect a to b;` 写进文本（`batteryToEsc`、`upperMotorToPropeller`，文本第 80、82 行）；
- **其余 18 条**（decomposes / satisfiedBy / verifies / refines）在我们 IR 里是追溯关系，**在文本里只以注释形式存在**，任何工具都不会把它们变成模型关系。

→ **不要**按"20 条关系"去核对，那一定"缺 18 条"，但这不是工具的错。

---

## 3. 三态判定（对面 agent 必须选一个）

| 态 | 触发条件 | 必须给出 | 我们据此能写什么 |
| --- | --- | --- | --- |
| **A｜可导入** | 出现根命名空间 `CoaxialOctoRotor`，元素数 34、`connect` 2 条 | 版本/build、许可、插件；树截图；校验诊断计数与明细；导出文件数与 sha256 | "另一个构建接受了同一份文本，诊断如下"（**不写**"通过验证"） |
| **B｜无入口** | `File` 无 `Import From`，或子项无 SysML v2 文本导入，或灰显 | File 菜单全文、Import From 子项（若有）、Export To/Convert To 状态、About/License/Plugin 三项 | "该构建也没有可用文本导入路径" → 缩小"CE 限制 vs 产品限制"的范围 |
| **C｜入口在但失败** | 菜单存在、点了有反应，但导入报错 / 根命名空间未生成 | 错误原文、行号（若有）、日志尾部、**冒烟文件结果** | 差分：哪类构造不被支持；仍需版本指纹才有意义 |

**不允许的第四态**："部分成功所以算通过"。要么按 A 给出完整数字，要么按 C 记录失败。

---

## 4. 高风险构造清单（路线 C 的二分定位用）

如果导入失败，按下列顺序**逐条单独试**（把该行删掉/替换后重导），能快速定位不是我们文本整体不合法，而是某类构造不被支持：

| # | 文件行 | 构造 | 为什么会成为风险点 |
| ---: | --- | --- | --- |
| R1 | 3 | `package CoaxialOctoRotor { … }` 单包 | 基础；若这都失败说明通道问题 |
| R2 | 4–5 | `private import ScalarValues::*;` / `private import SI::*;` | 依赖标准库可用性 |
| R3 | 13、66、69、98 | `attribute … : Real = 1200.0 [W*h];`（**单位表达式**） | 单位语法的实现覆盖差异大 |
| R4 | 37、43、50、56 | `part batteryPack : BatteryPack[1] { … }`（定义里嵌 usage + 多重度 + 花括号体） | 嵌套 usage 的归属语义 |
| R5 | 61、63 | `part lowerPropeller : LowerRotor[4];`（多重的对外 usage） | 多重度数组语法 |
| R6 | 75–78 | `constraint def EnduranceBudget { … }`（体内**只有注释**） | 空体 + 注释的处理 |
| R7 | 80、82 | `connect batteryPack to escUnit;` | 连接语句的目标解析（需要先有 usage） |
| R8 | 86、89 | `part def LowerRotor;`（**无体的定义**） | 分号结尾的空定义 |
| R9 | 109–113 | `part x8System : CoaxialOctoRotorSystem[1] { … }`（体内只有注释） | 同 R6 |
| R10 | 116–162 | `requirement def` + **多条 `doc /* 中文 */`** + `attribute … : String = "…"`（中文值） | doc 注释重复；**中文字符串**；requirement 的特化语义 |
| R11 | 171–193 | `action def` + `in/out` 方向参数 + 参数后的 `//` 注释 | 参数方向语法 |
| R12 | 195–211 | `state def` + `entry; then Takeoff;` + `state Takeoff;` + `transition T first A then B;` + `transition … if (expr) then B;` | 状态机 DSL 的实现覆盖差异最大 |
| R13 | 全文 | UTF-8 中文注释与字符串 | 编码/字体；若对面导入后中文变问号，记下来但不影响结构判定 |

**判定辅助**：

- 冒烟 `00-smoke-minimal.sysml` 也失败 → **通道问题**（走 B/C，重点在版本指纹）；
- 冒烟成功、正式文件失败 → **文本子集差异**（走 C，按上表二分，报告里写明"最小失败片段"）。

---

## 5. 对面报告的"最低合格线"

不管走哪条路，下面 5 项必须齐（缺一项这份证据就不可用）：

1. 产品名 + 版本/build（`Help > About` 截图 + 文字）；
2. 许可类型（License Manager 截图）；
3. SysML v2 插件状态（Resource/Plugin Manager 截图）；
4. `File` 菜单全文（截图 + 文字）；
5. `inputs/golden-coaxial-power-chain.sysml` 的 sha256 与本包一致。

加分项：冒烟结果、导入树截图、校验诊断、导出文件与 sha256、日志整份。
