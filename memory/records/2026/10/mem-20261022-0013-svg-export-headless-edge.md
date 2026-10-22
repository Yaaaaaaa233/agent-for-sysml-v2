---
id: mem-20261022-0013
kind: gotcha
status: active
slug: svg-export-headless-edge
title: 过程图转 PNG 用无头 Edge，qlmanage 在沙箱里会被拦
created: 2026-10-22T19:05:00+08:00
author: dsh-lead/deepseek-v4.1-flash/session-current
scope: [integrations/dsh-sysml-viz/**, examples/timeline-demo/**]
tags: [svg, png, sandbox, gotcha]
aliases: [截图, 图片导出, png, qlmanage]
confidence: medium
review_after: 2027-04-22
evidence:
  - session:current
  - file:examples/timeline-demo/timeline.svg
---

## 内容

把 `timeline.svg` 转成 PNG 做交付预览时，`qlmanage -t` 在本机沙箱下会失败（`sandbox initialization
failed`）；可用的是无头浏览器：

```bash
"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" --headless=new --disable-gpu \
  --no-sandbox --hide-scrollbars --user-data-dir=/tmp/edge-profile \
  --screenshot=/tmp/out.png --window-size=1314,700 "file:///path/to/timeline.svg"
```

## 为什么

2026-10-19 生成「建模全过程」演示图时踩到：qlmanage 需要沙箱外权限，`sips` 也不吃 SVG；无头浏览器
能直接按窗口尺寸截图，且不联网。

## 用法

- SVG→PNG 一律先试无头浏览器；
- 截图尺寸按 SVG 的 width/height 设，别用默认 800×600；
- 产物别提交进仓库，只作为对话里的预览附件。
