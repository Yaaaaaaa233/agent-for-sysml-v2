---
name: modeling-workflow
description: "SysML v2 建模的固定九步 SOP：从一句自然语言要求走到通过校验的 IR JSON 与合法 SysML v2 文本。每当用户说「加一条需求 / 改参数 / 建个模型 / 帮我建模 / 把这个写进模型 / 更新 SysML」，或任何需要产出 SysML v2 模型的动作，先加载本 skill 再动手。Triggers: 建模, SysML, 加需求, 改需求, 加参数, 改参数, 建模型, 更新模型, 追溯, 需求链, sysml, requirement, model the system, 生成模型, IR JSON."
metadata:
  version: "1.1.0"
  last_updated: "2026-10-17"
  status: active
  task_type: open-ended
  related_skills:
    - element-choice
    - anti-patterns
---

# modeling-workflow —— 建模九步 SOP

**一句话：顺序不能乱。** 先查现状 → 再填 JSON → 校验 → 生成 → 回验 → 汇报。
跳过任何一步都会以某种方式回来找你（造重复元素、引用悬空、文本与模型不一致）。

**工具清单（8 个）**：主链按下面顺序调用——`query_model`（查现状）→
`validate_model_json`（校验）→ `generate_sysml`（生成文本）→ `verify_sysml`（回验）；
配套工具按需插入——`patch_model`（按 id 增量编辑，改完必须回第 7 步重新校验）→
`traceability`（追溯矩阵 / 缺口 / 影响面）→ `parse_sysml`（SysML 文本解析导入）→
`export_simulink`（参数表导出）。配套工具用在对应步骤上，
**不要用它们绕开 SOP**（例如用 `patch_model` 改完不重新校验）。

## 用法

1. 判断用户这次要的是哪一类动作（见 §0 分流）。
2. 从第 1 步开始走，**每一步都做完「自检」再进下一步**。
3. 选型犹豫时叠加加载 `element-choice`；被校验或老师打回时叠加加载 `anti-patterns`。
4. **出错时改 IR JSON，不要改生成出来的文本。** 文本是代码渲染的，手改必然与模型漂移。

---

## §0 分流：先判断这是哪一类动作

| 用户说的 | 动作类型 | 起点 |
| --- | --- | --- |
| 「加一条需求：……」「帮我建个模型」 | 新增 | 第 1 步 |
| 「把参数改成 X」「需求改为 Y」 | 修改 | 第 2 步（先查到目标元素） |
| 「这条需求谁来满足」「有没有没人管的元素」 | 只读查询 | 跳到第 8 步 |
| 「解释一下这个模型」 | 只读查询 | 跳到第 2 步 + 第 9 步 |

**输入含糊时必须先追问，不要猜。** 例如「优化一下续航」—— 要优化到什么程度？
验收判据是什么？追问不出来就先按「补验收判据」处理（见 `element-choice` 第 1 节）。

---

## 第 1 步：理解需求，并判定它属于需求 / 功能 / 行为 / 参数哪一类

- **输入**：用户的一句自然语言。
- **动作**：问清三件事——① 要解决什么问题；② 有没有**可判定的验收标准**（时间 / 功率 / 精度 / 范围）；
  ③ 这是「类型」还是「这次具体用的那个」。选不准就加载 `element-choice`。
- **产出**：一句话的意图陈述 + 拟建元素的 kind 候选（1~2 个）。
- **自检**：
  - [ ] 我能写出这条要求的**验收判据**吗？写不出来 → 先追问，别往下走。
  - [ ] 我知道它该挂在哪个 owner 下吗？
  - [ ] 如果用户给的是物理关系（如 P = U·I），我确认过它不是 Requirement？

## 第 2 步：查现状 —— 动手前先看模型里已有什么

- **输入**：第 1 步的意图陈述。
- **动作**（确定性工具，只读）：
  - `query_model(keyword=<关键名词>)` —— 是否已有同类元素？
  - `query_model(kind=<拟建 kind>)` —— 该 kind 现在有多少、都叫什么？
  - 准备用的 `id` / `name`：`query_model(referrers_of=<候选id>)` 确认没被占用。
  - `query_model(duplicates=true)` —— 顺手确认现存的模型没重名。
