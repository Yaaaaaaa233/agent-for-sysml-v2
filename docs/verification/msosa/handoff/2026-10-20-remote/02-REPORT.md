# 02 · 跨机验证回报表（对面填写）

> 填写规则：所有 `< >` 都要换成事实；**没做/不能做**就写「未执行 + 原因」，不要留空、不要猜。
> 结论只能落在 A / B / C 三种之一（见文末判定）。填完连同 `evidence/` 的 zip 一起交回。

- 填写人（同学本人 / agent）：`< >`
- 机器名与 Windows 版本：`< >`
- 填写日期与当地时区：`< >`
- 任务开始 / 结束时间：`< >` / `< >`（总耗时 `<n>` 分钟）

---

## 0. 输入校验

| 文件 | 期望 sha256（前 12 位） | 实际 sha256 | 匹配 |
| --- | --- | --- | --- |
| `golden-coaxial-power-chain.sysml` | `bb64cc2cbfdc` | `< >` | 是 / 否 |
| `00-smoke-minimal.sysml` | `32b1a4954fed` | `< >` | 是 / 否 |

---

## 1. 版本指纹（F1–F6）

| # | 项 | 实际值 | 证据文件 |
| --- | --- | --- | --- |
| F1 | 产品名 + 版本（`Help > About` 原文） | `< >` | `<evidence/fingerprint/...png>` |
| F1b | build 号 / 构建日期 | `< >` | 同上 |
| F2 | 许可类型（Community Mode / 商业 / 试用 / EEP） | `< >` | `< >` |
| F2b | 许可到期日（若有） | `< >` | — |
| F3 | SysML v2 插件：Installed? 版本? | `< >` | `< >` |
| F3b | 其它插件（Evaluation / Simulation / Migration / Requirements） | `< >` | `< >` |
| F4 | File 菜单项（逐条原文，逗号分隔） | `< >` | `< >` |
| F5 | 安装路径 / OS 版本 | `< >` | — |
| F6 | 启动日志路径 + 大小 + 修改时间 | `< >` | `<evidence/logs/...>` |

