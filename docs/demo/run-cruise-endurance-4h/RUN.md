# 建模运行记录：给共轴八旋翼加「巡航时间不低于 4 小时」

> **起点**：`docs/demo/step0-before.ir.json`
> **需求**：给共轴八旋翼加一条需求——**巡航时间不低于 4 小时**
> 运行日期：2026-10-17 · 解释器：`.venv/bin/python`（Python 3.11.6，含 `jsonschema` 4.26.0）
> 工具：`sysml-modeling-agent` 本地调用模式（`run_server.py --call`），流程照 `skills/modeling-workflow/SKILL.md` 九步 SOP。
> 本目录下所有输出均为本次会话真实跑出，未手工编辑任何生成文本。

---

## 0. 结论

已新增需求 **`REQ-CRUISE-ENDURANCE` / `CruiseEndurance`**：

| 字段 | 值 |
| --- | --- |
| `text` | 巡航时间不低于 4 小时 |
| `acceptanceCriteria` | 在巡航速度 v 与转速比 eta 的稳态工作点下，满电续航时间 T >= 4.0 h |
| `verifyMethod` | `simulation` |
| `minEnduranceHours` | `4.0`（**数字**，不是字符串） |
| `refines` → | `REQ-MISSION-ENDURANCE`（由任务级续航分解而来） |
| `satisfiedBy` → | `PART-POWER-CHAIN`（由功率链保障） |
| 验证方 | `ACT-SIM-ENDURANCE` 新增 `verifies` → 本需求 |

**校验：0 error / 0 warning**（`schemaLayer: "ok(+0)"`，JSON Schema 第二层也跑了）。
**生成文本 41 行 / 1627 字符，回验 5/5 元素匹配、0 lint error。**
仓库自带测试 **186 个用例全绿**（未改动仓库既有文件）。

---

## 1. 产物清单

| 文件 | 说明 |
| --- | --- |
| [`step1-query.txt`](step1-query.txt) | 第 2 步 `query_model` 查现状的真实输出（元素清单 / 关键字 / 重名 / 引用者） |
| [`step2-revised.ir.json`](step2-revised.ir.json) | 追加需求后的 IR（**仍带** `W-REQ-NO-VERIFY`） |
| [`step3-4-validate.txt`](step3-4-validate.txt) | 两次 `validate_model_json` 的真实输出（改前 1 warning / 改后 0） |
| [`step4-final.ir.json`](step4-final.ir.json) | 补上 `verifies` 后的最终 IR（0 error / 0 warning）✅ |
| [`step5-generate.txt`](step5-generate.txt) | `generate_sysml` 两次运行的输出与确定性比对 |
| [`step5-generated.sysml`](step5-generated.sysml) | 生成产物（sha256 `10f83cce…`），**不得手改** |
| [`step6-verify.txt`](step6-verify.txt) | `verify_sysml` 回验 + 与仓库存档 T6 产物的交叉校验 |
| [`step8-traceability.txt`](step8-traceability.txt) | 第 8 步追溯检查的真实输出 |
| [`step0-diff.txt`](step0-diff.txt) | 变更集 diff（相对起点；以及相对仓库存档 T6） |

---

## 2. 九步 SOP 逐步实录

### 第 1 步：理解需求，判定元素类型

「巡航时间不低于 4 小时」含**「不低于」+ 可判定的数值门槛**（4 h）→ 判据可客观判定
→ **`Requirement`**（`element-choice` 岔路口 A）。不是 `Attribute`：换个设计它就会变，是「要做到什么」，
不是「世界是怎样的」。

### 第 2 步：查现状（**动手前必做**）

```
$ query_model(<step0-before.ir.json>)                       → 4 个元素，无重名（duplicateIds/Names 均空）
$ query_model(keyword="endurance")                          → 命中 ACT-SIM-ENDURANCE、REQ-MISSION-ENDURANCE
$ query_model(keyword="REQ-CRUISE-ENDURANCE")               → count 0，拟用 id 未被占用 ✅
$ query_model(referrers_of="REQ-MISSION-ENDURANCE")         → 被 ACT-SIM-ENDURANCE 通过 relations.verifies 引用 ✅
$ query_model(referrers_of="PART-POWER-CHAIN")              → 被 PART-USAGE-POWER-CHAIN(typeRef) 与 REQ-MISSION-ENDURANCE(satisfiedBy) 引用 ✅
$ query_model(unsatisfied_requirements=true)                → count 0（起点模型自身干净）
```

**结论**：可以「新增」而不是「修改」；`REQ-CRUISE-ENDURANCE` 可用；拟引用的两个目标 id **都已存在**
（抄下来备用，避免反模式第 2 条「悬空引用」）。

### 第 3–6 步：填 IA/IR 表（LLM 只填表，不写 SysML）