- **产出**：现有元素清单 + 拟用的新 id / name（已确认不冲突）。
- **自检**：
  - [ ] 我要建的元素，模型里是不是已经有了？（有 → 改成「修改」而不是「新增」）
  - [ ] 新 `id` 在全模型唯一吗？新 `name` 在同 owner 下唯一吗？
  - [ ] 我要引用的 `typeRef` / `relations.target` **确实已存在**吗？把它们的 id 抄下来。

## 第 3 步：功能分解 —— 从顶层逐级问「这由什么完成」

- **输入**：顶层意图。
- **动作**：每下钻一层就问一次「这个功能由什么完成」。用 `ActionDefinition` 表示一个能做完、
  有输入输出的功能；用 `decomposes` 关系记录分解。
- **产出**：功能清单（`ActionDefinition` 草稿，含 `inputs` / `outputs`）+ `decomposes` 关系。
- **自检**：
  - [ ] 每个功能都至少说得出一个输入和一个输出吗？（说不出 → 它可能其实是状态或参数）
  - [ ] 分解到底了吗？（再往下问一层，如果只能用「软件里面算的」回答，就到底了）
  - [ ] **模糊输入必须在此暴露**：功能名里如果出现「优化」「管理」这类词，追问它的判据是什么。
  - [ ] **拆出来的每条都能独立写验收判据吗？写不出就不该拆出来。**

### 第 3 步补充：需求怎么分层

顶层需求往下拆时，**每层子需求都要有自己的验收判据**——没有判据的那一层不是需求，是标题。
拆分关系二选一：

- `decomposes`：拆成**并列子条**，几条都满足才算满足父需求；
- `refines`：同一要求的**更精确表述**（收紧判据、明确工况），不产生并列子条。

判据见 `element-choice` 案例 8。参考层级：**顶层任务需求 → 子系统需求 → 功能需求**，
每条各自接 `satisfiedBy` / `verifies` 双线，父需求靠子需求集体满足。

## 第 4 步：行为建模 —— 状态机还是动作？

- **输入**：第 3 步的功能清单。
- **动作**：判据只有一条——**「持续处于某状态 + 事件触发迁移」用 `StateDefinition`，否则用 `ActionDefinition`**
  （一次性、有输入输出）。
- **产出**：`StateDefinition`（`states` 数组 + `transitions` 数组，`from`/`to` 必须都在 `states` 里）
  或补全的 `ActionDefinition`。
- **自检**：
  - [ ] `states` 里的每个名字都互不重复吗？
  - [ ] 每条 transition 的 `from` 和 `to` **都在 `states` 里**吗？（写错就是 `E-STATE-TRANSITION-ENDPOINT`）
  - [ ] 我有没有把流程图当状态机用？（如果节点是「先做 A 再做 B」而不是「处于 A 状态」，那是动作不是状态）
  - [ ] 给了 `initial` 的话，它在 `states` 里吗？
  - [ ] **同一判定出口的守卫互斥且完备吗？**（没有任何输入会同时命中两条；任何输入至少命中一条。
        见 `anti-patterns` 15）
  - [ ] **`initial` 的出边有 `trigger` / `guard` 吗？要「记忆恢复」给了默认去向吗？**（见 `anti-patterns` 16）

## 第 5 步：结构建模 —— 谁在物理上承担这些功能

- **输入**：功能 / 行为清单。
- **动作**：
  1. 先建 `PartDefinition`（类型，如 `BatteryPack`）；
  2. 再建 `PartUsage`（这次具体用的那个，**必须带 `typeRef` 指向那个定义**）；
  3. 用 `connects` 关系把物理链路串起来（**别漏环节**，见 `anti-patterns` 第 6 条）。
- **产出**：`PartDefinition` + `PartUsage` + `connects` 关系。
- **自检**：
  - [ ] 每个 `PartUsage` 的 `typeRef` 都指向一个**已存在的 `PartDefinition`**吗？（指向别的 kind 会报
        `E-PARTUSAGE-TYPEREF-WRONGKIND`）
  - [ ] 我刚建的每个 `PartDefinition`，最后都被某个 `PartUsage` 用到了吗？（没用到会出
        `W-PARTDEF-UNUSED`）
  - [ ] 链路两端的元素**都已在模型里**吗？（`connects` 的 target 也要存在）
  - [ ] 数量用 `quantity` 数字表达了吗？（别写进 `description` 里）