> 关键三问的答案：**有没有 `Import From`？`Export To` 是否 enabled？能在 `Open Project` 里选 `.sysml` 吗？** → `< >

---

## 2. 菜单观测（原文，不要总结）

| 位置 | 观测结果 |
| --- | --- |
| `File` 菜单是否有 `Import From` | `<有 / 没有>` |
| 若有，`Import From` 的子菜单项 | `<逐条>` |
| `Export To` 状态 | `<enabled / 灰显 disabled / 不存在>` |
| `Convert To` 状态 | `<同上>` |
| 右键 `Model` → `Tools` 子菜单项 | `<逐条>` |
| 右键 `Model` 是否有 `Textual Editor` | `<有 / 没有>`；点了以后：`<打开了空白页 / 打开了有内容 / 无反应>` |
| `Open Project` 里 `.sysml` 是否可选 | `<可选 / 灰显不可选>` |
| Perspective 名称 | `< >` |

---

## 3. 导入（冒烟 → 正式）

| 阶段 | 是否执行 | 结果 | 根命名空间 | 弹窗/报错原文 | 耗时 | 截图 |
| --- | --- | --- | --- | --- | --- | --- |
| 新建工程 `q1_remote_golden` | 是 / 否 | `<成功 / 失败>` | — | `< >` | `<n>` s | `< >` |
| 冒烟 `00-smoke-minimal.sysml` | 是 / 否 | `<成功 / 失败>` | `<SmokeTest?>` | `< >` | `<n>` s | `< >` |
| 正式 `golden-coaxial-power-chain.sysml` | 是 / 否 | `<成功 / 失败>` | `<CoaxialOctoRotor?>` | `< >` | `<n>` s | `< >` |

### 3.1 元素核对（对照 `ledgers/elements.csv`，34 行）

| 项 | 期望 | 实际 | 差异说明 |
| --- | --- | --- | --- |
| 元素总数 | 34 | `< >` | `<缺哪些/多了哪些>` |
| `part def` | 7 | `< >` | `< >` |
| `part`（usage） | 8 | `< >` | `< >` |
| `requirement def` | 4 | `< >` | `< >` |
| `attribute` | 9 | `< >` | `< >` |
| `action def` | 2 | `< >` | `< >` |
| `state def` | 1 | `< >` | `< >` |
| `constraint def` | 1 | `< >` | `< >` |
| `connect`（文本里只有这 2 条） | 2 | `< >` | `< >` |

抽查点名（6 个必须存在）：`BatteryPack` `<有/无>` ｜ `PowerChain` `< >` ｜ `CruiseEndurance` `< >` ｜ `FlightModeStates` `< >` ｜ `EnduranceBudget` `< >` ｜ `batteryToEsc` `< >`

> 说明：`ledgers/elements.csv` 的 `ir_id` 是我们内部编号，MSOSA 里只看 `name` 列。`ledgers/relations.csv` 里 20 条关系只有 2 条是文本里真的 `connect`，其余 18 条仅注释、**不会**出现，不要记成缺失。

---

## 4. 校验

| 项 | 值 |
| --- | --- |
| 校验入口是否可用 | `<可用 / 菜单不存在 / 灰显>` |
| 套件列表（全部可用套件名） | `<逐条>` |
| `SysMLConstraintsSuite` | `<Included / 未列出 / 不可用>` |
| `DassaultSystemesValidationSuite` | `<同上>` |
| 是否对根命名空间执行了递归 Validate | `<是 / 否>` |
| Fatal | `<n>` |
| Error | `<n>` |
| Warning | `<n>` |
| Info | `<n>` |
| Debug | `<n>` |
| 是否导出/保存了结果文件 | `<是（文件名）/ 否（原因）>` |

### 4.1 诊断明细（逐条抄，Element / Severity / Rule Name / Message 原文）

| # | Element（SysML 名） | Severity | Rule Name | Message（原文，不要翻译） |
| --- | --- | --- | --- | --- |
| 1 | `< >` | `< >` | `< >` | `< >` |
| 2 | `< >` | `< >` | `< >` | `< >` |
| … | | | | |

> 若诊断多，正文列前 20 条，其余放 `evidence/validate/` 里（截图或导出文件），并在报告里写清"完整清单见 X"。

---

## 5. 导出（回导）

| 项 | 值 |
| --- | --- |
| 导出入口 | `<File > Export To / 树右键 Tools > Export...>` |
| 是否成功 | `<是 / 否>` |
| 输出目录 | `<evidence/export/>` |
| 导出文件数 | `<n>` |
| 文件名 + 大小 + sha256 | `<name.sysml | 1234 B | abc…>` |
| 是否勾了"Delete existing .sysml" | `<否（按任务书）/ 是（说明原因）>` |

> 导出文本与输入不要求逐字一致，**不要**据此判断对错；只要记录。

---

## 6. 异常与日志

| # | 现象（原文/截图） | 出现步骤 | 是否可复现 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | `< >` | `< >` | `< >` | `< >` |

- `evidence/logs/` 里的文件：`<列表>`
- 若走了路线 C，附 `import-error-tail.txt`（日志尾部 300 行）：`<是/否>`

---

## 7. 结论（三选一，**只能选一个**）

- [ ] **A｜该构建可导入**：根命名空间 `CoaxialOctoRotor` 生成，元素 `<n>`/34，`connect` `<n>`/2，校验 Fatal `<a>`/Error `<b>`/Warning `<c>`，导出 `<n>` 个文件（sha256 `<…>`）。这只能说明"**该构建接受了这份文本**"，不代表模型正确或符合规范。
- [ ] **B｜该构建无文本导入入口**：`File` 菜单无 `Import From`（或子项无 SysML v2 文本导入 / 灰显），版本 `<ver>`、许可 `<许可>`、SysML v2 插件 `<状态>`。说明"**这份构建也没有可用的文本导入路径**"。
- [ ] **C｜有入口但导入失败**：冒烟 `<通过/失败>`，正式文件报错原文：`< >`；疑点构造：`<逐条>`。

补充说明（自由写，别写结论性夸大）：`< >`

---

## 8. 声明

- [ ] 我**没有**修改 `inputs/` 下的文件（sha256 与 §0 一致）。
- [ ] 我**没有**安装/升级/破解/改许可，**没有**改安装目录。
- [ ] 我**没有**手工重建模型来"凑"结果。
- [ ] 我**没有**把模型或截图上传到任何第三方服务。
- [ ] 我未读取与本次验证无关的个人文件。

证据包：`MSOSA-remote-evidence-< >.zip`，sha256 = `< >`，大小 `< >` MB，文件数 `<n>`。
