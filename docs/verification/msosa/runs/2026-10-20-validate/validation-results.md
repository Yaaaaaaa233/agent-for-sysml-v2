# Validation results — golden @ 2026-10-20

- 工具：MSOSA 2026x Refresh1（Community Mode），SysML v2 Plugin 2026x Refresh1
- 输入：`inputs/golden-coaxial-power-chain.sysml` sha256=`bb64cc2cbfdc5f5667049a76f6b57c4925a6ed29b2344c94d09d70e9ac6f6129`；根命名空间 `CoaxialOctoRotor`
- 套件：SysMLConstraintsSuite（Included）、DassaultSystemesValidationSuite（Included）
- 操作：Containment 树右键根命名空间 → Validate（递归）
- 截图：`screenshots/`

## 套件清单（Project Validation Suites 对话框抄录）

| 套件 | 状态（Included/Ignored） | 备注 |
| --- | --- | --- |
| SysMLConstraintsSuite | | |
| DassaultSystemesValidationSuite | | |
| （其他实际出现的套件） | | |

> 原始信息同时抄到 `suites-list.txt`。

## 汇总（Validation Results 面板底部原文）

Fatal: `<a>` / Error: `<b>` / Warning: `<c>` / Info: `<d>` / Debug: `<e>`

## 明细

| # | Element（界面名） | IR id（查 `../../ledgers/elements.csv`） | Severity | Message（原文抄录） | Rule Name | 截图 | 初判 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | | | | | | ⬜ | |

初判口径：`我方建模问题` / `规则严格性差异` / `待查`（三选一，不写"应该没事"）。

## 备注

- 面板是否重新打开过（改模型后必须重开才刷新）：
- 与官方 Pilot Implementation 诊断对照（同一文本，本地 `03-verify.json`：0 诊断）：
- 未记录到的情况：
