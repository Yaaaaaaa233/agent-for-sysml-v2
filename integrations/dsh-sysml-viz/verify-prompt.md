# Q2 右侧「模型视图」插件 · 验收提示词

> 用法：DSH 新建任务 → 预设选 **「SysML v2 建模」** → 把下面「提示词 A」整段粘进对话。
> 注意：`plugin_manager` 是 DSH 工具，**不是终端命令**；本文件里的命令都由 agent 执行。
>
> **v0.1.1 修复（2026-10-19）**：首轮真机验收出现 `MODEL_NOT_FOUND`——host 把桌面端进程 cwd
> （`~/.dsh/profiles/desktop`）当成了工作区。现已改为：tab 请求带 `?sessionId=` → host 读
> `~/.dsh/storages/workspace.json` 反查会话工作区 → 再自动发现 IR。
> **替换 bundle 后必须重启 DSH**（Cmd+Q 后重开），再新建 sysml-v2 会话验收。
>
> 已预置演示模型：`model-output/q2-demo/q2-demo.ir.json`（golden 副本，34 元素 / 20 关系），
> 重启后右栏应直接出图；提示词 A 的第 3 步会再复制/覆盖一次，属于幂等操作。
>
> **v0.1.2 诊断路由（2026-10-19）**：新增 `GET /api/sysml-viz/diagnostics`，可只读查看
> preset roster / broken 原因 / preset 内每个 plugin 行的 state、以及从 Host 进程直接拉起
> MCP server 的握手自检（`?mcpSelfTest=1`）。首轮真机验收发现 **sysml-v2 preset 生效但
> `mcp__sysml-agent__*` 工具缺失**，用这两个接口定位（见提示词 D）。
> 另：沙箱里 `ps` 被禁，查 MCP 进程改用 `pgrep -fl run_server.py`。
>
> **v0.1.3（2026-10-19）根因修复**：Desktop 下 preset 里 bare name `@deepseek-ai/dsh-mcp-client`
> 被 Node 解析到 profile 自带的**旧副本**（0.2.0-rc.2 / peer 0.1.6-alpha.1），与运行中的
> DSH 0.2.1-rc.2 不一致 → 行静默不激活（无 UI 报错）。已改为 `file://` 指向 app.asar 内同版本
> 模块，并加 `failOnStartupError: true`；profile 全局 mcp 行已 `disabled: true`。
> diagnostics 现在额外返回 `injected` / `services` / `loader`（profile 每行 fiber.state）/ `profilePatch`，
> 启动 3s 后还会写 `/tmp/dsh-sysml-viz-boot.json`。重启后预期 `pgrep -fl run_server.py` 能看到 1 个进程。
>
> **v0.1.4（2026-10-19）建模过程 + 全过程图**：右栏新增「过程」chip / 面板。每次模型语义变化自动记一步
> （`<workspace>/.sysml-viz/history/index.json` + 快照），面板里可看步骤时间、`+a ~c -r`、新增元素名、
> 「本会话 +N」持久描边；「生成过程图」调 `mcp-server/tools/timeline.py` 画按步骤着色的 SVG。
> 同时把状态行文案从「已同步」改为「模型更新 · X 前」——它是**模型文件 mtime 年龄**，不是网络耗时。
> **v0.1.4 的 host/client 改动必须重启 DSH 才生效**；重启后先跑「提示词 E」验收。
> 本机已把 20:48–20:51 那次真实生长（会话 a89d8bff 第 1–4 轮）从 DSH 会话日志重建为 5 步历史：
> `baseline(1 元素, sha8 98713da0) → 第1轮 +REQ → 第2轮 +PD/PU → 第3轮 +ATTR → 第4轮 +C-ENDURANCE(6 元素)`，
> 每步都标了 `session-log` / 第 N 轮，可直接在「过程」面板看到；面板会显示「日志重建」chip 区分真机实时记录。
> 如果重新打开原会话 `a89d8bff…`，header 会直接显示「本会话 +5」且这些元素带绿色虚线描边——正好验证「区分不同轮次/会话」的归属逻辑。

