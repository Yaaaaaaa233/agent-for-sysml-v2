# 录屏前检查单（人用）· 模型树生长实录

> 配套：[`PROMPT.md`](PROMPT.md)（粘给 agent 的任务书）。预计总时长 **8–15 分钟**：阶段 A 1 分钟 + 12 轮 × 20–40 秒 + 验收 1 分钟。
> 原则：**先把环境摆好再开录**；agent 每轮会停，节奏由你控制。

---

## 0. 录前 3 分钟：状态确认（都用只读命令，不动模型）

| 检查 | 命令 / 动作 | 期望 |
| --- | --- | --- |
| 右栏「模型视图」能打开 | 点右栏图标 → 模型树 | 显示 34 元素（当前标杆等价模型） |
| 当前模型路径 | `python3 -c "import json;d=json.load(open('.sysml-viz/history/index.json'));print(d['modelPath'])"` | `.../model-output/q2-demo/q2-demo.ir.json` |
| 模型 sha 是标杆等价 | `shasum -a 256 model-output/q2-demo/q2-demo.ir.json` | `adae5c61…` |
| 历史现状 | `ls .sysml-viz/history \| wc -l` | 13 左右（step 快照 + index.json + timeline.svg；具体不重要，A3 会清空） |
| 只有一份工作模型 | `ls model-output/q2-demo/*.ir.json` | 只有 `q2-demo.ir.json`（`_evidence/`、`_verification/` 不影响） |
| 过程面板 | 右栏「建模过程」 | 能看到 11 步（含旧的 Q2 实录步骤，等下会被清掉） |

> 若模型 sha 不是 `adae5c61…`：说明工作区模型已不是标杆等价，先别录——先把它恢复成 `sysml-modeling-agent/examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json` 的内容再开始。

---

## 1. 摆窗口（录出来的画面）

- [ ] 分辨率固定（建议 1920×1080 或窗口 1440 宽），**录前不要再改窗口大小**；
- [ ] 左：对话区（能看清 agent 每轮那一行状态 + 你打的「继续」）；
- [ ] 右：模型视图，**模型树面板占满右栏高度**；`CoaxialOctoRotor` 包节点默认**展开**；
- [ ] 如果右栏有「结构图 / IBD / 需求 / 状态」页签，留在**模型树**页（树是主角）；
- [ ] 关掉无关标签、通知、微信弹窗；系统「勿扰模式」打开；
- [ ] 字号调大到录屏能看清（DSH 设置里调界面缩放，或系统缩放）。

---

## 2. 开录顺序（建议）

1. **先开始录屏**（QuickTime / 系统录屏，选「录制所选窗口」或整屏）；
2. 在「SysML v2 建模」preset 里**新建会话**（不要复用旧会话的上下文）；
3. 把 [`PROMPT.md`](PROMPT.md) **全文**粘贴发送；
4. agent 做**阶段 A**（备份 → 1 元素基线 → 清空记录）：此时右侧树应"缩"成 1 个需求节点，过程面板只剩 1 步；
5. 之后每轮：agent 加完元素 → 右栏**约 2 秒内**自动刷新 → 树长出一截 → 你确认画面后打「**继续**」；
6. 第 12 轮（T12）结束后打「**验收**」，等它跑完验收汇总；
7. **停止录制前**让画面停在：完整 34 元素树 + 过程面板 13 步 + 验收汇总那一行。

> 想加口播/字幕：每轮的任务书里都写了一句「这一轮在讲什么」（T1–T12），可以直接照着念。

---

## 3. 每轮该看到的数字（对不上就暂停）

