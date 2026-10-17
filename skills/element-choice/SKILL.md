---
name: element-choice
description: "该用哪种 IR 元素：需求 vs 参数约束、状态 vs 动作、Definition vs Usage。给判断题、决策树与边界案例，不给定义。当你在建模时犹豫「这条该建成什么」，或用户的要求既能理解成需求又能理解成参数时加载本 skill。Triggers: 该用哪种元素, 需求还是参数, 状态还是动作, Definition 还是 Usage, 选型, 该建成什么, 这是需求吗, element choice, which kind."
metadata:
  version: "1.1.0"
  last_updated: "2026-10-17"
  status: active
  task_type: open-ended
  related_skills:
    - modeling-workflow
    - anti-patterns
---

# element-choice —— 元素选型决策树

**一句话：只问三个岔路口。** 每个岔路口都有一句**可判定**的判据；判不出来就说明输入不够，
该回去追问，而不是硬选一个。

MVP 的受控枚举只有 6 种 kind，**不许自创**：

```
PartDefinition · PartUsage · Requirement · ActionDefinition · StateDefinition · Attribute
```

---

## §1 决策树

```
拿到一句要求
│
├─ 岔路口 A：它有「可判定的验收标准」吗？（时间 / 功率 / 精度 / 范围 / 数量）
│   │   判据：我能不能写出一个通过/不通过可以客观判断的句子？
│   ├─ 能 ──→ 【Requirement】
│   │         阈值拆成数值属性（minEnduranceHours: 4.0），判据写成 acceptanceCriteria
│   └─ 不能 ─→ 回去追问，直到能写出判据为止
│             （追问不出来 = 它还不是一条需求，先别建）
│
├─ 岔路口 B：它是「某部件必然成立的物理关系」吗？（P = U·I、T = E/P、力 = 质量×加速度）
│   │   判据：这句话在**任何**设计选择下都成立吗？换个电池它也成立吗？
│   ├─ 是 ──→ 【Attribute】（公式写进 description）
│   │         MVP 没有正式的 Constraint 元素，公式暂由参数承载（二期补）
│   └─ 否 ─→ 回到岔路口 A / C / D
│
├─ 岔路口 C：它描述「持续处于某状态 + 被事件触发迁移」吗？
│   │   判据：我能不能列出「状态名」和「从哪个状态迁到哪个状态」？
│   ├─ 是 ──→ 【StateDefinition】（states + transitions）
│   └─ 否 ─→ 【ActionDefinition】（一次性、有输入输出）
│
└─ 岔路口 D：它是「一种事物的类型」还是「这次具体用的那个」？
    │   判据：我要不要给它一个**编号/位置/数量**？（"1 号机臂上的电机" vs "电机"）
    ├─ 类型 ──→ 【*Definition】（如 PartDefinition: BatteryPack）
    └─ 具体 ─→ 【*Usage】（如 PartUsage: batteryPack，**必须带 typeRef**）
```

## §2 三个岔路口的 30 秒版

| 岔路口 | 一句话判据 | 选 A | 选 B |
| --- | --- | --- | --- |
| A 需求 vs 参数/约束 | 「换个设计它是否就变了？」变了=需求；不变（物理定律）=参数 | 变了 → Requirement | 不变 → Attribute |
| C 状态 vs 动作 | 「我要写的是『处于什么状态』还是『做完什么』？」 | 状态 → StateDefinition | 做完 → ActionDefinition |
| D Definition vs Usage | 「我要不要数它的个数 / 指它的位置？」 | 不要 → *Definition | 要 → *Usage |
| 需求拆分 vs 细化 | 「拆出来的每条能各自写验收判据、各自被满足吗？」 | 能 → `decomposes`（并列子条） | 只是说得更准 → `refines` |

---

## §3 边界案例（含推理过程）

> 每个案例都给出：**输入 → 两边都像的理由 → 决定性判据 → 结论 → IR 片段**。

### 案例 1：「电池容量 1200 Wh」——需求还是参数？

