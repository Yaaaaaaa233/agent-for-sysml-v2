# 安装与配置 —— dsh-sysml-viz（Q2 右栏「模型视图」bundle）

> 本目录是可安装的 DSH bundle：`index.js`（host：HTTP 路由 + IR 读取 + 图投影 + 建模过程记录）、
> `client.js`（右栏 tab：模型树 + 图 + 建模中状态 + 过程面板）、`cordis.patch.yml`（插入 host/client 行）、
> `preset-sysml-v2.patch.yml`（Agent 预设）、`locale/`、`icon.svg`。
> 本机（2026-10-22）桌面端已安装并实测到 v0.1.7；host/client 改动需重启应用后生效，按第 7 节自查。

## 1. 前提

- DSH Desktop 或 `dsh web`（本 bundle 的 host 半边需要 `ctx.webServer` 注册 HTTP 路由）。
- 工作区里有 `sysml-ir/v1` 的 IR JSON（例如 `model-output/<包>/<包>.ir.json`）。
- 可选：`python3` + `sysml-modeling-agent/mcp-server/tools/graph.py`（有则优先用它的投影）。

## 2. 安装

> **注意**：`plugin_manager` 工具在标准预设里默认是禁用的（官方 standard 里 `tool-plugin-manager: disabled: true`）。安装入口用以下任一：
> ① DSH 侧边栏「插件」页（可视化安装/选择组合包）；② 切到「创造模式」（cordis preset）让 agent 调 `plugin_manager`；③ CLI `dsh plugin`。

方式 A（DSH 内，插件页或创造模式）：让 agent / 插件页执行 `plugin_manager`：

```
action: install_bundle
target: /absolute/path/to/2610_MBSE/proposal/q2-plugin
```

- 该动作会写 profile 的 `package.json` / `cordis.patch.yml`，可能弹出审批；批准后按返回的
  `application` 字段判断是否生效（`applied` 表示已生效）。
- **不要手工改 profile 文件**，也不要 `pnpm` 在 profile 目录里跑。

方式 B（CLI，若已配置 `dsh` 命令）：

```bash
dsh plugin --profile <profile> add /absolute/path/to/2610_MBSE/proposal/q2-plugin
```

安装后检查：bundle 列表里出现 `dsh-sysml-viz`，且本插件行（id `sysml-viz`）处于启用状态。
**替换同名已安装包需要重启应用**（浏览器侧 JS 模块代需要重新加载；HMR 只在同一代内生效）。

## 3. 配置

配置写在 profile `cordis.patch.yml` 里本插件行的 `config`（插件管理器安装后可在 bundle/plugin
配置里改；行 id=`sysml-viz`）。所有项可留空：

| 配置键 | 默认 | 说明 |
| --- | --- | --- |
| `model` | `''` | 显式 IR 文件；空则用 env `SYSML_VIZ_MODEL`，再空则自动发现 |
| `workspace` | `''` | 工作区根；空则按「请求带上的会话工作区（`?sessionId=` → `~/.dsh/storages/workspace.json`）→ `SYSML_VIZ_WORKSPACE` → `INIT_CWD` → 进程 cwd → 逐级父目录」解析 |
| `autoOpen` | `true` | 仅对 `agentPreset === 'sysml-v2'` 的会话自动打开；用户按会话关过就记住 |
| `pollMs` | `2000` | 客户端轮询间隔（500–60000ms） |
| `modelingWindowMs` | `8000` | IR 文件 mtime 在该窗口内显示「建模中」 |
| `preferPython` | `true` | 优先调用 `graph.py`；失败/超时自动降级到内置 JS |
| `python` | `python3` | python 解释器；默认会优先用工作区自带的 `sysml-modeling-agent/.venv/bin/python` |
| `graphScript` | `''` | `graph.py` 路径；空则自动找 `<workspace>/sysml-modeling-agent/mcp-server/tools/graph.py` |
| `pythonTimeoutMs` | `5000` | `graph.py` 调用超时 |
| `workspaceDepth` | `4` | 自动发现时 `*.ir.json` 的递归深度上限 |
| `history` | `true` | 建模过程记录：每次 IR 语义变化写 `<workspace>/.sysml-viz/history/`（步骤快照 + 增删改 + 会话短 id），不写 IR |
| `timelineScript` | `''` | `mcp-server/tools/timeline.py` 路径；空则自动找（生成「建模全过程」SVG） |
| `timelineTimeoutMs` | `20000` | 生成过程图超时 |

