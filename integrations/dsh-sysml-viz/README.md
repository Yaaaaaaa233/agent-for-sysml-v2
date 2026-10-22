# dsh-sysml-viz —— DSH 右栏「模型视图」插件 bundle

一个可安装的 DSH **bundle**（Host 半边 + Client 半边），把 SysML v2 模型做成右栏 tab：
**模型树 + 图（结构 / IBD / 需求 / 状态 / 参数）+ 建模中状态**。它与文件预览、文本预览等既有
tab 平级共存，不接管它们的 kind，可随时切 tab 或最多两格分栏。

## 它做什么

- **右栏新 tab**（kind=`sysml-viz`，普通 tab + `keepMounted`，可关闭，不是不可关闭面板）。
  注意：**模型视图按工作区显示当前 IR，不是会话私有画布**——同一工作区里所有会话看到同一份模型，
  新建会话不会清空模型；要看“从空白长出来”，请把 IR 换成最小骨架（见 verify-prompt.md 提示词 0）。
- **模型树**：按层级（part def 组合树 / 需求 / 行为 / 参数）与按类别两种分组。
- **图**：结构（BDD）、互联（IBD）、需求追溯、状态机（状态图），有属性/约束时再出参数视图。
  图数据来自 IR JSON 投影；`graph.py` 可用时优先用它，否则用 host 内置 JS 兜底。
- **画布交互（v0.1.6）**：滚轮以鼠标位置为锚点缩放（25%–400%），在图上按住拖动平移；
  `+ / − / 适应` 固定在 view bar 右侧。画布尺寸按实际挂载区域测量，换分栏/改窗口都会重新适配；
  平移边界是**近自由**的：只要求内容至少留约 15% 视口可见，两边范围对称，小图也不会被锁死。
  悬停图节点会轻微高亮该节点，并在左侧树定位对应行：
  层级模式精确到元素行（折叠分支延迟展开并滚动），类别模式高亮所属视图行；
  鼠标离开图后，**只为高亮临时展开的分支会恢复原来的折叠状态**，树也滚回悬停前的位置
  （手动展开/折叠的不受影响）。
- **文字适配（v0.1.7）**：节点标题按可用宽度自动缩字号，正文按真实字号与全角字符换行、
  再按像素宽度截断；SVG 另按节点矩形裁剪兜底，文字不会溢出边框。边标签也按像素截断，
  并与节点/其它标签做碰撞避让，不再压到节点上。
- **入口（v0.1.5）**：自动打开只开模型视图，不再先播种文件 tab；会话 header 的「▦ 模型视图」
  按钮只在 SysML v2 会话显示，其他预设仍可从右栏默认页的「模型视图」卡片进入。
- **状态行（v0.1.4 语义澄清）**：`rev sha8` / `N 元素 · R 关系` / `建模中`（文件 mtime 窗口或
  `.sysml-viz/modeling` 标记）/ `模型更新 · 12s 前`。最后这个数字是**模型文件最后写入距今多久**
  （mtime 年龄），不是网络请求耗时；因为视图每 2s 轮询一次，文件一变图层就换，数字大只说明模型没动。
  `+N 新增` 是最近一次变化的高亮，约 20 秒后淡出。
- **建模过程（v0.1.4，右栏「过程」面板）**：每次 IR **语义内容**变化（与缩进/格式无关）自动记一步，
  写 `<workspace>/.sysml-viz/history/`：`index.json`（每步 revision / 增删改 id / 会话短 id /
  快照文件名）+ `step-NNNN-<rev>.ir.json` 完整快照。面板里可看每步时间、`+a ~c -r`、新增元素名，
  本会话新增的元素在图上用**绿色虚线描边持久标出**（不依赖 20s 闪现），并可一键生成
  **「建模全过程」SVG**（按步骤着色：树节点颜色 = 首次出现步骤，图例 = 每步增量，底部 = 元素数曲线）。
  不写 IR、不改模型文件；`DELETE /api/sysml-viz/history` 清空后当前模型重新记为基线。
- **只读诊断**（v0.1.2+）：`GET /api/sysml-viz/diagnostics` 返回 preset roster / broken 原因 /
  preset 内每个 plugin 行的 `fiber.state` / Host 工具名；`?mcpSelfTest=1` 会从 Host 进程直接
  拉起 MCP server 做 stdio 握手（排查 `mcp__sysml-agent__*` 缺失时用）；
  启动 3s 后还会把 Host 组合快照写到 `/tmp/dsh-sysml-viz-boot.json`（profile loader 每行
  `fiber.state`/`disabled`/error + 服务探测），重启后可离线取证。
- **数据来源**：`SYSML_VIZ_MODEL` 显式 IR，或 `<workspace>/.sysml-viz/model.ir.json`、
  `<workspace>/model-output/<包>/*.ir.json`、`.sysml-agent/`、深度受限的 `*.ir.json` 自动发现。
  工作区优先按**会话**定位：tab 带 `?sessionId=` → host 查 `~/.dsh/storages/workspace.json`
  找到该会话的工作区（桌面端进程 cwd 是 profile 目录，不能当工作区）。

## 安装 / 配置

完整步骤见 [install.md](install.md)，摘要：`plugin_manager` `install_bundle`（target=本目录绝对路径），
或 `dsh plugin --profile <profile> add <本目录绝对路径>`。

