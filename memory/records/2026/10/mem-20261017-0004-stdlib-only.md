---
id: mem-20261017-0004
kind: convention
status: active
title: 核心逻辑零第三方依赖，新增工具默认纯标准库
created: 2026-10-17T14:30:00+08:00
author: dsh-lead/deepseek-v3/session-phase1
scope: [mcp-server/**, tests/**, "install.sh"]
tags: [dependencies, stdlib, convention]
aliases: [依赖, pip, 第三方库, 环境准备]
confidence: high
review_after: 2027-04-17
evidence:
  - file:README.md
  - file:mcp-server/requirements.txt
check:
  - contains:README.md::纯标准库
  - path_exists:mcp-server/requirements.txt
---

## 内容

本仓库核心逻辑**零第三方依赖**：`mcp-server/` 与 `tests/` 只用标准库；`requirements.txt` 里全是可选件
（`jsonschema`、官方解析器相关），一个不装也能完整工作。新增工具/脚本不得引入新依赖。

## 为什么

README §2「依赖策略（重要）」写明纯标准库即可完整工作，Windows 部署手册"一条命令跑起来"也依赖这条。
二期加 `graph.py`/`timeline.py` 时同样只用标准库；这是可复现性与"评委能自己跑"的前提。

## 用法

- 新增工具前先问能不能 stdlib；不能就做成可选依赖 + 明确降级行为（如 `schemaLayer: unavailable`）；
- 测试里别 `import pyyaml` 之类，frontmatter 用自写子集解析；
- 只有 `--official` 路径允许依赖 `.venv` 里的包。
