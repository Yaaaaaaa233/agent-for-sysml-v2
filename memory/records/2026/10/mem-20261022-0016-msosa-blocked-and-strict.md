---
id: mem-20261022-0016
kind: session-digest
status: active
slug: msosa-blocked-and-strict
title: 2026-10-22 晚：MSOSA 终局 BLOCKED 入库、插件 v0.1.7、记忆库开 strict
created: 2026-10-22T23:45:50+08:00
author: dsh-lead/deepseek-v4.1-flash/session-current
scope: ["**"]
tags: [digest, msosa, plugin, memory]
aliases: [终局, 阻断, v0.1.7, strict]
confidence: medium
review_after: 2026-11-22
evidence:
  - file:docs/verification/msosa/runs/2026-10-20-import/BLOCKER.md
  - file:memory/README.md
  - commit:8e54a32
  - commit:0f50018
check:
  - path_exists:docs/verification/msosa/handoff/README.md
  - contains:.github/workflows/memory.yml::strict-tracked
---

## 内容

本轮入库三件事 + 一处收紧：

- **插件 v0.1.7**（`0f50018`）：节点文字按真实字号/全角宽度换行与截断，smoke 39/39；
- **MSOSA 独立验证终局 BLOCKED**（`8e54a32`）：CE 构建无 `File > Import From`、Textual Editor 无窗口，
  BLOCKER + 跨机 handoff + 9 张截图 + 实验记录全部入库；后续等同学机器回传 A/B/C；
- **记录树生长演示素材**（`5a1b056`）：PROMPT / CHECKLIST / check_turn；
- 记忆库把 MSOSA 证据从 `external:` 改回 `file:`，CI 打开 `--strict-tracked`（未入库证据从警告变错误）。

## 为什么

MSOSA 这条腿的结论必须能被复查（截图 + BLOCKER + 冻结输入 sha256），所以证据必须进仓库；
一旦证据全入库，"证据未入库"就该是硬错误而不是警告，否则 strict 永远不开、链路形同虚设。

## 用法

- 引用 MSOSA 结论：先读 `BLOCKER.md`，只写"CE 无导入入口 → 本机无法完成独立验证"；
- 跨机结果回传前，不要写"MSOSA 验证通过"；
- 下一步（M2）：加 MCP `memory` 工具（search/propose），让 agent 不用敲命令行也能检索/写入。
