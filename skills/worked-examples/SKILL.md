---
name: worked-examples
description: "五个带完整推理过程的建模范例：从一句话需求 → 分类判断 → IR JSON → 渲染片段 → 校验结果 → 追溯落点，并解释「为什么这么选」。当用户说「照着上次那样做 / 有没有例子 / 给我个范例 / 照着这个写」，或你在两条建法之间犹豫、想先看一个能跑通的完整样本时加载本 skill。Triggers: 范例, 示例, 例子, 照着这个写, 照着上次那样做, 参考案例, 有没有例子, 怎么写这条, few-shot, worked example, show me an example, sample model."
metadata:
  version: "1.0.0"
  last_updated: "2026-10-17"
  status: active
  task_type: open-ended
  related_skills:
    - modeling-workflow
    - element-choice
    - anti-patterns
    - domain-patterns
---

# worked-examples —— 五个带推理的范例

**一句话：别只抄 JSON，要抄判断过程。** 五个范例都按同一副骨架走：

```
一句话需求 → 分类判断 → IR JSON → 关键渲染片段 → 校验结果 → 追溯落点 → 为什么这么选
```

**用法**

1. 先找与你手上任务**最像**的那个范例（见下面的索引），只读那一个。
2. 读的时候盯住两处：**分类判断**（为什么是这个 kind）与**为什么这么选**（岔路口/反模式条目）。
3. 抄结构，不抄数值：把范例里的占位值换成你项目里**有来源**的数，再走 `modeling-workflow` 的九步。
4. 范例里的 IR 都是**完整可运行**的：`examples/` 下每个文件都能直接喂给 `validate_model_json` 与
   `generate_sysml`。想验证「先错后改」，把 `05-...before.ir.json` 跑一遍即可。

> **解析器红线（逐字遵守）**：本 skill 与它生成的文本**没有**经过官方 SysML v2 解析器验证——
> 本机没有可用的官方解析器（见 `docs/T0-调研结论.md`）。我们只跑仓库内的
> `validate_model_json` / `generate_sysml` / `verify_sysml` 三件套。
> 对外**不许**把仓库内回验说成「官方解析器跑过」；只能说「通过了仓库内校验与元素级回验」。

> **数值纪律**：本文出现的每个具体数字——4.0 h、1200 Wh、240 W、0.95、0.85、0.72、24 V、10 A、
> 6200 rpm、100 ms、2.0 m、5.0 deg、0.75/1.25 等——**全部是占位值**，只用于演示「填在哪一格、量纲怎么放」，
> **不得当作实测结论**，也不代表任何真实机型性能。标杆案例
> `examples/golden-coaxial-power-chain/` 里的同名数值同样是占位值。换真实数据前，汇报里只能写「示例值」。

> **三档表述**：**模型事实**（工具查证过的）/ **规范语义**（SysML v2 与方案的约定）/
> **推断**（我的判断，需你确认）。下面每个范例的「校验结果」是模型事实；「为什么这么选」里
> 涉及设计取舍的部分是推断。

---

## 范例索引

| # | 一句话需求 | 主 kind | 最容易踩的坑 | 文件 |
| --- | --- | --- | --- | --- |
| 1 | 巡航时间不低于 4 小时 | `Requirement` | 阈值写成 `"4 小时"`；只写 text 不写判据 | [01](examples/01-endurance-requirement.ir.json) |
| 2 | 把 P = U·I 写进模型 | `Constraint` + `Attribute` | 把物理定律建成需求 | [02](examples/02-power-law-constraints.ir.json) |
| 3 | 遇逆风要调整、电量低要返航 | `StateDefinition` + `ActionDefinition` | 状态机画成流程图；守卫重叠 | [03](examples/03-flight-mode-states.ir.json) |
| 4 | 电池→电调→电机→桨 | `PartDefinition` + `PartUsage` + `Connection` | 漏电调；只建定义不建用法 | [04](examples/04-power-chain-structure.ir.json) |
| 5 | 加续航需求 + 额定电压 | 先错后改 | 悬空引用；把常量写成需求 | [before](examples/05-constant-as-requirement.before.ir.json) / [fixed](examples/05-constant-as-requirement.fixed.ir.json) |

