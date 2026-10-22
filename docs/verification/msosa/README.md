# MSOSA 独立验证（Q1 第二阶段）— 操作卡与证据

> **2026-10-20 执行状态：BLOCKED（Community Edition 能力缺口）。** 本机安装的是 SysML v2 Community Edition：File 菜单**没有 `Import From`**，`Export To` / `Convert To` 灰显禁用，Open Project 也不接受 `.sysml`。因此第 2 步无法执行，第 3–7 步没有输入模型，均未执行。证据与复现路径见 [`runs/2026-10-20-import/BLOCKER.md`](runs/2026-10-20-import/BLOCKER.md)。下文的七步操作保留为**商业版操作卡**，不要在 CE 上按此声称“已验证”。
>
> **2026-10-20 11:55 复核补充：结论状态改为「BLOCKED，根因未定」。** 安装包内证显示文本导入/导出动作存在、但位于 `actions/experimental` 且由环境选项 `md.sysml2.experimental.features`（默认关）控制；Textual Editor 空白与 JVM 语言 `zh` + 缺失 `UIKIT_zh.js` 相关。两条路径都还没被实际验证，详见 [`BLOCKER.md` §6](runs/2026-10-20-import/BLOCKER.md)。在验证前不要写“CE 不支持文本导入”。
>
> **2026-10-20 12:53 更新：** Textual Editor 空白的语言根因已定位并修复（每应用语言设为 en，日志确认 `user.language=en`），**待复测**；实验特性开关未在 GUI 暴露。详见 `BLOCKER.md` §6.6–§6.8。
>
> **2026-10-20 15:14 终局：** 已通过 `bin/msosa.properties` 注入 `-Dmd.sysml2.experimental.features=true` 并确认实验条目出现，但 **File 菜单仍无 `Import From`、Textual Editor 仍无任何窗口/CDP 页面**。本机 CE 构建上文本导入路径不存在，MSOSA 独立验证无法在本机完成。详见 `BLOCKER.md` §6.9。
>
> **2026-10-20 16:22：** 已按用户决定回滚全部 MSOSA 修改（`bin/msosa.properties` 恢复备份、删除每应用语言设置）并重启核验。实验阶段证据归档在 [`runs/2026-10-20-experimental/`](runs/2026-10-20-experimental/)。本目录结论保持 **BLOCKED（CE 能力缺口）**，不再继续。
>
> **2026-10-20 21:16：下一步改为「换构建」跨机验证。** 已打包交接包 [`handoff/2026-10-20-remote/`](handoff/2026-10-20-remote/)（`handoff/MSOSA-remote-probe-2026-10-20.zip`，sha256 `0f504a44…`），发到同学机器上的 agent 执行同一份冻结文本的导入/校验/导出；判定只有 A（可导入）/ B（无入口）/ C（有入口但失败）三态。本机结论不变，**在回传前不要写任何跨机结论**。

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
- **CE 能力缺口（2026-10-20 实测）**：File 菜单无 `Import From`；`Export To` / `Convert To` 的 AX `enabled=false`；Open Project 中 `.sysml` 灰显不可选。见 `runs/2026-10-20-import/screenshots/20261020-1118_golden_capability_01_file-menu-no-import-export-disabled.png` 与 `..._1059_golden_capability_02_open-project-sysml-not-selectable.png`
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
| 1 | **File > Local Repository** → Manage Projects → **New** → New Project，项目名 `q1-msosa-golden`，category 可新建 `q1-verification` → OK；若问是否切 perspective → **Yes** | 项目创建成功，perspective = **System Engineer SysML v2** | `runs/2026-10-20-import/screenshots/20261020-1040_golden_project_00_new-project-dialog.png`、`..._1041_golden_project_01_created.png`；填 `import-log.md` |
| 2 | **File > Import From > SysML v2 Textual Notation** → 选 `inputs/golden-coaxial-power-chain.sysml` → Open | 出现根命名空间 **`CoaxialOctoRotor`**，无错误弹窗 | 导入对话框 + 导入后整屏 |
| 3 | 展开 Containment 树，对照 `ledgers/elements.csv` 抽查：`BatteryPack`、`PowerChain`、`CruiseEndurance`、`FlightModeStates`、`EnduranceBudget`、`batteryToEsc` 等 | 名字/数量与账本一致（34 个声明元素；连接用法 2 条） | 树展开整屏 |
| 4 | 工具栏 **Analyze > Validation > Project Validation Suites** → 确认 **SysMLConstraintsSuite** 与 **DassaultSystemesValidationSuite** 都在 **Included** → OK（会生成 `ProjectValidationConfig` 包，属正常） | 两套件 Included | 对话框整屏；`runs/2026-10-20-validate/suites-list.txt` 抄录 |
| 5 | Containment 树右键根命名空间 **`CoaxialOctoRotor` → Validate** | **Validation Results** 面板打开，列 Element / Severity / Message / Name，底部有汇总 | 面板整屏（带窗口标题与时间） |
| 6 | 逐条抄进 `validation-results.md`（含 Severity、原文 Message、Rule Name；Element 显示的是 SysML 名字，需人工映射到 `ledgers/elements.csv` 的 `ir_id`） | 明细表完整 | 每条对应截图 |
| 7 | **File > Export To > SysML v2 Textual Notation** → 根命名空间移到 Selected → 选 `runs/2026-10-20-export/` → **不勾** Delete existing → Export | 导出 `.sysml` 文件；记录文件数与 sha256 | 导出对话框 + 文件系统目录 |