## 第 6 步：参数与约束 —— 指标写成数值属性

- **输入**：第 5 步的结构 + 第 1 步的验收判据。
- **动作**：
  - 性能指标建成 `Attribute`：`valueType` + `defaultValue` + `unit` **三件套**。
  - 物理公式 / 恒等关系建成 `Constraint`（**v1 增补 kind**，已支持）：`expression` 写单行公式，
    `parameters` 列出公式里用到的 `Attribute` id（**先建参数，再建约束**）。老工具版本还没收录
    `Constraint` 时，才退回写进该 `Attribute` 的 `description`——**别为了放公式去自创 kind**。
  - 需求里的阈值放进该 `Requirement` 的 `properties`，**必须是数字**。
- **产出**：`Attribute` 元素 + `Constraint` 元素（可选）+ 需求上的数值阈值字段。
- **自检**：
  - [ ] 每个量都是**数字 + 独立 unit 字段**吗？（写成 `"4 小时"` 会报 `E-PROP-THRESHOLD-STRING`）
  - [ ] `defaultValue` 的类型和 `valueType` 对得上吗？（`Real` 配数字、`Boolean` 配布尔……）
  - [ ] 我是不是把「物理上必然成立的关系」写成了需求？（那是 `Constraint`，见 `element-choice` 案例 2）
  - [ ] 如果建了 `Constraint`：`expression` 是**单行**吗？`parameters` 里的每个 id 都指向**已存在的 `Attribute`** 吗？

## 第 7 步：校验 —— 改到没有 error

- **输入**：完整的 IR JSON。
- **动作**：`validate_model_json(model)`。
- **产出**：`{ok, errors, warnings}`。**必须把 errors 清零才往下走。**
- **自检**：
  - [ ] `ok == true` 吗？
  - [ ] 每条 error 我都**改回了 JSON**、而不是去改文本吗？
  - [ ] `warnings` 我逐条看过了吗？——warning 不拦人，但每一条都在说「这里可能有问题」：
    - `W-REQ-NO-SATISFY`：这条需求没人满足 → 回第 5 步补 `satisfiedBy`；
    - `W-REQ-NO-VERIFY`：标了 `verifyMethod` 却没有 `verifies` 关系 → 补验证链；
    - `W-PARTDEF-UNUSED`：定义没被实例化 → 补 `PartUsage` 或删掉它。

## 第 8 步：追溯检查 —— 确认没有孤立与断链

> `traceability` 工具**已实现**（需求矩阵 / 缺口 / 影响面）。追溯检查**先用它拿到全局视图**，
> 再用 `query_model` 做单点复核——两者不是替代关系：`traceability` 回答「整个模型缺什么」，
> `query_model` 回答「这个 id 被谁引用」。

- **输入**：通过校验的 IR JSON。
- **动作**：
  - `traceability(model)` → 需求矩阵（`matrix`：每条需求的 `satisfiedBy` / `verifiedBy` 与四种状态）
    + 缺口 `gaps`（`unsatisfied` / `unverified_requirement` / `unverified_action`）；
  - `traceability(model, fmt="md")` → 可直接贴进报告的 Markdown 矩阵（`content`）；
  - `traceability(model, focus=<id>)` → 「改这里会波及谁」的反向影响面（`impact`，BFS）；
  - `query_model(unsatisfied_requirements=true)` / `query_model(referrers_of=<id>)`
    → 单点复核某个元素（口径见 `anti-patterns` 14）。
- **产出**：需求矩阵 + 缺口清单（未满足 / 未验证）+ 影响面。
- **自检**：
  - [ ] `traceability` 的 `gaps.unsatisfied` 是空的吗？不是 → 回第 5 步补 `satisfiedBy`，
        或明确标注该需求**待定**并告诉用户。
  - [ ] `gaps.unverified_requirement` 是空的吗？每条需求都至少有一条 `verifies`（验证）关系吗？
  - [ ] 我新建的元素，在追溯图上连得上吗？（孤立元素 = 白建，用 `focus=<新id>` 看一眼影响面）