> **版本说明**：`Constraint` 与 `Connection` 是 **v1 增补 kind**（方案 4.3 第 7、8 项，在 v1 内向后兼容新增，
> schema 版本号不变）。本仓库当前 schema 已收录；若你的工具版本尚未同步，范例 2 末尾给了
> 「用 `Attribute.description` 承载公式」的兼容形态——能跑，但不可被 `parameters` 追溯。

---

## 范例 1：可量化续航需求 —— 阈值拆数值属性

**一句话需求**：「给共轴八旋翼加一条：巡航时间不低于 4 小时。」

**分类判断**

- **岔路口 A（有没有可判定的验收标准）**：能写出「T >= 4.0 h」这种通过/不通过客观可判的句子 → **`Requirement`**。
- 不是 `Attribute`：换个电池、换载荷这句话就变了（element-choice 案例 1 的反例对照）——**会变的是需求**。
- 反模式对位：**反模式第 1 条**（需求没有验收判据）、**第 4 条**（把单位写进字符串）、
  **第 10 条**（没有 `satisfiedBy` / `verifies`）。

**IR JSON**（节选；完整文件见 [01-endurance-requirement.ir.json](examples/01-endurance-requirement.ir.json)）

```json
{
  "id": "REQ-CRUISE-ENDURANCE",
  "kind": "Requirement",
  "name": "CruiseEndurance",
  "owner": "EnduranceDemo",
  "properties": {
    "text": "巡航时间不低于 4 小时。",
    "acceptanceCriteria": "在巡航速度 v 与转速比 eta 的稳态工作点下，满电续航时间 T >= 4.0 h。",
    "verifyMethod": "simulation",
    "priority": "high",
    "minEnduranceHours": 4.0
  },
  "relations": [
    { "type": "satisfiedBy", "target": "PART-USE-POWER-CHAIN",
      "rationale": "续航由功率链的可用能量与巡航功率共同决定。" }
  ]
}
```

**关键渲染片段**（当前模板输出，节选）

```
requirement def CruiseEndurance {
    doc /* 巡航时间不低于 4 小时。 */
    doc /* 验收判据: 在巡航速度 v 与转速比 eta 的稳态工作点下，满电续航时间 T >= 4.0 h。 */
    attribute verifyMethod : String = "simulation";
    attribute minEnduranceHours : Real = 4.0;
    // 追溯关系 (relations):
    //   REQ-CRUISE-ENDURANCE --satisfiedBy--> PART-USE-POWER-CHAIN  (续航由功率链的可用能量与巡航功率共同决定。)
}

action def EnduranceSimulationRun {
    in cruiseSpeed : Real;  // unit: m/s
    in speedRatioEta : Real;
    out enduranceHours : Real;  // unit: h
    //   ACT-SIM-ENDURANCE --verifies--> REQ-CRUISE-ENDURANCE  (用仿真工况验证续航阈值。)
}
```

**校验结果**（模型事实）

- `validate_model_json`：`ok = true`，**0 error / 0 warning**。
- `generate_sysml`：`ok = true`（IR 合法才渲染）。
- `verify_sysml`：元素级比对 **0 missing / 0 extra / 0 mismatched**（元素 6 个、关系 2 条）。
- 数值是**占位值**：4.0 h / 960 Wh / 240 W 都只为把「阈值—参数」两格填满，不是实测。

**追溯落点**

- `REQ-CRUISE-ENDURANCE --satisfiedBy--> PART-USE-POWER-CHAIN`（谁满足它）；
- `ACT-SIM-ENDURANCE --verifies--> REQ-CRUISE-ENDURANCE`（谁验证它）；
- 自查：`query_model(unsatisfied_requirements=true)` 应为 0 条；`query_model(referrers_of="REQ-CRUISE-ENDURANCE")`
  应能看到验证动作。

**为什么这么选**

- 走的是**岔路口 A 的「能」分支**：判据可客观判定，才允许建 `Requirement`；判据写不出就去追问，别硬建。
- 阈值单独成字段 `minEnduranceHours: 4.0`，`text` 里只写人话（**反模式第 4 条**：单位进字符串就参与不了计算）。
- 需求不是孤立节点：`satisfiedBy` + `verifies` 双线补齐（**反模式第 10 条**）。
- **没有**把 `T = E/P` 的换算写成需求——那是物理关系，归范例 2（**反模式第 5 条**）。
- **没有**建 `Constraint`：这里要表达的是「必须达到 4 h」的门槛，不是恒等式；门槛属于需求阈值。

