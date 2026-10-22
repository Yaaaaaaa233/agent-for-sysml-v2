# 模型树生长实录 · 逐轮建模任务书（粘贴即用）

> **怎么用**：在「SysML v2 建模」preset 的**新会话**里，把本文件全文粘给 agent。之后每轮结束它都会停下，你说「**继续**」进入下一轮；最后一轮说「**验收**」。
>
> **这份任务书已离线预演**：按下面的轮次/规则跑完 12 轮，每轮 `errors=0`，终态与标杆模型**语义完全相等**，生成文本 sha256 = `bb64cc2c…`（与 `docs/verification/local/golden-2026-10-20/model.sysml` 逐字节一致）。表里的元素数 / 关系数 / warnings 都是实测值，agent 用 `check_turn.py` 自检即可。
>
> **这一场是录屏演示**：右侧模型树要从 **1 个节点**逐步长到 **34 个元素**，节奏比速度重要。

---

## 一、目标、文件与角色

| 项 | 说明 |
| --- | --- |
| **目标终态** | 与标杆 `sysml-modeling-agent/examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json` **语义完全相等**（34 元素 / 20 关系），生成文本 sha256 = `bb64cc2c…` |
| **过程** | 12 轮，每轮把一小批元素**追加**进工作模型；每轮都是一次真实的增量编辑，不是整份覆盖 |
| **当前模型**（视图读它） | `model-output/q2-demo/q2-demo.ir.json` —— 全程只动这一个文件 |
| **标杆（参考答案，只读）** | `sysml-modeling-agent/examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json` —— 只读；元素对象从这里取 |
| **过程记录**（侧栏用） | `.sysml-viz/history/` —— 阶段 A 清空一次，之后由插件自动记录，**不要手写** |
| **自检脚本** | `sysml-modeling-agent/docs/demo/record-tree-growth/check_turn.py` —— 每轮跑一次，一行给出元素/关系/校验/sha（只读） |

> 工作区根就是当前会话工作区（`pwd` 可确认）。下面所有命令都在工作区根执行。

---

## 二、每轮固定动作（12 轮一致）

**① 确认锚点**（只看文件末尾 ~15 行）：文件必须以这三行结尾（第 1 行 **4 个空格** + `}`，第 2 行 **2 个空格** + `]`，第 3 行顶格 `}`）：

```
    }
  ]
}
```

这是**唯一**的追加锚点（全文件仅一处，位于 EOF）。

**② 追加本轮元素**：用 `edit`，
- `old_string` = 上面这三行；
- `new_string` = `    },` + 本轮元素块（每块 4 空格缩进，块之间用 `,` 隔开）+ 上面这三行；
- 元素对象**从标杆文件按 `id` 取**（整份对象，含 `properties`），除下表注明外**不要改动**；
- 元素之间的先后顺序 = 下表给出顺序；
- **T1 / T2 的元素要"只留 refines"**（删掉 `satisfiedBy` 那条，T12 再补）；其余轮次整份照抄。

**③ 跑自检**（一行输出，必须 `PASS`）：

```bash
sysml-modeling-agent/.venv/bin/python sysml-modeling-agent/docs/demo/record-tree-growth/check_turn.py --expect-elements <N> --expect-relations <M>
```

`<N>`/`<M>` 用下表对应轮次的值。`PASS` 要求 `errors=0`，且元素/关系数对得上。

**④ 只回一行，然后停住等我说「继续」**：

```
T<k> 完成：<check_turn 输出>。等你「继续」。
```

> **关于 warnings**：中间轮次会出现 `W-ELEMENT-ORPHAN` / `W-PARTDEF-UNUSED` / `W-REQ-NO-SATISFY` / `W-REQ-NO-VERIFY`，这是**预期**的（模型还没长完）。判定只看 `errors=0`（PASS 已包含）；**T12 必须 warnings=0**。
>
> **格式**：追加的 JSON 只要合法即可，缩进保持 4 空格（与文件一致）。**不要**为了"看起来整齐"重排已有内容——追加式修改是为了让每一轮的历史差异干净。
>
> **可选（画面需要的话）**：每轮末尾可以额外调一次模型工具 `query_model(path="<工作区绝对路径>/model-output/q2-demo/q2-demo.ir.json", limit=1)` 做一次"查现状"（结果很小）；不是必须，不影响判定。

