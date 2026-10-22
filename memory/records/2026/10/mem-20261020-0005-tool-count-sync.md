---
id: mem-20261020-0005
kind: gotcha
status: active
title: 工具数/名单改动要同步 5 处；当前 9 个（含 export_timeline）
created: 2026-10-20T00:10:00+08:00
author: dsh-lead/deepseek-v4.1-flash/session-a89d8bff
scope: [mcp-server/run_server.py, tests/test_server.py, "README.md", integrations/dsh-sysml-viz/**]
tags: [mcp, tools, sync, gotcha]
aliases: [工具数量, 工具表, 新增工具, 删工具]
confidence: high
review_after: 2027-04-20
supersedes: [mem-20261017-0011]
evidence:
  - file:mcp-server/run_server.py
  - file:tests/test_server.py
  - file:README.md
  - commit:f4c2750
check:
  - path_exists:mcp-server/tools/timeline.py
  - contains:mcp-server/run_server.py::export_timeline
  - contains:README.md::九个工具
---

## 内容

改 MCP 工具数/名单时，**5 处必须同一 PR 改齐**：① `run_server.py` 的 `TOOL_SPECS`/dispatch/FastMCP
注册；② `tests/test_server.py` 的数量断言；③ `README.md` §4 工具表与"九个工具"字样；④ `INSTRUCTIONS`
调用顺序；⑤ 插件 preset 提示词里的工具数口径。当前 **9 个**，第 9 个是 `export_timeline`。

## 为什么

2026-10-20 加 `export_timeline` 时漏改 `test_server.py` 的 8 工具断言直接红灯；README 里 8/9 混写也出现
过；工具数是"契约级"数字，散落在文档、测试与提示词里，最容易漏。

## 用法

- 工具增删 PR：先 `--list-tools` 数一遍，再全仓 grep 旧数字；
- 文档里写成"当前 N 个"，别写永久声明；
- 插件/预设里的口径与 server 端同 PR 改。
