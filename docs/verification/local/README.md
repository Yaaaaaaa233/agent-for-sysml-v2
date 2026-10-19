# 本地模型验证（L0 / L1 / L2）

> **一句话**：这里验证的是「IR JSON → SysML v2 文本」这条**机器链条自身**——结构合不合法、文本与 IR 是否一一对应、官方实现能不能解析、需求有没有断链。
> 它**不**验证模型语义对不对、也不替代 MSOSA 的独立校验（那是 `../msosa/`）。

## 1. 三层各证明什么

| 层 | 工具（MCP 工具名） | 能证明 | 不能证明 |
| --- | --- | --- | --- |
| **L0 结构** | `validate_model_json` | IR 必填字段/枚举/id 唯一/owner 存在/引用目标存在/`typeRef` 指向正确 kind/数值字段是数字；JSON Schema 第二层交叉检查（装了 `jsonschema` 时） | 模型是否「建对了」——规则全绿的空壳模型也能过 |
| **L1 生成 + 回验** | `generate_sysml` → `verify_sysml(official=true)` | ① 渲染确定性（同输入两次 sha256 相同）；② 文本声明与 IR 元素**元素级一致**（`matched/missing/extra/mismatched`）；③ OMG SysML v2 Pilot Implementation 对整段文本**语法与引用解析 0 error** | 语义/建模质量；文本里 18 条 trace 关系只是注释，不是模型语义 |
| **L2 追溯** | `traceability` | 每条需求有没有 `satisfiedBy` / `verifies`；哪些 Action 没人验证 | 满足关系在工程上是否成立 |

> 官方解析器是**失败关闭**的：后端不可用（`status="unavailable"`）或报任何诊断时，`verify_sysml` 顶层 `ok` 一律为 `false`，不会拿内置 lint 冒充官方通过。

## 2. 一键复现

```bash
cd /Users/yea/Desktop/Study/比赛/2610_MBSE/sysml-modeling-agent

# 标杆案例（34 元素）
.venv/bin/python docs/verification/local/verify_model.py \
  examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json \
  docs/verification/local/golden-2026-10-20

# 工作区当前模型（35 元素，含 Q2 演示残留）
.venv/bin/python docs/verification/local/verify_model.py \
  ../model-output/q2-demo/q2-demo.ir.json \
  ../model-output/q2-demo/_verification
```

退出码：**0 = 通过**（L0 无 error、官方解析器可用且无诊断、元素级比对无缺口）；**1 = 不通过**。warning 与追溯缺口只记录、不阻断，需要人看。

## 3. 为什么必须用 `.venv/bin/python`

`.venv` 里有 `jsonschema 4.26.0` 与 `fastmcp`（MCP 服务实际就是用它启动的，见 `~/.dsh/profiles/desktop/cordis.patch.yml` 的 `command`）。
用系统 `python3` 跑会缺 `jsonschema`，`schemaLayer` 降级成 `unavailable`——**结果仍然有效，但少了一层**。两边解释器不一致时，证据里 `report.json → python` 字段会如实写出来，复核时先看这一行。

## 4. 产出物（每次运行一个目录）

```text
<outdir>/
├── report.json           # 汇总：输入 sha256 / 各层耗时结果 / 判定
├── 01-validate.json      # validate_model_json 原始输出
├── 02-generate.json      # generate_sysml 原始输出（无 text）
├── model.sysml           # 生成的文本（可直接给 MSOSA 导入）
├── 03-verify.json        # verify_sysml 原始输出（含 official 段）
├── 04-traceability.json  # traceability 原始输出
└── traceability.md       # 追溯矩阵（人读）
```

## 5. 与 MSOSA 验证的关系

本目录回答「我们的工具链自洽吗」；`../msosa/` 回答「另一个独立实现（MSOSA 2026x Refresh1）看到的是什么」。两者证据**不互相替代**：本地全绿 ≠ MSOSA 校验通过，MSOSA 校验通过 ≠ 模型正确。

## 6. 现有证据

| 目录 | 对象 | 结论 |
| --- | --- | --- |
| `golden-2026-10-20/` | `examples/golden-coaxial-power-chain`（34 元素 / 20 关系） | L0 0 error 0 warning；L1 官方解析 34/34、0 诊断；L2 0 缺口 |