环境变量：`SYSML_VIZ_WORKSPACE_STORE` 可把「会话 → 工作区」的存储指向别的 `workspace.json`（测试用）；
`SYSML_VIZ_HISTORY=0` 可关闭过程记录（等价 `history: false`），`SYSML_VIZ_TIMELINE_SCRIPT` 指定 timeline.py。

### 3.1 工作区是怎么定位的（v0.1.1 修复）

DSH 桌面端的宿主进程 cwd 是 **profile 目录**（`~/.dsh/profiles/desktop`），不是会话工作区；
早期版本直接拿进程 cwd 去找 IR，导致右栏出现 `MODEL_NOT_FOUND`（已实测踩到）。

现在的链路：

1. 右栏 tab 正文由 DSH 注入 `sessionId`，client 请求时带 `?sessionId=`；
2. host 读 `~/.dsh/storages/workspace.json`，按 `tables.workspaces[*].sessionIds` 反查
   该会话的 `path`，作为第一优先工作区根；
3. 请求不带 `sessionId`（旧 client / 直接 curl）时退回「最近更新的工作区」；
4. 再用 `workspace` 配置 / env / `INIT_CWD` / cwd 兜底。

因此 **替换 bundle 后必须重启 DSH**（host 半边是进程内模块，不会热替换）。

对应环境变量（config 为空时生效）：`SYSML_VIZ_MODEL`、`SYSML_VIZ_WORKSPACE`、
`SYSML_VIZ_AUTO_OPEN=0|1`、`SYSML_VIZ_POLL_MS`、`SYSML_VIZ_MODELING_WINDOW_MS`、
`SYSML_VIZ_PREFER_PYTHON=0|1`、`SYSML_VIZ_PYTHON`、`SYSML_VIZ_GRAPH_SCRIPT`、
`SYSML_AGENT_DIR`（指向 `sysml-modeling-agent` 目录，bundle 里找 `mcp-server/tools/graph.py`）。

模型发现优先级：`config.model`/env 显式路径 → `<ws>/.sysml-viz/model.ir.json` →
`<ws>/.sysml-agent/…/model.ir.json` → `<ws>/model-output/<包>/*.ir.json` →
深度受限的 `*.ir.json`（排除 node_modules/.git/.venv 等；`examples/`、`skills/` 里的样例优先级最低）。
不想自动发现时把 `model` 指向明确文件即可。

### 3.2 建模过程记录与「过程」面板（v0.1.4）

右栏除了图，还提供 **「过程」chip**（在视图 chip 行末尾）：

- 每次 IR 的**语义内容**变化（`sha256(stable({schema,package,elements}))` 变化；纯缩进/格式不算）
  自动追加一步，写入 `<workspace>/.sysml-viz/history/`：
  - `index.json`：`sysml-viz-history/v1`，每步 `seq / at / revision / irSha256 / semanticSha256 /
    elements / relations / added[] / removed[] / changed[] / source / sessionId / snapshot`；
  - `step-NNNN-<rev>.ir.json`：该步的完整 IR 快照（就是当时的模型，不反写）。
- 面板左侧是步骤列表（色块、时间、会话短 id、`+a ~c -r`、新增元素名）；右侧是全过程图：
  **「生成过程图」** 调 `sysml-modeling-agent/mcp-server/tools/timeline.py` 渲染 SVG（按步骤着色，
  同时落盘到 `.sysml-viz/history/timeline.svg`）。
- **本会话 +N**：`/history?sessionId=` 会返回该会话新增/修改的元素 id；图上这些元素用绿色虚线描边
  持久标出（与 20 秒的 `+N 新增` 闪现互补，回答"这一轮到底改了什么"）。
