---
id: mem-20261022-0015
kind: gotcha
status: active
slug: memory-ci-path-filter
title: CI required check 不能配 paths 过滤；bot 用 GITHUB_TOKEN 开的 PR 不触发 workflow
created: 2026-10-22T23:14:30+08:00
author: dsh-lead/deepseek-v4.1-flash/session-current
scope: [.github/workflows/**, memory/**]
tags: [ci, github-actions, gotcha]
aliases: [required check, paths 过滤, 卡住, auto-merge, 不触发]
confidence: high
review_after: 2027-04-22
evidence:
  - file:.github/workflows/memory.yml
  - file:AGENTS.md
check:
  - contains:.github/workflows/memory.yml::memory-validate
---

## 内容

两个会让"链路看起来搭好、实际卡死"的 GitHub 机制坑：

1. **required check 不能配 `paths:` 过滤**：workflow 被 paths 跳过时，它的 required check 会永远停在
   "Expected — Waiting for status"，把不相关的 PR 卡死。memory workflow 因此**不做 paths 过滤**（秒级）。
2. **用 Actions 自带的 `GITHUB_TOKEN` 开 PR 不会触发其他 workflow**（防递归规则）：required check 永远
   Expected，`--auto` 合并卡住。要么用 App/PAT 开 PR，要么 T0 改走 bot 直推。

## 为什么

2026-10-22 搭记忆库链路时逐条验证过；两条都是"CI 绿灯但合并按钮不亮"的经典故障，排查成本高。

## 用法

- 新 workflow 想省时间：不要加 paths，改成 always-run 的 gate job；
- 自动开 PR 的 bot：用 App/PAT token，别用默认 GITHUB_TOKEN；
- 遇到"check 一直 Expected"：先看该 workflow 是否被 paths/条件跳过。