---

## 范例 2：物理关系式 P = U·I —— Constraint + Attribute，不是 Requirement

**一句话需求**：「把 P = U·I 这条功率关系写进模型；巡航母线电压 24 V、电流 10 A。」

**分类判断**

- **岔路口 B（是不是任何设计下都成立的物理关系）**：换一块电池、换一个电机，`P = U·I` 仍然成立
  → **不是 `Requirement`**，是**参数约束**。
- 落点：`Constraint`（承载公式）+ `Attribute`（承载可被引用的参数值）。`Constraint` 是 **v1 增补 kind**。
- 反模式对位：**反模式第 5 条**（把常量写成需求）、**第 9 条**（自创 kind）。
  v1 增补之后，`Constraint` 不再是「自创」；但仍不许自己发明第 9 种 kind。

**IR JSON**（节选；完整文件见 [02-power-law-constraints.ir.json](examples/02-power-law-constraints.ir.json)）

```json
[
  { "id": "ATTR-BUS-VOLTAGE", "kind": "Attribute", "name": "busVoltageV",
    "owner": "PART-DEF-POWER-CHAIN",
    "properties": { "valueType": "Real", "defaultValue": 24.0, "unit": "V",
                    "description": "母线电压 U_batt。占位值。" } },

  { "id": "ATTR-CRUISE-CURRENT", "kind": "Attribute", "name": "cruiseCurrentA",
    "owner": "PART-DEF-POWER-CHAIN",
    "properties": { "valueType": "Real", "defaultValue": 10.0, "unit": "A",
                    "description": "巡航电流 I_cruise。占位值。" } },

  { "id": "CON-POWER-LAW", "kind": "Constraint", "name": "PowerLaw",
    "owner": "PART-DEF-POWER-CHAIN",
    "properties": {
      "expression": "P_cruise = U_batt * I_cruise",
      "parameters": ["ATTR-BUS-VOLTAGE", "ATTR-CRUISE-CURRENT", "ATTR-CRUISE-POWER"],
      "description": "物理关系式，不是需求；v1 增补 kind。"
    } }
]
```

**关键渲染片段**（当前模板输出，节选）

```
part def PowerChain {
    attribute busVoltageV : Real = 24.0 [V];
    attribute cruiseCurrentA : Real = 10.0 [A];
    attribute cruisePowerW : Real = 240.0 [W];
    // description: 物理关系式，不是需求；v1 增补 kind。
    constraint def PowerLaw {
        // expression: P_cruise = U_batt * I_cruise
        // parameters: busVoltageV, cruiseCurrentA, cruisePowerW
    }
}
```

> **渲染口径**：当前生成器把 `expression` / `parameters` 以 `//` 注释承载（`constraint def` 语句本身是模板产出的）。
> 这些记法**未经官方解析器回验**；语义不丢（公式文本与参数 id 都在 IR 里可查），但别把它当成官方语法范例。

**兼容形态**（工具版本还没收录 `Constraint` 时）

```json
{ "id": "ATTR-CRUISE-POWER", "kind": "Attribute", "name": "cruisePowerW",
  "owner": "PART-DEF-POWER-CHAIN",
  "properties": { "valueType": "Real", "defaultValue": 240.0, "unit": "W",
                  "description": "P_cruise = U_batt * I_cruise（占位值）。" } }
```

能通过校验、能渲染，但公式只是文本：**没有参数引用关系**，`query_model` 追不到「这条公式用了哪三个参数」。
只作过渡，别把它当目标形态。

**校验结果**（模型事实）

- `validate_model_json`：`ok = true`，**0 error / 0 warning**。
- `Constraint.parameters` 的三个 id 都解析到 `kind = Attribute` 的元素；`expression` 是单行文本（schema 不允许换行）。
- `generate_sysml`：`ok = true`；`verify_sysml` 元素级比对 **0/0/0**。
- 24 V / 10 A / 240 W 是**占位值**，三者恰好满足 24 × 10 = 240 只是为了让示例自洽，不是实测。

**追溯落点**

- `CON-POWER-LAW.owner = PART-DEF-POWER-CHAIN`：约束挂在**被约束的结构定义**下；
- `parameters` → 三个 `Attribute`（这是 `Constraint` 自己的引用字段，**不是** `relations`，
  所以 `query_model(referrers_of=...)` 不沿它走，需人工核对参数）；
