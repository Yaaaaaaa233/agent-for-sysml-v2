# 二期演示：对标杆案例做一次需求变更，追溯矩阵自动反映影响范围

> **演示目标**（方案 9.2 验收判据）：「对标杆案例做一次需求变更，追溯矩阵自动反映影响范围」。
> **起点**：`examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json`（34 元素 / 20 关系，
> 需求 + 结构 + 参数 + 行为四类齐备）。
> **变更**：`REQ-CRUISE-ENDURANCE` 的 `minEnduranceHours` **4.0 h → 5.0 h**（占位变更），
> 并同步所有提到 `4.0 h` 的字段。
> 运行日期：2026-10-17 · 解释器：`.venv/bin/python`（Python 3.11，仓库根 `.venv`）
> 流程：`parse_sysml` 导入 → `patch_model` 变更 → `validate/generate/verify` → `traceability` 前后对照 →
> `export_simulink` 导出。
>
> **本目录下所有输出均为真实执行输出**（`run_steps.py` 跑出来的），没有手写任何工具结果。
> 唯一的机械处理：输出里的仓库绝对路径被替换成 `<repo>`（见 §5「路径替换」）。
>
> ⚠️ **所有数值均为占位值，本演示不含实测数据。** `1200 Wh` / `240 W` / `0.95` / `0.85` / `0.72` /
> `4.0 h` / `5.0 h` / `0.75` 全部来自标杆案例 IR 的占位字段，只用于打通「模型 → 参数 → 仿真 → 验证」
> 链路；在拿到选型数据、台架数据或试飞数据之前，不得当作续航、效率或功率的实测结论（方案 10.2）。

---

## 0. 结论（三句话）

1. **改一处需求，矩阵自己变**：`REQ-CRUISE-ENDURANCE` 的文本与阈值改完后，`traceability` 的矩阵行
   自动从「巡航时间不低于 4 小时」变成「巡航时间不低于 5 小时」，**没有手工维护任何表格**；
   其余 3 行逐字段不变（`step5-trace-after.txt` §5.1）。
2. **影响范围算得出来**：以 `REQ-CRUISE-ENDURANCE` 为焦点做反向引用 BFS，直接受影响 4 个元素
   （`REQ-MISSION-ENDURANCE` / `REQ-ROTOR-SPEED-RATIO` / `REQ-POWER-BUDGET` / `ACT-SIM-ENDURANCE`），
   传递受影响 2 个（`ACT-ONLINE-OPTIMIZATION` / `PART-USAGE-SYSTEM`），受影响需求 4 条。
3. **补丁是原子的、可回验的**：3 个 `update_element` 一次应用，`ok=true`、`diff` 3 条；
   变更后 `validate` 0 error 0 warning、`verify_sysml` 34/34 元素匹配、官方解析器 0 条诊断；
   `export_simulink` 的参数表里阈值已是 `5.0`。

---

## 1. 产物清单

| 文件 | 说明 |
| --- | --- |
| [`run_steps.py`](run_steps.py) | 驱动脚本（只调仓库已实现的工具函数，与 MCP 工具同一批代码路径） |
| [`step1-import.txt`](step1-import.txt) | `parse_sysml` 把 golden `.sysml` 逆解析回 IR 的真实返回（`ok=true`，34 元素 / 20 关系） |
| [`step1-imported.ir.json`](step1-imported.ir.json) | 导入得到的 IR（后续补丁的输入） |
| [`step2-trace-before.txt`](step2-trace-before.txt) | `traceability` 基线矩阵 + `gaps`（变更前） |
| [`step3-patch.txt`](step3-patch.txt) | `patch_model` 的 `ops`、返回、`diff`（3 条 `~`） |
| [`step3-ops.json`](step3-ops.json) | 第 3 步实际传入的 `ops`（`--input` 里直接 `cat` 它，命令可复制） |
| [`step3-patched.ir.json`](step3-patched.ir.json) | 变更后的 IR（34 元素 / 20 关系，只改字段） |
| [`step4-validate-generate-verify.txt`](step4-validate-generate-verify.txt) | 变更后 `validate` / `generate` / `verify`（含 `official`） |
| [`step4-changed.sysml`](step4-changed.sysml) | 变更后的生成文本（sha256 `06fbfb5a…`），**不得手改** |
| [`step5-trace-after.txt`](step5-trace-after.txt) | 变更后矩阵 + 前后逐行比对 + `focus` 影响面 + Markdown 矩阵 |
| [`step6-export.txt`](step6-export.txt) | `export_simulink`（Markdown 全表 + CSV 的阈值行，`5.0`） |

---

## 2. 逐步实录（命令 + 真实输出摘录）

复现全部步骤（在**仓库根**执行；本目录所有命令都以仓库根为工作目录）：

```bash
cd sysml-modeling-agent
PYTHONPATH="$PWD/mcp-server" .venv/bin/python docs/demo/run-phase2-change/run_steps.py
```

脚本内部逐步调用等价于下面这些命令行（**都可以直接复制执行**，本轮已逐条实跑核对）：