---

## 提示词 0 · 从最小骨架实时生长（演示/肉眼验收用）

> 背景：模型视图读的是**工作区当前 IR**，不是会话私有画布——所有会话看到同一份模型。
> 当前 `model-output/q2-demo/q2-demo.ir.json` 是 20:51 那次演示的结束状态（6 元素，sha8 `b6d3b3a1`），
> 已经在 `.sysml-viz/history/` 里有 5 步真实历史（见顶部 v0.1.4 说明）。
> 要从空白重新长一遍：先把历史快照里的基线复制回去——
> `cp .sysml-viz/history/step-0000-98713da0.ir.json model-output/q2-demo/q2-demo.ir.json`
> （恢复 34 元素标杆模型：`cp sysml-modeling-agent/examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json model-output/q2-demo/q2-demo.ir.json`；
> 当前 6 元素版本也备份在 `/tmp/q2-demo-34-elements.ir.json.bak`——那是 34 元素旧备份，注意别混用）。
> 演示时右栏会从"1 元素 · 0 关系"逐步长出来；每一步都应出现在「过程」面板并可用颜色区分。

```text
在 model-output/q2-demo/q2-demo.ir.json 上从最小骨架开始建模（不要改 examples，不要手改 .sysml）。
每做完一步：validate_model_json 必须 0 error，原子写回同一文件，并报告
[当前 sha8 / 元素数 / 关系数]；等我确认再继续下一步。

第 1 步：新增 Requirement（id=REQ-CRUISE-ENDURANCE，owner=Q2Demo，
       properties.text="巡航时间不少于 4 小时"，acceptanceCriteria="T >= 4.0 h"，
       verifyMethod="analysis"，priority="high"）——让需求视图出现第 1 个节点。
第 2 步：新增 PartDefinition Q2DemoSystem 下的 PartUsage（id=PU-Battery，
       name=Battery，typeRef=PU-Battery 指向的 PartDefinition 需先建：PartDefinition id=PD-Battery，
       name=BatteryPack，owner=Q2Demo），体现"结构树里长出子部件"。
第 3 步：新增 Attribute（id=ATTR-BATTERY-KWH，owner=PD-Battery，
       properties.defaultValue=3.6，unit="kWh"）——参数视图出现数值。
第 4 步：新增 Constraint（id=C-ENDURANCE，owner=Q2Demo，
       properties.expression="T = E / P"）——参数/约束视图出现公式节点。
```

**同步看右栏**：每一步写回后 2 秒内状态行 sha8 变、`建模中` 闪一下、新增节点带高亮（20 秒）；
元素数 1→2→3→4…逐级上升。现在还会在「过程」面板多出一步（色块 + 会话 id + `+1`），
header 出现持久的 `本会话 +N`，新增节点带绿色虚线描边。如果右栏数字不动而 agent 说已写回，才是真的刷新 bug。

---

## 提示词 E · 建模全过程 / 过程图专项验收（v0.1.4，粘到新开的 SysML v2 会话）

