---
name: domain-patterns
description: "无人机领域建模套路库：功率链（电池→电调→电机→桨）、功率公式的约束组织、续航需求逐级分解、单桨失效冗余保护、在线优化决策量的约束区间。每个模式给「什么时候用 / 骨架片段 / 常见错法」，当任务涉及功率、续航、旋翼、失效保护或在线寻优时加载本 skill。Triggers: 功率链, 功率, 续航, 电池, 电调, 电机, 桨, 旋翼, 共轴, 八旋翼, 单桨失效, 冗余, 失效保护, 在线优化, 约束区间, 转速比, domain pattern."
metadata:
  version: "1.0.0"
  last_updated: "2026-10-17"
  status: active
  task_type: open-ended
  related_skills:
    - modeling-workflow
    - element-choice
    - anti-patterns
    - worked-examples
---

# domain-patterns —— 无人机领域建模套路

**一句话：领域套路是「先摆哪几块、线往哪连、数放哪格」的固定打法。**
它不替代 `modeling-workflow` 的九步，而是在第 3~6 步里告诉你**这个领域通常怎么摆**。

**用法**

1. 先按下面的「选模式」定位到 1~2 个模式；
2. 照着**骨架片段**摆元素、连关系；
3. 交付前逐条过**常见错法**；
4. 拿不准某个元素该不该建 → 叠加 `element-choice`；报错 → 叠加 `anti-patterns`；
   想看完整走通一遍的样子 → 叠加 `worked-examples`。

> **数值纪律**：本文所有具体数字——1200 Wh、240 W、0.95、0.85、0.72、4.0 h、
> 0.75 / 1.25、6200 rpm、100 ms、2.0 m、5.0 deg 等——**全部是占位值**，
> 只用于演示「填在哪一格」，**不得当作实测结论**。标杆案例里的同名数值同样是占位值。

> **解析器红线**：本 skill 的片段与渲染文本**没有**经过官方 SysML v2 解析器验证
> （本机无可用官方解析器，见 `docs/T0-调研结论.md`）。只经过仓库内
> `validate_model_json` / `generate_sysml` / `verify_sysml`。
> 对外只能如实说「通过了仓库内校验与元素级回验」。

> **三档表述**：**模型事实**（工具查证）/ **规范语义**（SysML v2 与方案约定）/
> **推断**（我的判断，需你确认）。模式里的「通常这样摆」是**推断性经验**，不是规范。

---

## 选模式

```
任务里有「电池 / 电调 / 电机 / 桨 / 功率链」？
  └─ 模式 1（功率链结构）
任务里有公式（P=U·I、T=E/P、效率乘积）或要挂参数？
  └─ 模式 2（功率公式的约束组织）
任务里有「续航 / 航时 / 任务时间」要拆到子系统或功能？
  └─ 模式 3（续航需求逐级分解）
任务里有「失效 / 冗余 / 不坠毁 / 安全返回」？
  └─ 模式 4（单桨失效保护）
任务里有「在线寻优 / 决策量 / 上下界 / 转速比区间」？
  └─ 模式 5（优化决策量的约束区间）
```

> 五个模式经常**组合**出现：续航指标（3）落到功率链（1），功率链上挂公式（2），
> 飞行/失效行为用状态机（4），在线寻优输出受区间约束（5）。组合顺序建议：
> **先结构（1）→ 再参数/约束（2）→ 再需求分解（3）→ 再行为（4/5）**，
> 因为后一步总要引用前一步的 id。

---

## 模式 1：功率链（电池 → 电调 → 电机 → 桨）

**什么时候用**

- 要建/改整机功率链，或任何「能量从电池一路走到桨」的结构；
- 续航、效率、功率预算类需求要落到结构上（`satisfiedBy`）；
- 需要给仿真导出「每一环是什么、几份、怎么连」。

**骨架片段**（完整可运行：[01-power-chain-mini.ir.json](examples/01-power-chain-mini.ir.json)）