---

## 三、阶段 A：备份 + 清空（收到任务书先做这个，做完停下）

### A1. 备份（先留后路）

```bash
mkdir -p model-output/q2-demo/_evidence/recording-2026-10-22/before
cp model-output/q2-demo/q2-demo.ir.json model-output/q2-demo/_evidence/recording-2026-10-22/before/q2-demo.ir.json
cp -R .sysml-viz/history model-output/q2-demo/_evidence/recording-2026-10-22/before/history
shasum -a 256 model-output/q2-demo/_evidence/recording-2026-10-22/before/q2-demo.ir.json
```

期望 sha256 = `adae5c6146a3e0f3f8e5eff0982f1efb258efba3bdac3b76e3445eaa078af0e3`（当前标杆等价模型）。
`_evidence/` 是安全位置（视图发现工作模型时优先级远低于 `model-output/q2-demo/*.ir.json`，不会被误选）。

### A2. 写 1 元素基线（"空树"起点）

先 `read` 标杆与当前模型，然后用 `write` 把工作模型替换为：

- `schema` = `sysml-ir/v1`、`package` = `CoaxialOctoRotor`、`meta` = **整份照抄标杆**；
- `elements` 只有 1 个：标杆里第 1 个元素 `REQ-MISSION-ENDURANCE`（`MissionEndurance`），**`relations` 写成 `[]`**（其余字段原样），便于 T1 用 `edit` 精准插入关系；
- 2 空格缩进、`ensure_ascii=False`、文件末尾换行。

然后跑：
```bash
sysml-modeling-agent/.venv/bin/python sysml-modeling-agent/docs/demo/record-tree-growth/check_turn.py --expect-elements 1 --expect-relations 0 --expect-warnings 2
```
应 `PASS … text_sha=<某值>`（warnings 2 是预期的两条"需求尚未满足/未被验证"）。

### A3. 清空过程记录

```bash
rm -rf .sysml-viz/history
```

（界面等效操作：侧栏「建模过程」面板的「清空记录」按钮。**二选一**，不要两边都做。）视图会在 2 秒内自动重建基线：**步骤 = 1（baseline）、元素 = 1、关系 = 0**。

### A4. 自检并停下

回报一行，格式：
```
阶段 A 完成：基线 1 元素 / 0 关系 / validate ok（warnings 2）；备份在 model-output/q2-demo/_evidence/recording-2026-10-22/before/；过程记录已重置为 1 步。等你「继续」。
```

---

## 四、阶段 B：12 轮生长（每轮做完停下）

**元素数 / 关系数 / warnings 是该轮结束后的累计实测值**；用 `check_turn.py --expect-elements N --expect-relations M` 自检。