```yaml
config:                # cordis.patch.yml 中本插件行；全部可留空
  model: ''            # 显式 IR 路径；留空则自动发现
  workspace: ''        # 工作区根；留空按 会话工作区（?sessionId=）/ SYSML_VIZ_WORKSPACE / INIT_CWD / 进程 cwd
  autoOpen: true       # 自动打开（仅对 agent preset = sysml-v2 的会话）
  pollMs: 2000
  modelingWindowMs: 8000
  preferPython: true   # 优先调用 sysml-modeling-agent/mcp-server/tools/graph.py
  python: python3      # 默认优先用工作区 .venv/bin/python
  graphScript: ''      # graph.py 路径；留空自动在 workspace 里找
  history: true        # 建模过程记录（.sysml-viz/history/，只读 IR 的投影，不写 IR）
  timelineScript: ''   # mcp-server/tools/timeline.py 路径；留空自动找
  timelineTimeoutMs: 20000
```

## 过程图 / 时间线数据契约

- 写入方：host 半边在每次 `/api/sysml-viz/model` 加载（含缓存命中）时比较 IR 语义哈希
  `sha256(stable({schema,package,elements}))`；变化才追加一步。纯格式改动不会产生噪声步骤。
- 目录：`<workspace>/.sysml-viz/history/`，格式 `sysml-viz-history/v1`：
  `{schema, workspace, modelPath, createdAt, updatedAt, steps:[{seq, at, revision, irSha256,
  semanticSha256, elements, relations, added[], removed[], changed[], source, sessionId, turn?,
  note?, snapshot}]}`；快照是当时的完整 IR。
- 消费方：client「过程」面板 + `mcp-server/tools/timeline.py`（生成 `timeline.svg`，schema
  `sysml-timeline/v1`）。MCP 侧对应 `export_timeline` 工具（重启 DSH / MCP 后出现在 SysML 会话）。
- 归属：`sessionId` 是 host 从 tab 请求 `?sessionId=` 得到的**会话短 id**；一轮对话里多次写模型会合并成
  同一会话的多步。当前来源标记为 `baseline` / `change`，由历史日志重建的步骤会标 `session-log`
  并在面板显示「日志重建」。

## 与 agent preset 的关系

`preset-sysml-v2.patch.yml` 是同一个 bundle 的第二个 patch：安装后**新建会话**的预设列表里出现
「SysML v2 建模」。**preset 只决定模型可见的工具与提示词，不控制 UI**；右栏是否自动打开由本插件
的 client 半边按 `projectionValues.agentPreset === 'sysml-v2'` 判断（用户关过就按会话记住；
header 的「模型视图」按钮只在 SysML 会话显示，其他预设从右栏默认页的「模型视图」卡片进入）。
**工具只在 SysML 模式出现**：preset 里有一行 scoped
`mcp-sysml-agent`；启用前请先禁用 profile 里同 id 的全局行
（`plugin_manager set_plugin target=mcp-sysml-agent enabled=false`），两条 MCP 行不要同时启用；
详见 [install.md §6.1](install.md)。已开始的会话不能切换 preset，只有新会话生效。

## 自检（不需要装插件）

```bash
node --check index.js && node --check client.js
node smoke-test.mjs    # 39 项：5 条路由 / 图 / 过程记录 / 全过程图 / 会话归属 / 错误降级 / client 装配 / 画布数学 / 文字适配
```

## 已知限制

- **真机状态（v0.1.7）**：已在本机 DSH 桌面端安装（profile `desktop`，symlink 到本目录）。
  v0.1.1 修过 `MODEL_NOT_FOUND`（按会话定位工作区）；v0.1.2/v0.1.3 修过 MCP 行静默失效；
  v0.1.4 新增过程记录与全过程图；v0.1.5 收口入口（header 仅 SysML、不播种 files）、
  画布滚轮缩放/拖拽平移、图节点悬停联动左树；v0.1.6 修画布尺寸测量与平移边界、
  悬停展开后恢复折叠；v0.1.7 修节点文字溢出（换行宽度、像素截断、标题缩字号、节点裁剪、
  边标签避让）。**host/client 改动都要重启 DSH 才生效**。
- 过程记录只在**有人打开模型视图 tab**时随 `/model` 请求写入：没有 tab 在轮询时，模型变化不会
  自动落历史（下一次打开时只会记当时状态为一步）。这是「只读、无后台常驻进程」的取舍。
- 会话归属是启发式：host 只能拿到 tab 请求的 `?sessionId=`，无法知道是"哪一轮对话"；跨会话的
  改动按请求方会话记。要精确到对话轮次，可在 MCP 工具侧补显式 `note`（后续）。
- 图布局是插件侧确定性简化布局（graph.py 只做投影不做布局）；复杂模型可能出现长边与拥挤，需缩放/平移。
- 自动打开依赖 `useSessions` 投影值；窄窗口（<768px）不自动打开。SysML 会话仍可用 header 按钮，
  其他预设从右栏默认页的「模型视图」卡片进入。
- 模型视图是 SysML 会话右栏唯一自动打开的 tab；关闭这个唯一 tab 会让整列右栏收起（DSH 规则），
  用 header 按钮可重开。
- 悬停联动按 IR `elementId` 匹配：状态图里多个状态共用状态机的 id，trace 节点指向被追溯元素，
  所以会高亮同一行/被引用元素；没有 `elementId` 的节点不联动。鼠标移开后只收回“为高亮临时展开”
  的祖先；如果悬停期间手动改了树，以手动操作为准。
- 轮询而非 SSE；Electron 下相对路径 `fetch('/api/...')` 是否经 IPC 桥接未验证（Web 同源可用）。
- 追溯关系来自 IR 投影；SysML 文本里 trace 关系仅以注释存在，IBD 只有 2 条真实 Connection 边，
  界面展示的是 IR 投影而非「文本里看得见的连线」。