```text
只做验收，不改插件源码，不要手工改 IR 文本。每一步都报告命令输出摘要。

【0. 前置】确认当前会话是「SysML v2 建模」预设；确认端口（lsof -nP -iTCP -sTCP:LISTEN | grep -i deepseek）。

【1. 历史与工具自检】
- curl -s "http://127.0.0.1:<端口>/api/sysml-viz/history?sessionId=<当前会话 id>" > /tmp/hist.json
  用 python 输出：available / stepCount / current.elements / steps[] 每步 {seq,at,revision,source,sessionId,turn,added,changed}
- 预期：至少 5 步（基线 + 20:48–20:51 那 4 轮重建历史），当前 6 元素；步骤里有 source=session-log、turn=1..4。
- 确认 timeline.py 存在：ls sysml-modeling-agent/mcp-server/tools/timeline.py
- 如果 MCP 工具列表里有 mcp__sysml-agent__export_timeline，说明重启后新工具已加载；没有也能继续（走 HTTP）。

【2. 生成全过程图】
- curl -s -o /tmp/timeline.svg -w '%{http_code} %{content_type} %{size_download}\n' \
    "http://127.0.0.1:<端口>/api/sysml-viz/timeline.svg?sessionId=<当前会话 id>"
- 预期：200 + image/svg+xml + 20KB 以上；/tmp/timeline.svg 里应包含：
  「建模全过程」、5 种步骤颜色（#3b82f6 / #f59e0b / #10b981 / #ef4444 / #a855f7）、
  元素名（REQ_CRUISE_ENDURANCE、BatteryPack、ATTR_BATTERY_KWH、C_ENDURANCE）、图例里「第 1..4 轮」或「日志重建」。
- python3 -c "import xml.etree.ElementTree as ET;ET.parse('/tmp/timeline.svg');print('xml ok')" 必须通过。
- 落盘检查：ls -la .sysml-viz/history/timeline.svg

【3. 实时生长 + 历史追加（做一次小改动即可）】
- 用 patch_model 把 C-ENDURANCE 的 expression 改成 "T = E / (P * eta)"（或新增一个 Attribute），
  validate_model_json 0 error 后原子写回 model-output/q2-demo/q2-demo.ir.json。
- 等 3 秒，再取 /api/sysml-viz/history：stepCount 应 +1，最后一步 added/changed 非空、elements 为 6 或 7；
  sessionId 应等于当前会话短 id。
- 再取一次 /api/sysml-viz/model：revision 变化；元素数/关系数/视图节点变化贴表。

【4. 「过程」面板人眼清单（贴给用户核对）】
1) 视图 chip 行末尾出现「过程」chip，右侧数字 = 步骤数；
2) 点开后看到基线 + 第 1..4 轮（或实时步骤），每步有色块、时间、会话 chip、+a ~c -r；
3) 点「生成过程图」→ 面板内出现按步骤着色的 SVG（不是空白/裂图）；
4) header 出现「本会话 +N」；当前会话新增的元素在结构图上带绿色虚线描边；
5) 点「清空记录」→ 确认后步骤回到 1 条基线（模型文件不变），再改一次模型会重新从基线开始记。

【5. 失败时】贴出：HTTP 状态 / content-type / SVG 文件前 500 字节 / history JSON /
host 日志里的 timeline.py 错误（500 响应体里有 error.code 和 timeline payload），不要改源码。
```

---

## 提示词 A · 主验收（粘到 SysML v2 会话）

