---
id: mem-20261020-0008
kind: glossary
status: active
title: 验证分层 L0–L5 的口径，以及本仓库当前落地到 L2
created: 2026-10-20T11:30:00+08:00
author: dsh-lead/deepseek-v4.1-flash/session-a89d8bff
scope: [docs/**, "README.md"]
tags: [verification, glossary, layers]
aliases: [验证层级, L4, L5, 分层, 几层, 做到第几层, 层号]
confidence: high
review_after: 2027-04-20
evidence:
  - file:docs/verification/local/README.md
  - external:proposal/新功能可行性方案.md
check:
  - contains:docs/verification/local/README.md::L0 结构
---

## 内容

验证分层口径：**L0** 结构（IR 必填/枚举/引用）→ **L1** 名称与引用（文本回验 / 官方解析器语法）→
**L2** 规范符合性（官方 validator / 第三方套件）→ **L3** 模型质量（覆盖/孤立/命名/粒度）→
**L4** 领域与参数正确性（约束求值）→ **L5** 人工评审。本仓库当前落地的是 **L0/L1/L2 的本地部分**
（`docs/verification/local/`）；MSOSA 那一腿因 CE 无导入入口 BLOCKED；L3/L4/L5 属待补能力。

## 为什么

`proposal/新功能可行性方案.md` §1 定义了六层与各自证据形式；仓库内 `docs/verification/local/README.md`
只写到 L0/L1/L2。把"未落地"说成"没验证"或反之，都会让结论失真，也是评审最容易被追问的点。

## 用法

- 说"验证到哪一层"必须带层号 + 证据文件路径；
- 新增验证能力时更新本条并加 check 断言；
- 回答"模型准不准"按层回答，不给整体背书。
