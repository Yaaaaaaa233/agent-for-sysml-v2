# 01 · 给对面电脑上 AI agent 的任务书（全文可粘贴）

> **使用方法（给发件人）**：把整个 `MSOSA-remote-probe-2026-10-20` 目录（或 zip）放到同学电脑上，然后把**本文件全文**粘给他的 agent；或者只对它说一句「读取 `01-AGENT-TASK.md`，严格照它执行」。
>
> **使用方法（给接收方 agent）**：这是一次**只读的跨机器验证任务**。你不需要联网查资料，不需要装任何东西。按 §0 的边界和 §2 的顺序执行，最后填 `02-REPORT.md` 并打包 `evidence/`。

---

## 0. 边界（违反其中任何一条，本次结果作废）

1. **不要安装、升级、破解、修改许可证**。不要改 MSOSA/Cameo 的安装目录、`*.properties`、`vm.options`、插件包。
2. **不要修改 `inputs/` 下的任何文件**。开始前先校验 sha256（§2 第 1 步），不匹配立即停止并回报。
3. **不要在同学已打开的工程里做实验**。需要建工程时，新建一个独立工程（名字见 §4.1），做完不要保存对他人工程的改动。
4. **不要手工重建模型**。如果导入入口不存在或导入失败，就如实记录失败，不要用图形界面一个个摆元素来"凑出"一个看起来像的模型。
5. **不要宣称"通过了 MSOSA 验证 / 符合规范"**。这个工具不是认证机构；你只能报告"这个构建接受了这份文本 / 报了什么诊断"。
6. **不要上传、外发**这份模型或截图到任何第三方服务。模型是对方的比赛作品，仅用于本次验证。
7. **时间盒 45 分钟**。卡在某个对话框超过 5 分钟没进展，就停在现场、截图、记日志、回报，不要反复试安装目录里的东西。
8. 涉及同学的个人文件/聊天记录，不要读取、不要截进图里。截图只截应用窗口。

---

## 1. 背景（30 秒读完）

- 我们（发件方）做了一个 SysML v2 的建模智能体，产出 **IR → `.sysml` 文本**。
- 本机（macOS）装的是 **MSOSA 2026x Refresh1 的 Community Edition**，实测 **没有可用的文本导入入口**：File 菜单无 `Import From`，`Export To`/`Convert To` 灰显，`Open Project` 不接受 `.sysml`；把实验特性 `md.sysml2.experimental.features` 打开后仍无 `Import From`。详见 `reference/01-background.md`。
- 所以现在需要一台**另一个构建**的工具来回答一个问题：**同一份 `.sysml` 文本，换一个 MSOSA/Cameo 构建，能不能被接受？报什么诊断？**
- 这就是本次任务的全部目的：**拿到"另一个独立实现的接受性 + 诊断"证据**。成功和失败**都是有价值的结果**。

---

## 2. 执行顺序（先取证，再动手）

### 第 1 步：校验输入文件（1 分钟）

Windows PowerShell / CMD：

```powershell
certutil -hashfile "inputs\golden-coaxial-power-chain.sysml" SHA256
certutil -hashfile "inputs\00-smoke-minimal.sysml" SHA256
```

或 PowerShell：

```powershell
Get-FileHash "inputs\golden-coaxial-power-chain.sysml" -Algorithm SHA256 | Format-List
```

**必须匹配**：

| 文件 | 期望 sha256 |
| --- | --- |
| `golden-coaxial-power-chain.sysml` | `bb64cc2cbfdc5f5667049a76f6b57c4925a6ed29b2344c94d09d70e9ac6f6129` |
| `00-smoke-minimal.sysml` | `32b1a4954fed191f7aebede6df8abb4b10084f0af9b722dd7e5888f9140ec515` |

不匹配 → 停止，回报"输入损坏"（大概率是传输过程改动了换行/编码）。

### 第 2 步：采集版本指纹（3–5 分钟，**必做，即使后面全部失败**）

> 若 MSOSA/Cameo 还没运行：启动它即可。**不要**注册新账号、不要申请试用、不要改许可——用同学当前这台机器上的既有状态。
> 若界面语言是中文，菜单名按中文找：`文件 > 导入自`（Import From）、`文件 > 导出至`（Export To）、`分析 > 验证`（Analyze > Validation）、`帮助 > 关于`（Help > About）；报告里两种名字都记下来。

