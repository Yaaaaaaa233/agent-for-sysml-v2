---
name: anti-patterns
description: "SysML v2 IR 建模的反模式清单：每条给出【错误现象 / 为什么错 / 正确做法 / 校验会报什么码】。当校验报错、老师/同学打回、或在动手前想把已知的坑一次性避开时加载本 skill。Triggers: 报错了, 校验不过, 老师说不合格, 反模式, 常见错误, 又错了, 之前踩过的坑, anti-patterns, 别再犯, 复盘."
metadata:
  version: "1.1.0"
  last_updated: "2026-10-17"
  status: active
  task_type: open-ended
  related_skills:
    - modeling-workflow
    - element-choice
---

# anti-patterns —— 反模式清单

**用法**：动手前扫一遍（三分钟），或报错后按 `错误码` 直接定位。
每条格式固定为 **现象 / 为什么错 / 正确做法 / 校验响应**。

> 这份清单与「纠错记忆」联动：每次被人工指出一个新错误，就在这里加一条（方案 3.4 的飞轮）。
> 加条目的门槛是——**它必须能改变下一次的动作**；「要注意规范」这种话不许写进来。
>
> 标注「来源：Cameo 案例实证」的条目，提炼自真实工具（Cameo / MagicDraw）自带官方案例里
> **已逐字核实过的瑕疵**，再改写为我们 IR 语境下的规则——不是我们的模型犯过，但同样会犯。
---

## 1. 需求没有验收判据

| | |
| --- | --- |
| **现象** | `properties` 里只有 `text: "续航要够久"`，`acceptanceCriteria` 缺了或写成「续航满足任务要求」。 |
| **为什么错** | 没有判据的需求**无法被验证，也无法被满足**——追溯矩阵上它永远是个悬空节点，仿真跑完了也不知道算不算通过。写「满足任务要求」等于把判据又推回给人。 |
| **正确做法** | 写成**可客观判定**的句子，并把阈值拆成**数字字段**：<br>`acceptanceCriteria: "在巡航速度 v 与转速比 eta 的稳态工作点下，满电续航时间 T >= 4.0 h"`，同时 `minEnduranceHours: 4.0`。 |
| **校验响应** | `E-REQ-NO-ACCEPTANCE`（缺或空白）；阈值写成字符串则追加 `E-PROP-THRESHOLD-STRING`。 |

## 2. 引用了不存在的元素（悬空引用）

| | |
| --- | --- |
| **现象** | `relations[].target` 或 `PartUsage.typeRef` 指向一个「我知道它应该有、但还没建」的元素。模型看着挺合理，一改就崩。 |
| **为什么错** | 这是**最隐蔽的一类错误**：文本照样能渲染出来，人眼扫过去完全正常，但模型已经不闭合了——追溯链断了，别人的工具按 id 查会查不到。方案 4.4 第 3 条专门为它设了强制检查。 |
| **正确做法** | **先建被引用的元素，再建引用方**（`modeling-workflow` 第 2 步就把「把目标 id 抄下来」列为自检项）。引用前用 `query_model(referrers_of=...)` 或直接查一次目标 id 是否存在。 |
| **校验响应** | `relations.target` → `E-REL-TARGET-DANGLING`；`typeRef` → `E-PARTUSAGE-TYPEREF-DANGLING`。 |

## 3. 命名冲突

| | |
| --- | --- |
| **现象** | 同一个 owner 下两个元素都叫 `Motor`；或者两个不同元素共用了同一个 `id`。 |
| **为什么错** | `id` 是模型内的唯一键（追溯、增量编辑、导出全靠它），`name` 是落进 SysML 文本的标识符。重了以后「按 id 查」和「按名字引用」都变成多义的，**改了 A 可能改到 B**。 |
| **正确做法** | `id` 用带前缀的 kebab-case（`PART-DEF-MOTOR` / `PART-USAGE-MOTOR-UPPER`），`name` 用大驼峰或小驼峰并把角色写进名字（`upperMotor` / `lowerMotor`）。动手前跑一次 `query_model(duplicates=true)`。 |
| **校验响应** | `E-ID-DUP`；同 owner 同名 → `E-NAME-DUP`。注意：**不同 owner 下可以同名**，那不算冲突。 |

