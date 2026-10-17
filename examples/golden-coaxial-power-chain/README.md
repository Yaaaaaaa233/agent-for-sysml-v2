# 标杆案例：共轴八旋翼功率链（Golden Case）

> 对应技术方案 7.3「精做一个完整的共轴八旋翼功率链 SysML 标杆模型」。
> 上位任务：9.1 的 T4 —— 需求 + 结构 + 参数（骨架）；**二期补齐行为**（2026-10-17 新增
> `StateDefinition` 飞行模式状态机）。至此**需求、结构、参数、行为四类元素齐备**。

## 文件

| 文件 | 说明 |
| --- | --- |
| `golden-coaxial-power-chain.ir.json` | **事实来源**：IR JSON（`schema: sysml-ir/v1`，34 个元素、20 条关系） |
| `golden-coaxial-power-chain.sysml` | `generate_sysml` 的产物，**由生成器输出后原样存档，不得手改** |
| `README.md` | 本页 |

校验状态：`validate_model_json` → **`ok = true`，0 error，0 warning**
回验状态：`verify_sysml`（lint + 元素级比对）→ **`ok = true`**，34/34 元素匹配，0 lint error

重新生成（产物与生成器逐字节一致由 `tests/test_examples.py` 钉住）：

```bash
cd sysml-modeling-agent/mcp-server
python run_server.py --call generate_sysml --input ../examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json \
  | python -c "import json,sys; sys.stdout.write(json.load(sys.stdin)['text'])" \
  > ../examples/golden-coaxial-power-chain/golden-coaxial-power-chain.sysml
```

---

## 模型讲的是什么

一条从**任务指标**走到**参数公式**的链：

```
任务级续航（≥5.0 h，含降落裕度）
   │ decomposes
   ├── 巡航续航（≥4.0 h）          ← 本案例的主角
   │      │ refines
   │      ├── 转速比区间（0.75 ≤ eta ≤ 1.25）
   │      └── 巡航功率预算（P_cruise ≤ 0.9·P_batt_max）
   │
   └── 被满足于 ─→ 功率链：电池 → 电调 → 电机 → 桨（上/下桨各一条支路）

参数（Attribute）：
   E_batt = 1200 Wh     usableEnergyFraction = 0.8     P_cruise = 240 W
   T = E_batt × usableEnergyFraction / P_cruise = 1200 × 0.8 / 240 = 4.0 h  ← 恰好满足下限
   eta_esc = 0.95   eta_motor = 0.85   eta_prop = 0.72（共轴双桨含气动干涉）

约束（Constraint）：
   EnduranceBudget：T = batteryCapacityWh × usableEnergyFraction / cruisePowerW
   参数绑定：batteryCapacityWh、usableEnergyFraction、cruisePowerW、enduranceHours

连接（Connection）：
   batteryToEsc（electrical）：batteryPack → escUnit
   upperMotorToPropeller（mechanical）：upperMotor → upperPropeller

行为（StateDefinition，二期补）：
   FlightModeStates：Takeoff →（完成迁移）→ Cruise → ReturnToHome → Landed
                     Cruise --[转速比越界]--> Fault → Landed
```

> **诚实红线**：以上 1200 Wh / 240 W / 0.95 / 0.85 / 0.72 / 4.0 h 等数值全部是**占位示例值**，
> 尚未用真实电池与桨的测试数据替换，**不得当作实测结论**。日常回验由项目内置 lint +
> 元素级比对完成（见 `docs/T0-调研结论.md`）。
>
> 2026-10-17 实测（范围限定）：生成器补上 `private import ScalarValues::*;` /
> `private import SI::*;` 两行标准库 import、并把 `Wh` 渲染为 `W*h` 之后，用官方
> Pilot Implementation 后端（`tools/official_parser.py`，release 2026-08）解析本案例
> 生成文本：**0 条诊断，`ok = true`**（证据：
> `docs/probe-official-parser/EVIDENCE.txt` §13；补上行为元素后重新实测的
> 34 元素版本见同文件 §14）。
> 这只说明**语法与引用解析**被官方实现接受；**语义/建模质量未验证**，因此**不能**
> 说「已通过官方解析器验证」这种整体性背书。补 import 之前的历史结果（0 语法 / 77 诊断）
> 留在 EVIDENCE §6–§8，仅作对照。