- **清空记录**：`DELETE /api/sysml-viz/history?sessionId=...` 只清 `.sysml-viz/history/`，不动模型；
  清空后当前模型重新记为基线。
- 取舍：记录是**拉取式**的——只有模型视图 tab 在轮询（或手动打开过程面板）时才落步骤；没有 tab
  打开期间发生的多次变化会合并成下一次观察到的一步。会话归属是 host 从 tab 请求拿到的 id，
  不是 DSH 的对话轮次；跨会话改动归到请求方会话。
- 状态行 `模型更新 · 12s 前` 是**模型文件 mtime 年龄**（不是网络耗时）：轮询 2s 一次，文件一变图就换；
  数字变大只说明模型没动。`建模中` 表示 mtime 在 `modelingWindowMs` 内或有 `.sysml-viz/modeling` 标记。

## 4. 打开「模型视图」

- **自动**：新会话选择「SysML v2 建模」预设后，当前会话的右栏会自动打开模型视图（如果
  `autoOpen=true`、窗口 ≥768px、用户没在这个会话里显式关过、右栏没有该 tab）。右栏为空时
  **只打开模型视图**，不再先播种文件 tab。
- **手动**：SysML 会话 header 里有本插件注册的「▦ 模型视图」按钮；其他预设不显示该按钮，
  从右栏 tab 条的添加控件 → 引导页里的「模型视图」入口进入。
- **关闭**：正常关闭即可；该会话会记住「不要自动打开」（`localStorage` 键
  `dsh.sysml-viz.dismissed.<sessionId>`）。想恢复自动打开：开发者工具删掉该键，或直接用 header 按钮。
  注意：模型视图是唯一 tab 时，关闭它会收起整列右栏（DSH 规则），header 按钮可重开。

## 5. 与文件预览 / 其它 tab 共存

本插件只注册新的 tab 类型 `kind='sysml-viz'`（`priority='extension'`，`keepMounted`），**不接管**
`files`、`text`/文档预览等既有类型；它们仍可在右栏 tab 条里切换，或用分栏（最多两格）同屏。

## 6. 与 Agent 预设（preset-sysml-v2）的关系 + 让工具只在 SysML 模式出现

- 安装本 bundle 后，**新建会话**的预设列表出现「SysML v2 建模」（`id: sysml-v2`，order 15）；
  这是 `preset-sysml-v2.patch.yml` 的 `@deepseek-ai/dsh-agent-preset` 行。
- preset **只决定该会话可见的工具/提示词**，不控制 UI；右栏自动打开由 client 半边读取
  `projectionValues.agentPreset === 'sysml-v2'` 决定。
- 配置错误会显示在预设列表里（不静默）；**已开始的会话不能切换 preset**，只能新开会话。
- 安装后不要求一定用该 preset：其它预设会话可以从右栏默认页的「模型视图」卡片进入
  （header 按钮只在 SysML 会话显示）。

### 6.1 推荐：工具只在 SysML 模式出现（用户已选此方案）

`preset-sysml-v2.patch.yml` 里已包含一行 **scoped 的 `mcp-sysml-agent`**（`@deepseek-ai/dsh-mcp-client`），
它只被选中「SysML v2 建模」的 Agent 继承。要让它生效，必须**同时禁用 profile 里同 id 的全局行**，否则会起两个 python 进程：

1. 安装本 bundle（§2）；
2. 禁用全局行（三选一）：
   - **插件页**：在 DSH 侧边栏「插件」里找到 `mcp-sysml-agent`（`@deepseek-ai/dsh-mcp-client`），关闭；
   - **创造模式 / 有 `plugin_manager` 的会话**：
     ```
     plugin_manager  action: set_plugin
                     target: mcp-sysml-agent
                     enabled: false
     ```
     （需要 `danger-full-access` 或本次调用审批；返回 `application: applied` 为成功）
   - **手工**：把 `~/.dsh/profiles/desktop/cordis.patch.yml` 里该行加 `disabled: true`（不推荐，官方建议用插件管理器）。