```text
你是 Q2「模型视图」插件的验收执行者。请严格按顺序做，不要改插件源码，不要假装看到 GUI。
如果任何前置条件不满足，立即停止并报告，不要继续后面的步骤。

【1. 会话与工具自检】
- 确认当前会话的 agent preset 是 sysml-v2（看会话头/设置；如果不是，告诉我怎么切）。
- 列出你当前可用的工具，确认存在 mcp__sysml-agent__query_model、patch_model、validate_model_json、generate_sysml。
- 如果这些工具不存在：报告「SysML v2 预设的 MCP 未生效」，并继续执行【诊断】段，不要跳到建模。

【2. 插件自检（命令由你执行）】
- 查找 DSH Web 端口：lsof -nP -iTCP -sTCP:LISTEN | grep -i deepseek
- 请求：curl -s http://127.0.0.1:<端口>/api/sysml-viz/health
- 再请求：curl -s http://127.0.0.1:<端口>/api/sysml-viz/model | head -c 500
- 把 health 里的 ok、routes、model.found、model.path、workspace.roots、
  workspace.sessionWorkspace、graph.pythonScript、graph.python、pythonAvailable、autoOpen 字段贴出来；
  把 model 里的 schema、views 数量、modelRef.path、modelRef.revision、stats.elements/relations 贴出来。
- 检查 MCP 进程（沙箱禁 ps，用 pgrep）：pgrep -fl run_server.py
  （预期 1 个进程，preset 是 eager mount，应用启动后就已经在跑；无输出=行没激活）
- 只读诊断：curl -s http://127.0.0.1:<端口>/api/sysml-viz/diagnostics
  把 presets.presets[] 里 id=sysml-v2 的 broken、mountedRows 里 mcp-sysml-agent 行的
  disabled/fiber.state、以及 compositions 里是否含 @deepseek-ai/dsh-mcp-client 贴出来；
  再跑一次带自检：curl -s "http://127.0.0.1:<端口>/api/sysml-viz/diagnostics?mcpSelfTest=1"
  贴出 mcpSelfTest.ok / protocolVersion / toolNames（预期 8 个）/ latencyMs / stderrTail。
- 如果 health 的 model.found=false 或 model 返回 MODEL_NOT_FOUND，先报告并停止（不要继续建模）。
- 如果 pgrep 没有 run_server.py 或 mcpSelfTest.ok=false：报告「MCP server 未启动/未接通」，
  并把 diagnostics 的两段 JSON 贴出来，然后停止（工具不全，不要继续建模）。

【3. 准备演示模型（不改仓库里的 examples）】
- 工作区根：/Users/yea/Desktop/Study/比赛/2610_MBSE
- 确保 model-output/q2-demo/ 存在（Host 现在按会话工作区自动发现，多个模型时选最近修改的
  model-output 包；这个文件已预置为 golden 副本，覆盖写一次保证 mtime 最新）
- 把 sysml-modeling-agent/examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json
  复制成 model-output/q2-demo/q2-demo.ir.json
- 用 query_model(path=model-output/q2-demo/q2-demo.ir.json) 或 python 读一遍，记录：元素数、关系数、文件 sha256 前 8 位。
- 预期：34 元素 / 20 关系；调用 /api/sysml-viz/model 的 modelRef.path 应指向 q2-demo.ir.json。

【4. 触发“模型长出来”（两次小改动，每次都落盘）】
改动 1（改参数值）：
- 用 patch_model 把 ATTR-CRUISE-POWER 的 defaultValue 从 240.0 改成 235.0；
- 调用 validate_model_json 确认 0 error；
- 把 patch_model 返回的 model 原子写回 model-output/q2-demo/q2-demo.ir.json。
改动 2（加一个新需求，让树多一个节点）：
- 用 patch_model add_element 增加一个 Requirement，字段完整：
  id=REQ-Q2-DEMO，name=Q2DemoRequirement，owner=CoaxialOctoRotor，
  properties.text="Q2 验收用需求：巡航功率调整后仍满足续航下限。",
  properties.acceptanceCriteria="P_cruise <= 0.9 * P_batt_max 且 T >= 4.0 h。",
  properties.verifyMethod="analysis"，properties.priority="low"；
- validate_model_json 确认 0 error；把 model 写回同一路径。
- 注意：如果 patch/validate 失败，把错误码原样贴出来，不要手工改文本。

【5. 等 3 秒，再取一次 /api/sysml-viz/model】
- 对比改动前后的 revision / elementCount / views[].nodes 数量变化；
- 预期：elementCount 34→35；requirements 视图节点 +1；参数视图里 cruisePowerW 显示 235.0 W；
  revision 变化（sha8 变）。
- 把对比做成表格：字段 / 改动前 / 改动后。

【6. 输出「人眼验收清单」】
逐条告诉我应该看到什么（我会在 GUI 里核对）：
1) 右栏是否自动出现「模型视图」tab（新会话 + sysml-v2 预设）；
2) 右栏 tab 条里是否同时有「文件」/「模型视图」（文件预览没被顶掉）；
3) 模型树是否有「层级 / 类别」切换，叶子是否列出 结构/IBD/需求/状态/参数；
4) 5 个视图是否都能切换：结构 BDD、功率链 IBD、需求追溯、状态机、参数；
5) 状态行是否显示：元素数、关系数、修订 sha8、「建模中」或「模型更新 · X 前」
   （X 是模型文件最后写入距今的秒数——不是网络延迟；轮询 2s 一次，文件一变就刷新）；
6) 改动后是否在 2 秒内自动刷新，且新元素/参数值有高亮；header 是否出现「本会话 +N」；
7) 点视图 chip 行末尾的「过程」→ 步骤数是否变化，最后一步是否显示 `+N` / 改动元素名；
   点「生成过程图」是否出现按步骤着色的 SVG；
8) 手动关闭「模型视图」tab 后，会话 header 的「▦ 模型视图」按钮是否还能打开；
9) 右栏分栏后，文件预览与模型视图是否能同屏（两格）。

【7. 如果失败】
不要修改 plugin 源码。输出：
- 失败项编号 + 现象；
- 相关命令输出（health/model/ps/端口）；
- 插件页里 dsh-sysml-viz 的 application 状态、preset 列表里「SysML v2 建模」是否 broken；
- 下一步建议（例如：重启 DSH / 关闭全局 mcp-sysml-agent / 修改 preset 路径）。
```