| 轮次 | 本轮追加（按此顺序，从标杆取对象） | 元素 | 关系 | warnings | 这一轮在讲什么（可直接口播） |
| --- | --- | ---: | ---: | ---: | --- |
| **T1** | `REQ-CRUISE-ENDURANCE`（relations 只留 `refines`）、`REQ-ROTOR-SPEED-RATIO`（relations 只留 `refines`）；**另做一次 edit（先做这次，再追加元素）**：把 `REQ-MISSION-ENDURANCE` 的 `"relations": []` 换成含 `decomposes → REQ-CRUISE-ENDURANCE` 的数组（对象照标杆） | 3 | 3 | 6 | 任务级续航拆出「巡航续航」和「转速比区间」两条子需求 |
| **T2** | `REQ-POWER-BUDGET`（relations 只留 `refines`） | 4 | 4 | 8 | 再加功率预算需求：巡航功率不超过电池持续放电的 90% |
| **T3** | `PART-STRUCT-SYSTEM`（整机）、`PART-POWER-CHAIN`（功率链） | 6 | 5 | 10 | 结构层落地：整机系统 + 功率链子系统 |
| **T4** | `PART-BATTERY-PACK`、`PART-ESC`、`PART-MOTOR`、`PART-PROP-UPPER`、`PART-PROP-LOWER` | 11 | 5 | 20 | 功率链五个零件定义：电池包 / 电调 / 无刷电机 / 上桨 / 下桨 |
| **T5** | `PART-USAGE-SYSTEM`（x8System）、`PART-USAGE-POWER-CHAIN`（powerChain） | 13 | 6 | 18 | 整机与功率链各落一份实例 |
| **T6** | `PART-USAGE-BATTERY`、`PART-USAGE-ESC`、`PART-USAGE-MOTOR-UPPER`、`PART-USAGE-MOTOR-LOWER`、`PART-USAGE-PROP-UPPER`、`PART-USAGE-PROP-LOWER` | 19 | 11 | 8 | 功率链内部六份部件实例（电调 ×8、上下电机各 ×4…） |
| **T7** | `CONN-BATTERY-ESC`、`CONN-UPPER-MOTOR-PROP` | 21 | 11 | 8 | 两条连接：电池→电调（电气）、上电机→上桨（机械） |
| **T8** | `ATTR-CRUISE-SPEED`、`ATTR-SPEED-RATIO`、`ATTR-BATTERY-CAPACITY`、`ATTR-USABLE-FRACTION`、`ATTR-CRUISE-POWER`、`ATTR-ENDURANCE` | 27 | 11 | 8 | 参数层：两个决策量 + 电池容量/可用系数 + 巡航功率/续航时间 |
| **T9** | `CONSTRAINT-ENDURANCE-BUDGET`、`ATTR-ESC-EFFICIENCY`、`ATTR-MOTOR-EFFICIENCY`、`ATTR-PROP-EFFICIENCY` | 31 | 11 | 8 | 续航换算约束 + 三段传动效率参数 |
| **T10** | `ACT-SIM-ENDURANCE`、`ACT-ONLINE-OPTIMIZATION` | 33 | 16 | 4 | 行为层：续航仿真工况 + 在线功率优化（带 in/out 参数） |
| **T11** | `STATE-FLIGHT-MODES` | 34 | 16 | 4 | 飞行模式状态机：起飞→巡航→返航/故障→降落 |
| **T12** | 4 次 `edit`：给 4 条需求各追加一条 `satisfiedBy`（见下表） | 34 | **20** | **0** | 追溯落位：四条需求的 `satisfiedBy` 接上实现 |

**T12 的四条关系（顺序即下表；对象必须带 `rationale`，从标杆对应元素里原样取）**：

| 宿主元素 | 追加的关系对象 |
| --- | --- |
| `REQ-MISSION-ENDURANCE` | `{"type": "satisfiedBy", "target": "PART-POWER-CHAIN", "rationale": "由功率链（电池→电调→电机→桨）的整体能量效率保障"}` |
| `REQ-CRUISE-ENDURANCE` | `{"type": "satisfiedBy", "target": "PART-BATTERY-PACK", "rationale": "由电池包可用能量与放电效率保障"}` |
| `REQ-ROTOR-SPEED-RATIO` | `{"type": "satisfiedBy", "target": "ACT-ONLINE-OPTIMIZATION", "rationale": "由在线功率优化功能在寻优时施加区间约束"}` |
| `REQ-POWER-BUDGET` | `{"type": "satisfiedBy", "target": "PART-POWER-CHAIN", "rationale": "由功率链各环节的效率与选型共同保障"}` |

T12 的 `edit` 锚点：先 `read` 该元素的 `relations` 数组区域，`old_string` 取数组最后一个对象到 `]` 的原文，`new_string` = 原文 + `,` + 新关系对象（保持缩进）。

> **为什么 T1/T2 要"只留 refines"**：这几条需求的 `satisfiedBy` 指向后面轮次才出现的元素（功率链 / 电池包 / 优化动作），现在加会 `E-REL-TARGET-DANGLING`。**T3–T11 的元素整份照标杆追加**，不要改（它们的引用目标在同一轮或更早已存在）。

---

## 五、阶段 C：验收（我说「验收」后一次做完，不要停）

按顺序执行，最后给一张汇总表：

**1）结构 + 语义 + 文本 sha 一次过**：
```bash
sysml-modeling-agent/.venv/bin/python sysml-modeling-agent/docs/demo/record-tree-growth/check_turn.py \
  --expect-elements 34 --expect-relations 20 --expect-warnings 0 \
  --expect-text-sha bb64cc2cbfdc5f5667049a76f6b57c4925a6ed29b2344c94d09d70e9ac6f6129 \
  --compare sysml-modeling-agent/examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json
```
必须：`PASS … text_sha=bb64cc2c … compare=equal`。

