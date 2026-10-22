---
id: mem-20261020-0001
kind: decision
status: active
title: MSOSA 指 Magic Systems of Systems Architect；CE 版没有文本导入/导出入口
created: 2026-10-20T10:45:00+08:00
author: dsh-lead/deepseek-v4.1-flash/session-a89d8bff
scope: [docs/verification/**, "README.md"]
tags: [msosa, catia-magic, verification, community-edition]
aliases: [华望, Magic SoSA, MagicDraw, CATIA Magic, 独立实现]
confidence: high
review_after: 2027-04-20
evidence:
  - file:docs/verification/msosa/runs/2026-10-20-import/BLOCKER.md
  - file:docs/verification/msosa/README.md
  - external:智能体/Magic Systems of Systems Architect UserManual.pdf
check:
  - contains:docs/verification/msosa/README.md::Import From
---

## 内容

MSOSA = **Magic Systems of Systems Architect**（CATIA Magic 的 SysML v2 版），不是"华望"。本机装的是
2026x Refresh1 Community Seat：`File` 菜单**没有 `Import From`**，`Export To`/`Convert To` 灰显，
`Open Project` 不接受 `.sysml`，`Textual Editor` 无窗口。所以"把冻结文本导进 MSOSA 跑套件"在本机
CE 上做不到，只能换构建（商业版 / 其他独立实现如 SysON）或换验证方式。

## 为什么

2026-10-19 我用日志确认了安装与插件启动（`Plugin started: SysML v2`），据此写过"只差项目级导入/校验"；
2026-10-20 实际操作打脸：CE 没有文本导入入口（BLOCKER.md 的 6 条现场事实 + 截图）。命名此前也误记为
"华望"，已纠正。结论必须按"可导入 / 无入口 / 有入口但失败"三态说，不能笼统说"支持"。

## 用法

- 有人问"MSOSA 能不能验证模型"：先问是哪一态；本机是"无入口"；
- 不要把"已安装 + 插件启动"说成"能做独立验证"；
- 写工具名一律用全名，首次出现带 CATIA Magic。
