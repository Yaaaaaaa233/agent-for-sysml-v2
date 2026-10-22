# Import log — golden @ 2026-10-20

- 工具：MSOSA 2026x Refresh1（Use in Community Mode；Version Info 记为 `2026x Refresh1 Enterprise Community Seat`），SysML v2 Plugin 2026x Refresh1
- 输入：`inputs/golden-coaxial-power-chain.sysml` sha256=`bb64cc2cbfdc5f5667049a76f6b57c4925a6ed29b2344c94d09d70e9ac6f6129`
- 预期根命名空间：`CoaxialOctoRotor`；预期元素账本：34 元素 + 2 `connect`（见 `../../ledgers/`）
- **执行状态：BLOCKED（2026-10-20 11:18）**。本机 Community Edition 的 File 菜单没有 `Import From`，`.sysml` 也无法通过 Open Project 打开；既定导入步骤不可执行。详见同目录 `BLOCKER.md`。
- **收尾决策：2026-10-20 接受 BLOCKED。** 不换商业版、不改用其他实现、不手工重建；本轮不提供 MSOSA 的独立接受性/诊断结论。

## 前置截图（install 阶段）

| # | 画面 | 文件 |
| --- | --- | --- |
| 1 | License Manager（Community Mode） | `screenshots/20261020-1036_golden_install_01_license-manager.png` |
| 2 | Resource/Plugin Manager（SysML v2 已安装） | `screenshots/20261020-1038_golden_install_04_resource-plugin-manager.png` |
| 3 | Perspective = System Engineer SysML v2 | `screenshots/20261020-1035_golden_install_03_perspective.png` |
| 4 | Help > About（版本/build） | `screenshots/20261020-1037_golden_install_02_about-licensing-community.png` |

## 项目

| 项目名 | category | 创建时间 | perspective | 截图 |
| --- | --- | --- | --- | --- |
| `q1-msosa-golden` | `q1-verification` | 2026-10-20 10:41 | System Engineer SysML v2 | `screenshots/20261020-1040_golden_project_00_new-project-dialog.png`（名称/category）；`screenshots/20261020-1041_golden_project_01_created.png`（创建后） |

项目树（导入前）：`q1-msosa-golden` → `[Model]` → `package Model`（空包，尚无 `CoaxialOctoRotor`）。

## 导入

| 时间 | 操作 | 菜单路径 | 文件（sha256 前 12 位） | 根命名空间 | 结果 | 耗时 | 截图 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-20 11:18 | 未执行 | 既定路径：File > Import From > SysML v2 Textual Notation；**本机 File 菜单无 `Import From`** | `bb64cc2cbfdc` | 未生成 | **BLOCKED** | — | `screenshots/20261020-1118_golden_capability_01_file-menu-no-import-export-disabled.png`；`screenshots/20261020-1059_golden_capability_02_open-project-sysml-not-selectable.png` |

## 树核对（对照 `../../ledgers/elements.csv` 抽查）

| 应出现 | 实际出现 | 备注 |
| --- | --- | --- |
| `BatteryPack` / `PowerChain` / `CruiseEndurance` / `FlightModeStates` / `EnduranceBudget` / `batteryToEsc` | 未执行 | 无导入模型，项目内只有空包 `Model` |
| 元素总数 34 | 未执行 | 同上 |

## 异常/差异

- **阻断 1：File 菜单没有 `Import From`。** 菜单只有 New Project / Open Project / Local Repository / Save Project / Save Project As / Close Project / Close All Projects / Migrate Legacy DDL Models / Open Element from URL / Export To / Convert To / Save as Image / Print / Project Properties / Switch Projects / Exit。`Export To` 与 `Convert To` 同时为灰显禁用（辅助功能检查 `enabled=false`，2026-10-20 11:18）。
- **阻断 2：Open Project 不接受 `.sysml`。** 在 Open 对话框中导航至 `docs/verification/msosa/inputs/` 后，`golden-coaxial-power-chain.sysml` 灰显不可选，Open 按钮保持禁用；该命令只接受项目包，不是文本导入入口。
- **旁证（不作为结论依据）**：Containment 树右键 `package Model` 可见 `Textual Editor` 菜单项；通过辅助功能触发后，未出现可见编辑器标签页、无报错、无 CDP page target（localhost:9231 为空），因此本轮未把它当作可用的文本导入路径。
- **未做的事**：没有用图形界面手工重建模型，也没有把空项目或手工模型当作“导入成功”。`CoaxialOctoRotor` 未生成，Validate/Export 均未执行。
