# integrations — DSH 侧集成

本目录放**不属于 MCP 工具链、但属于本产品交付面**的集成代码。目前只有一项：

```
integrations/
└── dsh-sysml-viz/     # DSH 右栏「模型视图」插件 bundle（v0.1.4）
```

## dsh-sysml-viz 是什么

一个可安装的 DSH **bundle**（Host 半边 + Client 半边，零外部 npm 依赖），把 IR 做成右栏 tab：

- **模型树**：按 part 组合树 / 按类别两种分组；
- **图**：结构（BDD）、互联（IBD）、需求追溯、状态机，有属性/约束时再出参数视图
  （优先调用本仓库 `mcp-server/tools/graph.py`，不可用时退回插件内置 JS 投影）；
- **状态行**：`rev sha8` / `N 元素 · R 关系` / `建模中` / `模型更新 · Ns 前`（后者是模型文件
  mtime 年龄，不是网络耗时）；
- **建模过程面板**：每次 IR **语义内容**变化记一步，写 `<workspace>/.sysml-viz/history/`，
  可按步骤着色生成「建模全过程」SVG（调 `mcp-server/tools/timeline.py`，即第 9 个工具
  `export_timeline` 的同一实现）；
- **只读诊断**：`/api/sysml-viz/diagnostics`（`?mcpSelfTest=1` 会从 Host 拉起 MCP server 做
  stdio 握手，排查 `mcp__sysml-agent__*` 缺失）。

它**只读**工作区：不写 IR、不改模型文件；过程记录写在 `.sysml-viz/` 下的独立快照目录里。

## 与仓库其他部分的关系

| | Python 工具链（`mcp-server/`） | 本插件（`integrations/dsh-sysml-viz/`） |
| --- | --- | --- |
| 角色 | 唯一写模型的通道（IR 是唯一事实源） | 只读展示层（树/图/状态/过程），不参与建模决策 |
| 依赖 | 纯标准库 | 纯 `node:` 内置模块 |
| 测试 | `./tests/run_tests.sh`（606 用例；**不覆盖**插件） | `node integrations/dsh-sysml-viz/smoke-test.mjs`（33 项，自带 mock ctx，不装插件、不改 profile） |
| 数据契约 | `docs/图投影契约.md`、`docs/建模过程记录契约.md` | 同一份契约的消费方 |

## 两种摆放方式（代码都能自己找到仓库）

插件通过 `agentRootCandidates()`（`index.js`）从**自身位置**向上定位 agent 仓库根
（判定条件：存在 `mcp-server/run_server.py`），不依赖写死的绝对路径：

1. **现场安装**：插件在 `<workspace>/proposal/q2-plugin`，仓库在 `<workspace>/sysml-modeling-agent`
   （同级兜底）；
2. **仓库内副本**（本目录）：插件在 `<repo>/integrations/dsh-sysml-viz`，仓库就是往上两级。

`graph.py` / `timeline.py` 的解释器同样优先取仓库自带 `.venv/bin/python`，再退回 `python3`。
`probeMcpServer()` 与 `smoke-test.mjs` 用同一套探测逻辑，因此**换机器/换目录不用改代码**；
仍可用环境变量覆盖：`SYSML_AGENT_ROOT` / `SYSML_AGENT_PY` / `SYSML_AGENT_SERVER` /
`SYSML_AGENT_CWD` / `SYSML_VIZ_*`。

> `cordis.patch.yml`、`preset-sysml-v2.patch.yml` 里的默认路径仍是**某台机器的绝对值**
> （`!!js process.env.… ?? '<绝对路径>'`），这是 DSH patch 表达式的兜底写法；换机器时
> 用对应环境变量覆盖，或按 `install.md` 重新生成。

## 安装与自检

```bash
# 自检（不需要装插件，不需要 DSH 运行）
node integrations/dsh-sysml-viz/smoke-test.mjs
#   期望：✓ smoke-test 全部通过：33 项检查
#   没有 .venv 的机器上会跳过一条 MCP 自检，显示 32 项

# 安装（详见 integrations/dsh-sysml-viz/install.md）
dsh plugin --profile <profile> add "$(pwd)/integrations/dsh-sysml-viz"
```

`plugins` 是**进程内模块**：改完必须完全退出并重启 DSH（`Cmd+Q`）才生效，
仅改文件或 `touch` 不会热更新。

## 诚实边界

- 插件不是建模器：所有模型改动仍必须经 MCP 工具写 IR，插件只是把 IR 画出来；
- 过程记录是**拉取式**采集（只有右栏 tab 在轮询时才会记到步骤），不保证与对话轮次一一对应；
- 会话归属是启发式（按 tab 的 `?sessionId=` 短 id），不是「对话第几轮」的事实；
- 「建模全过程」图是**本仓库过程记录的自述**，不能替代 MSOSA/工具的模型历史；
- smoke-test 全绿只说明**只读路径**在当前机器上自洽，不等于 DSH 里已正确挂载。

## 与现场安装源的关系

本目录是**版本化副本**；本机 DSH profile 目前 `link:` 到另一个路径（`proposal/q2-plugin`）。
两处代码应保持一致，修改时请同时更新，或后续改为软链接只留一份。