## 4. 把单位写进字符串

| | |
| --- | --- |
| **现象** | `"minEnduranceHours": "4 小时"`、`"quantity": "4"`、`"capacity": "1200 Wh"`。 |
| **为什么错** | 字符串**不能参与计算，也不能被导出**（方案的 `export_simulink` 要拿它做仿真）。而且单位一旦进了字符串，单位就不一致了——有人写 `"4h"`、有人写 `"4 小时"`、有人写 `">=4h"`，机器一个都读不懂。 |
| **正确做法** | 数值写数字，单位单独成字段：`"minEnduranceHours": 4.0`（单位在 `Attribute.unit` 里，或写 `{"value": 4.0, "unit": "h"}`）。 |
| **校验响应** | `E-PROP-THRESHOLD-STRING`；`quantity` 写成字符串 → `E-PROP-TYPE`。 |

## 5. 把常量写成需求

| | |
| --- | --- |
| **现象** | 把 `P = U·I`、`T = E/P` 这种物理公式或「额定电压 24 V」建成 `Requirement`。 |
| **为什么错** | 需求是「**要做到什么**」，公式和常量是「**世界是怎样的**」。混在一起的后果很具体：追溯矩阵里会出现一条**永远不会失败的需求**（因为它在任何设计下都成立），评审时一条就能问倒你；而且需求条目被稀释，真正的约束反而被淹没。 |
| **正确做法** | 物理关系 → `Attribute`（公式写进 `description`）；固有值 → `Attribute` + `defaultValue`；只有带「不低于 / 不大于 / 必须」的门槛才建 `Requirement`。判据口诀：**「换个设计会不会变」——会变是需求，不会变是参数。** |
| **校验响应** | 校验**不会报错**（结构合法）——这条正是方案 10.1 说的「validate 只抓结构错误，不抓建模质量错误」。靠本清单 + 人工评审拦。 |

## 6. 功率链漏掉电调（以及任何「少一环」）

| | |
| --- | --- |
| **现象** | 结构链写成「电池 → 电机 → 桨」，`connects` 直接连电池到电机；或者上下桨只建了一副。 |
| **为什么错** | 功率链每少一环，**效率链就少一个乘积项**，算出来的续航会偏乐观；`export_simulink` 导出的参数表少一项，仿真结果和模型对不上。共轴八旋翼尤其致命——**上下桨各占一条并联支路**，只建一条就把 8 副桨算成了 4 副。 |
| **正确做法** | 链路逐环建齐：`电池 → 电调 → 电机 → 桨`，且上桨、下桨各一条支路（`quantity: 4` / `quantity: 4`）。用 `connects` 逐段连接，每段都指向**已存在**的元素。建完自查：`query_model(referrers_of=<链路末端>)` 看能不能从电池一路走到桨。 |
| **校验响应** | 目标存在性靠 `E-REL-TARGET-DANGLING` 兜底；**「少了一环」本身校验抓不到**，靠本清单与标杆案例对照。 |

## 7. 把状态机画成流程图

| | |
| --- | --- |
| **现象** | `StateDefinition` 的 `states` 写成 `["Start", "Step1", "Step2", "End"]`，transitions 是一条直线，没有任何 trigger。 |
| **为什么错** | 状态机的价值在**「停下来等事件」**：能被外部事件打断、能跳回、能在某状态里停留并让参数漂移。直线流程没有任何停留与跳转，建出来是个装饰品，占着 `states` 却不表达任何行为语义。 |
| **正确做法** | 先问「这个环节**能不能停在里面**、**会不会被事件踢出去**」。会 → 状态（补 `trigger`，必要时补 `guard`）；不会 → 它其实是 `ActionDefinition` 里的一个步骤。方案 7.3 要的正是「巡航状态下遇逆风导致参数漂移」，那就是状态内的自迁移。 |
| **校验响应** | 结构上不报错（`states`/`transitions` 语法合法）；`from`/`to` 写错才报 `E-STATE-TRANSITION-ENDPOINT`。 |