---

## 提示词 B · 没看到侧栏时的诊断（粘到任意会话）

```text
只做诊断，不要改模型：
1) 读 ~/.dsh/profiles/desktop/package.json，确认是否有 dsh-sysml-viz 依赖；
2) ls ~/.dsh/profiles/desktop/node_modules | grep dsh-sysml-viz；
3) grep -n "dsh-sysml-viz\|sysml-viz\|mcp-sysml-agent" ~/.dsh/profiles/desktop/cordis.patch.yml；
4) ps aux | grep run_server.py | grep -v grep | wc -l（预期 1，2 表示 MCP 双份）；
5) 找 DSH 端口并 curl /api/sysml-viz/health 与 /api/sysml-viz/model；
6) 检查预设列表里「SysML v2 建模」是否存在/报错，当前会话 preset 是什么。
输出表格：检查项 / 结果 / 判断，并给出最可能原因（未启用 / 需重启 / preset 配置 broken / MCP 双份 / 端口不对 / 插件未安装）。
```

---

## 提示词 C · A/B 验证"工具只在 SysML 模式"

```text
做 A/B 对照，不要建模型：
A) 在标准预设会话里，列出含 mcp__sysml-agent__ 前缀的工具（预期：0 个）；
B) 新开一个「SysML v2 建模」预设会话，同样列出（预期：query_model / patch_model / validate_model_json / generate_sysml 等）。
把两次名单和数量对照输出；如果有偏差，报告 preset/MCP 配置状态。
```

---

## 提示词 D · MCP 工具缺失专项诊断（粘到任意会话）

```text
只做诊断，不要改任何代码/配置：
1) 找端口：lsof -nP -iTCP -sTCP:LISTEN | grep -i deepseek（可能有 2 个端口）
2) curl -s http://127.0.0.1:<端口>/api/sysml-viz/diagnostics > /tmp/diag.json
   用 python 解析并输出：
   - presets.presets[].id / broken（尤其 sysml-v2）
   - sysml-v2 的 mountedRows：列出每行 id/name/disabled/fiber.state/fiber.error；
     特别看有没有 mcp-sysml-agent，state 是否 =2
   - compositions[].modules[] 里是否含 @deepseek-ai/dsh-mcp-client
   - tools.available / tools.count
3) curl -s "http://127.0.0.1:<端口>/api/sysml-viz/diagnostics?mcpSelfTest=1" > /tmp/mcp.json
   输出 mcpSelfTest：ok/command/server/exists/protocolVersion/toolNames/latencyMs/stderrTail
4) pgrep -fl run_server.py
5) 结论表：检查项 / 结果 / 判断，并给出最可能原因：
   A) preset 没挂 mcp 行或 disabled → preset patch 问题
   B) 挂了且 state=2 但会话没工具 → 工具注册/作用域问题
   C) mountedRows 正常 + mcpSelfTest.ok=true → server 正常，问题在 DSH mcp-client 连接
   D) mcpSelfTest.ok=false → 看 stderrTail（python/路径/协议）
```