**关键设计意图**：`enduranceHours = 4.0` 不是拍出来的，而是由 `batteryCapacityWh`、
`usableEnergyFraction`、`cruisePowerW` 三个参数**换算**出来的，且恰好等于
`REQ-CRUISE-ENDURANCE` 的下限 4.0 h。这样演示时的一句话就是成立的：
**「改任何一个参数，续航需求是否还满足，立刻算得出来」**——这正是方案 10.2 那条
「模型 → 参数 → 仿真 → 验证」叙事链要的效果。

---

## 元素清单（34 个）

### 需求 4 条

| id | name | 阈值字段 | satisfiedBy |
| --- | --- | --- | --- |
| `REQ-MISSION-ENDURANCE` | `MissionEndurance` | `minMissionDurationHours: 5.0`、`minLandingReserveFraction: 0.15` | `PART-POWER-CHAIN` |
| `REQ-CRUISE-ENDURANCE` | `CruiseEndurance` | `minEnduranceHours: 4.0` | `PART-BATTERY-PACK` |
| `REQ-ROTOR-SPEED-RATIO` | `RotorSpeedRatioBand` | `minSpeedRatio: 0.75`、`maxSpeedRatio: 1.25`、`maxRotorSpeedRpm: 6200.0` | `ACT-ONLINE-OPTIMIZATION` |
| `REQ-POWER-BUDGET` | `CruisePowerBudget` | `maxCruisePowerW: 260.0`、`batteryDeratingFactor: 0.9` | `PART-POWER-CHAIN` |

四条都有 `verifyMethod`，且都被 `ACT-SIM-ENDURANCE` / `ACT-ONLINE-OPTIMIZATION` 用 `verifies` 覆盖
（所以没有 `W-REQ-NO-VERIFY`）。

### 结构 7 个定义 + 8 个用法

定义：`CoaxialOctoRotorSystem`、`PowerChain`、`BatteryPack`、`ElectronicSpeedController`、
`BrushlessMotor`、`UpperRotor`、`LowerRotor`

用法（全部带 `typeRef`，`quantity` 表达数量）：`x8System`(1)、`powerChain`(1)、`batteryPack`(1)、
`escUnit`(8)、`upperMotor`(4)、`lowerMotor`(4)、`upperPropeller`(4)、`lowerPropeller`(4)

> **7 个定义全部被实例化**——所以没有 `W-PARTDEF-UNUSED`。

### 参数 9 个（`Attribute`）

`cruiseSpeed` 15 m/s · `speedRatioEta` 1.0 · `batteryCapacityWh` 1200 Wh ·
`usableEnergyFraction` 0.8 · `cruisePowerW` 240 W · `enduranceHours` 4.0 h ·
`escEfficiency` 0.95 · `motorEfficiency` 0.85 · `propellerEfficiency` 0.72

### 功能 2 个（`ActionDefinition`）

- `EnduranceSimulationRun` —— 续航仿真工况（输入 v、eta，输出 T）
- `OnlinePowerOptimization` —— 在线功率优化（输入功率遥测、空速估计，输出 v、eta）

### 行为 1 个（`StateDefinition`，二期补，2026-10-17）

`FlightModeStates` —— 飞行模式状态机（5 状态 / 5 迁移，`initial = Takeoff`）：

| from → to | trigger（自由文本，`// trigger:` 注释） | guard（正式 `if (...)`） |
| --- | --- | --- |
| `Takeoff` → `Cruise` | —（**完成迁移**：起飞爬升结束即离开） | — |
| `Cruise` → `ReturnToHome` | 返航指令或任务段剩余时间不足 | — |
| `Cruise` → `Fault` | 转速比越界或功率遥测持续异常 | `x8System.speedRatioEta <= 0.75` |
| `ReturnToHome` → `Landed` | 触地检测（起落架受压） | — |
| `Fault` → `Landed` | 迫降完成（触地检测） | — |

设计约束（`skills/anti-patterns` 第 16 条）：初始态 `Takeoff` 的出边是**完成迁移**，不挂
`trigger` / `guard`；「起飞指令」这类事件迁移一律从非初始态出发。`Landed` 是终止状态，没有出边。
`StateDefinition` **不新增追溯关系**（关系数保持 20）。

- guard 里的 `0.75` 是**占位阈值**（与 `REQ-ROTOR-SPEED-RATIO.minSpeedRatio` 同源），非实测结论。
- `x8System.` 前缀不是装饰：官方解析器要求嵌套特征用点号访问，裸写 `speedRatioEta` 会被判
  `Must be an accessible feature (use dot notation for nesting)`。该形态已随本节更新重新实测
  （0 条诊断，见 `docs/probe-official-parser/EVIDENCE.txt` §14）。

### 约束 1 个（`Constraint`，v1 增补）