| 轮 | 元素 | 关系 | warnings | 树里冒出来的东西 |
| --- | ---: | ---: | ---: | --- |
| 基线 | 1 | 0 | 2 | `MissionEndurance` 一条需求 |
| T1 | 3 | 3 | 6 | 巡航续航、转速比区间两条需求 |
| T2 | 4 | 4 | 8 | 功率预算需求 |
| T3 | 6 | 5 | 10 | 整机 + 功率链（两个 part def） |
| T4 | 11 | 5 | 20 | 电池/电调/电机/上桨/下桨 五个零件 |
| T5 | 13 | 6 | 18 | 整机实例、功率链实例 |
| T6 | 19 | 11 | 8 | 六份部件实例（挂在功率链下） |
| T7 | 21 | 11 | 8 | 两条连接（batteryToEsc / upperMotorToPropeller） |
| T8 | 27 | 11 | 8 | 6 个参数（巡航速度、转速比、容量、可用系数、巡航功率、续航时间） |
| T9 | 31 | 11 | 8 | 续航约束 + 3 个效率参数 |
| T10 | 33 | 16 | 4 | 两个动作定义 |
| T11 | 34 | 16 | 4 | 飞行模式状态机 |
| T12 | 34 | **20** | **0** | 关系补齐（树不变，过程面板加一步） |

> agent 每轮会贴一行 `check_turn.py` 输出（`PASS elements=… relations=… errors=0 warnings=… text_sha=…`）。对不上就暂停，不要说"差不多"。

---

## 4. 常见故障（录到一半出问题怎么办）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 树不刷新 | 轮询 2 秒；或写到了别的文件 | 等 3 秒；让 agent 确认写的是 `model-output/q2-demo/q2-demo.ir.json` |
| 树显示的还是 34 元素 | 模型文件没被替换/A3 没执行 | 让 agent 重做 A2+A3（先备份再覆盖） |
| 过程面板还是旧的 9 步 | `rm -rf .sysml-viz/history` 没执行 | 让 agent 重试；或手动点「清空记录」 |
| 树跳到另一个模型（比如 examples 的） | 工作模型文件被临时删掉/改名 | 立刻把基线写回原路径；以后不要动那个文件 |
| agent 想一口气跑完 12 轮 | 任务书 §六.5 没被遵守 | 打断它，说「停，按轮次等我说继续」 |
| 某轮 validate 报 `E-REL-TARGET-DANGLING` | 加了指向未出现元素的关系 | 让 agent 按任务书 §四 的规则把该关系留到 T12 |
| 录到 T4 发现 warning 变成 20 | 正常（零件定义还没实例） | 不用管，只看 errors=0 |
| `edit` 报 old_string 找不到/不唯一 | 文件末尾锚点变了或空白不一致 | 让 agent `read` 末尾 15 行按实际内容调整锚点；**别让它整份重写** |
| `check_turn.py` 报 JSON parse error | 上一轮追加时逗号/括号错了 | 让 agent 读出错位置附近修正（可以 `--json` 看校验，但 parse 错误要先修文本） |
| `check_turn.py` 报 elements/relations 数不符 | 多加了或漏加了元素 | 让 agent 对照本轮清单修正；修不了就停下重来这一轮 |

---

## 5. 录完存哪（建议）

- 录屏文件：`docs/demo/record-tree-growth/recording-<YYYYMMDD-HHMM>.mov`（或你惯用位置，别删除）；
- 若想让 agent 留档：验收时说「留档」，它会写 `RUN-LOG.md`（每轮数字 + 终态 sha + 官方校验结果）；
- 最终证据（固定在）：
  - 模型：`model-output/q2-demo/q2-demo.ir.json`（34/20）
  - 生成文本 sha：`bb64cc2c…`（与 `docs/verification/local/golden-2026-10-20/model.sysml` 一致）
  - 官方解析器 + 追溯证据：`docs/verification/local/record-2026-10-22/`（`report.json`、`model.sysml`、`03-verify.json`、`04-traceability.json`）
  - 过程图：`.sysml-viz/history/timeline.svg`
  - 旧模型与旧历史备份：`model-output/q2-demo/_evidence/recording-2026-10-22/before/`
