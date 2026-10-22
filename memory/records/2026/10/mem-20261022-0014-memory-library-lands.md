---
id: mem-20261022-0014
kind: session-digest
status: active
slug: memory-library-lands
title: 2026-10-22：记忆库链路入仓（同仓 + 周度 review）
created: 2026-10-22T23:12:12+08:00
author: dsh-lead/deepseek-v4.1-flash/session-current
scope: [memory/**, tests/test_memory.py, .github/**]
tags: [digest, memory, ci]
aliases: [记忆库, memory, 周度 review]
confidence: medium
review_after: 2026-11-22
evidence:
  - file:memory/README.md
  - file:.github/workflows/memory.yml
check:
  - path_exists:memory/tools/memory.py
  - contains:AGENTS.md::项目记忆库
---

## 内容

本轮把记忆库链路接进仓库：`memory/`（13 条真实记录 + `memory.py` + 三套检索评测）、`AGENTS.md`
（检索协议，DSH 自动注入）、`.github/workflows/{tests,memory}.yml`（全量用例 + 记忆校验/周度复核）、
`.github/CODEOWNERS`（按路径分级）、`.github/PULL_REQUEST_TEMPLATE/memory.md`；测试从 606 增到 632。

## 为什么

光有库不会自动生效：必须接上"会话开头注入 core、动手前 inject、写完 propose→drain→批 PR、CI 校验、
周度 rot issue"这条回路，否则又变成一个没人维护的目录。

## 用法

- 开工前：`python3 memory/tools/memory.py --root . inject "<任务>" --scope <路径>`；
- 有新结论：`propose --write` → 会话结束 `drain` → 批 PR（一条一 commit）；
- 每周：看 rot issue；T1 记录批量 review。