```
5 个 PartDefinition：BatteryPack / ElectronicSpeedController / BrushlessMotor / Propeller
                  + PowerChain（整体）
1 个 PartUsage：powerChain（整体那一份，typeRef → PowerChain）
6 个 PartUsage（owner = powerChain）：
    batteryPack(1) → escUnit(8) → upperMotor(4) / lowerMotor(4)
                                → upperPropeller(4) / lowerPropeller(4)
    ← 共轴构型：上下桨各一条并联支路；数量为占位值
连接：每段一条，二选一，不要重复：
    · connects 关系（轻量，无 flowKind）
    · Connection 元素（v1 增补，带 flowKind = electrical / mechanical）
```

```json
{ "id": "PART-USE-ESC", "kind": "PartUsage", "name": "escUnit",
  "owner": "PART-USE-POWER-CHAIN",
  "properties": { "typeRef": "PART-DEF-ESC", "quantity": 8 } }
```

渲染（当前模板输出，节选；`connects` 形态）：

```
part powerChain : PowerChain[1] {
    part batteryPack : BatteryPack[1];
    part escUnit : ElectronicSpeedController[8];
    part lowerMotor : BrushlessMotor[4];
    part upperMotor : BrushlessMotor[4];
    part lowerPropeller : Propeller[4];
    part upperPropeller : Propeller[4];
    //   PART-USE-ESC --connects--> PART-USE-MOTOR-UPPER  (四路电调驱动上桨电机。)
    //   PART-USE-ESC --connects--> PART-USE-MOTOR-LOWER  (四路电调驱动下桨电机。)
}
```

**常见错法**

| 错法 | 后果 | 对位 |
| --- | --- | --- |
| 写成「电池 → 电机 → 桨」，漏掉电调 | 效率链少一个乘积项，续航算乐观；导出参数少一项 | 反模式第 6 条 |
| 只建 `PartDefinition`，不建 `PartUsage` | 数量、连接、`satisfiedBy` 全无处落脚 | 反模式第 8 条 |
| 上下桨只建一条支路 | 共轴八旋翼被算成四旋翼 | 反模式第 6 条 |
| `quantity: "8"` 或把数量写进 `description` | 不能参与计算/导出 | 反模式第 4 条 |
| 同一条边既写 `connects` 又建 `Connection` | 追溯图出现平行边，评审看不出哪条算数 | 本模式自检 |

**自检**

- [ ] 四层（电池/电调/电机/桨）都在吗？上下桨各一条支路吗？
- [ ] 每个 `PartUsage.typeRef` 都指向 `PartDefinition` 吗？
- [ ] `quantity` 是数字吗？总数与构型对得上吗（8 路 = 上下各 4）？
- [ ] 每条边只描述一次；`Connection` 两端同 owner、`sourceRef != targetRef` 吗？
- [ ] 从电池能沿连接一路走到桨吗？（`query_model(referrers_of=<末端>)` 自查）

---

## 模式 2：功率公式的约束组织（Constraint + Attribute）

**什么时候用**

- 模型里出现**恒等式**：`P = U·I`、`T = E/P`、`P_elec = P_mech / (eta_esc·eta_motor·eta_prop)`；
- 要把「公式用了哪几个参数」变成**可查的引用**，而不是一段说明文字；
- 需求侧只该留门槛（如「不超过 260 W」），公式本身不该变成需求。

**骨架片段**（`Constraint` 是 **v1 增补 kind**；完整可运行：
[02-power-formula-mini.ir.json](examples/02-power-formula-mini.ir.json)，带 `Constraint` 的完整版见
`worked-examples` 的范例 2）

```
Attribute（owner = 被约束的那个 PartDefinition）
    busVoltageV      24.0 V   ← 占位
    cruiseCurrentA   10.0 A   ← 占位
    cruisePowerW    240.0 W   ← 占位
    escEfficiency     0.95     ← 占位
    motorEfficiency   0.85     ← 占位
    propellerEfficiency 0.72   ← 占位
Constraint（owner = 同一个 PartDefinition）
    expression = "P_cruise = U_batt * I_cruise"      ← 单行，别换行
    parameters = [三个 Attribute 的 id]
Requirement（门槛，不是公式）
    maxCruisePowerW = 260.0
```