## 8. 只建 Definition 不建 Usage（或反过来）

| | |
| --- | --- |
| **现象** | 建了 `BatteryPack`、`Motor` 一堆 `PartDefinition`，一个 `PartUsage` 都没有；或者反过来，`PartUsage` 的 `typeRef` 指向一个还没建的 `PartDefinition`。 |
| **为什么错** | 只建定义 = **图纸上的零件，从未真正装上飞机**——`quantity`、`connects`、`satisfiedBy` 全都无处落脚；只建用法 = 悬空引用，必报错。两者是「类型」与「这一次具体用的那个」的关系，**缺一不可**。 |
| **正确做法** | 成对建：`PartDefinition`（类型）+ `PartUsage`（具体那一份，带 `typeRef` 与 `quantity`）。定义建完立刻问一句「它在模型里被用到了吗」。 |
| **校验响应** | 只有定义没用法 → `W-PARTDEF-UNUSED`（warning，不拦）；只有用法没定义 → `E-PARTUSAGE-TYPEREF-DANGLING`（error，拦）。 |

## 9. 自创 kind 或自创关系类型

| | |
| --- | --- |
| **现象** | 建 `"kind": "Constraint"`、`"kind": "Port"`、`"kind": "Interface"`，或 `"type": "derives"`、`"type": "implements"`。 |
| **为什么错** | 受控枚举是方案 4.3「宁窄勿宽」的地基：**kind 一多，渲染模板、校验规则、选型决策树跟着膨胀，模型选错的概率成倍上升**。而且自创的种类渲染器不认识，文本里会冒出一个我们不负责的东西。 |
| **正确做法** | 只用这 6 种 kind：`PartDefinition` / `PartUsage` / `Requirement` / `ActionDefinition` / `StateDefinition` / `Attribute`；只用这 5 种关系：`refines` / `satisfiedBy` / `decomposes` / `verifies` / `connects`。确实需要新的（比如 `Constraint`）→ **走方案 9.2 的二期流程加一种**，并同步补渲染模板、测试与反模式，而不是当场自创。 |
| **校验响应** | `E-KIND-INVALID`；关系类型 → `E-REL-TYPE-INVALID`。 |

## 10. 需求没有 satisfiedBy / 标了 verifyMethod 却没有验证链

| | |
| --- | --- |
| **现象** | 需求建得挺漂亮，但没人满足它，也没人验证它。 |
| **为什么错** | 这是**断链**。MBSE 的全部价值在追溯：一条孤立需求在评审时无法回答「你打算怎么做到」「你怎么知道做到了」——它只是一句写在模型里的愿望，跟写在 Word 里没区别。 |
| **正确做法** | 每条需求至少两条线：`satisfiedBy`（谁满足它，可以是结构也可以是功能）+ `verifies`（谁验证它，MVP 用仿真工况 `ActionDefinition` 充当验证方）。定期跑 `query_model(unsatisfied_requirements=true)`。 |
| **校验响应** | `W-REQ-NO-SATISFY` 与 `W-REQ-NO-VERIFY`（都是 warning，所以**不主动看就会漏**）。 |

## 11. 手改生成出来的 SysML 文本

| | |
| --- | --- |
| **现象** | 生成文本后觉得某一行不顺眼，直接在文本里改；或者在文本里补一条模型里没有的元素。 |
| **为什么错** | 文本是**渲染产物**，不是事实来源。手改之后，「模型」与「文本」两份东西就分叉了——下次重新生成会把你的修改全部抹掉；更要命的是**追溯、导出、回验全都基于 IR**，文本里的东西 IR 不知道，等于没建。方案 3.2 明写：**IR JSON 是模型的唯一事实来源。** |
| **正确做法** | **改 JSON，然后重新生成。** 回验（`verify_sysml`）会用 `missing` / `extra` / `mismatched` 三个列表把「文本里多出来的 / 少了的 / 对不上的」逐条点出来，正好用来抓这件事。 |
| **校验响应** | `verify_sysml` 报 `extra`（文本多出声明）或 `mismatched`（同一元素两边不一致）。 |