> 校验面板打开后若改了模型需重新打开才刷新；不要没记录就关面板。
>
> **CE 实际路径（2026-10-20）**：第 2 步的 `Import From` 与第 7 步的 `Export To` 在本机 Community Edition 均不可用（前者菜单不存在，后者灰显禁用）。本机只完成了第 1 步（项目创建）；不要把这七步当成已执行。

## 3. 记录表（直接填，不要另起格式）

- `runs/2026-10-20-import/import-log.md`
- `runs/2026-10-20-validate/validation-results.md`（+ `suites-list.txt`）
- `runs/2026-10-20-export/export-log.md`

截图命名：`<YYYYMMDD>-<HHMM>_golden_<stage>_<nn>_<说明>.png`，整屏、不裁剪关键栏、不 P 图。

## 4. 结论模板（只写事实，回填参数）

> **本机未执行，以下模板仅供商业版/具备文本导入的构建复跑时填写。** Community Edition 本轮没有生成任何可回填的诊断或导出文件，禁止把模板留空后当作“已完成”。

> 在 MSOSA 2026x Refresh1（SysML v2 Plugin 2026x Refresh1，Use in Community Mode，macOS 26.6.2 / Apple M5）下，`golden-coaxial-power-chain.sysml`（sha256 `bb64cc2c…`）于 `<date>` 经 `File > Import From > SysML v2 Textual Notation` 导入成功，生成根命名空间 `CoaxialOctoRotor`；Textual Editor 显示 `<n>` 处语法错误。启用 SysMLConstraintsSuite 与 DassaultSystemesValidationSuite 后对根命名空间执行递归 Validate，得到 Fatal `<a>` / Error `<b>` / Warning `<c>` / Info `<d>` / Debug `<e>` 条诊断（明细见 `validation-results.md`）；导出 `.sysml` 共 `<n>` 个文件（sha256 `<…>`），与输入不做逐字比对。**本结论仅覆盖 L0/L1 与上述套件规则覆盖的 L2 子集，不含求值（L4），不构成 OMG 规范符合性认证。**

## 5. 与本地验证的关系

| | `../local/` | 本目录 |
| --- | --- | --- |
| 回答 | 我们的「IR→文本」链条是否自洽 | 独立实现看到同一文本时是否接受、报什么 |
| 方式 | 自动、可重跑、秒级 | 人工 GUI、一次一轮、截图留证 |
| 不能替代 | MSOSA 的套件诊断 | 本地元素级一致性的可复算证据 |

## 6. 本轮执行状态（2026-10-20）

| 步骤 | 状态 | 证据/说明 |
| --- | --- | --- |
| 1. 创建项目 `q1-msosa-golden` / category `q1-verification` | ✅ 完成（10:41） | `runs/2026-10-20-import/screenshots/20261020-1040_golden_project_00_new-project-dialog.png`；`..._1041_golden_project_01_created.png` |
| 2. File > Import From > SysML v2 Textual Notation | ⛔ **BLOCKED** | CE File 菜单无 `Import From`；`.sysml` 在 Open Project 中灰显。`runs/2026-10-20-import/BLOCKER.md` |
| 3. 树核对 | ⏸ 未执行 | 无 `CoaxialOctoRotor`，项目内只有空包 `Model` |
| 4. Project Validation Suites | ⏸ 未执行 | 无模型可校验 |
| 5. Validate | ⏸ 未执行 | 同上 |
| 6. 诊断抄录 | ⏸ 未执行 | 不能把“未运行”写成“0 诊断” |
| 7. Export To > SysML v2 Textual Notation | ⏸ 未执行（且 CE 禁用了 Export To） | AX `enabled=false` |

**下一步需要外部决策**：换商业版 / 具备文本导入的构建，或改用其他独立实现；不要用图形化手工重建来替代“同一文本的导入”。

**2026-10-20 决策：接受 BLOCKED 收尾。** 本轮不换商业版、不改用 SysON、不手工重建；MSOSA 这一腿不提供独立接受性/诊断结论，仅保留 CE 能力缺口与项目创建证据。