逐项截图 + 抄文字，全部存进 `evidence/`：

| # | 采集项 | 怎么做 | 记录什么 |
|---|---|---|---|
| F1 | **版本/build** | 菜单 `Help > About`（或 `Help > About Magic Systems of Systems Architect`） | 产品名、版本号（如 2026x Refresh1）、build 号、Java/OS 信息。**整窗截图** |
| F2 | **许可类型** | `Help > Licensing` / `Help > License Manager`（若菜单名不同，截图菜单原文） | Community Mode / 商业许可 / 试用 / EEP 内测，有没有到期日 |
| F3 | **插件清单** | `Options > Resource/Plugin Manager`（或 `Help > Resource/Plugin Manager`） | **SysML v2 插件**是否 Installed、版本；另记 Evaluation / Simulation / Migration 插件状态 |
| F4 | **File 菜单全文** | 点开 `File` 菜单，**整屏截图**（要能看到全部菜单项） | 逐条抄下菜单项原文；特别确认是否有 **`Import From`** 以及是否有子菜单 |
| F5 | **操作系统/安装路径** | `winver`；`bin` 目录路径 | Windows 版本、MSOSA/Cameo 安装路径、是否为 `D:\CEA2026xR1` 之类 |
| F6 | **启动日志** | 找 `msosa.log` / `cameo*.log`（见 §2 末尾命令） | 复制**整份**日志到 `evidence/logs/`，文件名保留原名 |

找日志的命令（Windows，PowerShell）：

```powershell
# 候选位置（逐个看，存在就整体拷走）
Get-ChildItem "$env:USERPROFILE\.magic*","$env:LOCALAPPDATA\.magic*","$env:APPDATA\.magic*" -ErrorAction SilentlyContinue | Select-Object FullName
# 兜底：在用户目录浅层搜日志
Get-ChildItem $env:USERPROFILE -Depth 4 -Include *.log -Recurse -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -match 'msosa|cameo|magic' } |
  Select-Object FullName, Length, LastWriteTime
```