新增一个 `Requirement` 元素，并挂两条关系；同时**只动一处既有元素**——给 `ACT-SIM-ENDURANCE`
补验证关系（见第 4 步的 warning）。产物：`step2-revised.ir.json`。

**参数与单位**（第 6 步自检）：阈值 `4.0` 是数字；单位由字段名 `minEnduranceHours` 承载
（对齐起点模型 `minMissionDurationHours: 5.0` 的既有约定）。写成 `"4 小时"` 会报 `E-PROP-THRESHOLD-STRING`。

### 第 7 步：校验 —— 并把 warning 读到底

```
$ validate_model_json(step2-revised.ir.json)
{
  "ok": true,
  "errors": [],
  "warnings": [
    { "code": "W-REQ-NO-VERIFY",
      "element": "REQ-CRUISE-ENDURANCE",
      "message": "该需求标注 verifyMethod=simulation，但尚未建立指向验证用例（仿真/试验）的 verifies 关系。",
      "pointer": "/elements/4/properties/verifyMethod" }
  ],
  "schemaLayer": "ok(+0)",
  "counts": { "errors": 0, "warnings": 1 }
}
```

**这一步是闭环的价值所在**：结构合法（无 error），但校验器精确指出
「你声明了用仿真验证，**可谁去验证它？**」——验证链是断的。

**改 JSON，不改文本**（此刻文本还没生成）。按 warning 指路，给现成的仿真工况补一条关系：

```json
{ "type": "verifies", "target": "REQ-CRUISE-ENDURANCE", "rationale": "同一仿真工况直接验证巡航续航指标" }
```

```
$ validate_model_json(step4-final.ir.json)
{ "ok": true, "errors": [], "warnings": [], "schemaLayer": "ok(+0)", "counts": { "errors": 0, "warnings": 0 } }
```

### 第 8 步：追溯检查

```
unsatisfied_requirements → count 0                       「没人满足的需求」为空 ✅
duplicates               → duplicateIds/Names 均空       无重名/重复 id ✅
referrers_of(REQ-CRUISE-ENDURANCE)  → 1 条 via relations.verifies            （ACT-SIM-ENDURANCE）✅
referrers_of(REQ-MISSION-ENDURANCE) → 2 条 via relations.verifies / refines  （ACT-SIM-ENDURANCE、新需求）✅
referrers_of(PART-POWER-CHAIN)      → 3 条 via properties.typeRef / satisfiedBy ×2 ✅
```

新元素在追溯图上**四个方向都连得上**，无孤立节点。

### 第 9 步：生成 → 回验 → 汇报

```
$ generate_sysml(step4-final.ir.json) ×2
tool sha256 run1 : 10f83cceb91f8aaa470512d55f809b7c3e6a92eb049fd5b49bd8bcff38a64a92
tool sha256 run2 : 10f83cceb91f8aaa470512d55f809b7c3e6a92eb049fd5b49bd8bcff38a64a92
本地复算 sha256  : 10f83cceb91f8aaa470512d55f809b7c3e6a92eb049fd5b49bd8bcff38a64a92
byte-identical   : True          stats: elements 5 / relations 5 / lines 41 / chars 1627

$ verify_sysml(step5-generated.sysml, step4-final.ir.json)
{ "ok": true,
  "counts": { "irElements": 5, "textDeclarations": 10, "matched": 5,
              "missing": 0, "extra": 0, "mismatched": 0, "lintErrors": 0 } }
```

文本里新需求的形态：

```sysml
requirement def CruiseEndurance {
    doc /* 巡航时间不低于 4 小时 */
    doc /* 验收判据: 在巡航速度 v 与转速比 eta 的稳态工作点下，满电续航时间 T >= 4.0 h */
    attribute verifyMethod : String = "simulation";
    attribute minEnduranceHours : Real = 4.0;
    // 追溯关系 (relations):
    //   REQ-CRUISE-ENDURANCE --refines--> REQ-MISSION-ENDURANCE  (…)
    //   REQ-CRUISE-ENDURANCE --satisfiedBy--> PART-POWER-CHAIN  (…)
}
```

---

## 3. 关键决策与理由

1. **建成 `Requirement` 而非 `Attribute`**：带「不低于」的数值门槛 = 需求；若是「本机实测巡航 4.0 h」
   才是 `Attribute`（`element-choice` 案例 6：**「不得低于」= 需求，「是多少」= 参数**）。
2. **阈值写数字 `4.0` + 单位独立成字段**：字符串不能参与计算、也不能被二期 `export_simulink` 导出
   （反模式第 4 条）。
3. **`refines` 指向任务级续航**：巡航段是任务剖面中最长的一段，任务级 ≥5 h 向下分解出巡航段 ≥4 h，
   在文本里落成一眼可见的需求分解链。
4. **验证链复用现成工况，不新建元素**：`ACT-SIM-ENDURANCE` 的输入/输出（`cruiseSpeed` → `enduranceHours`）
   本来就覆盖巡航续航指标，再建一个仿真工况会造重复元素（第 2 步自检项）。