---

## 预期观察（人眼版）

| # | 你应该看到 |
| --- | --- |
| 1 | 新会话选「SysML v2 建模」后，右栏自动展开并出现「模型视图」tab |
| 2 | 右栏同时有「文件」（或文件预览）与「模型视图」两枚 tab，互不覆盖 |
| 3 | 模型树顶部可切「层级 / 类别」；层级下是 X8 / PowerChain / 电机等 |
| 4 | 5 个视图可点：结构 BDD、功率链 IBD、需求追溯、状态机、参数 |
| 5 | 状态行显示 34 元素 / 20 关系 / sha8 / 「模型更新 · X 前」（或「建模中」）；改 IR 后 2s 内刷新并出现「建模中」或高亮 |
| 6 | header 出现「本会话 +N」；新增元素在图上带绿色虚线描边（持久），最近一次变化另有 20s `+N 新增` 闪现 |
| 7 | 视图 chip 行末尾有「过程」chip；面板里能看到每步时间/会话/增删改，点「生成过程图」出按步骤着色的 SVG |
| 8 | 关闭 tab 后 header「▦ 模型视图」可重新打开；分栏可文件+图同屏 |

## 常见失败对照

| 现象 | 最可能原因 |
| --- | --- |
| 没有自动打开 | 当前会话不是新开的 sysml-v2 会话；用 header 按钮或右栏 "+" → 引导页入口 |
| 右栏只有文件没有模型视图 | 插件行未启用（插件页 `dsh-sysml-viz` 开关）；或替换包后未重启 |
| health 404 | host 半边未激活 / 未重启 / 端口错（用 lsof 找） |
| 会话工具里没有 mcp__sysml-agent__* | sysml-v2 preset 挂了但 MCP 行没生效：先看 `/api/sysml-viz/diagnostics` 的 mountedRows 与 `?mcpSelfTest=1`；`pgrep -fl run_server.py` 无输出=server 没起 |
| tab 显示 MODEL_NOT_FOUND | ① 替换 v0.1.1 后没重启（host 还是旧代码，拿进程 cwd 找模型）；② 工作区里确实没有 `*.ir.json`；③ 当前会话不是通过 `?sessionId=` 请求（旧 client）且最近工作区不对——重启后重开 tab 即可 |
| tab 有图但元素数不是 34 | 自动发现选中了别的 `model-output` 模型；看 health 的 `model.path`，或把演示模型放 `.sysml-viz/model.ir.json` |
| 预设列表无「SysML v2 建模」 | preset patch 未生效或配置 broken（看插件页错误/GUI 预设列表） |
| 工具在标准模式也有 | 全局 `mcp-sysml-agent` 没关；两条 MCP 行只能留一条 |
| 过程面板空白 / 只有 1 步 | 还没有模型变化（基线是自动记的）；或 v0.1.4 host 未重启（health.version 仍是 0.1.3）；或 `<workspace>/.sysml-viz/history/` 被清 |
| 过程图 500 `TIMELINE_GENERATE_FAILED` | `sysml-modeling-agent/mcp-server/tools/timeline.py` 不存在/报错；看 500 响应体里的 `timeline` payload 与 `error.message` |
| 过程图 503 `TIMELINE_TOOL_MISSING` | timeline.py 没被找到：检查工作区里该文件，或 host config `timelineScript` 指向绝对路径 |
| 「已同步」字样还在 | client 还是旧版本（未重启 DSH）；v0.1.4 起改为「模型更新 · X 前」 |
| 状态数字很大（如 2h） | 正常：那是模型文件 mtime 年龄，不是网络延迟；改一次模型就会归零 |