```bash
# 第 1 步：文本 → IR
PYTHONPATH="$PWD/mcp-server" .venv/bin/python -m tools.parser \
  examples/golden-coaxial-power-chain/golden-coaxial-power-chain.sysml

# 第 2 步：基线矩阵（含 gaps）
PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call traceability \
  --model-file docs/demo/run-phase2-change/step1-imported.ir.json --input '{"fmt": "md"}'

# 第 3 步：需求变更（ops 直接取自 step3-ops.json）
PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call patch_model \
  --model-file docs/demo/run-phase2-change/step1-imported.ir.json \
  --input "{\"ops\": $(cat docs/demo/run-phase2-change/step3-ops.json)}"

# 第 4 步：校验 / 生成 / 回验（official=true）
PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call validate_model_json \
  --model-file docs/demo/run-phase2-change/step3-patched.ir.json
PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call generate_sysml \
  --model-file docs/demo/run-phase2-change/step3-patched.ir.json
PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call verify_sysml \
  --text "$(cat docs/demo/run-phase2-change/step4-changed.sysml)" \
  --model-file docs/demo/run-phase2-change/step3-patched.ir.json \
  --input '{"official": true}'

# 第 5 步：变更后矩阵 + 影响面
PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call traceability \
  --model-file docs/demo/run-phase2-change/step3-patched.ir.json --input '{"fmt": "md"}'
PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call traceability \
  --model-file docs/demo/run-phase2-change/step3-patched.ir.json \
  --input '{"focus": "REQ-CRUISE-ENDURANCE", "fmt": "md"}'

# 第 6 步：参数表导出
PYTHONPATH="$PWD/mcp-server" .venv/bin/python -m tools.export \
  docs/demo/run-phase2-change/step3-patched.ir.json --fmt md --scope all
```

> 上面每条命令的**完整、未经手写的返回**在对应 `step*.txt` 里。
> `--model-file` 用来把 IR 文件直接喂给工具（等价于把文件内容塞进 `--input` 的 `model` 字段）；
> `--text` 与 `--model-file` 可以同时给，`verify_sysml` 才能做「文本 ↔ IR」元素级比对。

### 第 1 步：`parse_sysml` 导入

```
输入：examples/golden-coaxial-power-chain/golden-coaxial-power-chain.sysml
      chars  = 9766
      sha256 = bb64cc2cbfdc5f5667049a76f6b57c4925a6ed29b2344c94d09d70e9ac6f6129

ok = true · errors = [] · warnings = [] · unsupported = []
stats: elements = 34（PartDefinition 7 / PartUsage 8 / Requirement 4 / ActionDefinition 2 /
       StateDefinition 1 / Attribute 9 / Constraint 1 / Connection 2），relations = 20

与 golden IR 元素级等价：是 ✅
```

导入结果与仓库里的 golden IR **元素级等价**（id/kind/name/owner/properties/relations 全等），
说明「IR → 文本 → IR」这条链在补上行为元素后仍然闭合。

### 第 2 步：基线追溯矩阵

4 条需求全部 `satisfied-and-verified`，`gaps` 三项全空：
`unsatisfied = []`、`unverified_requirement = []`、`unverified_action = []`。

### 第 3 步：`patch_model` 需求变更（原子）

3 个 `update_element`：

| id | 改了哪些字段 |
| --- | --- |
| `REQ-CRUISE-ENDURANCE` | `text`（4 小时 → 5 小时）、`acceptanceCriteria`（`>= 4.0 h` → `>= 5.0 h`）、`minEnduranceHours`（4.0 → 5.0） |
| `ATTR-ENDURANCE` | `description`（把「恰好满足下限」改成「不再满足 5.0 h 下限，缺口由 traceability 暴露」） |
| `CONSTRAINT-ENDURANCE-BUDGET` | `description`（把需求下限 5.0 h 一并写清） |

返回：`ok = true`、`errors = []`、`warnings = []`、`diff` **3 条**（每条 `change="~"`、`kind="element"`）。
`ATTR-ENDURANCE` 的 `defaultValue`（4.0 h）**没有改**——它是公式 `E·f/P` 算出来的结果量，
改需求不等于改设计；这个「需求提上去了、设计还没跟上」的缺口，正是下一步要暴露的东西。

### 第 4 步：校验 / 生成 / 回验

```
validate_model_json : ok=true · errors=[] · warnings=[] · schemaLayer="ok(+0)"
generate_sysml      : ok=true · sha256=06fbfb5af8cfbbc50114cec1a863cf9952633d9dab7a161fed3e60b2f7f77b46
                      stats: 34 元素 / 20 关系 / 213 行 / 9811 字符
verify_sysml        : ok=true · 34/34 元素匹配 · 0 lint error · missing/extra/mismatched 全空
verify_sysml(official=true)
                    : official.ok=true · status="available" · diagnostics=[]（0 条）
```

### 第 5 步：变更后矩阵 + 影响面

**5.1 矩阵自动变化**（前后逐行比对，1 行变、3 行不变）：