## 第 9 步：生成文本、回验、汇报

- **输入**：通过校验的 IR JSON。
- **动作**：
  1. `generate_sysml(model)` → SysML v2 文本（**同输入必得同输出**，别手改）；
  2. `verify_sysml(text, model)` → 回验（语法自查 + 与 IR 的元素级比对）；
  3. 汇报。
- **产出**：SysML v2 文本 + 回验结果 + 一段人话汇报。
- **自检**：
  - [ ] `verify_sysml` 的 `ok == true` 吗？（有 `missing` / `extra` / `mismatched` 说明文本与模型不一致，
        那是生成器或 IR 的问题，**回去改 JSON**）
  - [ ] 汇报里我说清了这三件事吗：**产出了什么**、**关键决策理由**、**哪些地方要人工确认**？
  - [ ] 我有没有把「待人工确认项」藏起来？（方案 10.1：顶层架构划分、需求分解策略、仿真边界设定
        不由智能体单独拍板——必须显式交回给用户）

### 第 9 步补充：交付前模型级自检清单

`verify_sysml` 绿了只说明「文本 == IR」，不说明「模型没问题」。交付前再逐条过一遍（5 条）：

- [ ] **owner 挂对了吗？** 每个元素的 `owner` 指向的父元素是不是它该在的位置（不是「随便挂了个存在的 id」）；
- [ ] **命名干净吗？** 无空名、无首尾空格、无占位名（`unnamed1` / `item1`）、**同概念没有两个名字**
      （见 `anti-patterns` 13）；
- [ ] **有孤儿元素吗？** 每个新建元素都至少被一条关系引用或引用别人（见 `anti-patterns` 14）；
- [ ] **链路闭合吗？** 从需求能走到结构（`satisfiedBy`）、从结构能走到验证（`verifies`）；
- [ ] **文本与模型一致吗？** `verify_sysml` 已核（`missing` / `extra` / `mismatched` 全空）。

### 第 9 步补充：汇报纪律（三档表述与引用纪律）

- **区分三档表述，不混写**：**模型事实**（`query_model` / `validate_model_json` 查证过的）/
  **规范语义**（SysML v2、方案的约定）/ **自己的推断**（「大概是」「应该是」）。
  **推断不得写成事实**——推断要显式标「这是我的推断，需你确认」。
- **引用模型细节前先查证**：说得出元素名就有对应的 id，**不许凭记忆臆造模型里没有的元素**。
  （依据优先级：模型事实 > 规范 > 推断。来源：Cameo 便携包 AGENTS.md 的依据优先级链）

---

## 一页速查

```
1 理解需求 ──有验收判据吗？没有就先追问
2 查现状 ────query_model：id/name 占用？引用目标存在？
3 功能分解 ──每步问「这由什么完成」
4 行为建模 ──「持续处于某状态+事件迁移」→ State；否则 Action
5 结构建模 ──先 Definition 再 Usage；Usage 必带 typeRef；别漏链路环节
6 参数约束 ──数字 + 独立 unit；公式进 Constraint（v1 增补）；自创 kind 是禁区
7 校验 ──────validate_model_json，errors 清零，warnings 逐条读
8 追溯检查 ──traceability（矩阵/缺口/影响面）+ query_model 单点复核
9 生成汇报 ──generate_sysml → verify_sysml → 说清「产出了什么/为什么/待确认」+ 交付自检 5 条
```

## 常见卡点

| 卡在哪 | 十有八九是 |
| --- | --- |
| 第 1 步就写不出验收判据 | 这还不是需求，是愿望。追问用户要可判定的判据 |
| 第 5 步 `typeRef` 校验不过 | 你在引用一个还没建的 `PartDefinition`，或者引用了一个非 PartDefinition 元素 |
| 第 7 步反复报同一个码 | 你在改文本而不是改 JSON |
| 第 8 步总有孤立需求 | 第 5 步的结构没建完，或者这条需求本来就还没设计定，该如实告诉用户 |
| 第 9 步 `verify_sysml` 报 mismatched | 生成文本被手工改过，或者 IR 在上次生成后被改过——重新生成 |