- 门槛仍在需求侧：`REQ-POWER-BUDGET` 的 `maxCruisePowerW: 260.0`，`satisfiedBy` 指向功率链用法。

**为什么这么选**

- 走的是**岔路口 B 的「是」分支**：任何设计下都成立的关系 → 参数/约束，不是需求（**反模式第 5 条**）。
- 公式与参数**分开放**：`Constraint` 存关系，`Attribute` 存值。这样换电池只改参数、不动公式。
- 参数必须是**模型内已存在的 `Attribute` id**——先建参数，再建约束（**反模式第 2 条的「先建被引用方」**）。
- 需求侧只留「不超过 260 W（占位）」的门槛；需求与约束**成对但不同层**，评审时不会出现
  「一条永远不会失败的需求」。
- 若把 `P = U·I` 建成 `Requirement`，它永远为真、永远不失败，会稀释需求链——这是**推断**，
  但也是反模式第 5 条写明的后果。

---

## 范例 3：飞行状态机 + 在线优化动作 —— 状态 vs 动作

**一句话需求**：「巡航中遇逆风要能自动调整；电量不足要返航；在线寻优也要建进去。」

**分类判断**

- **飞行模式**（Grounded / Climbing / Cruising / Returning / Landing）：能**停在里面**、能被事件
  （逆风、电量告警、到点）**踢出去** → **岔路口 C 的「是」分支** → `StateDefinition`。
- **在线寻优**：吃遥测、吐 (v, eta)，**算完就结束**，不会停在某个状态等事件 → `ActionDefinition`
  （element-choice 案例 4）。
- 反模式对位：**反模式第 7 条**（状态机画成流程图）、**第 15 条**（守卫不互斥不完备）、
  **第 16 条**（初始迁移挂触发器）。

**IR JSON**（节选；完整文件见 [03-flight-mode-states.ir.json](examples/03-flight-mode-states.ir.json)）

```json
{
  "id": "STATE-FLIGHT-MODE",
  "kind": "StateDefinition",
  "name": "FlightModeStates",
  "owner": "PART-DEF-X8",
  "properties": {
    "states": ["Standby", "Grounded", "Climbing", "Cruising", "Returning", "Landing"],
    "initial": "Standby",
    "transitions": [
      { "from": "Standby", "to": "Grounded" },
      { "from": "Grounded", "to": "Climbing", "trigger": "takeoff command" },
      { "from": "Climbing", "to": "Cruising", "trigger": "altitude reached" },
      { "from": "Cruising", "to": "Returning", "trigger": "reserve check",
        "guard": "reserveEnergyFraction <= 0.15" },
      { "from": "Cruising", "to": "Cruising", "trigger": "reserve check",
        "guard": "reserveEnergyFraction > 0.15" },
      { "from": "Cruising", "to": "Cruising", "trigger": "wind gust",
        "guard": "speedRatio >= 0.75 and speedRatio <= 1.25" },
      { "from": "Cruising", "to": "Cruising", "trigger": "wind gust",
        "guard": "speedRatio < 0.75 or speedRatio > 1.25" }
    ]
  }
}
```

**关键渲染片段**（当前模板输出，节选）

```
state def FlightModeStates {
    initial Standby;
    state Standby;
    state Grounded;
    state Climbing;
    state Cruising;
    state Returning;
    state Landing;
    transition from Standby to Grounded;
    transition from Grounded to Climbing when takeoff command;
    transition from Cruising to Returning when reserve check if (reserveEnergyFraction <= 0.15);
    transition from Cruising to Cruising when reserve check if (reserveEnergyFraction > 0.15);
    transition from Cruising to Cruising when wind gust if (speedRatio >= 0.75 and speedRatio <= 1.25);
    transition from Cruising to Cruising when wind gust if (speedRatio < 0.75 or speedRatio > 1.25);
}
```

**校验结果**（模型事实）

- `validate_model_json`：`ok = true`，**0 error / 0 warning**；
  每条 transition 的 `from` / `to` 都在 `states` 里（否则 `E-STATE-TRANSITION-ENDPOINT`）。