## 12. 顺手改动无关元素

| | |
| --- | --- |
| **现象** | 用户只要求「加一条需求」，结果顺手改了别人的需求正文、重排了 id、删了几个「看起来没用」的元素。 |
| **为什么错** | 模型是可 diff、可评审、可版本化的工程资产（方案 2.4 第 4 条）。无关改动会**污染 diff**，让评审者无法一眼看出这次改了什么；删元素还会把别人的追溯链一起删掉。 |
| **正确做法** | **只改用户要求的那一棵子树。** 需要动无关元素时，先说明理由并征得同意。改完用 `git diff` 级别的粒度汇报「只动了哪些 id」。 |
| **校验响应** | 校验抓不到——靠流程与人工评审拦。 |

## 13. 命名脏数据：空名、尾随空格、拼写不一致、同概念两个名字

| | |
| --- | --- |
| **现象** | `name` 为空或全是空格；名字带首尾空格（`"Name read "`）；同一概念两处写法不一致（一处 `Queen`、一处 `Quaaaaeen`）；用占位名（`unnamed1`、`item1`）。 |
| **为什么错** | 名字一脏，按名字做映射、写脚本替换、渲染文本时全成事故；同概念两名更糟，评审会以为是两个不同的东西。Cameo 官方案例自己就犯了这四种：4 个事件名带尾随空格、升变迁移名拼错 `Quaaaaeen`、2 个守卫被工具自动命名 `unnamed1`/`unnamed2`、1 个匿名状态。<br>**关键区分**：Cameo 的 UML 名字是**自由文本**，所以这四种都藏得住；我们的 `name` 是 **SysML 标识符**，空名 / 带空格名 / 连字符名会被 `E-NAME-INVALID` 在门口拦下——**真正混进模型的是「同概念两个名字」与「占位名」，因为它们都是合法标识符**。 |
| **正确做法** | 建之前 `name` 先 `trim`；**同概念全模型只留一个写法**；弃用占位名（没想好名字 = 还没想清这个元素是什么）。命名约定：`Requirement` / `ActionDefinition` 用动宾短语（`RegisterReturn` 风格），`PartDefinition` 名词大驼峰（`BatteryPack`），`PartUsage` 小驼峰带角色（`upperMotor`）。动手前跑 `query_model(duplicates=true)`。 |
| **校验响应** | `E-NAME-INVALID` 抓空名、含空格名（含首尾空格）、连字符名（`name` 必须匹配 `^[A-Za-z_][A-Za-z0-9_]*$`）；`E-NAME-DUP` 抓同 owner 重名。**同概念两名（`Queen` vs `Quaaaaeen`）与占位名（`unnamed1`）是合法标识符，validate 放行**，靠本清单与人工评审拦。 |

来源：Cameo 案例实证（03 文档 §4#1/#3/#5/#6）。

## 14. 孤儿元素与半截链路

| | |
| --- | --- |
| **现象** | 元素建了却没有任何关系引用它（孤立事件、没人引用的 `Attribute`）；声明了出口却没有入口（出口点作为 `target` 出现 0 次）；`description` 为空的占位元素。 |
| **为什么错** | 模型噪声 + 语义破洞。「兵被吃掉」的出口点有出边没入边，等于这条路**进不去**；孤立元素在读图/清理时又常被误删（因为它看起来没用）。追溯图上出现断头节点，评审第一个问的就是它：「这条线从哪来？」 |
| **正确做法** | 建完立刻跑 `query_model(referrers_of=<新元素id>)`，零引用的要么接上、要么删掉；每条链路两端都问一遍「**谁能走到它、它能走到谁**」。 |
| **校验响应** | `W-ELEMENT-ORPHAN`（warning）**当前实现只覆盖 `PartDefinition`**（既无引用也无 relations 才报）；其他 kind（`Attribute`、`Requirement` 等）的孤立 **validate 不报**，靠 `query_model(referrers_of=<id>)` 自查；需求侧另有 `W-REQ-NO-SATISFY`。 |