5. **只改请求的那一棵子树**（反模式第 12 条）：相对起点，改动 = 「新增 1 个 Requirement + 给既有
   ActionDefinition 补 1 条 `verifies`」，无其它改动。`step0-diff.txt` 可逐行核对。
6. **保持起点的紧凑 JSON 风格**：新增元素按 `step0-before.ir.json` 的排版写入，
   使 diff 相对**起点**最小；与仓库存档的 pretty-print 版本只差排版，语义相同。

---

## 4. 待人工确认（不替用户拍板）

1. **「4 小时」是任务书给的硬指标，还是当前估算？** —— 它决定这条需求要不要再往上 `refines` 一层，
   以及是否要同步改动任务级 ≥5 h 的门槛。
2. **巡航标称工作点（巡航速度 v、转速比 eta）取何值？** —— 现在的验收判据是**条件式**的，
   仿真跑起来必须先把工作点定下来。本模型**没有**凭空写入 v / eta 的数值（那会是编造数据）。
3. **需求分解策略本身**：任务级 ≥5 h 分解出巡航段 ≥4 h 是本次的建模假设，属于 `element-choice` 与
   方案 10.1 里「不由智能体单独拍板」的顶层决策，请你确认。

---

## 5. 能力边界（诚实披露，两条红线）

- ✅ **实际做到**：文本由固定模板确定性生成（同输入逐字节同输出，sha256 两次一致）+ 通过内置轻量
  lint（带行列定位）+ 与 IR 完成元素级比对（`missing/extra/mismatched` 全空）。
- ⛔ **没有做到**：「生成的文本已通过**官方 SysML v2 解析器**验证」。本机无 JVM，PySysML2 对
  `requirement` 关键字与带默认值的 `attribute` 存在语法缺口（实测 5 处报错，见
  [`docs/T6-演示记录.md`](../T6-演示记录.md) §7.1 与 [`docs/probe-pysysml2/`](../probe-pysysml2/)）。
  **不得对外宣称已通过官方解析器验证。**
- ⚠️ 本次用 `.venv/bin/python` 运行，因此 JSON Schema 第二层**真的跑了**（`schemaLayer: "ok(+0)"`）；
  存档 T6 记录用的是系统 `python3`（无 `jsonschema`），故那里显示 `unavailable`。两者核心规则层一致。
- ⚠️ 标杆案例中的数值（1200 Wh / 240 W / 0.95 / 0.85 / 0.72）**是占位示例值**，本次未引用、也未当作实测结论。
- ⚠️ **未验证**：DSH 通过 `cordis.yml` 把本 MCP 服务挂进 profile 后再调用一次（本次走的是
  `run_server.py --call` 本地调用模式，工具逻辑与 MCP 模式完全一致）。

---

## 6. 交叉校验：与仓库存档 T6 产物对照

仓库里已有同一请求的存档（`docs/demo/step4-final.ir.json` / `step5-generated.sysml`）。本次做了两项对照：

| 校验 | 结果 |
| --- | --- |
| 用本次工具链重跑**存档 IR** 并与**存档文本**逐字节比对 | ✅ 一致；sha256 复现 `32e23d5e14bb8e1e62e03cf82207c01a828dd02b1df0ab803f1492355e359e6c` |
| 本次产物 vs 存档文本逐行 diff | 仅 1 行不同：我选择的 `refines` rationale 更详细（多 17 字符，正好等于两文件 1627−1610 的差） |

即：**工具链对存档产物可逐字节复现**；本次 IR 与存档的唯一实质差异，是我在 `refines` 的理由里
多写了一句「巡航段是任务剖面中耗时最长的一段」——这是本次的建模选择，`text`、`acceptanceCriteria`、
`minEnduranceHours`、两条关系与验证链的闭合方式均与存档一致。

---

## 7. 复现命令

```bash
cd sysml-modeling-agent
D=docs/demo/run-cruise-endurance-4h
PY=.venv/bin/python   # 或 python3（无 jsonschema 时 schemaLayer 显示 unavailable）

# 第 7 步
$PY mcp-server/run_server.py --call validate_model_json --input $D/step4-final.ir.json

# 第 9 步
$PY mcp-server/run_server.py --call generate_sysml --input $D/step4-final.ir.json
$PY mcp-server/run_server.py --call verify_sysml --input "$($PY - <<'PY'
import json
text  = open("docs/demo/run-cruise-endurance-4h/step5-generated.sysml", encoding="utf-8").read()
model = json.load(open("docs/demo/run-cruise-endurance-4h/step4-final.ir.json", encoding="utf-8"))
print(json.dumps({"text": text, "model": model}, ensure_ascii=False))
PY
)"

# 回归：仓库自带 186 个用例
./tests/run_tests.sh
```