- `generate_sysml`：`ok = true`；`verify_sysml` 元素级比对 **0/0/0**。
- **校验抓不到的东西**：守卫是否互斥/完备、初始出边有没有挂触发器——这两条只能靠下面的自检与评审
  （**反模式第 15、16 条**都明说 validate 不报）。
- 0.75 / 1.25 / 0.15 / 6200 rpm 都是**占位值**。

**追溯落点**

- `REQ-ROTOR-SPEED-RATIO --satisfiedBy--> ACT-ONLINE-OPT`（功能满足区间要求）；
- `ACT-ONLINE-OPT --verifies--> REQ-ROTOR-SPEED-RATIO`（同一功能做区间校核）；
- 状态机 `STATE-FLIGHT-MODE` 的 owner 是整机定义 `PART-DEF-X8`，它**没有**直接的需求关系；
  追溯靠 owner 归属 + 人工/回顾评审。**这是模型事实**：不要声称状态机已挂上 `satisfiedBy`。

**三条状态机自检（本范例逐条过了）**

- [x] **不是流程图**：Cruising 能停留、能被 `reserve check` / `wind gust` 踢出去，有自迁移与跳出边
      （反模式第 7 条）。
- [x] **同一判定出口的守卫二分且互补**：
      `reserveEnergyFraction <= 0.15` / `> 0.15`；`speedRatio` 在区间内 / 不在区间内。
      没有任何输入同时命中两条，也没有输入落空（反模式第 15 条）。
- [x] **`initial` 的出边不挂 trigger / guard**：`Standby → Grounded` 是「进入即走」的完成迁移；
      `takeoff command` 这类事件迁移都从非初始状态 `Grounded` 出发（反模式第 16 条）。
      这也是为什么状态里多了一个 `Standby`——不是装饰，是为了让「上电」与「起飞」分开。

**为什么这么选**

- 走的是**岔路口 C 的「能停留 + 被事件踢出」判据**：状态机的价值在停留与跳转，不在画一串箭头。
- 在线寻优被单独建成 `ActionDefinition`：它**算完就结束**，没有「停在收敛状态等事件」的语义
  （element-choice 案例 4 的分界线）。若改成「优化器处于收敛/发散两态，发散时回退工作点」，
  才需要第二个 `StateDefinition`。
- 守卫写成**互补对**而不是「先到先得」，这是反模式第 15 条的正面样板。
- 宁可多一个 `Standby`，也不给 `initial` 的出边挂触发器——**反模式第 16 条**的坑很隐蔽，validate 不报。

---

## 范例 4：功率链结构分解 + Connection

**一句话需求**：「把电池 → 电调 → 电机 → 桨的功率链建成结构，八路各一份。」

**分类判断**

- **岔路口 D（类型还是这次具体用的那个）**：既要「电机是什么」（类型），也要「这台/这八台」（可数、可指）
  → **`PartDefinition` + `PartUsage` 成对建**。
- **连接**：功率链的每条边有明确流动类型（电/机械），且需要独立可查的 id → 用 **`Connection`**
  （**v1 增补 kind**）；如果只是画一条没有属性的线，用 `connects` 关系即可，**别两种都写**。
- 反模式对位：**反模式第 6 条**（功率链漏电调）、**第 8 条**（只建 Definition 不建 Usage）、
  **第 4 条**（数量写成字符串）。

**IR JSON**（节选；完整文件见 [04-power-chain-structure.ir.json](examples/04-power-chain-structure.ir.json)）

```json
[
  { "id": "PART-DEF-ESC", "kind": "PartDefinition", "name": "ElectronicSpeedController",
    "owner": "PowerChainDemo", "properties": { "description": "电子调速器，每路电机一个。" } },

  { "id": "PART-USE-ESC", "kind": "PartUsage", "name": "escUnit",
    "owner": "PART-USE-POWER-CHAIN",
    "properties": { "typeRef": "PART-DEF-ESC", "quantity": 8 } },

  { "id": "PART-USE-MOTOR-UPPER", "kind": "PartUsage", "name": "upperMotor",
    "owner": "PART-USE-POWER-CHAIN",
    "properties": { "typeRef": "PART-DEF-MOTOR", "quantity": 4 } },

  { "id": "CON-ESC-TO-UPPER-MOTOR", "kind": "Connection", "name": "escToUpperMotor",
    "owner": "PART-USE-POWER-CHAIN",
    "properties": { "sourceRef": "PART-USE-ESC", "targetRef": "PART-USE-MOTOR-UPPER",
                    "flowKind": "electrical",
                    "description": "八路电调中的四路驱动上桨电机。" } }
]
```