| requirement | 变更前 `text_short` | 变更后 `text_short` | status |
| --- | --- | --- | --- |
| `REQ-CRUISE-ENDURANCE` | 巡航时间不低于 4 小时 | 巡航时间不低于 5 小时 | `satisfied-and-verified`（不变） |

**5.2 影响面**（`focus="REQ-CRUISE-ENDURANCE"`）：

```
direct     : ACT-SIM-ENDURANCE, REQ-MISSION-ENDURANCE, REQ-POWER-BUDGET, REQ-ROTOR-SPEED-RATIO
transitive : ACT-ONLINE-OPTIMIZATION, PART-USAGE-SYSTEM
affected_requirements : REQ-CRUISE-ENDURANCE, REQ-MISSION-ENDURANCE, REQ-POWER-BUDGET,
                        REQ-ROTOR-SPEED-RATIO
```

**5.3 以「被改的 3 个元素」为焦点的合并影响面**：把 `REQ-CRUISE-ENDURANCE` /
`ATTR-ENDURANCE` / `CONSTRAINT-ENDURANCE-BUDGET` 一起当焦点，就是「这次补丁到底动了谁」的
完整影响面（见 `step5-trace-after.txt` §5.4）。

### 第 6 步：导出参数表

`export_simulink(fmt="md", scope="all")`：18 行，其中
`CoaxialOctoRotor.CruiseEndurance / minEnduranceHours / Real / 5.0 / RequirementThreshold`
——**变更后的阈值确实进到了仿真侧参数表**。CSV 里同一行：

```csv
CoaxialOctoRotor.CruiseEndurance,minEnduranceHours,Real,,5.0,RequirementThreshold,REQ-CRUISE-ENDURANCE,"{""note"":""需求阈值，非部件参数""}"
```

---

## 3. 三层汇报示范（模型事实 / 规范语义 / 推断）

| 层次 | 这次演示能说的 | 证据 |
| --- | --- | --- |
| **模型事实** | IR 从 34 元素 / 20 关系变成 34 元素 / 20 关系（只改 3 个元素的字段，结构与关系不变）；`REQ-CRUISE-ENDURANCE.minEnduranceHours = 5.0`；`ATTR-ENDURANCE.defaultValue` 仍是 `4.0`；生成文本 213 行 / 9811 字符 / sha256 `06fbfb5a…`；矩阵 4 行，1 行文本变化；影响面 direct 4 / transitive 2；导出 18 行且阈值 5.0。 | `step1`–`step6` 的原始返回 |
| **规范语义** | 在**本项目约定**下：`patch_model` 的 `update_element` 是整体替换（`element.id` 必须等于 `id`），3 条补丁一次应用、失败整体回滚；`traceability` 的矩阵行状态由 `satisfiedBy` / `verifiedBy` 结构决定，`text_short` 取 `properties.text` 前 60 字；影响面按 `relations.target` / `properties.typeRef` / `owner` 三条引用边做反向 BFS；`export_simulink` 只透传 `defaultValue`，不做量纲检查。 | `mcp-server/schema/渲染约定.md`、`mcp-server/schema/字段说明.md` |
| **推断** | ①「矩阵反映了影响范围」严格说只反映**结构引用**，不代表需求真的被满足或验证过——`satisfied-and-verified` 是「有人声称满足、有人声称验证」，不是实测结论；②本次变更只改字段值，没有增删元素与关系，所以影响面**恰好**等于结构上的引用面；若改动涉及新增 `Connection` 或删除元素，`cascade` 语义会额外删掉子树（本次未触发）；③官方解析器 0 条诊断只覆盖**语法与引用解析**，不代表语义成立。 | 见 §4 |

---

## 4. 诚实边界（这份演示**不**证明什么）

- **不证明需求已被满足**：`enduranceHours = 4.0 h` 与新的下限 `5.0 h` 之间存在缺口，
  演示里刻意**没有**改设计去凑阈值——这正是「模型能立刻暴露不一致」的用处。要闭环，
  下一步是改 `batteryCapacityWh` / `cruisePowerW` 或接受需求让步，并重跑同一套命令。
- **不证明数值是真的**：所有数值都是占位值；`5.0 h` 只是一次占位变更。
- **不证明「已通过官方解析器验证」**：`official.diagnostics=[]` 只支持
  「语法与引用解析经官方 Pilot Implementation（release 2026-08）实测 0 error」，
  范围限定到这一份文本与这个后端版本；语义/建模质量未验证。
- **不证明矩阵 = 语义真相**：矩阵是 IR 里**已经写了**的关系的排版，不做语义推断；
  需求是否真的被满足、动作是否真的能验证需求，仍需人判断。

---

## 5. 路径替换（唯一的手工干预，明写在此）

工具返回的 `detail` 字段里带仓库绝对路径（官方解析器命令、classpath 等）。为了让本目录
换机器也能读，`run_steps.py` 在写文件前把**仓库绝对路径**替换成 `<repo>`，
其余字符（含中文、换行、引号）原样保留。这与 `docs/probe-official-parser/EVIDENCE.txt`
「省略绝对路径前缀」的口径一致；替换是机械的、可复核的（`run_steps.py` 的 `write()`）。