- `EnduranceBudget` —— 续航换算公式 `T = batteryCapacityWh * usableEnergyFraction / cruisePowerW`；
  `parameters` 绑定 4 个已有 `Attribute`（含结果量 `enduranceHours`）。
  生成文本里以 `constraint def EnduranceBudget { // expression: ... // parameters: ... }` 承载。

### 连接 2 个（`Connection`，v1 增补）

| id | name | 端点 | flowKind |
| --- | --- | --- | --- |
| `CONN-BATTERY-ESC` | `batteryToEsc` | `batteryPack` → `escUnit` | `electrical` |
| `CONN-UPPER-MOTOR-PROP` | `upperMotorToPropeller` | `upperMotor` → `upperPropeller` | `mechanical` |

两个 `Connection` 与两端 `PartUsage` 同属 `PART-POWER-CHAIN`；生成文本里渲染为
结构化注释 + `connect <src> to <tgt>;`。

---

## 为什么是这个范围（T4 的取舍，如实说明）

| 方案 7.3 要求的 | 本期状态 |
| --- | --- |
| 需求：任务级续航 → 巡航 ≥4h → 转速比区间 | ✅ 已覆盖（另加一条功率预算需求作为能量侧约束） |
| 结构：电池→电调→电机→桨的功率链（含上下桨） | ✅ 已覆盖，上下桨各一条支路，`connects` 逐段连接 |
| 参数：功率公式、电池容量换算 | ✅ 已覆盖：参数齐备，并用正式 `Constraint`（`EnduranceBudget`）承载续航换算公式；`parameters` 逐个绑定到 `Attribute`。 |
| 行为：起飞→爬升→巡航→返航→降落状态机 | ✅ **已覆盖**（二期 2026-10-17 补 `StateDefinition` `FlightModeStates`：`Takeoff` 完成迁移进 `Cruise`，`Cruise` 可被返航指令或转速比越界事件打断，`ReturnToHome` / `Fault` 两条路径收束到 `Landed`）。`tests/test_examples.py` 钉住「四类元素齐备且 `StateDefinition` 恰好 1 个」。 |

**关于单位/数量/状态迁移的语法（v1 增补）**：`Attribute.unit`、`PartUsage.quantity` 与
`transitions` 已从注释改为正式后缀/语句形态（`[W]`、`[8]`、官方 `entry; then X;` 与
`transition <name> first ... [if (...)] then ...;`；trigger 用 `// trigger:` 注释），
规则见 `mcp-server/schema/渲染约定.md`。单位 `Wh` 在文本里写作 `W*h`（官方标准库没有
`Wh`），由生成器别名映射、`parse_sysml` 逆映射回 `Wh`。上述语法形态经官方 Pilot
Implementation 实测 0 error（2026-10-17，EVIDENCE §13），但该结论只覆盖语法与引用解析，
语义/建模质量未验证；内置 lint + 元素级比对不等同于官方解析器。

---

## 这份案例的五个用途（方案 7.3）

1. **few-shot 范例** —— 给 LLM 看的「照着这样填」的完整样本（配套 `skills/element-choice` 的案例讲解）
2. **领域模板** —— 可裁剪成四旋翼变体
3. **测试基准** —— `tests/test_examples.py` 用它做端到端回归
4. **知识库镇馆** —— `knowledge/samples/` 的首份入库材料（见 `knowledge/README.md`）
5. **比赛展示物** —— 「从一句需求到模型到参数到仿真」的现场演示起点

---

## 已知待办（二期）

- [x] 行为建模：已补 `StateDefinition`（`FlightModeStates`：起飞 → 巡航 → 返航 → 降落，含故障分支）。
      细化项（逆风/顺风的状态内参数漂移）仍是**后续可选**增强，尚未建模。
- [x] 参数公式：已补正式 `Constraint`（`EnduranceBudget`），公式不再只写在 `description` 里
- [x] 单位与数量：后缀语法已落地（`[W]` / `[8]`），并已用官方解析器实测语法/引用解析 0 error（EVIDENCE §13，2026-10-17）；语义/建模质量仍未验证
- [x] 追溯矩阵：`traceability`（T9）已落地，本案例的矩阵与「改需求看影响面」演示见
      `docs/demo/run-phase2-change/`
- [ ] 参数来源核实：`1200 Wh` / `240 W` / `0.95` / `0.85` / `0.72` 等数值目前是**示例值（占位）**，
      需由团队用真实电池与桨的测试数据替换。**在替换之前，本案例的任何数值都不得作为实测结论呈现**
      （方案 10.2 的数据真实性红线）。
