---
id: mem-20261017-0011
kind: provenance
status: superseded
superseded_by: mem-20261020-0005
title: （历史）二期完成时 MCP 工具是 8 个
created: 2026-10-17T18:00:00+08:00
author: dsh-lead/deepseek-v3/session-phase2
scope: [mcp-server/**, "README.md"]
tags: [mcp, tools, history]
aliases: [历史工具数]
confidence: high
review_after: 2027-04-17
evidence:
  - commit:38dbd9e
---

## 内容

（历史事实）二期发布时工具数是 **8 个**：validate / generate / query / verify / patch / trace /
parse / export。这个数字当时写进了 README、`INSTRUCTIONS` 与测试断言。

## 为什么

二期发布 `38dbd9e` 时确实只有 8 个工具；2026-10-20 加 `export_timeline` 后变成 9 个，因此本记录被
`mem-20261020-0005` 取代（append-only：不改旧内容，只把状态改成 superseded）。

## 用法

- 只作版本考古；现状口径见 `mem-20261020-0005`；
- 不要引用本条数字做现状判断。
