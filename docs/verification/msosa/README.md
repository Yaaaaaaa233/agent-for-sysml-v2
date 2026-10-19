# MSOSA 独立验证（Q1 第二阶段）— 操作卡与证据

> **一句话**：把**冻结**的 `golden-coaxial-power-chain.sysml` 导进 MSOSA 2026x Refresh1（Community Mode），跑预置校验套件，导出文本并留证；它提供**另一个独立实现**对同一文本的接受性/诊断，不是认证。

## 0. 边界（先读，防止把结论说过头）

| 能写 | 不能写 |
| --- | --- |
| 导入成功、根命名空间成形、Textual Editor 语法错误数 | "已通过 MSOSA 验证" |
| 两个套件给出的 Fatal/Error/Warning/Info/Debug 计数与明细 | "100% 标准符合"（厂商声明，不是 OMG 认证） |
| 导出文件数 + sha256（不与输入逐字 diff） | "20/20 关系一致"（文本里只有 2 条 `connect`，其余 18 条是注释） |
| 本轮覆盖 L0/L1 + 套件子集 L2 | "校验通过所以模型正确" |

本机已核对事实（来自安装目录与 `msosa.log`，非猜测）：

- 版本 **2026x Refresh1**，build `2026.1.0-42-b71a9669`（2026-05-26），`Version Info: 2026x Refresh1 Enterprise Community Seat`
- SysML v2 插件已启动（`Plugin started: SysML v2`）；Evaluation 插件 `Not supported`（缺商业 CST/MMA，符合预期）
- 安装包：`No_Magic_2026x_Refresh1.Magic_Systems_of_Systems_Architect_2026x_Refresh1_mac_aarch64.dmg`
- 完整指纹见 `fingerprint.json`

## 1. 输入已冻结（不要现生成一份去导）

| 文件 | sha256 |
| --- | --- |
| `inputs/golden-coaxial-power-chain.sysml` | `bb64cc2cbfdc5f5667049a76f6b57c4925a6ed29b2344c94d09d70e9ac6f6129` |
| 源 IR `examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json` | `adae5c6146a3e0f3f8e5eff0982f1efb258efba3bdac3b76e3445eaa078af0e3` |

> 该文本的 sha256 与本地验证 `../local/golden-2026-10-20/model.sysml` **一致**：冻结件是生成器可复现产物。
> 预期内容：**34 个元素 + 2 条 `connect`**（7 PartDefinition / 8 PartUsage / 4 Requirement / 9 Attribute / 2 ActionDefinition / 1 StateDefinition / 1 Constraint / 2 Connection）。逐元素清单见 `ledgers/elements.csv`，20 条关系（18 条仅注释）见 `ledgers/relations.csv`。

## 2. 七步操作（每步都截图）

| # | 操作（菜单路径） | 预期 | 证据 |
| --- | --- | --- | --- |
| 1 | **File > Local Repository** → Manage Projects → **New** → New Project，项目名 `q1-msosa-golden`，category 可新建 `q1-verification` → OK；若问是否切 perspective → **Yes** | 项目创建成功，perspective = **System Engineer SysML v2** | `runs/2026-10-20-import/screenshots/*_project_*.png`；填 `import-log.md` |
| 2 | **File > Import From > SysML v2 Textual Notation** → 选 `inputs/golden-coaxial-power-chain.sysml` → Open | 出现根命名空间 **`CoaxialOctoRotor`**，无错误弹窗 | 导入对话框 + 导入后整屏 |
| 3 | 展开 Containment 树，对照 `ledgers/elements.csv` 抽查：`BatteryPack`、`PowerChain`、`CruiseEndurance`、`FlightModeStates`、`EnduranceBudget`、`batteryToEsc` 等 | 名字/数量与账本一致（34 个声明元素；连接用法 2 条） | 树展开整屏 |
| 4 | 工具栏 **Analyze > Validation > Project Validation Suites** → 确认 **SysMLConstraintsSuite** 与 **DassaultSystemesValidationSuite** 都在 **Included** → OK（会生成 `ProjectValidationConfig` 包，属正常） | 两套件 Included | 对话框整屏；`runs/2026-10-20-validate/suites-list.txt` 抄录 |
| 5 | Containment 树右键根命名空间 **`CoaxialOctoRotor` → Validate** | **Validation Results** 面板打开，列 Element / Severity / Message / Name，底部有汇总 | 面板整屏（带窗口标题与时间） |
| 6 | 逐条抄进 `validation-results.md`（含 Severity、原文 Message、Rule Name；Element 显示的是 SysML 名字，需人工映射到 `ledgers/elements.csv` 的 `ir_id`） | 明细表完整 | 每条对应截图 |
| 7 | **File > Export To > SysML v2 Textual Notation** → 根命名空间移到 Selected → 选 `runs/2026-10-20-export/` → **不勾** Delete existing → Export | 导出 `.sysml` 文件；记录文件数与 sha256 | 导出对话框 + 文件系统目录 |

> 校验面板打开后若改了模型需重新打开才刷新；不要没记录就关面板。

## 3. 记录表（直接填，不要另起格式）

- `runs/2026-10-20-import/import-log.md`
- `runs/2026-10-20-validate/validation-results.md`（+ `suites-list.txt`）
- `runs/2026-10-20-export/export-log.md`

截图命名：`<YYYYMMDD>-<HHMM>_golden_<stage>_<nn>_<说明>.png`，整屏、不裁剪关键栏、不 P 图。

## 4. 结论模板（只写事实，回填参数）

> 在 MSOSA 2026x Refresh1（SysML v2 Plugin 2026x Refresh1，Use in Community Mode，macOS 26.6.2 / Apple M5）下，`golden-coaxial-power-chain.sysml`（sha256 `bb64cc2c…`）于 `<date>` 经 `File > Import From > SysML v2 Textual Notation` 导入成功，生成根命名空间 `CoaxialOctoRotor`；Textual Editor 显示 `<n>` 处语法错误。启用 SysMLConstraintsSuite 与 DassaultSystemesValidationSuite 后对根命名空间执行递归 Validate，得到 Fatal `<a>` / Error `<b>` / Warning `<c>` / Info `<d>` / Debug `<e>` 条诊断（明细见 `validation-results.md`）；导出 `.sysml` 共 `<n>` 个文件（sha256 `<…>`），与输入不做逐字比对。**本结论仅覆盖 L0/L1 与上述套件规则覆盖的 L2 子集，不含求值（L4），不构成 OMG 规范符合性认证。**

## 5. 与本地验证的关系

| | `../local/` | 本目录 |
| --- | --- | --- |
| 回答 | 我们的「IR→文本」链条是否自洽 | 独立实现看到同一文本时是否接受、报什么 |
| 方式 | 自动、可重跑、秒级 | 人工 GUI、一次一轮、截图留证 |
| 不能替代 | MSOSA 的套件诊断 | 本地元素级一致性的可复算证据 |
