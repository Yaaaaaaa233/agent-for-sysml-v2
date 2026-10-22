# BLOCKER — MSOSA Community Edition 无法执行文本导入

- 日期：2026-10-20
- 工具：Magic Systems of Systems Architect 2026x Refresh1（SysML v2 Community Edition）
- 项目：`q1-msosa-golden`（category `q1-verification`，perspective `System Engineer SysML v2`）
- 结论：**既定操作卡第 2 步 `File > Import From > SysML v2 Textual Notation` 在本机不存在，导入未发生；后续树核对、Validate、Export 均未执行。**

## 1. 现场事实

| # | 事实 | 证据 |
| --- | --- | --- |
| 1 | 版本/席位为 `2026x Refresh1 Enterprise Community Seat`，License 为 Use in Community Mode | `screenshots/20261020-1036_golden_install_01_license-manager.png` |
| 2 | SysML v2、SysML v2 Simulation、SysML v1 → v2 Migration 插件显示 Installed | `screenshots/20261020-1038_golden_install_04_resource-plugin-manager.png` |
| 3 | 项目创建成功，perspective 为 `System Engineer SysML v2`，树为 `q1-msosa-golden > [Model] > package Model` | `screenshots/20261020-1040_golden_project_00_new-project-dialog.png`；`screenshots/20261020-1041_golden_project_01_created.png` |
| 4 | **File 菜单没有 `Import From`**；`Export To` / `Convert To` 为禁用灰显（AX `enabled=false`） | `screenshots/20261020-1118_golden_capability_01_file-menu-no-import-export-disabled.png` |
| 5 | Open Project 对话框中 `.sysml` 灰显不可选，Open 按钮禁用 | `screenshots/20261020-1059_golden_capability_02_open-project-sysml-not-selectable.png` |
| 6 | 右键 `package Model` 的 `Textual Editor` 菜单项可被辅助功能触发，但无可见编辑器、无报错、CDP page target 为空（`localhost:9231`） | 本轮观察；未作为导入路径 |

## 2. 影响

- 无法在 MSOSA 内得到 `CoaxialOctoRotor` 根命名空间，因此无法跑 `SysMLConstraintsSuite` / `DassaultSystemesValidationSuite`，也无法导出 `.sysml`。
- `runs/2026-10-20-validate/validation-results.md` 与 `runs/2026-10-20-export/export-log.md` 保持“未执行”，不得据此写“MSOSA 验证通过”。
- 本轮证据只能证明**工具能力缺口**，不能证明模型被独立实现接受或拒绝。

## 3. 可选的后续（需要用户/评测方选择）

1. **商业版 / SysML v2 Solution 版**：在具备 textual import/export 的授权构建上按原操作卡重跑第 2–7 步。
2. **确认 Textual Editor 的可用入口**：如果 CE 允许通过 Textual Editor 粘贴文本并同步，需把导入方式如实改为“Textual Editor 粘贴同步”，不能用原菜单路径；本轮未能打开该编辑器。
3. **更换独立实现**：例如 SysON 等支持 `.sysml` 文本导入的工具，替换 MSOSA 这一腿，并在 README 说明替换理由。
4. **图形化手工重建**（不推荐）：工作量大，且不是对同一文本的接受性验证，不能替代导入。

## 4. 复现路径

1. 启动 MSOSA 2026x Refresh1（Community Mode）。
2. 打开任意项目 → 展开 File 菜单 → 观察无 `Import From`，`Export To`/`Convert To` 灰显。
3. File > Open Project… → 导航到 `docs/verification/msosa/inputs/` → `.sysml` 文件灰显、Open 禁用。
4. 如需辅助功能复核：读取 File 菜单的 `AXEnabled`，`Export To` 与 `Convert To` 均为 `false`。

## 5. 本轮决策

**2026-10-20：接受 BLOCKED 收尾。** 不换商业版、不改用 SysON、不手工重建；本轮不产出 MSOSA 的独立接受性/诊断结论，只保留能力缺口与项目创建证据。

## 6. 2026-10-20 11:40–11:55 复核（computer use + 安装包内证）

> 本节只记录**新观察到的事实**与**未验证的候选路径**。§5 的收尾决策暂不推翻，但“CE 不支持文本导入”这个根因判断降级为**待复验**。

### 6.1 现场状态：没有卡死

- 复核时 MSOSA 进程正常响应，界面停在已打开的空项目：`q1-msosa-golden > [Model] > package Model`，没有模态框、没有未保存提示。
- 也就是说“卡住”指的是**流程停在导入入口**，不是应用挂死。