```json
{ "id": "CON-POWER-LAW", "kind": "Constraint", "name": "PowerLaw",
  "owner": "PART-DEF-POWER-CHAIN",
  "properties": {
    "expression": "P_cruise = U_batt * I_cruise",
    "parameters": ["ATTR-BUS-VOLTAGE", "ATTR-CRUISE-CURRENT", "ATTR-CRUISE-POWER"],
    "description": "物理关系式，不是需求；v1 增补 kind。" } }
```

渲染（当前模板输出，节选）：

```
part def PowerChain {
    attribute busVoltageV : Real = 24.0 [V];
    attribute cruiseCurrentA : Real = 10.0 [A];
    attribute cruisePowerW : Real = 240.0 [W];
    constraint def PowerLaw {
        // expression: P_cruise = U_batt * I_cruise
        // parameters: busVoltageV, cruiseCurrentA, cruisePowerW
    }
}
```

> **兼容形态**：工具版本还没收录 `Constraint` 时，把公式写进承载它的 `Attribute.description`
> （例如 `cruisePowerW` 的 description），能通过校验、能渲染；但**没有参数引用**，
> `query_model` 追不到公式用了谁。只作过渡，别当目标形态。**不要**为了放公式自创 kind（反模式第 9 条）。

**常见错法**

| 错法 | 后果 | 对位 |
| --- | --- | --- |
| 把 `P = U·I` 建成 `Requirement` | 需求链里多一条永远不失败的需求 | 反模式第 5 条 |
| `expression` 写多行 / 带换行 | schema 拒绝（单行 pattern） | `propsConstraint` 约束 |
| `parameters` 指向 `Requirement` 或 id 不存在 | 参数无法解析，公式不可查 | 反模式第 2 条 |
| 参数值散落在 `description` 里，不建 `Attribute` | 仿真导不出、改值要改文本 | 模式 2 自检 |
| 把门槛也塞进公式（`P <= 260`） | 约束与需求混层，评审分不清哪个会失败 | 模式 5 |

**自检**

- [ ] 每条公式都问过「换个设计它变不变」？不变 → 约束，不是需求。
- [ ] `expression` 单行、非空；`parameters` 至少 1 项，且每个都能解析到 `Attribute` 吗？
- [ ] 公式里的每个符号，都能在 `parameters` 里找到对应的 `Attribute` 吗？（符号名与 `Attribute.name` 不必逐字相同，但对应关系要写清）
- [ ] 门槛留在 `Requirement` 的数值字段里了吗？
- [ ] 渲染文本里的 `// expression` / `// parameters` 只是注释承载，**没有被官方解析器回验过**——汇报时说清了吗？

---

## 模式 3：续航需求逐级分解

**什么时候用**

- 顶层指标是「任务级续航 / 航时」，要落到子系统或功能；
- 评审问「这条需求谁满足、谁验证」，而你只有一句总指标；
- 需要判断该用 `decomposes` 还是 `refines`。

**分解层级**（与 `element-choice` 案例 8 的既有结论一致）

```
顶层任务需求（任务剖面、总时长）
   │ decomposes
   ├── 子系统需求（巡航续航、功率预算……）
   │      │ decomposes / refines
   │      └── 功能需求（转速比区间、检测时延……）
   └── 每条都各自接 satisfiedBy + verifies
```

**拆到哪一层为止**：**拆到「单条可被一个部件或一个功能满足」为止**。
拆出来的每一条都要能独立写验收判据；写不出判据的那一层不是需求，是标题（反模式第 1 条）。

**骨架片段**（完整可运行：[03-endurance-decomposition-mini.ir.json](examples/03-endurance-decomposition-mini.ir.json)）

```
REQ-MISSION-ENDURANCE  minMissionDurationHours = 5.0   ← 占位
   ├── decomposes → REQ-CRUISE-ENDURANCE  minEnduranceHours = 4.0   ← 占位
   ├── decomposes → REQ-POWER-BUDGET      maxCruisePowerW = 260.0   ← 占位
   └── satisfiedBy → PART-USE-POWER-CHAIN（系统级满足方，真实存在，不是虚设的「综合部件」）
每条子需求：satisfiedBy（结构或功能）+ verifies（仿真/试验动作）
```