**2）官方解析器 + 追溯（本地验证脚本，L0→L2）**：
```bash
cd sysml-modeling-agent && .venv/bin/python docs/verification/local/verify_model.py \
  ../model-output/q2-demo/q2-demo.ir.json docs/verification/local/record-2026-10-22
```
退出码应为 0。然后从 `docs/verification/local/record-2026-10-22/report.json` 摘出：`L0 errors=0`、`official diagnostics=0`、`L2 gaps=0`、`model.sysml sha256`（应 = `bb64cc2c…`）。

**3）过程图**：`export_timeline(model_path="model-output/q2-demo/q2-demo.ir.json")`（从模型路径向上找到 `.sysml-viz/history/`，默认写出该目录下 `timeline.svg`），记录文件大小与步数。若报 `E-HISTORY-NOT-FOUND`，先 `pwd` 取绝对路径再传 `history_dir`。

**4）汇总表**：每轮的 元素/关系/warnings（可用过程记录 `index.json` 的 `steps` 逐个核对）、总耗时、终态 `text_sha`、官方解析器结果、timeline.svg 大小。

**5）留档（可选）**：我说「留档」时，把汇总写进 `docs/demo/record-tree-growth/RUN-LOG.md`。

**措辞红线**：只说"模型已按标杆顺序重建完成、与标杆语义一致、生成文本 sha 一致、官方解析器 0 诊断"；**不要**写"验证通过 / 符合 OMG 规范"这类超出证据的话。

---

## 六、红线（违反任何一条，这轮录制就白录了）

1. **不许整份复制/整份覆盖**标杆到工作模型（阶段 A 的 1 元素基线是唯一例外；T1–T12 只能追加/插入）。
2. **不许一轮追加多于清单里的元素**，不许提前加后面轮次的元素。
3. **不许删元素、改 id / name / owner / 顺序、改 `meta`；不许重排已有内容**。
4. **不许修改标杆文件**，也不许动其它 `.ir.json`（`examples/`、`docs/demo/` 里的都不许碰）。
5. **每轮必须停下等「继续」**——不要一口气跑完。
6. 汇报**只写一行**（`check_turn.py` 的输出），不要贴整份 SysML 文本或整份 JSON。
7. 某轮 `PASS` 失败：只在**本轮范围内**修（多半是逗号/括号/遮罩没做对；`--json` 可看完整 errors），最多重试 3 次；还失败就**停下如实报告**，绝对不要"重写一份新的 34 元素模型"糊过去。
8. 录制期间不要跑测试、不要装依赖、不要重启 DSH；视图刷新是自动的（2 秒轮询），不要手动改 `.sysml-viz/`。

---

## 七、附录：常见问题与实测数字

| 现象 | 处理 |
| --- | --- |
| `edit` 报 "old_string not found" / 不唯一 | `read` 文件末尾 15 行核对实际空白与括号；锚点只有一处（EOF）。**不要**因此改成整份 `write` |
| `check_turn.py` 报 JSON parse error | 上一轮追加的逗号/括号错了；`read` 出错位置附近修正 |
| 元素数多了/少了 | 看 `check_turn.py` 的差值和本轮清单；宁可停下报告，不要"猜着删" |
| warnings 比表里多几条 | 只要 `errors=0` 且元素/关系数对，允许；T12 必须回到 0 |
| 侧栏树没刷新 | 等 3–5 秒；确认写的是 `model-output/q2-demo/q2-demo.ir.json` |
| 树突然显示成别的模型 | 说明工作模型文件被改名/删了；把它写回原路径后继续 |

**每轮的数字为什么是这些**（离线实测，供核对）：基线 1/0/w2 → T1 3/3/w6 → T2 4/4/w8 → T3 6/5/w10 → T4 11/5/w20 → T5 13/6/w18 → T6 19/11/w8 → T7 21/11/w8 → T8 27/11/w8 → T9 31/11/w8 → T10 33/16/w4 → T11 34/16/w4 → T12 34/20/w0。