- **两边都像**：它是个数值指标，有单位，像需求；但它也是电池的固有属性，像参数。
- **决定性判据**：**换个电池，这句话还成立吗？** 成立——它只是描述「我们选的这块电池是多少」，
  没有任何「必须达到」的约束。需求必须有**通过/不通过**的语义。
- **结论**：`Attribute`（`valueType: Real`, `unit: "Wh"`）。
- **反例对照**：「电池可用能量不低于 1000 Wh」——这就带了「不低于」，是可判定的 → `Requirement`
  且 `minUsableEnergyWh: 1000.0`。
- **IR 片段**：
```json
{ "id": "ATTR-BATTERY-CAPACITY", "kind": "Attribute", "name": "batteryCapacityWh",
  "owner": "PART-BATTERY-PACK",
  "properties": { "valueType": "Real", "defaultValue": 1200.0, "unit": "Wh",
                  "description": "电池包标称容量 E_batt。" } }
```

### 案例 2：「P = U·I」——需求还是参数？

- **两边都像**：它是工程上的重要约束，写进模型天经地义；但它不是「要求」，是定律。
- **决定性判据**：**换任何设计，这条都成立吗？** 成立。需求描述的是「我们要做到什么」，
  物理定律描述的是「这个世界怎样运行」。
- **结论**：**不是 Requirement**。MVP 把它写进相关 `Attribute` 的 `description`
  （正式 `Constraint` 元素是二期，别为了放公式去自创 kind——会报 `E-KIND-INVALID`）。
- **常见误判**：把它建成 Requirement 会污染需求链，导致追溯矩阵里出现一条「永远不会失败的需求」，
  评审时会当场被问住。

### 案例 3：「起飞 → 爬升 → 巡航 → 返航」——状态机还是动作序列？

- **两边都像**：都是四个环节，都能画成一串。
- **决定性判据**：**问「能不能停在中间」**。如果「巡航」可以持续 4 小时、期间外界事件
  （逆风、电量告警）能让它**跳出去**，那是**状态**；如果「爬升」做完就必然进下一环、没有停留与跳转，
  那只是流程里的一个步骤。
- **结论**：这四个都是 `StateDefinition` 的 `states`，且 transition 要带 `trigger`
  （如 `逆风告警`、`电量低于阈值`）。方案 7.3 的原始要求就是「巡航（在线寻优）状态内的参数漂移」——
  正说明它们是有停留、有事件的状态。
- **IR 片段**：
```json
{ "id": "STATE-FLIGHT-MODE", "kind": "StateDefinition", "name": "FlightModeStates",
  "owner": "CoaxialOctoRotor",
  "properties": { "states": ["Grounded", "Climbing", "Cruising", "Returning", "Landing"],
                  "initial": "Grounded",
                  "transitions": [
                    { "from": "Grounded", "to": "Climbing", "trigger": "takeoff command" },
                    { "from": "Climbing", "to": "Cruising", "trigger": "altitude reached" },
                    { "from": "Cruising", "to": "Returning", "trigger": "reserve energy reached" },
                    { "from": "Cruising", "to": "Cruising", "trigger": "wind gust", "guard": "speed ratio within band" } ] } }
```
- **注意**：transition 的 `from`/`to` 必须都在 `states` 里，否则报 `E-STATE-TRANSITION-ENDPOINT`。

### 案例 4：「在线功率优化」——ActionDefinition 还是 StateDefinition？

- **两边都像**：它在巡航过程中反复执行，有点像「持续处于某状态」。
- **决定性判据**：**它有没有「输入 → 输出」？** 有——吃功率遥测与空速估计，吐出 (v, eta)。
  而且它是一次性的、有始有终的计算；它不会「持续停在里面等事件」。
- **结论**：`ActionDefinition`。
- **分界线一句话**：**「算完就结束」是动作，「停在里面等事情发生」是状态。**
- **反例对照**：如果描述改成「优化器处于『收敛』与『发散』两种状态，发散时回退到上一个工作点」，
  那才需要 StateDefinition。

### 案例 5：`BatteryPack` 与 `batteryPack`——Definition 还是 Usage？