来源：Cameo 案例实证（03 文档 §4#4/#7/#9/#10）。

## 15. 判定分支的守卫不互斥或不完备

| | |
| --- | --- |
| **现象** | 同一判定出口的多条 transition 守卫有重叠（`[speed > 10]`、`[speed > 5]`），或者有遗漏（只写了 `[low battery]`，没写兜底 else）。 |
| **为什么错** | 重叠时条件落到**哪个分支不确定**，行为语义随工具实现漂移；遗漏时那种情况发生时「**不知道去哪**」。正面样板是二分守卫 `[reservation list is empty]` / `[... is not empty]`——互斥且完备，读图的人一眼能穷举所有情况。 |
| **正确做法** | 判定出口逐个写守卫，然后检查两两不重叠、合起来覆盖全集；覆盖不了就补一条兜底出口。自查口诀：**互斥 = 没有任何输入会同时命中两条；完备 = 任何输入至少命中一条**。 |
| **校验响应** | 校验抓不到（结构完全合法：不是缺 `from`/`to`，是守卫条件之间的矛盾）。靠建模-workflow 第 4 步的状态机自检清单与人工评审拦。 |

来源：Cameo 案例实证（03 文档 §3#2 与 §4 末尾正面样板）。

## 16. 初始迁移挂触发器、历史伪状态没有默认出口

| | |
| --- | --- |
| **现象** | `initial` 状态的出边 transition 挂 `trigger`（甚至挂 `guard`）；声明了「断电记忆」这类历史语义，却没有给「从未运行过」时的默认去向。 |
| **为什么错** | 初始迁移是「**进入即走**」的完成迁移，挂触发器等于入口**永远在等一个不会来的事件**（官方案例的兵图就犯了：外层初始 → `Unmoved` 挂了 `create` 信号事件）；历史语义没有默认出口时，「机器从未运行过就直接恢复供电」这条路径**无定义**，行为取决于工具实现。 |
| **正确做法** | `initial` 的出边一律不写 `trigger` / `guard`；需要「上电触发」就**显式建一个上电状态或一条事件迁移**，别偷偷挂在初始边上。要「记忆恢复」就必须**同时**给默认去向（历史为空时指向起始子状态）。 |
| **校验响应** | `from` / `to` 写错或不在 `states` 里才报 `E-STATE-TRANSITION-ENDPOINT`；**「初始出边挂了 trigger」这件事 validate 不报**（结构合法），靠自检与评审拦。 |

来源：Cameo 案例实证（03 文档 §4#2/#8）。

---

## 速查：错误码 → 该看哪一条

| 错误码 | 看本清单第几条 |
| --- | --- |
| `E-REQ-NO-ACCEPTANCE` / `E-REQ-NO-TEXT` | 1 |
| `E-REL-TARGET-DANGLING` / `E-PARTUSAGE-TYPEREF-DANGLING` / `E-PARTUSAGE-TYPEREF-WRONGKIND` | 2、8 |
| `E-ID-DUP` / `E-NAME-DUP` / `E-NAME-INVALID` | 3（同概念两名/占位名见 13） |
| `E-PROP-THRESHOLD-STRING` / `E-PROP-TYPE` | 4 |
| `E-KIND-INVALID` / `E-REL-TYPE-INVALID` / `E-ENUM-INVALID` | 9 |
| `W-REQ-NO-SATISFY` / `W-REQ-NO-VERIFY` | 10（需求侧孤立见 14） |
| `W-PARTDEF-UNUSED` / `W-ELEMENT-ORPHAN` | 8、6、14 |
| `E-STATE-TRANSITION-ENDPOINT` | 7、16 |
| `E-REL-FIELD-MISSING` / `E-REL-NO-RATIONALE` | 关系必须写清「为什么连这一条」——没理由的追溯关系等于没建立 |
| `verify_sysml` 报 `extra` / `mismatched` | 11 |
| 校验全绿但老师说不合格 | 5、6、7、12、13、15、16（**这些是建模质量问题，validate 抓不到**，见方案 10.1） |