3. **新开**一个会话，选「SysML v2 建模」预设 → 工具列表应出现 `mcp__sysml-agent__query_model` 等；
   在标准预设的新会话里应**看不到**这些工具。
4. 回退：如果 preset 里的 MCP 启动失败（预设列表会显示配置错误），先把全局行重新启用
   （`set_plugin enabled: true`），再排查 python 路径/venv；两条 MCP 行**不要同时启用**。
5. 路径：preset 里 MCP 的 python / run_server.py / cwd 默认写死为本机路径；
   换机器或换目录时改 `preset-sysml-v2.patch.yml` 末尾，或设环境变量
   `SYSML_AGENT_PY` / `SYSML_AGENT_SERVER` / `SYSML_AGENT_CWD`。

> 如果暂时不想动全局 MCP 行：把 preset 里那段 `mcp-sysml-agent` 注释掉，保留全局行——代价是
> 所有预设都能看到 SysML 工具（不是"只在 SysML 模式"）。两种形态二选一，不要叠加。

### 6.2 Desktop 下的模块解析坑（2026-10-19 实测，导致 MCP 行静默失效）

preset 里的 `mcp-sysml-agent` 行如果写 **bare name** `@deepseek-ai/dsh-mcp-client`，Desktop 会从
profile 目录做 Node 解析，命中 `~/.dsh/profiles/desktop/node_modules` 里的**旧副本**
（`0.2.0-rc.2`，其 peer 又落到 `~/.dsh/profiles/node_modules` 的 `0.1.6-alpha.1`），与运行中的
DSH `0.2.1-rc.2` 不一致 → 行静默不激活：会话里没有 `mcp__sysml-agent__*`，`health` 里
`pythonAvailable:false`、`pgrep -fl run_server.py` 无进程，且 UI 无报错。

**本 bundle 已采用的修法**：`name` 直接指向 app.asar 内与运行时同版本的模块：

```yaml
name: 'file:///Applications/DeepSeek%20Harness.app/Contents/Resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-mcp-client/lib/index.js'
failOnStartupError: true   # 连接失败时让 preset 显式 broken，而不是静默少工具
```

同时 profile 里的**全局** mcp 行要禁用（`disabled: true`），避免双进程；本机已在
`~/.dsh/profiles/desktop/cordis.patch.yml` 加上 `disabled: true`（备份在 `/tmp/cordis.patch.yml.bak-*`）。
换 DSH 版本/安装路径或改用源码 checkout 时，改这一行指向对应路径即可。

## 7. 验证（安装后自查）

1. HTTP（Web 模式，端口见 DSH 启动输出）：

   ```bash
   curl -s http://127.0.0.1:<port>/api/sysml-viz/health
   curl -s "http://127.0.0.1:<port>/api/sysml-viz/health?sessionId=<会话 id>"
   curl -s "http://127.0.0.1:<port>/api/sysml-viz/model?sessionId=<会话 id>" | head -c 400
   curl -s "http://127.0.0.1:<port>/api/sysml-viz/history?sessionId=<会话 id>" | python3 -m json.tool | head -40
   curl -s -o /tmp/timeline.svg -w '%{http_code} %{content_type}\n' \
     "http://127.0.0.1:<port>/api/sysml-viz/timeline.svg?sessionId=<会话 id>"
   ```

   `health` 应 `ok:true`，并显示 `model.found`、`workspace.roots`、
   `workspace.sessionWorkspace`（带 `?sessionId=` 时）、`graph.pythonScript` / `graph.python`、
   `graph.pythonAvailable`；`model` 应 `ok:true`、`schema:"sysml-graph/v1"`、`views.length>=4`
   （结构/IBD/需求/状态，+参数视图）、`stats.elements/relations`、`modelRef.revision`。
   IR 非法时返回 `{ok:false,error:{code,message}}`（HTTP 仍 200），client 会显示错误卡片。