- **两边都像**：名字只差大小写，说的都是电池。
- **决定性判据**：**我要不要数它 / 指它？** 「八路电调，每副桨一路」→ 要数；
  「整机里功率链那一份实例」→ 要指。
- **结论**：**两个都要建，而且用法不同**——
  `PART-BATTERY-PACK`（`PartDefinition`，类型）与 `PART-USAGE-BATTERY`（`PartUsage`，具体那一份，
  `typeRef` 指向前者、`quantity: 1`）。
- **最容易犯的错**：只建 Definition 不建 Usage。校验会放过，但会报 `W-PARTDEF-UNUSED`——
  「这个定义从没被实例化过」。反过来只建 Usage 不建 Definition，`typeRef` 一定悬空，直接 error。
- **IR 片段**：
```json
[{ "id": "PART-BATTERY-PACK", "kind": "PartDefinition", "name": "BatteryPack",
   "owner": "CoaxialOctoRotor", "properties": { "description": "动力锂电池包。" } },
 { "id": "PART-USAGE-BATTERY", "kind": "PartUsage", "name": "batteryPack",
   "owner": "PART-POWER-CHAIN",
   "properties": { "typeRef": "PART-BATTERY-PACK", "quantity": 1 } }]
```

### 案例 6：「燃烧效率 0.72」——Attribute 还是 Requirement 阈值？

- **两边都像**：都是个小数，都跟性能有关。
- **决定性判据**：它是**被测量出来的固有值**（我们这架飞机的桨就是这个效率），
  还是**被要求达到的门槛**？
- **结论**：
  - 「效率测量值 0.72」→ `Attribute`（`defaultValue: 0.72`）；
  - 「效率不得低于 0.70」→ 该写成 `Requirement` 的阈值字段 `minEfficiency: 0.70`。
- **两者可以同时存在**：需求给门槛，参数给实测/设计值，仿真验证时对比二者——
  这正是方案 10.2 那条「模型 → 参数 → 仿真 → 验证」叙事链要的东西。
- **判据口诀**：**「不得低于 / 不大于 / 必须满足」= 需求；「是多少」= 参数。**

### 案例 7：「续航不低于 4 小时」——阈值写数字还是写字符串？

- **两边都像**：JSON 里 `"4.0"` 和 `4.0` 看起来差不多，人读都懂。
- **决定性判据**：**它要参与计算或导出吗？** 要（`export_simulink` 二期要拿它做仿真）。
- **结论**：**必须写成数字** `"minEnduranceHours": 4.0`，单位放进独立字段；
  写成 `"4 小时"` 会直接报 `E-PROP-THRESHOLD-STRING`。
- **一句话**：字符串是给人看的，数字是给机器算的。需求阈值属于后者。

### 案例 8：「单桨失效时无人机不坠毁」要不要拆？——`refines` 还是 `decomposes`

- **两边都像**：它既是顶层任务需求，听起来也像子系统需求；拆成四条之后，父需求自己也还在。
- **决定性判据**：**拆出来的每一条，能不能各自写出独立的验收判据、各自被一个部件或功能满足？**
  - 能 → 用 `decomposes` 拆成**并列子需求**（四条都满足，才算满足父需求）；
  - 只是同一要求的**更精确表述**（收紧判据、明确工况，没有新增并列条目）→ 那是 `refines`，不产生子条目。
- **结论**：这个例子落在前一半，拆成四条并列子需求——**失效检测 / 姿态保持 / 控制分配重构 / 高度保持**，
  每条各自有验收判据、各自接满足链。**拆到「单条可被一个部件或一个功能满足」为止**；
  拆不出判据的那一层不要建（建了就是 `anti-patterns` 第 1 条「空判据」与第 14 条「孤儿」的原料）。
- **层级范式**（来源：真实多旋翼 SysML 工程的四级结构）：**顶层任务需求 → 子系统需求（`S1_` / `SS1-1_` 层级）
  → 功能需求**，每条各有验收判据与满足链。别跳级建条目。