> 我们这边 macOS 上的路径是 `~/.magic.systems.of.systems.architect/2026x/msosa.log`；Windows 上通常同构（用户目录下 `.产品名\版本\`），但**以你实际找到的为准**，别猜。

### 第 3 步：探测"文本导入通道"是否存在（2 分钟）

按这个顺序，**每一步都截图**：

1. `File > Import From > SysML v2 Textual Notation` —— 官方 2026x Refresh1 文档写的路径。
   - 如果 `File` 菜单里**根本没有 `Import From`** → 记录"无入口"（这是我们本机 CE 的情况），继续第 3.3 步。
   - 如果有 `Import From` 但**没有** `SysML v2 Textual Notation` 子项 → 把子菜单项逐条抄下来。
   - 如果灰显 → 记 `enabled=false` + 截图。
2. 在 Containment 树里右键根 `Model` 包 → 看 `Tools` 子菜单里是否有 **`Export to SysML v2 Textual Notation`**；再右键看有没有 `Textual Editor`。
   - 有 `Textual Editor` 就点一次，看是否打开编辑器标签页（有内容/空白都记下来）。
3. `File > Open Project`（或 `Open`），导航到 `inputs/`，看 `.sysml` 文件是否可选（灰显 = 不接受该格式）。

**判定**：

- 有可用入口 → 走 **第 4 步（路线 A）**；
- 无入口/灰显 → 走 **第 5 步（路线 B）**，然后直接跳到第 7 步回报；
- 有入口但导入报错 → 抄报错原文后走 **第 6 步（路线 C）**。

### 第 4 步（路线 A）：导入 → 核对 → 校验 → 导出

#### 4.1 新建一个独立工程

`File > New Project`（或 `File > Local Repository > Manage Projects > New`），工程名：

```
q1_remote_golden
```

位置用默认即可。若弹窗问是否切换 perspective，选 **`System Engineer SysML v2`**（没有这个 perspective 就选任何带 SysML v2 的，并记录实际名字）。

#### 4.2 先导最小冒烟文件

- `File > Import From > SysML v2 Textual Notation` → 选 `inputs/00-smoke-minimal.sysml` → Open。
- 期望：出现根命名空间 **`SmokeTest`**，下面有 `Widget`，其下有属性 `mass`。
- 记录：成功/失败、弹窗文字、耗时。**这一步失败就先别导正式文件**，直接回报（说明导入通道本身有问题）。

#### 4.3 再导正式模型

- 同一路径 → 选 `inputs/golden-coaxial-power-chain.sysml` → Open。
- 期望：出现根命名空间 **`CoaxialOctoRotor`**。
- 如果成功：展开 `CoaxialOctoRotor`，把包含所有子节点的树**整屏截图**（可分多张，保证能数清）。

#### 4.4 核对元素账本

对照 `ledgers/elements.csv`（34 行，每行一个元素）：

- `name` 列是 MSOSA 里应出现的**显示名**；
- 期望总数 **34**，按种类：7 个 `part def`、8 个 `part`、4 个 `requirement def`、9 个 `attribute`、2 个 `action def`、1 个 `state def`、1 个 `constraint def`、2 个 `connect`；
- 抽查这几个名字必须在：`BatteryPack`、`PowerChain`、`CruiseEndurance`、`FlightModeStates`、`EnduranceBudget`、`batteryToEsc`。

**关系不要按 20 条来核**：文本里只有 **2 条可导入的 `connect`**（`batteryToEsc`、`upperMotorToPropeller`），其余 18 条是我们 IR 里的追溯关系，只以注释形式存在于文本中，**不会**变成工具里的关系。见 `ledgers/relations.csv` 的 `in_sysml_text` 列。

#### 4.5 跑预置校验

1. `Analyze > Validation > Project Validation Suites`（菜单名若不同，截图 `Analyze` 菜单原文）。
2. 确认 **`SysMLConstraintsSuite`** 与 **`DassaultSystemesValidationSuite`** 在 Included 列；不在就加进去。把**套件列表整屏截图**，并把可用套件名逐条抄下。
3. 在 Containment 树右键根命名空间 `CoaxialOctoRotor` → `Validate`（或 `Analyze > Validation > Validate`）。
4. `Validation Results` 面板打开后：**先整屏截图**，再逐条抄进 `02-REPORT.md` 的表（Element / Severity / Rule Name / Message 原文）。
5. 面板若有导出/保存（如 `Export to CSV`、`Save`），导出到 `evidence/validate/`。

> 注意：校验面板打开后如果又改了模型，要重新 Validate 才会刷新。别没记录就关面板。

#### 4.6 导出文本（验证能否回导）

- `File > Export To > SysML v2 Textual Notation`（或树里右键 `CoaxialOctoRotor` → `Tools > Export to SysML v2 Textual Notation`）；
- 在 `Export SysML File` 窗口把根命名空间挪到 Selected 列；
- 输出目录选 `evidence/export/`；**不要勾** `Delete existing .sysml files`；
- 点 Export，然后记录导出的文件名、大小、sha256：

```powershell
Get-ChildItem evidence\export | Select-Object Name, Length
Get-ChildItem evidence\export\*.sysml | ForEach-Object { Get-FileHash $_.FullName -Algorithm SHA256 }
```

> 允许导出结果与输入**不完全一致**（排版/名称限定符可能变），**不要**把它当失败；只如实记录文件数与 sha256，不要手工 diff 后宣称"关系 20/20 一致"。

### 第 5 步（路线 B）：无入口时做什么

**只做记录，不做变通**。把下面这些抄成文字放进 `02-REPORT.md` §2：

- `File` 菜单全部菜单项（逐条）；
- `Import From` 是否存在；若存在，其子菜单项逐条；
- `Export To` / `Convert To` 是否灰显；
- 右键 `Model` 的 `Tools` 子菜单逐条；
- `Open Project` 是否接受 `.sysml`；
- `Help > About` / License Manager 的版本与许可。

**不要**去改安装目录、开实验特性、换 jar、改注册表。我们已经在 macOS 上试过实验开关（`-Dmd.sysml2.experimental.features=true`）：会多出若干 `[Experimental]` 条目，但**仍然没有 `Import From`**。重复这条路只会浪费时间。

### 第 6 步（路线 C）：有入口但导入失败

- **原样抄**弹窗文字（不要转述、不要翻译）；能选中就复制，不能就截图 + 手打；
- 若能定位到文本的**行号/元素名**，一并记；
- 复制日志**尾部 300 行**到 `evidence/logs/import-error-tail.txt`；
- 再用 `00-smoke-minimal.sysml` 试一次：如果冒烟也失败 → 是通道问题；如果冒烟成功、正式文件失败 → 是我们的文本用了它不支持的构造，这时对照 `reference/02-expected-and-criteria.md` 的"高风险构造清单"逐条标出。

### 第 7 步：回报（10 分钟）

1. 填 `02-REPORT.md`（所有 `<>` 占位符都要换成事实；做不到的写"未执行 + 原因"，**不要留空**）。
2. 把 `evidence/` 打成一个 zip：`MSOSA-remote-evidence-<你的机器名或姓名缩写>-<YYYYMMDD-HHMM>.zip`。
3. 给 zip 算 sha256，写在报告最后。
4. 把 `02-REPORT.md` + zip 交回给发起人。

---

## 3. 如果你不能操作 GUI（只有 shell / 只能读文件）

那你就是"记录员"角色，不要假装点了菜单：

1. 完成 **第 1 步**（校验和）、**第 2 步**里能做的部分（F5 系统信息、F6 日志：直接读 `msosa.log`，里面通常有 `Version Info`、`Plugin started`、`user.language` 等硬事实）；
2. 输出一份**给人看的点击清单**（就照 §2 第 3–4 步的菜单路径），让同学本人去点，点完把截图和日志给你；
3. 你负责校验截图里的文字、把结果填进 `02-REPORT.md`。

日志里值得 grep 的关键词：`Version Info`、`Plugin started`、`Not supported`、`SysML`、`Import`、`Experimental`、`license`。

---

## 4. 事实参考（可直接引用，不用再查网）

官方 2026x Refresh1 文档写明的路径：

- 导入：`File > Import From > SysML v2 Textual Notation`；支持单文件、多文件、整个目录；**每个文件导成一个独立根命名空间**。
  来源：<https://docs.nomagic.com/SYSML2P/2026x-refresh1/textual-notation-import-export-304006231.html>
- 导出：`File > Export To > SysML v2 Textual Notation`，或 Containment 树右键 → `Tools > Export to SysML v2 Textual Notation`；可勾"删除输出目录已有 .sysml"。
  来源：同上
- 模型校验：2026x Refresh1 起提供（SysML / KerML / Dassault Systèmes 三套预定义规则）。
  来源：<https://docs.nomagic.com/SYSML2P/2026x-refresh1/validation-304005165.html>

> 这三条是**官方文档写的**，不等于**本机这个构建里真的有**。文档 vs 实际不一致时，**以你眼前的菜单为准**，并把这个不一致本身当作结论写进报告。

---

## 5. 报告纪律

- 只写**亲眼看到**的事实。截图里没有的、日志里没有的，不要推断成结论。
- 三种合法结论，只能选一个：
  - **A**：该构建可导入 → 写出根命名空间、元素计数、校验诊断、导出文件数与 sha256；
  - **B**：该构建无文本导入入口 → 写出菜单证据 + 版本/许可指纹；
  - **C**：有入口但失败 → 写出错误原文 + 日志 + 冒烟对照结果。
- **禁止**写"验证通过/符合 OMG 规范/模型正确"这类话。工具的接受性 ≠ 模型正确性。
- 版本、许可、插件这三项是**无论成败都必须拿到**的，因为它们决定这份证据能说明什么。

---

## 6. 一页速查（贴在旁边照做）

```
1 校 sha256                  → inputs/sha256sums.txt
2 Help>About / Licensing / Resource-Plugin Manager / File 菜单 / 日志   → evidence/fingerprint/
3 File>Import From>SysML v2 Textual Notation 在不在？
    不在 → 路线 B：抄菜单，回报
    在   → 新建工程 q1_remote_golden
           先导 00-smoke-minimal.sysml → 期望根 SmokeTest
           再导 golden-coaxial-power-chain.sysml → 期望根 CoaxialOctoRotor
           对照 ledgers/elements.csv 核 34 个名字 / 2 条 connect
           Analyze>Validation>Project Validation Suites → 勾两套件 → 右键根 Validate → 抄面板
           File>Export To>SysML v2 Textual Notation → evidence/export/ → 记 sha256
4 填 02-REPORT.md  →  evidence/ 打包 zip  → 回报
```