渲染（当前模板输出，节选）：

```
requirement def MissionEndurance {
    doc /* 任务级续航：完成起飞、巡航与安全返航。 */
    doc /* 验收判据: 标称任务剖面下全程可用飞行时间 T_mission >= 5.0 h（占位值）。 */
    attribute minMissionDurationHours : Real = 5.0;
    //   REQ-MISSION-ENDURANCE --decomposes--> REQ-CRUISE-ENDURANCE  (任务剖面中最长的一段是巡航，单列为可验证子条。)
    //   REQ-MISSION-ENDURANCE --decomposes--> REQ-POWER-BUDGET  (能量侧分解：功率不越界才能保证时间指标。)
    //   REQ-MISSION-ENDURANCE --satisfiedBy--> PART-USE-POWER-CHAIN  (系统级满足方是整条功率链，不是虚设的「综合部件」。)
}
```

**常见错法**

| 错法 | 后果 | 对位 |
| --- | --- | --- |
| 子需求只写「满足任务要求」 | 无法验证，等于没拆 | 反模式第 1 条 |
| 跳级：从任务需求直接拆到「软件里算」 | 中间层缺失，追溯矩阵断层 | 模式 3 自检 |
| 给父需求硬塞一个「综合部件」来满足 | 凭空造结构，评审会问这部件是什么 | element-choice 案例 8 |
| 把 `refines` 当 `decomposes` 用 | 需求树缺子条，`query_model` 看不到分解 | element-choice 案例 8 |
| 子需求只有 `satisfiedBy`，没有 `verifies` | `W-REQ-NO-VERIFY`，断验证链 | 反模式第 10 条 |
| 拆到每条都带「优化」「管理」这类词 | 判据写不出，后面全崩 | 反模式第 1 条 |

**自检**

- [ ] 每条子需求都能独立写出通过/不通过判据吗？
- [ ] 每条子需求都能指到一个**具体的部件或功能**吗？（指不到 → 还没拆到底或拆错了）
- [ ] 父需求的满足是「子需求集体满足」，还是硬塞了一个综合部件？
- [ ] `decomposes` 与 `refines` 用对了吗？（并列子条 vs 同一要求的更精确表述）
- [ ] 每条都有 `satisfiedBy` + `verifies` 吗？`query_model(unsatisfied_requirements=true)` 是 0 吗？

---

## 模式 4：八旋翼单桨失效保护 / 冗余

**什么时候用**

- 需求里出现「单桨失效不坠毁 / 失效后安全返回 / 冗余」；
- 要把一句安全目标拆成可验证的检测、姿态、分配、高度子条；
- 需要描述「正常 → 检测到失效 → 重构 → 安全降落/继续任务」的行为。

**骨架片段**：需求分解（父 + 四条子需求；每条各自有判据、满足链、验证链）

```
REQ-FAIL-SAFE  单桨失效时无人机不坠毁   maxAltitudeLossM=2.0  maxAttitudeErrorDeg=5.0（占位）
   ├── REQ-FAIL-DETECT    失效检测      maxDetectionTimeMs=100（占位）   satisfiedBy ACT-FAIL-DETECT
   ├── REQ-FAIL-ATTITUDE  姿态保持      maxAttitudeErrorDeg=5.0（占位）  satisfiedBy ACT-HOLD-ATTITUDE
   ├── REQ-FAIL-ALLOC     控制分配重构  （可被控制分配功能满足）
   └── REQ-FAIL-ALTITUDE  高度保持      maxAltitudeLossM=2.0（占位）
父需求：satisfiedBy → PART-USE-X8（整机，不是虚设的综合部件）+ 仿真动作 verifies
```

> 上面四条是**完整清单**；配套迷你模型
> [04-single-rotor-failure-mini.ir.json](examples/04-single-rotor-failure-mini.ir.json) 只落了检测与姿态两条，
> 用来把骨架压到可运行的最小尺寸——**别把「迷你」当成「只要两条」**。

**骨架片段**：状态机

