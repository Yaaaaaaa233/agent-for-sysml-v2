---
id: mem-20261019-0003
kind: gotcha
status: active
title: 插件是进程内模块，改完必须 Cmd+Q 重启 DSH 才生效
created: 2026-10-19T23:40:00+08:00
author: dsh-lead/deepseek-v4.1-flash/session-a89d8bff
scope: [integrations/dsh-sysml-viz/**]
tags: [dsh, plugin, restart, gotcha]
aliases: [热更新, 不生效, reload, 旧版本, 插件没更新, 界面变化, 界面看不到, 落盘没生效]
confidence: high
review_after: 2027-04-19
evidence:
  - file:integrations/dsh-sysml-viz/install.md
  - session:a89d8bff
check:
  - contains:integrations/dsh-sysml-viz/install.md::重启 DSH
---

## 内容

DSH 插件的 host/client 是**进程内模块**：改 `index.js`/`client.js` 后，改文件、`touch`、甚至动
`cordis.patch.yml` 都不会热更新。必须**完全退出 DSH（Cmd+Q）再启动**，否则 `/api/sysml-viz/health`
还是旧版本号、新路由 404。

## 为什么

2026-10-19 把插件 0.1.3 改到 0.1.4 后，health 一直回 0.1.3、新路由缺失，排查很久才确认是模块未重载。
浏览器侧 JS 模块代也只在重启后重新加载；`install.md` 与 `verify-prompt.md` 都写了这条。

## 用法

- 改插件后第一步：让用户 Cmd+Q 重启，再 `curl /api/sysml-viz/health` 核对 version 与 routes；
- 不要把"不热更新"当插件 bug 报；
- 验收脚本先核版本，再断言新行为。