**关键渲染片段**（当前模板输出，节选）

```
part def BatteryPack;
part def ElectronicSpeedController;
part def BrushlessMotor;
part def Propeller;

part powerChain : PowerChain[1] {
    part batteryPack : BatteryPack[1];
    part escUnit : ElectronicSpeedController[8];
    part lowerMotor : BrushlessMotor[4];
    part upperMotor : BrushlessMotor[4];
    part lowerPropeller : Propeller[4];
    part upperPropeller : Propeller[4];
    // Connection CON-BATTERY-TO-ESC flowKind=electrical description: 电池母线向八路电调供电。
    connect batteryPack to escUnit;
    // Connection CON-ESC-TO-LOWER-MOTOR flowKind=electrical description: 八路电调中的四路驱动下桨电机。
    connect escUnit to lowerMotor;
    // Connection CON-ESC-TO-UPPER-MOTOR flowKind=electrical description: 八路电调中的四路驱动上桨电机。
    connect escUnit to upperMotor;
    // Connection CON-LOWER-MOTOR-TO-PROP flowKind=mechanical description: 下桨电机驱动下桨。
    connect lowerMotor to lowerPropeller;
    // Connection CON-UPPER-MOTOR-TO-PROP flowKind=mechanical description: 上桨电机驱动上桨。
    connect upperMotor to upperPropeller;
}
```

**校验结果**（模型事实）

- `validate_model_json`：`ok = true`，**0 error / 0 warning**。
- 每个 `PartUsage.typeRef` 都指向 `PartDefinition`（否则 `E-PARTUSAGE-TYPEREF-WRONGKIND`）；
  每个 `Connection` 两端都存在、同 owner、`sourceRef != targetRef`，`flowKind` 在受控枚举内。
- `generate_sysml`：`ok = true`；`verify_sysml` 元素级比对 **0/0/0**。
- 8 路电调 / 上下各 4 台电机、各 4 副桨是**构型占位值**，不是实测。

**追溯落点**

- `REQ-CRUISE-ENDURANCE --satisfiedBy--> PART-USE-POWER-CHAIN`（需求落到整条链）；
- 结构链自身沿 `Connection` 走：`batteryPack → escUnit → upperMotor/lowerMotor → upperPropeller/lowerPropeller`；
- 自查：`query_model(referrers_of="PART-USE-PROP-UPPER")` 能看到 `CON-UPPER-MOTOR-TO-PROP` 指向它——
  链路末端有人引用，不是断头节点。

**为什么这么选**

- **每一环都建齐**：电池、电调、电机、桨四层齐全，`escUnit` 不是可选装饰——漏了电调，效率链就少一个乘积项
  （**反模式第 6 条**）。共轴构型还要把**上下桨拆成两条并联支路**（各 4 份），只建一条就是把它当四旋翼算。
- **定义与用法成对**：`BatteryPack` 是类型，`batteryPack` 是这一次装上的那一份，`quantity` 用数字表达
  （**反模式第 8 条、第 4 条**）。
- **连接用元素而不是纯关系**：功率链每条边需要 `flowKind`（电/机械）与独立 id 供导出与查询，
  所以建 `Connection`；若只是「这两块有根线」，用 `connects` 关系更轻。**同一条边只描述一次**，
  两种写法混用会让追溯图出现平行边。
- 数量写在 `quantity` 而不是 `description`：8 是数量，不是说明文字。

---

## 范例 5：先错后改 —— 悬空引用 + 把常量写成需求

**一句话需求**：「加一条续航需求，顺手把额定电压 24 V 也写进模型。」

这个范例**故意先写错**，用来演示「校验报什么码 → 改哪一格 → 为什么」。改前文件：
[05-constant-as-requirement.before.ir.json](examples/05-constant-as-requirement.before.ir.json)；
改后文件：[05-constant-as-requirement.fixed.ir.json](examples/05-constant-as-requirement.fixed.ir.json)。

**分类判断**

