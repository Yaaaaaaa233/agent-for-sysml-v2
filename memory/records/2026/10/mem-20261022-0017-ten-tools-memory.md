---
id: mem-20261022-0017
kind: gotcha
status: active
slug: ten-tools-memory
title: 工具数 9→10：新增 memory 工具；同步面仍是 5 处
created: 2026-10-22T23:47:58+08:00
author: dsh-lead/deepseek-v4.1-flash/session-current
scope: [mcp-server/run_server.py, tests/test_server.py, README.md, integrations/dsh-sysml-viz/**]
tags: [mcp, tools, memory, sync]
aliases: [工具数量, 工具表, 新增工具, memory 工具]
confidence: high
review_after: 2027-04-22
supersedes: [mem-20261020-0005]
evidence:
  - file:mcp-server/run_server.py
  - file:tests/test_server.py
  - file:README.md
check:
  - contains:mcp-server/run_server.py::E-MEMORY-UNAVAILABLE
  - contains:README.md::十个工具
  - contains:integrations/dsh-sysml-viz/preset-sysml-v2.patch.yml::memory(op=search
  - path_exists:memory/tools/memory.py
---

## 内容

MCP 工具从 9 个变 **10 个**：新增 `memory`（`op=search` 只读检索项目记忆；`op=propose` 只把候选写进
`memory/.spool/`，不联网、不改 IR、不自动提交）。**同步面仍是 5 处**：① `run_server.py` 的
`TOOL_SPECS` / `dispatch` / FastMCP 注册 / `INSTRUCTIONS`；② `tests/test_server.py` 的数量与名单断言；
③ `README.md` §4 工具表与"十个工具"；④ `INSTRUCTIONS` 调用顺序；⑤ 插件 preset 提示词里的口径。

## 为什么

2026-10-22 加 `memory` 时实测：只改 `run_server.py`，`tests/test_server.py` 的"9 个工具"断言立刻红；
`--list-tools` 的输出顺序也被测试逐项钉住。工具数是契约级数字，散落在文档、测试与提示词里，最容易漏。

## 用法

- 工具增删 PR：先 `python3 mcp-server/run_server.py --list-tools` 数一遍，再全仓 grep 旧数字（"九个/9 个"）；
- README 里写"当前 N 个"，别写永久声明；
- 插件 preset 与 `INSTRUCTIONS` 的口径与 server 端同 PR 改。
