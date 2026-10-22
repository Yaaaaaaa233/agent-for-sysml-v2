# reference/01 · 背景与版本线索（发件方整理，2026-10-20）

本文件说明：**我们这边已经试过什么、结论是什么、以及"对方的版本"目前能查到什么程度**。目的是让对面不重复我们的失败，并且知道要采集哪些版本信息才能让这次证据有效。

---

## 1. 我们这台机器（macOS）已经做过的事

| 项 | 事实 |
| --- | --- |
| 产品/版本 | Magic Systems of Systems Architect **2026x Refresh1**，build `2026.1.0-42-b71a9669`（BUILD 2026-05-26）；`msosa.log` 的 Version Info 记为 `2026x Refresh1 Enterprise Community Seat` |
| 安装包 | `No_Magic_2026x_Refresh1.Magic_Systems_of_Systems_Architect_2026x_Refresh1_mac_aarch64.dmg` |
| 许可 | `Use in Community Mode`（Community Seat，免费版，上限约 500 个主要元素） |
| 插件 | SysML v2 插件已安装并启动（日志 `Plugin started: SysML v2`）；Evaluation / Simulation 插件为 `Not supported`（缺商业 CST/MMA） |
| 测试项目 | 新建了 `q1-msosa-golden`，perspective = `System Engineer SysML v2`，项目内只有空包 `Model` |

### 实测到的阻断（这是本次跨机验证的直接动机）

1. **`File` 菜单没有 `Import From`**。菜单项全文：New Project / Open Project / Local Repository / Save Project / Save Project As / Close Project / Close All Projects / Migrate Legacy DDL Models / Open Element from URL / Export To / Convert To / Save as Image / Print / Project Properties / Switch Projects / Exit。
2. **`Export To` 与 `Convert To` 灰显禁用**（辅助功能接口读到 `enabled=false`）。
3. **`Open Project` 不接受 `.sysml`**：文件灰显不可选，Open 按钮保持禁用。
4. **`Textual Editor` 无反应**：Containment 树右键 `package Model` 能看到该菜单项（enabled），点下去不出现任何编辑器标签页、无报错、无内嵌浏览器调试端口页面。
5. **实验特性开关无效**：给 `bin/msosa.properties` 注入 `-Dmd.sysml2.experimental.features=true` 并重启后，`File > Export To` 下多出 3 个 `[Experimental]` 项、`Tools` 下出现 `[Experimental] KerML/SysML File Tools`、右键菜单多出 `[Experimental]` 子菜单，**但 `File` 菜单仍未出现 `Import From`**，Textual Editor 仍无窗口。

**我们的结论（已归档为 BLOCKED）**：这台 CE 构建上**没有可用的文本导入路径**；不宣称"CE 不支持文本导入"这种产品级结论，只记"本机这个构建不支持"。

> **给对面的提醒**：不要重复"开实验开关 / 改 properties / 换 jar"这条路，我们已经试过且无效；也可能把安装弄坏。你要做的只是**记录你这台机器上有没有入口**。

---

## 2. "对方的版本"目前能查到什么程度

### 2.1 能查到的（有文档级证据）

**（a）你之前提供的那份 PDF 手册**——`智能体/Magic Systems of Systems Architect UserManual.pdf`：

- 标题页原文：`Dassault Systemes Americas Corp. 2026 / Magic Systems of Systems Architect 2026x Refresh1 / User Manual`
- 共 **4524 页**，`mdls` 记为 `User Guide`（K15t Scroll PDF Exporter 从 docs.nomagic.com 导出）
- 即：**这份文档对应的是 2026x Refresh1 版本线的通用手册**（不是某个人的安装包）。
- 注意两点：
  1. 它是**通用用户手册**，全文 **0 处**提到 `SysML v2` / `KerML` / `textual notation`（SysML v1 内容才在这本手册里）；v2 的文档在独立站点 `docs.nomagic.com/SYSML2P`。所以**手册本身不能回答"他装的那台有没有文本导入"**。
  2. 2026x Refresh1 正是**首次引入 SysML v2 模型校验**的版本（[Version News](https://docs.nomagic.com/VN/latest/sysml-v2-plugin-314180114.html)）；2024x Refresh2 的 Early Experience Program 版本没有 v2 校验。

**（b）CAMEO 建模案例便携包的源机器**——`智能体/CAMEO建模案例便携包/`：

- 其中 20 个 `.mdzip` 样本来自一台 Windows 机器上的 `D:\CEA2026xR1\samples\diagrams\`，启动程序是 `bin\cameoea.exe`（**Cameo Enterprise Architecture**，不是 MSOSA）；
- 这些 `.mdzip` 的模型 XML 里 `<xmi:exporterVersion>2026x v2</xmi:exporterVersion>`；
- 同机还有一个自建工程 `多旋翼.md3t`（原路径 `D:\Study\Sophomore_to_Junior\UAV\多旋翼.md3t`）。
- 即：**如果那台 Windows 机器就是你同学的机器**，那么他手上的工具是 **Cameo Enterprise Architecture 2026x 线**（目录名里的 `R1` 通常指 Refresh1，但**未经确认**），而不是我们这台 macOS 上的 MSOSA CE。

> ⚠️ 这一段是**旁证**，不是结论：便携包是谁的机器导出的、是否等于同学现在用的那台，我们没有直接证据。写报告时不要把它当成"同学的版本已确认"。

### 2.2 查不到的（必须现场读，30 秒）

| 项 | 为什么查不到 | 怎么读 |
| --- | --- | --- |
| 精确 build 号 | 手册只标版本线，不标 build | `Help > About` |
| 许可类型（Community / 商业 / 试用 / EEP） | 同一版本可有多种许可 | `Help > Licensing` / License Manager |
| 装了哪些插件、SysML v2 插件版本 | 取决于安装时的选择 | `Resource/Plugin Manager` |
| **有没有 `Import From`** | 这是构建/许可决定的，文档只说"官方路径应该这样点" | 点开 `File` 菜单看 |

所以任务书的第 2 步把 **F1–F6 指纹采集**列为"即使后面全失败也要做"的必做项——就是来补这几项。

---

## 3. 官方文档写明的路径（2026x Refresh1 线，不代表任何具体构建）

- 导入：`File > Import From > SysML v2 Textual Notation`（支持单文件 / 多文件 / 整目录，**每个文件导成一个独立根命名空间**）
- 导出：`File > Export To > SysML v2 Textual Notation`，或 Containment 树右键 → `Tools > Export to SysML v2 Textual Notation`
- 校验：2026x Refresh1 起提供（SysML / KerML / Dassault Systèmes 预定义规则）

来源：

- <https://docs.nomagic.com/SYSML2P/2026x-refresh1/textual-notation-import-export-304006231.html>
- <https://docs.nomagic.com/SYSML2P/2026x-refresh1/validation-304005165.html>
- <https://docs.nomagic.com/SYSML2P/2026x-refresh1/sysml-v2-plugin-documentation-304004594.html>

---

## 4. 一句话交给对面

> 我们只需要知道三件事：**你这台是什么版本/什么许可**、**`File` 菜单里有没有 `Import From`**、**有的话这份 `.sysml` 导进去报什么诊断**。前两件 3 分钟能拿到，第三件是加分项。
