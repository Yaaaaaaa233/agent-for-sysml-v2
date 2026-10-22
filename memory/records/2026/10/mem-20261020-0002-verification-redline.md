---
id: mem-20261020-0002
kind: convention
status: active
title: 写验证结论时"未执行"≠"0 诊断"，阻断不得写成"验证通过"
created: 2026-10-20T11:10:00+08:00
author: dsh-lead/deepseek-v4.1-flash/session-a89d8bff
scope: [docs/verification/**]
tags: [verification, evidence, red-line]
aliases: [验证通过, 空表, 误报, 没跑]
confidence: high
review_after: 2027-04-20
evidence:
  - file:docs/verification/msosa/runs/2026-10-20-validate/validation-results.md
  - file:docs/verification/msosa/runs/2026-10-20-import/BLOCKER.md
check:
  - contains:docs/verification/msosa/runs/2026-10-20-validate/validation-results.md::0 诊断
---

## 内容

验证报告的硬规则：**没跑 = 没跑**。上游阻断导致 Validate 未执行时，必须写"未执行（上游阻断）"，
不能把"没有运行"写成"0 诊断"，更不能写成"验证通过"。结论句必须带范围限定。

## 为什么

`validation-results.md` 的空表最容易被人和 agent 读成"没问题所以是 0 诊断"。BLOCKER.md 已把三态
判据固定，但结论表只留空行仍然会被下游误读；2026-10-20 修文档时专门在表头加了"执行状态"。

## 用法

- 任何"证据包/验证结论"类 PR，review 第一步看执行状态字段；
- 只有 Validation Results 面板的**抄录原文**才算证据；
- 模板：`在 <构建> 上 <操作> <执行/未执行>，得到 <计数>；本结论只覆盖 <范围>，不含 <未覆盖>`。
