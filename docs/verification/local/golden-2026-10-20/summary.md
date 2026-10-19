# 本地验证证据 — golden-coaxial-power-chain @ 2026-10-20

- 对象：`examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json`
  - IR sha256：`adae5c6146a3e0f3f8e5eff0982f1efb258efba3bdac3b76e3445eaa078af0e3`
  - 生成文本 sha256：`bb64cc2cbfdc5f5667049a76f6b57c4925a6ed29b2344c94d09d70e9ac6f6129`
- 规模：**34 元素 / 20 条关系**（7 PartDefinition、8 PartUsage、4 Requirement、9 Attribute、2 ActionDefinition、1 StateDefinition、1 Constraint、2 Connection）
- 解释器：`.venv/bin/python`（Python 3.11.6，`jsonschema 4.26.0`）
- 复现：`.venv/bin/python docs/verification/local/verify_model.py examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json docs/verification/local/golden-2026-10-20`

## 结果

| 层 | 结果 | 细节 |
| --- | --- | --- |
| L0 `validate_model_json` | ✅ ok=true | errors=0，warnings=0，`schemaLayer: ok(+0)`（JSON Schema 第二层已执行），0.11 s |
| L1 `generate_sysml` | ✅ | 9766 字符 / 213 行；两次渲染 sha256 相同（`bb64cc2c…`），确定性成立 |
| L1 `verify_sysml(official=true)` | ✅ | 元素级比对 `matched=34 / missing=0 / extra=0 / mismatched=0 / lintErrors=0`；官方 Pilot Implementation `status=available, ok=true`，0 诊断，4.1 s |
| L2 `traceability` | ✅ | 4 条需求全部 `satisfied-and-verified`；未满足 / 未验证需求 / 未验证 Action 均为空 |

判定：`{"pass": true, "warnings": 0, "officialPass": true, "traceabilityGaps": 0}`

## 两个可复算的交叉证据

1. **生成文本 sha256 与 `proposal/CommunityEdition配置方案.md` §4.0 的输入冻结值一致**（`bb64cc2c…`）——说明冻结给 MSOSA 的那份 `.sysml` 是生成器可复现产物，不是手工文件。
2. **官方解析器后端**：`docs/probe-official-parser/jre`（Temurin 21）+ `kernel/jupyter-sysml-kernel-0.62.0-all.jar` + `kernel/sysml.library`；运行时完整命令行见 `03-verify.json → official.detail`。

## 证据边界（不要扩大解读）

- 只覆盖**语法与引用解析**，**不覆盖语义/建模质量**；官方实现解析通过 ≠ 模型符合工程意图。
- 文本里的 18 条 trace 关系是 `//` 注释，不进入官方解析语义；能作为模型元素被解析的只有 34 个声明 + 2 条 `connect`。
- 本证据是**工具链自证**，不能替代 MSOSA 的独立校验结果（见 `../../msosa/`）。
