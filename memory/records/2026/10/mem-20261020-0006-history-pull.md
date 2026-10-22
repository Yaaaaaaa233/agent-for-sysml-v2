---
id: mem-20261020-0006
kind: gotcha
status: active
title: 过程记录是拉取式采集；"5 步过程"不等于"5 轮对话"
created: 2026-10-20T00:12:00+08:00
author: dsh-lead/deepseek-v4.1-flash/session-a89d8bff
scope: [integrations/dsh-sysml-viz/**, mcp-server/tools/timeline.py, docs/建模过程记录契约.md]
tags: [history, timeline, honesty]
aliases: [过程图, 步骤少, 缺失步骤, 漏记]
confidence: high
review_after: 2027-04-20
evidence:
  - file:docs/建模过程记录契约.md
  - file:mcp-server/tools/timeline.py
check:
  - contains:docs/建模过程记录契约.md::只有模型视图 tab 在轮询
  - contains:docs/建模过程记录契约.md::日志重建
---

## 内容

右栏「建模过程」是**拉取式**采集：只有模型视图 tab 在轮询 `/api/sysml-viz/model` 时才归档一步；
没开着 tab 期间的变化不会实时记到。从会话日志事后重建的步骤标 `source:"session-log"`，UI 标
「日志重建」。所以"过程面板 5 步"不等于"对话 5 轮"。

## 为什么

`docs/建模过程记录契约.md` 写明 pull-based 与 `session-log` 标记；本机真实历史就是从会话日志重建的
（基线 + 4 轮 = 5 步）。对外讲"全过程可追溯"必须带这个前提，否则属于过度承诺。

## 用法

- 演示"实时生长"：先开着 tab 再让 agent 改模型；
- 解释"少了步骤"：先查 tab 是否开着、轮询是否中断；
- 引用过程图时标注"实时 / 日志重建"。