- 「巡航时间不低于 4 小时」→ **岔路口 A**（能写出通过/不通过判据）→ `Requirement`；
- 「额定电压 24 V」→ **岔路口 A 的「否」分支** + element-choice 案例 1 的判据（换个设计它也不变）
  → `Attribute`。把它建成需求，就是**反模式第 5 条**；
- 阈值写成「4 小时」→ **反模式第 4 条**；引用不存在的电机 → **反模式第 2 条**；
- 结论：先按错误直觉写一遍（都建成需求、阈值随手写成字符串），让校验把结构错误抓出来，
  剩下的「合法但错」再靠判据纠正。

**IR JSON**（错误版本，三处坑）

```json
[
  { "id": "REQ-ENDURANCE", "kind": "Requirement", "name": "CruiseEndurance",
    "owner": "ConstantDemo",
    "properties": {
      "text": "巡航时间不低于 4 小时。",
      "acceptanceCriteria": "满电续航 T >= 4.0 h（占位值）。",
      "verifyMethod": "simulation",
      "minEnduranceHours": "4 小时"
    },
    "relations": [
      { "type": "satisfiedBy", "target": "PART-DEF-MOTOR",
        "rationale": "想指向电机，但电机这个元素只存在于脑子里，模型里没有。" }
    ] },

  { "id": "REQ-NOMINAL-VOLTAGE", "kind": "Requirement", "name": "NominalVoltage24V",
    "owner": "ConstantDemo",
    "properties": { "text": "额定电压 24 V。", "acceptanceCriteria": "母线电压等于 24 V。",
                    "nominalVoltageV": 24.0 } }
]
```

**校验结果**（模型事实，实际跑出来的）

```
validate_model_json → ok = false
errors:
  E-PROP-THRESHOLD-STRING   REQ-ENDURANCE  阈值字段 minEnduranceHours 被写成了字符串 "4 小时"
  E-REL-TARGET-DANGLING     REQ-ENDURANCE  relations[0].target = PART-DEF-MOTOR 在模型内不存在
warnings:
  W-REQ-NO-SATISFY          REQ-NOMINAL-VOLTAGE  该需求没有 satisfiedBy 关系
```

`generate_sysml` 此时**拒绝渲染**并回传同一批 errors（`modeling-workflow` 第 7 条：先校验后生成）。

### 第 1 步：逐条定位

| 症状 | 反模式 | 怎么改 |
| --- | --- | --- |
| `minEnduranceHours: "4 小时"` | **第 4 条**（单位写进字符串） | 改成数字 `4.0`，单位放到 `Attribute.unit` 或阈值对象 |
| `target: PART-DEF-MOTOR` 悬空 | **第 2 条**（引用不存在的元素） | 指向真实存在的 `PART-USE-BATTERY`，或先把电机建出来 |
| 「额定电压 24 V」是 `Requirement` | **第 5 条**（把常量写成需求） | 改成 `Attribute`，挂到 `BatteryPack` 下 |
| `REQ-NOMINAL-VOLTAGE` 没人满足 | **第 10 条**（断链） | 删掉这条「伪需求」后，告警自然消失 |

**这里最值得注意的一点**：第三处错误**没有触发任何 error**——它结构完全合法，validate 只报了一条
`W-REQ-NO-SATISFY`。这正是**反模式第 5 条**说的「validate 只抓结构错误，不抓建模质量错误」：
「额定电压 24 V」在任何设计下都成立，是一条**永远不会失败的需求**。工具放行，评审会问住你。
**改法不能靠等报错，要靠「换个设计它会不会变」这句判据。**

### 第 2 步：改后版本

```json
[
  { "id": "ATTR-NOMINAL-VOLTAGE", "kind": "Attribute", "name": "nominalVoltageV",
    "owner": "PART-DEF-BATTERY",
    "properties": { "valueType": "Real", "defaultValue": 24.0, "unit": "V",
                    "description": "电池包额定电压。固有常量，不是需求。占位值。" } },

  { "id": "REQ-ENDURANCE", "kind": "Requirement", "name": "CruiseEndurance",
    "owner": "ConstantDemo",
    "properties": { "text": "巡航时间不低于 4 小时。",
                    "acceptanceCriteria": "满电续航 T >= 4.0 h（占位值）。",
                    "verifyMethod": "simulation", "minEnduranceHours": 4.0 },
    "relations": [
      { "type": "satisfiedBy", "target": "PART-USE-BATTERY",
        "rationale": "续航由电池可用能量保障；引用的是模型里真实存在的用法。" }
    ] }
]
```