### 6.2 候选路径 A：导入/导出是“实验特性”，默认未暴露

从安装包内的 class 与常量池字符串得到的证据：

| 观察 | 出处 |
| --- | --- |
| 导入/导出动作存在：`importTextualModelIntoProject`、`Import SysML v2 Textual With Diagrams` | `plugins/com.nomagic.magicdraw.sysml2/lib/sysml2.sysml.interchange.ui-…jar` 内 class 常量池；`lib/sysml2.sysml.core-…jar` 的 `TextualModelHelper` |
| 这些动作所在的包/标记是 experimental：`/actions/experimental/ExperimentalActions`、`prependExperimental` | 同上 |
| 主菜单配置器是否添加这些动作，取决于 `isExperimentalFeaturesEnabled` | `sysml2.sysml.interchange.ui-…jar` 内菜单配置器 class |
| 实验开关是一个环境选项：键 `md.sysml2.experimental.features`，类 `…kerml.core.options.EnvironmentOptions`（`isExperimentalFeaturesEnabled` / `setExperimentalFeaturesEnabled`） | `lib/sysml2.kerml.core-…jar` |

**未验证**：在 `Options > Environment` 里是否存在这个开关；打开后 File 菜单是否出现导入/导出项；开关是否被 CE 许可模式屏蔽。

### 6.3 候选路径 B：Textual Editor 空白是语言缺陷

| 观察 | 证据 |
| --- | --- |
| JVM 默认语言是 `zh`：启动日志 `user.language=zh` | `~/.magic.systems.of.systems.architect/2026x/msosa.log`（每次启动） |
| web UX 组件只带英文资源：`lib/webux-components-ui-6.40.12.jar` 中只有 `UIKIT_en.js` / `UIKIT_en.json` | `unzip -l` 实测 |
| 编辑器页面请求中文资源并 404：`Classpath resource …/UIKIT/UIKIT_zh.js not found` | 同一日志（11:15:47 等） |
| 浏览器引擎已起但无页面：CDP `http://127.0.0.1:9231/json/list` 返回 `[]`（浏览器版本 Chrome/145） | 现场 curl 实测 |

**未验证**：把 JVM 语言切成英文后，Textual Editor 是否能正常渲染；若可以，则可改走“Textual Editor 粘贴 / 同步模型”的导入路径（CE 官方页宣称文本与图形双向同步）。

### 6.4 本次重启实验：`open --env` 不生效

- 尝试 1：`launchctl setenv JAVA_TOOL_OPTIONS …` → `Not privileged to set domain environment.`（受 DSH 文件沙箱限制）。
- 尝试 2：`open --env "JAVA_TOOL_OPTIONS=-Duser.language=en -Duser.country=US -Dmd.sysml2.experimental.features=true" -a <MSOSA>` 重启 → 日志仍为 `user.language=zh`。
- 解释：MagicDraw 的启动器用 JNI 内嵌 JVM，`JAVA_TOOL_OPTIONS` 由 `java` 启动器解析，不是 JNI 初始化路径，所以不生效。
- 要真正注入 JVM 参数，只能改安装目录的 `bin/msosa.properties` 的 `JAVA_ARGS`（需在 /Applications 写文件；当前沙箱下写不了，需授权或人工执行），或使用 macOS“每应用语言”设置。

### 6.5 当前留下的状态

- MSOSA 已被本轮回溯重启，停在 **Welcome** 画面；`q1-msosa-golden` 在 Recent Projects 里，**没有重开**。
- 项目仍是空包，没有模型元素；Validate / Export 仍未执行。
- 下一步（需人工或授权）：① 授权 DSH 的自动化/辅助功能后由 Agent 点菜单；或 ② 人工打开 `Options > Environment` 找实验特性开关；或 ③ 备份后改 `bin/msosa.properties` 注入 `-Duser.language=en -Dmd.sysml2.experimental.features=true` 再重启。

### 6.6 语言根因已定位并修复（2026-10-20 12:53）

- 根因：JVM 默认 `user.language=zh`（macOS 系统语言 zh-Hans-CN），而 webux 组件包只带 `UIKIT_en.js`；Textual Editor 页面请求 `UIKIT_zh.js` → 404，页面空白。
- 修复（不改安装包）：`defaults write "com.nomagic.Magic Systems of Systems Architect" AppleLanguages -array en`，重启后日志确认 **`user.language=en`**（`msosa.log` 12:53:13）。
- 副作用：MSOSA 菜单/界面切到英文（File/Edit/Options…）。
- **Textual Editor 尚未复测**：见 §6.7。

### 6.7 桌面焦点冲突（computer use 的硬限制）