```
Standby（initial，出边是完成迁移，不挂 trigger/guard）
  → Normal
      → FailureDetected        [trigger: failure detected]
          → Reconfigured       [trigger: control allocation updated]
              → SafeLanding    [trigger: post-reconfiguration check, guard: remainingMissionFeasible == false]
              → Normal         [trigger: post-reconfiguration check, guard: remainingMissionFeasible == true]
```

渲染（当前模板输出，节选）：

```
state def SingleFailureStates {
    initial Standby;
    state Standby;
    state Normal;
    state FailureDetected;
    state Reconfigured;
    state SafeLanding;
    transition from Standby to Normal;
    transition from Normal to FailureDetected when failure detected;
    transition from FailureDetected to Reconfigured when control allocation updated;
    transition from Reconfigured to SafeLanding when post-reconfiguration check if (remainingMissionFeasible == false);
    transition from Reconfigured to Normal when post-reconfiguration check if (remainingMissionFeasible == true);
}
```

**常见错法**

| 错法 | 后果 | 对位 |
| --- | --- | --- |
| 同一判定出口守卫重叠（`[>= 0.5]` 与 `[>= 0.3]`） | 落到哪条不确定 | 反模式第 15 条 |
| 守卫不完备，没有兜底 | 某种情况「不知道去哪」 | 反模式第 15 条 |
| `initial` 的出边挂 trigger / guard | 入口永远在等一个不会来的事件 | 反模式第 16 条 |
| 只建「失效检测」，不建重构/高度 | 安全目标没有完整满足链 | 模式 4 自检 |
| 把「保护模式」建成一个 `ActionDefinition` | 它需要持续停留并等事件，不是一次性动作 | 反模式第 7 条 |
| 父需求硬塞一个「冗余管理器」部件 | 凭空造结构，评审问不住才怪 | element-choice 案例 8 |

**自检**

- [ ] 父需求的四条子需求齐了吗？每条都能独立判定吗？
- [ ] 每条子需求都指到一个具体功能/部件了吗？
- [ ] 状态机的守卫**互斥且完备**吗？（二分守卫最稳：`feasible == true` / `== false`）
- [ ] `initial` 状态的出边没有 trigger / guard 吗？
- [ ] 「失效检测」「姿态保持」这些状态/动作，和需求用 `satisfiedBy` / `verifies` 连上了吗？

---

## 模式 5：在线优化决策量的约束区间

**什么时候用**

- 有在线寻优/决策量（转速比 eta、巡航速度 v、桨转速），需要**上下界**；
- 要证明「任意寻优输出都落在允许区间」；
- 需要把区间同时表达成**需求门槛**与**约束公式**，并接到状态机的自迁移上。

**骨架片段**（完整可运行：[05-optimization-band-mini.ir.json](examples/05-optimization-band-mini.ir.json)）

```
Requirement：REQ-ROTOR-SPEED-RATIO
    minSpeedRatio = 0.75   maxSpeedRatio = 1.25   maxRotorSpeedRpm = 6200   ← 全是占位
    acceptanceCriteria：「任意寻优输出满足 0.75 <= eta <= 1.25，且转速 <= 6200 rpm」
    satisfiedBy → ACT-ONLINE-OPT
Attribute（owner = 整机定义）：minSpeedRatio / maxSpeedRatio / maxRotorSpeedRpm / etaCmd
Constraint（v1 增补 kind）：
    expression = "eta_min <= eta_cmd and eta_cmd <= eta_max"
    parameters = [ATTR-ETA-MIN, ATTR-ETA-MAX, ATTR-ETA-CMD]   ← 全部是已存在的 Attribute
ActionDefinition：OnlinePowerOptimization
    inputs: powerTelemetry(W), airspeedEstimate(m/s)
    outputs: speedRatioCommand, speedCommand(m/s)
    verifies → REQ-ROTOR-SPEED-RATIO
StateDefinition（可选）：Cruising 自迁移
    [trigger: wind gust, guard: speedRatio 在区间内] 与 [guard: 不在区间内] 二分
```

渲染（当前模板输出，节选）：

