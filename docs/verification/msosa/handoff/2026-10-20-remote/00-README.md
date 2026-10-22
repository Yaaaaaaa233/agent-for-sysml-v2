# 跨机验证包 · MSOSA 文本导入能力（2026-10-20）

**一句话**：请你帮忙用你电脑上的 **MSOSA / Cameo**（Magic 家的建模工具）打开/导入一份 `.sysml` 文本，看它**认不认**、**报什么错**。约 **15–40 分钟**，不需要你安装任何东西，也不会改你现有的工程。

发起方：叶安（2610_MBSE 比赛组）。用途：我们做了一个 SysML v2 建模智能体，需要**另一个独立实现**对同一份文本的接受性/诊断作为交叉验证证据。我们自己那台 macOS 上的 Community Edition **没有文本导入入口**，所以在找别的构建做对照。

---

## 你要做的只有三件事

1. **解压**这个包（保持目录结构，别把 `inputs/` 挪走）。
2. **二选一**：
   - **路线 A（推荐，省事）**：把你电脑上的 AI agent 打开，把 `01-AGENT-TASK.md` **全文**粘给它（或跟它说"读取 01-AGENT-TASK.md 并严格照做"）。它会自己取证、建工程、导入、跑校验、填报告。
   - **路线 B（自己点，约 15 分钟）**：照 `01-AGENT-TASK.md` 的 §2 第 2–4 步手动操作，把截图和日志给我，我来整理。
3. **回传**：`02-REPORT.md`（填好的）+ `evidence/` 打成的 zip。微信/U盘/网盘都行。

---

## 为什么要做（以及为什么失败也有用）

我们关心的只有一个问题：**同一份 `.sysml` 文本，换一个构建，能不能被接受？**

- **能导入** → 我们得到一个"独立第二实现"的接受性 + 诊断证据；
- **没有导入入口** → 说明"这台构建也没有文本导入路径"，这本身也是结论（能帮我们判断是我们这套 CE 的限制还是整个产品的限制）；
- **有入口但报错** → 更有价值：它会告诉我们文本里哪类构造不被支持。

所以**不用怕失败**，也**不用**帮我们"想办法弄成功"（比如手工摆元素）——那样反而不算证据。

---

## 重要约束（请别做这几件事）

| 别做 | 原因 |
| --- | --- |
| 不要安装/升级/破解、不要动许可证 | 我们只要"你现在这台构建"的证据 |
| 不要改 MSOSA 安装目录里的文件（`*.properties`、`vm.options`、jar） | 我们已在 macOS 上试过实验开关，没用；改坏了要重装 |
| 不要在你**正在用**的工程里做实验 | 请新建一个叫 `q1_remote_golden` 的工程 |
| 不要修改 `inputs/` 里的文件 | 校验和一变，证据就失效 |
| 不要手工重建模型 | 那会污染结论 |
| 不要把模型/截图发到网上 | 模型是我们比赛的作品 |

**隐私**：截图只截应用窗口即可（别把桌面、聊天窗口截进去）。我们只会把这批证据用于比赛材料与内部技术报告。

---

## 文件清单

```
MSOSA-remote-probe-2026-10-20/
├── 00-README.md                      ← 你正在看的
├── 01-AGENT-TASK.md                  ← 给 agent 的任务书（也可当你的操作手册）
├── 02-REPORT.md                      ← 填这个回报
├── 03-MESSAGE-TO-CLASSMATE.txt       ← 发件方写好的微信消息模板（对面可忽略）
├── inputs/
│   ├── golden-coaxial-power-chain.sysml   ← 正式待导入文本（34 个元素 / 2 条 connect）
│   ├── 00-smoke-minimal.sysml             ← 最小冒烟文件（先证明导入通道能用）
│   └── sha256sums.txt
├── ledgers/
│   ├── elements.csv                  ← 34 个元素的核对账本
│   └── relations.csv                 ← 20 条追溯关系（只有 2 条在文本里）
└── reference/
    ├── 01-background.md              ← 背景：我们哪台机器试过什么、版本线索
    └── 02-expected-and-criteria.md   ← 期望值、三态判定、高风险构造清单
```

---

## 校验和（解压后建议核对一次）

PowerShell：

```powershell
Get-FileHash inputs\golden-coaxial-power-chain.sysml -Algorithm SHA256
Get-FileHash inputs\00-smoke-minimal.sysml -Algorithm SHA256
```

| 文件 | sha256 |
| --- | --- |
| `golden-coaxial-power-chain.sysml` | `bb64cc2cbfdc5f5667049a76f6b57c4925a6ed29b2344c94d09d70e9ac6f6129` |
| `00-smoke-minimal.sysml` | `32b1a4954fed191f7aebede6df8abb4b10084f0af9b722dd7e5888f9140ec515` |

> 如果打开 md 文件看到乱码：文件是 UTF-8，用 VS Code / 记事本（Win10 以上默认 UTF-8）打开即可；实在不行告诉我，我换编码重发。

---

## 回传什么（清单）

1. `02-REPORT.md`（填好，所有 `< >` 都替换掉）
2. `MSOSA-remote-evidence-<你的名字缩写>-<日期时间>.zip`，里面至少要有：
   - `fingerprint/`：About、License、Plugin Manager、File 菜单、Containment 树 的截图
   - `logs/`：`msosa.log`（或你找到的那个日志）整份
   - `validate/`：校验面板截图（若有导出结果也放这）
   - `export/`：导出的 `.sysml`（若走到这一步）
3. 报告最后写一行这个 zip 的 sha256

---

## 我们拿到之后会做什么

把结果写进 `docs/verification/msosa/` 的证据链，结论只写三态之一（A/B/C），**不会**写成"通过了 MSOSA 认证"这种话；也不会公开你的机器信息（报告里用"同学机器"代称，截图若要引用会先问过你）。