**关键渲染片段**（改后，当前模板输出，节选）

```
part def BatteryPack {
    // description: 电池包额定电压。固有常量，不是需求。占位值。
    attribute nominalVoltageV : Real = 24.0 [V];
}

part batteryPack : BatteryPack[1];

requirement def CruiseEndurance {
    doc /* 巡航时间不低于 4 小时。 */
    doc /* 验收判据: 满电续航 T >= 4.0 h（占位值）。 */
    attribute minEnduranceHours : Real = 4.0;
    //   REQ-ENDURANCE --satisfiedBy--> PART-USE-BATTERY  (续航由电池可用能量保障；引用的是模型里真实存在的用法。)
}
```

**校验结果**（改后，模型事实）

- `validate_model_json`：`ok = true`，**0 error / 0 warning**。
- `generate_sysml`：`ok = true`；`verify_sysml` 元素级比对 **0/0/0**。
- 24 V / 4.0 h 是**占位值**。

**追溯落点**

- 需求侧：`REQ-ENDURANCE --satisfiedBy--> PART-USE-BATTERY` + `ACT-SIM-ENDURANCE --verifies--> REQ-ENDURANCE`；
- 常量侧：`ATTR-NOMINAL-VOLTAGE` 的 owner 是 `PART-DEF-BATTERY`，靠**归属**参与追溯；
  它不被任何 `relations` 引用，所以 `query_model(referrers_of=...)` 查不到——**这是模型事实**，
  与反模式第 14 条一致：参数类元素靠 owner 自查，别指望 validate 报孤立。

**为什么这么选**

- 错的地方都改在 **IR JSON** 上，没有去改生成文本（`modeling-workflow` 第 7 步的硬规矩）。
- 阈值 `4.0` 是数字、单位只在 `unit` 里：字符串阈值不能参与计算或导出（**反模式第 4 条**）。
- 悬空引用改指向**已存在**的 `PART-USE-BATTERY`，而不是「先把电机建出来凑引用」——
  后者会为一个不存在的需求凭空造结构（**反模式第 2 条的「先建被引用方」**）。
- 常量从 `Requirement` 降级为 `Attribute`：**「是多少」是参数，「不得低于」才是需求**
  （岔路口 A 与 element-choice 案例 1 的判据口诀）。
- 这个反例的价值在于：**两个 error 好抓，一个「合法但错」的需求难抓**。skill 能替你记住的，
  就是最后这一条。

---

## 五个范例的共同骨架

```
1. 先问「有没有可判定判据 / 换设计会不会变 / 能不能停留 / 要不要数个数」
2. 再查 query_model（id/name 占用、引用目标存在）
3. 每个元素都有 owner；每条引用都指向已存在的 id
4. 数值是数字、单位独立成字段、公式进 Constraint/description
5. 每条需求双线：satisfiedBy + verifies
6. 校验清零 → 生成 → 回验 → 汇报三档（事实/规范/推断）
```

## 复用检查清单

- [ ] 我要建的东西，能在上面 5 个范例里找到**同构**的那一个吗？（找不到 → 先回 `element-choice`）
- [ ] 我抄的是**结构**还是**数值**？数值有没有来源？没有来源就标「占位值」。
- [ ] 我引用到的每个 id，都在 `query_model` 里查得到吗？
- [ ] 我有没有把物理公式/常量建成需求？（**反模式第 5 条**）
- [ ] 我有没有把「校验过了」说成「官方解析器跑过了」？（**红线**：没有）

## 常见卡点

| 卡在哪 | 十有八九是 |
| --- | --- |
| 范例 1 的判据写不出来 | 这还不是需求，是愿望；回去追问可判定条件 |
| 范例 2 的 `parameters` 报错 | 参数指向了非 `Attribute` 元素，或 id 还没建 |
| 范例 3 的 transition 报 `E-STATE-TRANSITION-ENDPOINT` | `from`/`to` 拼错，或状态没进 `states` |
| 范例 4 的链路走不通 | 少了电调/少了上下桨支路，或 `Connection` 端点不同 owner |
| 范例 5 改完还有 warning | 另一条需求没接 `satisfiedBy`，或 `verifyMethod` 没配 `verifies` |