- 复核期间检测到另一 DSH 会话（`体素中国古典建筑群` 项目）用 Playwright 启动 `Google Chrome for Testing`，反复把自己切到前台；此后用户本人操作 DSH 也会抢焦点。
- 后果：合成的鼠标/键盘事件多次落到错误窗口（右键菜单开在 Finder / Chrome 上），MSOSA 的“打开 Textual Editor”动作被中断。
- 结论：**共享桌面上的 computer use 必须独占焦点**；这不是权限问题。要完成 GUI 操作，需要用户暂停其他会话并 1–2 分钟不碰键鼠，或由用户手动点那一下。

### 6.8 AX（辅助功能）复核结论（独立于截图）

- 权限：Screen Recording ✅（截屏正常）、Accessibility ✅（`AXIsProcessTrusted()=True`，可读菜单/点按）；System Events 的 Automation 未授权（-10004），本轮用 AX 绕开。
- 项目打开状态下 File 菜单（AX 逐项读取）：**无 `Import From`**；全菜单扫描无 import 动作；`Export To > SysML v2 Textual Notation` 存在但 disabled。
- `Options > Environment`：`SysML v2` 组只有 `Show Element Keyword`；`SysML v2 Textual Editor` 组只有 Code Style / Editor；过滤 “experimental” 无结果 → **实验特性开关未在 GUI 暴露**（要验证只能改 `bin/msosa.properties` 注入 `-Dmd.sysml2.experimental.features=true`）。
- 右键 `package Model` 的上下文菜单含 `Textual Editor`、`Validate`（AX 可见）。

### 6.9 实验特性开关已打开：证实“没有导入入口”不是没开开关（2026-10-20 15:14）

- 操作系统级注入（已备份 `/tmp/msosa.properties.bak-*`）：在 `bin/msosa.properties` 的 `JAVA_ARGS` 追加
  `-Duser.language=en -Duser.country=US -Dmd.sysml2.experimental.features=true`，重启后日志确认三项都进入 JVM 参数。
- 实验特性**确实生效**（新条目出现）：
  - `File > Export To` 多出 `[Experimental] SysML v2 Textual Notation with Diagrams`、`[Experimental] SysML v2 Model as MDZIP`、`[Experimental] SysML v2 Model to Active Project`；
  - `Tools` 多出 `[Experimental] KerML/SysML File Tools`（Re-adapt / Resave / Flatten *.sysml into clipboard 等）；
  - 右键菜单多出 `[Experimental]` 子菜单（Is Implied Included / Preview in Any Table Action / Table Example）。
- **但导入仍然不存在**：File 菜单在 `System Engineer SysML v2` 与 `System Engineer` 两个 perspective 下都**没有 `Import From`**；全菜单扫描无 import 动作；`Export To` 下也仍然没有任何 Import 项。
- **Textual Editor 仍是 no-op**：右键 `package Model` → `Textual Editor`（AX `enabled=True`）→ 菜单关闭，但**不产生窗口、日志没有编辑器启动记录、JxBrowser CDP `http://127.0.0.1:9231/json/list` 仍为 `[]`（0 个页面）**。
- 语言：`user.language=en` 已确认，但启动日志仍出现 `UIKIT_zh.js not found` → 该 404 不是唯一原因，Textual Editor 失败与语言无直接可证关系。
- 结论：**在本机这个 Community Edition 构建上，文本导入路径不存在（不是菜单藏起来、也不是实验开关没开）**；Textual Editor 动作是空实现/不可用。原 BLOCKER 的“CE 能力缺口”判断方向成立，但现在有可复现的加强证据。
- 遗留：对安装包的修改（`bin/msosa.properties`）与每应用语言设置可按需回滚。

### 6.10 回滚与归档（2026-10-20 16:22）

- 按用户决定回滚：恢复 `bin/msosa.properties`（备份来自 `/tmp/msosa.properties.bak-151429`），删除每应用 `AppleLanguages` 设置，重启 MSOSA。
- 回滚后核验：启动日志恢复 `user.language=zh`，Input Arguments 中无 `-Dmd.sysml2.experimental.features`。
- 实验阶段的菜单原始记录归档在 [`../2026-10-20-experimental/`](../2026-10-20-experimental/)（`README.md`、`file-menu-after-experimental.txt`、`tools-menu-after-experimental.txt`）。
- **最终结论**：本机 SysML v2 Community Edition 构建没有可用的文本导入路径；MSOSA 这一腿不产出“独立实现接受性/诊断”结论。后续若换商业版/具备 textual import 的构建，按本目录 §2 操作卡复跑即可。