2. 只读诊断（排查「mcp__sysml-agent__* 工具没出现」/preset 状态，v0.1.2+）：

   ```bash
   # preset roster + broken 原因 + preset 内每个 plugin 行的 state/error + Host 工具名
   curl -s http://127.0.0.1:<port>/api/sysml-viz/diagnostics | python3 -m json.tool | head -80
   # 再加一步：从 Host 进程直接拉起 MCP server 做 stdio 握手（验证路径/venv/协议）
   curl -s "http://127.0.0.1:<port>/api/sysml-viz/diagnostics?mcpSelfTest=1" \
     | python3 -c "import json,sys;d=json.load(sys.stdin);print(json.dumps(d['mcpSelfTest'],ensure_ascii=False,indent=1))"
   ```

   - `presets.presets[].mountedRows[]` 里应出现 `mcp-sysml-agent` 行，`fiber.state=2`（active）；
     没有这一行 / `disabled:true` / `fiber.state` 非 2，就是 preset 没把 MCP 行挂起来。
   - `mcpSelfTest.ok=true` 且 `toolNames` 有 8 个 → server、venv、路径、协议都正常，问题在 DSH 的 MCP 接入层。
   - `presets.compositions[]` 的 `modules[]` 里应包含 `@deepseek-ai/dsh-mcp-client`。

3. 前端：右栏出现「模型视图」tab，树/图/修订号/建模中状态可见；改一下 IR 文件（或让 agent 建模），
   2s 内图与修订号刷新，刚变更的元素带高亮。画布滚轮缩放、按住拖动；拖到边缘仍会留一小块可见，
   「适应」按实际画布重新 fit。节点文字不会越出边框：标题过长会缩字号，正文按像素截断，
   边标签会与节点/其它标签避让。悬停图节点时左树对应行高亮；
   若祖先折叠，会临时展开并滚动，鼠标离开后恢复原来的折叠状态与滚动位置。
4. 过程面板（v0.1.4）：点视图 chip 行末尾的「过程」→ 应看到基线/步骤列表；让 agent 再改一次模型，
   刷新后应多一步并显示 `+N`；点「生成过程图」应显示按步骤着色的 SVG（文件同时写在
   `<workspace>/.sysml-viz/history/timeline.svg`）。「清空记录」后步骤回到 1 条基线。
5. 共存：右栏 tab 条里同时存在文件预览与模型视图，可切换；分栏后两格同屏。

不装插件也可以跑 bundle 自检：`node --check index.js && node --check client.js && node smoke-test.mjs`
（smoke-test 用 mock ctx 注册 5 条路由、读 golden IR、断言 4 类视图/错误降级/diagnostics/真实 MCP 握手，
并用临时工作区验证「基线 → 变化 → 新增步骤 → 清空 → 重建基线」与 timeline.svg 生成（缺 timeline.py 时 SKIP）；
另外检查 client 装配形态与静态约束）。

## 8. 已知限制

- **真机状态（v0.1.7）**：已在本机桌面端安装（profile `desktop`，symlink 到本目录），v0.1.1–v0.1.7
  已在真机跑通（工作区定位、与文件 tab 共存、MCP 工具按 preset 出现、画布缩放/平移、悬停联动、
  文字适配与边标签避让）；
  **host/client 改动需重启 DSH 才生效**（host 半边是进程内模块，不会热替换）。
- 过程记录是拉取式的：没有模型视图 tab 在轮询时不落步骤；会话归属来自 tab 的 `?sessionId=`，
  精确不到对话轮次。
- 图布局是 host 侧简化确定性布局（`graph.py` 只做投影、不做布局）；大模型可能拥挤，需缩放/平移。
- Electron（`file://`）下相对 `/api/...` fetch 是否走 IPC 桥接未验证；Web 同源模式可用。
- 轮询刷新（2s）而非 SSE；「建模中」是 mtime 窗口 + `.sysml-viz/modeling` 标记的近似判断。
- 追溯关系图来自 IR 投影（文本里 trace 仅为注释），IBD 展示 2 条真实 Connection + connects 投影。
