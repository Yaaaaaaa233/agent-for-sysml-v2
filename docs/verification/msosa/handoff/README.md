# MSOSA 跨机验证交接包（handoff）

> **状态：2026-10-20 已打包，待发送 / 待回传。** 本目录是「把验证任务交给同学机器上的 agent」的一整套材料；包本身在 [`2026-10-20-remote/`](2026-10-20-remote/)，zip 见同目录 `MSOSA-remote-probe-2026-10-20.zip`。

## 为什么要跨机

本机（macOS，MSOSA 2026x Refresh1 **Community Seat**）实测**没有可用的文本导入入口**：`File` 菜单无 `Import From`，`Export To`/`Convert To` 灰显，`Open Project` 不接受 `.sysml`，`Textual Editor` 无窗口，实验特性开关打开后仍无 `Import From`。详细证据与回滚记录见 [`../runs/2026-10-20-import/BLOCKER.md`](../runs/2026-10-20-import/BLOCKER.md) 与 [`../runs/2026-10-20-experimental/`](../runs/2026-10-20-experimental/)。

因此把同一份**冻结**文本交给另一个构建去试，判定只有三态：

- **A｜可导入** —— 拿到"独立第二实现"的接受性 + 诊断；
- **B｜无入口** —— 说明该构建也没有文本导入路径，缩小"CE 限制 vs 产品限制"的范围；
- **C｜有入口但失败** —— 差分出不被支持的构造。

## 包内结构

```
handoff/2026-10-20-remote/
├── 00-README.md                    给同学（人）的一页说明
├── 01-AGENT-TASK.md                对面 agent 的任务书（全文可粘贴；边界/取证/两段导入/校验/导出/回报）
├── 02-REPORT.md                    对面填写的回报表（A/B/C + 证据清单 + 声明）
├── 03-MESSAGE-TO-CLASSMATE.txt     发件方用的微信消息模板
├── inputs/
│   ├── golden-coaxial-power-chain.sysml   冻结文本 bb64cc2c…（34 元素 / 2 connect）
│   ├── 00-smoke-minimal.sysml             冒烟文件 32b1a495…（先证明通道可用）
│   └── sha256sums.txt
├── ledgers/{elements.csv,relations.csv}   核对账本（34 元素；20 关系里仅 2 条在文本中）
└── reference/
    ├── 01-background.md             我们试过什么 + 版本线索（PDF 手册 2026x Refresh1 / CAMEO 包 D:\CEA2026xR1）
    └── 02-expected-and-criteria.md  期望值 + 三态判定 + 13 条高风险构造（供二分定位）
```

## 关键事实（发给谁之前先记住）

- 输入文件**已冻结**：文本 sha `bb64cc2cbfdc5f5667049a76f6b57c4925a6ed29b2344c94d09d70e9ac6f6129`，与本地验证 `../local/golden-2026-10-20/model.sysml` 逐字节一致；IR sha `adae5c61…`。
- 文本已通过 OMG SysML v2 Pilot Implementation 官方解析器（0 诊断）。**对面报语法错误 = 实现覆盖差异，不等于我们文本非法。**
- 版本线索：用户提供的 4524 页 PDF 是 **MSOSA 2026x Refresh1** 通用手册（只含 SysML v1 内容，v2 在独立文档站）；CAMEO 便携包来自一台 `D:\CEA2026xR1`（Cameo Enterprise Architecture 2026x 线）的 Windows 机器。**这两条都不能替代现场读 `Help > About`**，所以任务书把指纹采集设为必做。
- 任务的**最低合格线**（缺一项证据不可用）：版本/build、许可类型、SysML v2 插件状态、`File` 菜单全文、输入 sha256 一致。

## 回传后怎么落地

1. 对方回传 `02-REPORT.md` + `evidence-*.zip`；先核对 zip sha256 与报告一致。
2. 按判定新建一轮运行记录（沿用现有命名）：
   - A → `../runs/<date>-remote-import/`（`import-log.md`、`validation-results.md`、`export-log.md`、`screenshots/`）
   - B → `../runs/<date>-remote-import/BLOCKER.md` 追加一节（构建指纹 + 菜单证据），并在 `../README.md` 顶部补一行状态
   - C → 同上，另加 `construct-bisect.md`（对照 `reference/02` 的 R1–R13）
3. 更新 `../fingerprint.json` 的 `remoteBuild` 字段（对方构建）——**只记事实，不写推断**。
4. 结论措辞红线：只写"该构建接受了这份文本，诊断如下"；**不写**"通过 MSOSA 验证 / 符合 OMG 规范 / 模型正确"。

## 传输与校验

- 传输：微信 / U 盘 / 网盘（zip，**29,763 B**，11 个文件，解开约 84 KB）。
- 发出去前自己先核一次：`shasum -a 256 MSOSA-remote-probe-2026-10-20.zip`，把值记在本文件末尾。
- 对面解压后核对 `inputs/` 两个文件的 sha256（PowerShell `Get-FileHash`），不一致先查传输（换行/编码/BOM）。

## 记录

| 日期 | 动作 | 结果 |
| --- | --- | --- |
| 2026-10-20 21:16 | 交接包打包（`MSOSA-remote-probe-2026-10-20.zip`） | 11 文件 / 59,339 B 未压缩；zip 29,763 B；输入 sha 解包复校一致 |
| 2026-10-20 | 发送 | 待发送 |
| — | 回传 | 待回传 |

- zip：`MSOSA-remote-probe-2026-10-20.zip`
- zip sha256：`0f504a440dcecc56f20cd19d75f35a8741bf9427e4de7af0c35d3ad91db9ee57`