```
part def CoaxialOctoRotorSystem {
    attribute etaCmd : Real = 1.0 [1];
    attribute maxRotorSpeedRpm : Real = 6200.0;
    attribute maxSpeedRatio : Real = 1.25;
    attribute minSpeedRatio : Real = 0.75;
    constraint def SpeedRatioBand {
        // expression: eta_min <= eta_cmd and eta_cmd <= eta_max
        // parameters: minSpeedRatio, maxSpeedRatio, etaCmd
    }
}

requirement def RotorSpeedRatioBand {
    doc /* 在线寻优给出的转速比必须落在允许区间内。 */
    doc /* 验收判据: 对任意寻优输出满足 0.75 <= eta <= 1.25（占位值），且桨转速 <= 6200 rpm（占位值）。 */
    attribute maxRotorSpeedRpm : Real = 6200.0;
    attribute maxSpeedRatio : Real = 1.25;
    attribute minSpeedRatio : Real = 0.75;
    //   REQ-ROTOR-SPEED-RATIO --satisfiedBy--> ACT-ONLINE-OPT  (由在线寻优在求解时施加区间约束。)
}

action def OnlinePowerOptimization {
    in powerTelemetry : Real;  // unit: W
    in airspeedEstimate : Real;  // unit: m/s
    out speedRatioCommand : Real;
    out speedCommand : Real;  // unit: m/s
    //   ACT-ONLINE-OPT --verifies--> REQ-ROTOR-SPEED-RATIO  (对寻优输出逐点检查区间约束。)
}
```

**常见错法**

| 错法 | 后果 | 对位 |
| --- | --- | --- |
| 区间只写进 `acceptanceCriteria` 字符串，没有数字字段 | 无法参与校核/导出 | 反模式第 4 条 |
| 把「必须落在区间」写成 `Constraint`，需求侧空着 | 门槛没人负责，评审问「谁保证」 | 反模式第 5 条（反向误用） |
| `Constraint.parameters` 里写了不存在的 id | 参数解析失败 | 反模式第 2 条 |
| 优化动作没有 `inputs`/`outputs` | 不是功能，是标题 | `modeling-workflow` 第 3 步 |
| 上下界/单位不一致（一个 0.75、一个 1.25 %） | 区间失效且很难看出来 | 模式 5 自检 |
| 状态机守卫写成开区间与闭区间混用 | 边界值落空或双命中 | 反模式第 15 条 |

**自检**

- [ ] 决策量的**每个**上下界都有独立的数字字段吗？单位一致吗？
- [ ] 需求门槛（`Requirement`）与约束公式（`Constraint`）**分层**了吗？
- [ ] `parameters` 引用的每个 id 都真实存在且是 `Attribute` 吗？
- [ ] 优化动作有明确的输入和输出吗？输出能被仿真核验吗？
- [ ] 区间边界在状态机守卫里是闭区间还是开区间？与需求写的 `<=` / `<` 一致吗？

---

## 模式组合：一次任务里的推荐顺序

```
1. 模式 1  先摆功率链结构（拿到全部 PartUsage id）
2. 模式 2  在结构上挂参数与公式（拿到 Attribute / Constraint id）
3. 模式 3  把续航指标逐级拆到「一个部件/功能能满足」
4. 模式 4  失效/安全行为：需求分解 + 状态机
5. 模式 5  在线决策量：需求阈值 + 约束区间 + 状态自迁移
6. 回到 modeling-workflow 第 7~9 步：校验 → 追溯 → 生成回验 → 三档汇报
```

## 常见卡点

| 卡在哪 | 十有八九是 |
| --- | --- |
| 功率链怎么连都少一环 | 漏了电调，或上下桨只建了一条支路（模式 1） |
| 公式没地方放 | 还在用旧工具版本；先用 `Attribute.description` 过渡，升级到收录了 `Constraint` 的版本后按模式 2 迁移 |
| 续航拆不下去 | 叶子层没有「一个部件/功能」可指，说明还没拆到功能需求（模式 3） |
| 单桨失效的守卫写不清 | 没有用二分守卫；补 `feasible == true / false`（模式 4） |
| 优化输出越界没人管 | 区间只写在判据字符串里，没建数值字段与约束（模式 5） |
