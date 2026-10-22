<!-- 记忆库 PR。代码 PR 请用默认模板；本模板只在改 memory/** 时使用。 -->

## 这条记忆是什么

- 记录 id：`mem-YYYYMMDD-NNNN`
- kind：decision / gotcha / convention / glossary / session-digest / provenance
- confidence：low / medium / high
- scope：<这些路径变了才需要想起它>
- supersedes：<取代了哪条旧记忆 / 无>

## 为什么现在要记（三问）

1. **跨文件/跨轮次**才成立的吗？
2. **非显然**吗（不看这条会不会重复踩坑）？
3. **会改变下一个动作**吗？

> 三问有一个答"否"，说明它更适合进代码注释 / docs / tests，不适合进记忆库。

## 证据

- [ ] `evidence` 里的 `file:` 引用都存在（`memory.py validate` 会查）
- [ ] `commit:` / `session:` 可回溯
- [ ] 易陈腐的记录加了 `check:` 断言（`contains:` / `path_exists:`）

## 写入分级（勾一个）

- [ ] **T0 自动**：session-digest / 纯新增 gotcha，CI 绿即可由 bot 合并
- [ ] **T1 人审**：decision / convention / 任何 supersedes（会改旧记录状态）
- [ ] **T2 人写**：改了 `memory/core/**`（红线/常驻记忆，不接受 agent 直提）

## 自检

- [ ] `python memory/tools/memory.py --root . validate` 通过
- [ ] `python memory/tools/memory.py --root . check` 通过
- [ ] 先检索过一遍，确认没有重复记录（按 id / title / tags）
- [ ] 没有把"过程日志 / 原始工具输出 / 密钥 / 临时路径"写进来