- **每条子需求仍要走双线**：`satisfiedBy`（谁做到）+ `verifies`（谁验证）；**父需求的满足靠子需求集体满足**，
  不给父需求硬塞一个「综合」部件。
- **IR 片段**（只落到我们 6 种 kind 上：父需求与四条子需求都是 `Requirement`，关系是 `decomposes`）：
```json
[{ "id": "REQ-UAV-SINGLE-FAILURE", "kind": "Requirement", "name": "SingleRotorFailureSafety",
   "owner": "UAV-REQUIREMENTS",
   "properties": { "text": "单桨失效时无人机不坠毁。",
                   "acceptanceCriteria": "任一桨失效后高度损失 <= 2 m 且姿态误差 <= 5 deg" } },
 { "id": "REQ-UAV-FAIL-DETECT", "kind": "Requirement", "name": "DetectRotorFailure",
   "owner": "UAV-REQUIREMENTS",
   "properties": { "text": "失效检测：识别失效桨位。",
                   "acceptanceCriteria": "失效后 100 ms 内报出失效桨位" } }]
```
  四条子需求与父需求之间各连一条 `decomposes`，四条各自的 `satisfiedBy` / `verifies` 照常接。
- **一句话**：**要独立判据才能拆（`decomposes`）；只是说得更准是细化（`refines`）。**

### 案例 9：「借阅日期 / 应还时间」放哪？——建独立元素还是塞进两端？

- **两边都像**：借阅这件事挂在「顾客—书」的关系上，借阅日期 / 应还时间看起来可以塞进
  「顾客」或「书」的属性里——反正都是那次借阅的数据。
- **决定性判据**：**这个关系本身要不要名字、要不要属性、会不会被别处引用？**
  - 要 → 把关系**建成独立元素**（用 `PartUsage` 或 `Attribute` 承载「一次借阅」，再用具名关系连两端），
    不要把日期硬塞进「顾客」或「书」的属性——那会让「书的应还日期」变成**书的固有属性**，
    同一本书被多人同时借（或历史上被借过多次）就崩了。
  - 不要 → 直接一条**具名 relation**（写清 `rationale`）即可，别为一条线建元素。
- **结论**：借阅落在前一半，建独立元素承载它的数据，两端各连一条具名关系。
  **注意 IR 语境**：我们没有 UML 的「关联类」这种构造，表达只能落在 6 种 kind + 5 种关系里，
  **别为了表达关系属性自创 kind**（`E-KIND-INVALID` 红线照旧）；
  承载数据的那个元素必须有 owner、**不能是孤儿**（`PartDefinition` 有 `W-ELEMENT-ORPHAN` 兜底；
  其他 kind validate 不报，靠 `query_model(referrers_of=<id>)` 自查）。
- **来源标注**：Cameo 案例实证（03 文档 §3#10，官方类图用独立类 `Loan` / `Loan Date` 代替关联类，
  被称为「最值得学的一招」）。
- **一句话口诀**：**「关系有名有姓有数据，就把它建成元素；只是连线，就用 relation。」**

---

## §4 选型时的自查清单

- [ ] 我选的 kind **在受控枚举的 6 个里面**吗？（自创 = `E-KIND-INVALID`，没得商量）
- [ ] 如果是 `Requirement`：`text` 和 `acceptanceCriteria` 都写了吗？阈值是数字吗？
- [ ] 如果是 `PartUsage`：`typeRef` 指向的 `PartDefinition` **已存在**吗？
- [ ] 如果是 `StateDefinition`：transition 的 `from`/`to` 都在 `states` 里吗？
- [ ] 如果是 `Attribute`：`valueType` 给了吗？`defaultValue` 的类型对得上吗？`unit` 单独成字段了吗？
- [ ] 如果我在「需求 vs 参数」之间摇摆：**换个设计它会不会变？** 会变 → 需求。
- [ ] 如果我在「状态 vs 动作」之间摇摆：**停下来等事件？** 会等 → 状态。
- [ ] 如果我在「Definition vs Usage」之间摇摆：**要数个数吗？** 要数 → Usage。
