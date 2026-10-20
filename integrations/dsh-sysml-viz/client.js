/**
 * dsh-sysml-viz — Client half（浏览器侧）。
 *
 * 在 DSH 右栏注册新的 tab 类型 kind='sysml-viz'：
 *   - 模型树（层级 / 类别两种分组）
 *   - 图：结构（BDD）、互联（IBD）、需求视图、状态机、参数视图（数据来自 host 的 sysml-graph/v1）
 *   - 头部状态：已加载 N 元素 / 修订 sha8 / 建模中（文件 mtime 窗口内或有 modeling 标记）
 *   - 2s 轮询 /api/sysml-viz/model，窄宽度自适应（树可收起、画布可滚动缩放）
 *
 * 只注册自己新增的 tab 类型，不接管 files/text 等既有类型，因此与文件预览 tab 共存；
 * 不引用任何 http(s) 外链，React 由宿主模块表提供。
 */

window.__ModuleLoader__.load({
  id: 'dsh-sysml-viz',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useCallback, useEffect, useMemo, useRef, useState } = React

    /* ============================================================ *
     * 常量 / 文案
     * ============================================================ */

    const PACKAGE_ID = 'dsh-sysml-viz'
    const TAB_KIND = 'sysml-viz'
    const NS = 'sysmlViz'
    const API_MODEL = '/api/sysml-viz/model'
    const API_HEALTH = '/api/sysml-viz/health'
    const API_HISTORY = '/api/sysml-viz/history'
    const API_TIMELINE = '/api/sysml-viz/timeline.svg'
    const DISMISS_PREFIX = 'dsh.sysml-viz.dismissed.'
    const FALLBACK_POLL_MS = 2000
    const NEW_HIGHLIGHT_MS = 20000
    // 步骤配色：与 mcp-server/tools/timeline.py 的 STEP_COLORS 保持一致（基线固定灰）
    const STEP_BASELINE_COLOR = '#94a3b8'
    const STEP_COLORS = [
      '#3b82f6', '#f59e0b', '#10b981', '#ef4444', '#a855f7', '#06b6d4',
      '#84cc16', '#ec4899', '#6366f1', '#14b8a6', '#f97316', '#8b5cf6',
    ]

    /** 步骤颜色：基线灰、第 N 步取调色板 (N-1) % 12。 */
    function stepColorOf(index, source) {
      if (source === 'baseline' || index <= 0) return STEP_BASELINE_COLOR
      return STEP_COLORS[(index - 1) % STEP_COLORS.length]
    }

    function pad2(value) {
      return String(Math.max(0, Number(value) || 0)).padStart(2, '0')
    }

    /** ISO 时间 → 本地 "MM-DD HH:MM:SS"（无效时返回空串）。 */
    function formatClock(iso) {
      try {
        const date = new Date(iso)
        if (Number.isNaN(date.getTime())) return ''
        return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`
      } catch {
        return ''
      }
    }

    const ZH = {
      'type.label': '模型视图',
      'guide.title': '模型视图',
      'guide.description': '模型树 + 结构 / IBD / 需求 / 状态图 + 建模中状态',
      title: '模型视图',
      'tree.hierarchy': '层级',
      'tree.category': '类别',
      'tree.toggle': '模型树',
      'header.open': '打开模型视图',
      'status.modeling': '建模中',
      'status.synced': '模型更新',
      'status.age': '· {age} 前',
      'status.tip': '这个状态来自模型文件 mtime（最后写入时间），不是网络请求耗时：视图每 {ms}ms 轮询一次 /model，文件一变图层就换；数字变大只说明模型这段时间没动。',
      'status.updated': '{age} 前更新',
      'status.added': '+{count} 新增',
      'status.added.tip': '最近一次变化新增的元素，约 20 秒后淡出；要长期追溯每一轮改了什么，请切到「过程」。',
      'rev.tip': 'IR sha256：{sha}',
      'stats': '{elements} 元素 · {relations} 关系',
      'source.python': '来源：graph.py',
      'source.js': '来源：内置 JS',
      'poll': '轮询 {ms}ms',
      'zoom.in': '放大',
      'zoom.out': '缩小',
      'zoom.fit': '适应',
      'refresh': '刷新',
      'loading': '正在读取模型…',
      'error.title': '模型视图暂不可用',
      'error.retry': '重试',
      'error.network': '无法连接 /api/sysml-viz/model，请确认 host 半边插件已激活。',
      'error.searched': '已尝试的位置：',
      'error.poll': '刷新失败，显示上一次成功的数据。',
      'empty.title': '未找到可绘制的视图',
      'empty.hint': 'IR 里没有 PartDefinition / Requirement / StateDefinition 等可投影元素。',
      'canvas.hint': '点击节点查看元素 ID；滚轮缩放，拖动平移；悬停节点会在左侧树中定位。',
      'selected': '已选：{label}',
      'model.path': '模型：{path}',
      'view.nodes': '{nodes} 节点 / {edges} 关系',
      'kinds.structure': '结构',
      'kinds.ibd': '互联',
      'kinds.requirement': '需求',
      'kinds.state': '状态',
      'kinds.param': '参数',
      'kinds.action': '动作',
      'legend.node': '元素',
      'legend.trace': '追溯',
      'legend.flow': '连接',
      'legend.state': '迁移',
      'legend.session': '本会话新增',
      'process.tab': '过程',
      'process.title': '建模过程',
      'process.hint': '每次模型语义变化记一步；颜色按步骤区分，便于追溯每一轮对话各加了什么。',
      'process.empty': '还没有步骤记录。模型下一次变动会自动记第 1 步；也可以先「清空记录」从当前模型重新开始。',
      'process.disabled': '过程记录已关闭（host 配置 history: false）。',
      'process.steps': '{n} 步',
      'process.updated': '更新于 {time}',
      'process.baseline': '基线',
      'process.step': '第 {n} 步',
      'process.added': '+{n}',
      'process.changed': '~{n}',
      'process.removed': '-{n}',
      'process.session': '会话 {id}',
      'process.session.now': '本会话',
      'process.reconstructed': '日志重建',
      'process.turn': '第 {n} 轮',
      'process.generate': '生成过程图',
      'process.regenerate': '重新生成',
      'process.open': '新窗口打开',
      'process.reset': '清空记录',
      'process.reset.confirm': '清空本工作区的建模步骤记录？（不会改模型文件；清空后当前模型会重新记为基线）',
      'process.image.empty': '点「生成过程图」按步骤着色画一张全过程图（同时写入 <workspace>/.sysml-viz/history/timeline.svg）。',
      'process.image.loading': '正在生成过程图…',
      'process.image.failed': '生成失败：{error}',
      'process.session.added': '本会话 +{n}',
      'process.session.tip': '本会话新增/修改的元素会一直用绿色描边标出（不依赖 20 秒的闪现）。',
      'process.history.error': '读取过程记录失败：{error}',
    }

    const EN = {
      'type.label': 'Model View',
      'guide.title': 'Model View',
      'guide.description': 'Model tree + structure / IBD / requirements / state diagrams + modeling status',
      title: 'Model View',
      'tree.hierarchy': 'Hierarchy',
      'tree.category': 'Category',
      'tree.toggle': 'Tree',
      'header.open': 'Open Model View',
      'status.modeling': 'Modeling',
      'status.synced': 'Model',
      'status.age': '· {age} ago',
      'status.tip': 'Derived from the model file mtime (last write), not network latency: the view polls /model every {ms}ms and swaps when the file changes; a growing number just means the model has been idle.',
      'status.updated': 'updated {age} ago',
      'status.added': '+{count} new',
      'status.added.tip': 'Elements added by the latest change; fades after ~20s. Use the Process tab for lasting per-step traceability.',
      'rev.tip': 'IR sha256: {sha}',
      'stats': '{elements} elements · {relations} relations',
      'source.python': 'Source: graph.py',
      'source.js': 'Source: built-in JS',
      'poll': 'poll {ms}ms',
      'zoom.in': 'Zoom in',
      'zoom.out': 'Zoom out',
      'zoom.fit': 'Fit',
      'refresh': 'Refresh',
      loading: 'Reading model…',
      'error.title': 'Model view unavailable',
      'error.retry': 'Retry',
      'error.network': 'Cannot reach /api/sysml-viz/model. Check that the host half is active.',
      'error.searched': 'Searched:',
      'error.poll': 'Refresh failed; showing the last successful data.',
      'empty.title': 'No drawable views',
      'empty.hint': 'The IR has no PartDefinition / Requirement / StateDefinition elements to project.',
      'canvas.hint': 'Click a node for its element ID; scroll to zoom, drag to pan; hover to locate it in the tree.',
      selected: 'Selected: {label}',
      'model.path': 'Model: {path}',
      'view.nodes': '{nodes} nodes / {edges} edges',
      'kinds.structure': 'Structure',
      'kinds.ibd': 'IBD',
      'kinds.requirement': 'Requirements',
      'kinds.state': 'State',
      'kinds.param': 'Parameters',
      'kinds.action': 'Action',
      'legend.node': 'Element',
      'legend.trace': 'Trace',
      'legend.flow': 'Flow',
      'legend.state': 'Transition',
      'legend.session': 'Added this session',
      'process.tab': 'Process',
      'process.title': 'Modeling process',
      'process.hint': 'One step per semantic model change; colors distinguish steps so you can trace what each round of dialogue added.',
      'process.empty': 'No steps yet. The next model change is recorded automatically as step 1; you can also reset the record from the current model.',
      'process.disabled': 'Process recording is disabled (host config history: false).',
      'process.steps': '{n} steps',
      'process.updated': 'updated {time}',
      'process.baseline': 'Baseline',
      'process.step': 'Step {n}',
      'process.added': '+{n}',
      'process.changed': '~{n}',
      'process.removed': '-{n}',
      'process.session': 'session {id}',
      'process.session.now': 'this session',
      'process.reconstructed': 'rebuilt',
      'process.turn': 'turn {n}',
      'process.generate': 'Generate process diagram',
      'process.regenerate': 'Regenerate',
      'process.open': 'Open in new tab',
      'process.reset': 'Reset record',
      'process.reset.confirm': 'Clear the modeling step record for this workspace? (The model file is not touched; the current model becomes the new baseline.)',
      'process.image.empty': 'Click “Generate process diagram” to render a step-colored SVG (also written to <workspace>/.sysml-viz/history/timeline.svg).',
      'process.image.loading': 'Generating process diagram…',
      'process.image.failed': 'Generation failed: {error}',
      'process.session.added': 'This session +{n}',
      'process.session.tip': 'Elements added/changed by this session keep a green outline instead of a 20s flash.',
      'process.history.error': 'Failed to read process record: {error}',
    }

    const DICTS = { zh: ZH, en: EN }
    const LANG = (() => {
      try {
        const language = String((typeof navigator !== 'undefined' && navigator.language) || 'zh').toLowerCase()
        return language.startsWith('zh') ? 'zh' : 'en'
      } catch {
        return 'zh'
      }
    })()

    function dictText(key, params) {
      const dict = DICTS[LANG] || ZH
      let text = dict[key] ?? ZH[key] ?? key
      if (params && typeof params === 'object') {
        for (const [name, value] of Object.entries(params)) text = text.replaceAll(`{${name}}`, String(value))
      }
      return text
    }

    /* ============================================================ *
     * 样式（只用宿主主题 token，diagram 的语义色属于图稿）
     * ============================================================ */

    const CSS = `
.svz-root{display:flex;flex-direction:column;height:100%;min-height:0;min-width:0;color:var(--dsw-alias-label-primary,#e6e8eb);background:var(--dsw-alias-bg-base,#14161a);font-size:12px;line-height:1.5;
  --svz-border:var(--dsw-alias-border-l3,#333a45);--svz-layer1:var(--dsw-alias-bg-layer-1,#1b1e24);--svz-layer2:var(--dsw-alias-bg-layer-2,#20242b);--svz-layer3:var(--dsw-alias-bg-layer-3,#242933);
  --svz-label:var(--dsw-alias-label-primary,#e6e8eb);--svz-label2:var(--dsw-alias-label-secondary,#9aa3ad);--svz-label3:var(--dsw-alias-label-tertiary,#6c7683);--svz-hover:var(--dsw-alias-interactive-bg-hover,#262b34);}
.svz-root *{box-sizing:border-box}
.svz-header{flex:none;display:flex;align-items:center;gap:7px;flex-wrap:wrap;padding:7px 9px;border-bottom:1px solid var(--svz-border);background:var(--svz-layer1)}
.svz-title{display:flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;white-space:nowrap}
.svz-title .svz-logo{width:15px;height:15px;border-radius:4px;display:grid;place-items:center;background:linear-gradient(145deg,#2c6bff,#7c5cff);color:#fff;font-size:9px;flex:none}
.svz-badge{display:inline-flex;align-items:center;gap:4px;height:19px;padding:0 6px;border-radius:4px;border:1px solid var(--svz-border);background:var(--svz-layer2);color:var(--svz-label2);font-size:10px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap}
.svz-badge.rev{color:#8fb6ff}
.svz-badge.new{color:#79c98f;border-color:rgba(63,185,80,.35)}
.svz-status{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;color:var(--svz-label3);white-space:nowrap}
.svz-dot{width:6px;height:6px;border-radius:50%;background:#3fb950;flex:none}
.svz-status.modeling{color:var(--dsw-alias-state-warn-label,#e0b155)}
.svz-status.modeling .svz-dot{background:#d29922;animation:svzPulse 1.1s ease-in-out infinite}
@keyframes svzPulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.45;transform:scale(.8)}}
.svz-spacer{flex:1 1 auto;min-width:4px}
.svz-btn{display:inline-flex;align-items:center;justify-content:center;gap:4px;height:23px;min-width:23px;padding:0 7px;border-radius:5px;border:1px solid var(--svz-border);background:var(--svz-layer2);color:var(--svz-label2);font-size:11px;cursor:pointer;white-space:nowrap}
.svz-btn:hover{color:var(--svz-label);background:var(--svz-hover)}
.svz-btn.on{color:#cfe0ff;border-color:rgba(76,141,255,.5);background:rgba(76,141,255,.14)}
.svz-main{flex:1 1 auto;display:flex;min-height:0;min-width:0;position:relative}
.svz-tree{flex:none;width:212px;min-width:180px;max-width:290px;overflow:auto;border-right:1px solid var(--svz-border);padding:5px 3px 16px;background:var(--svz-layer1)}
.svz-treehead{display:flex;gap:4px;align-items:center;padding:2px 5px 7px}
.svz-tab-btn{font-size:10.5px;padding:2px 8px;border-radius:5px;color:var(--svz-label3);cursor:pointer;border:1px solid transparent}
.svz-tab-btn:hover{color:var(--svz-label)}
.svz-tab-btn.on{background:var(--svz-hover);color:var(--svz-label);border-color:var(--svz-border)}
.svz-tnode{display:flex;align-items:center;gap:4px;padding:2.5px 5px;border-radius:5px;cursor:pointer;white-space:nowrap;overflow:hidden;font-size:11.5px;color:var(--svz-label2)}
.svz-tnode:hover{background:var(--svz-hover);color:var(--svz-label)}
.svz-tnode.hov{background:rgba(76,141,255,.13);color:#d7e6ff;box-shadow:inset 2px 0 0 #4c8dff}
.svz-tnode.sel{background:rgba(76,141,255,.16);color:#cfe0ff}
.svz-tnode .svz-caret{width:10px;flex:none;text-align:center;color:var(--svz-label3);font-size:9px}
.svz-tnode .svz-ico{width:13px;flex:none;text-align:center;color:#8fb6ff;font-size:10px}
.svz-tnode.view .svz-ico{color:#c9b8ff}
.svz-tnode .svz-lbl{overflow:hidden;text-overflow:ellipsis}
.svz-tnode .svz-cnt{margin-left:auto;color:var(--svz-label3);font-size:9px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;padding-left:4px}
.svz-canvas-col{flex:1 1 auto;display:flex;flex-direction:column;min-width:0;min-height:0}
.svz-viewbar{flex:none;display:flex;align-items:center;gap:5px;padding:5px 7px;border-bottom:1px solid var(--svz-border);overflow:hidden}
.svz-viewchips{flex:1 1 auto;display:flex;align-items:center;gap:5px;min-width:0;overflow-x:auto;scrollbar-width:thin}
.svz-viewchip{flex:none;display:inline-flex;align-items:center;gap:5px;height:22px;padding:0 8px;border-radius:11px;border:1px solid var(--svz-border);background:transparent;color:var(--svz-label2);font-size:10.5px;cursor:pointer;white-space:nowrap}
.svz-viewchip:hover{color:var(--svz-label);border-color:var(--svz-label3)}
.svz-viewchip.on{color:#cfe0ff;border-color:rgba(76,141,255,.55);background:rgba(76,141,255,.14)}
.svz-viewchip .svz-kdot{width:5px;height:5px;border-radius:50%;flex:none}
.svz-zoombar{margin-left:auto;display:flex;align-items:center;gap:3px;flex:none}
.svz-zoomval{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:9.5px;color:var(--svz-label3);min-width:34px;text-align:center}
.svz-canvas-wrap{flex:1 1 auto;min-height:0;overflow:hidden;position:relative;background:var(--dsw-alias-bg-base,#14161a);cursor:grab;touch-action:none;user-select:none}
.svz-canvas-wrap.dragging{cursor:grabbing}
.svz-canvas-wrap.dragging *{cursor:grabbing!important}
.svz-canvas-stage{position:absolute;left:0;top:0;transform-origin:0 0;will-change:transform}
.svz-svg{display:block;margin:0}
.svz-loading,.svz-empty,.svz-error{flex:1 1 auto;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;padding:24px;text-align:center;color:var(--svz-label2);min-height:0}
.svz-loading .svz-spin{width:16px;height:16px;border-radius:50%;border:2px solid var(--svz-border);border-top-color:#4c8dff;animation:svzSpin .8s linear infinite}
@keyframes svzSpin{to{transform:rotate(360deg)}}
.svz-error .svz-errcode{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10px;color:var(--dsw-alias-state-warn-label,#e0b155);border:1px solid rgba(210,153,34,.32);background:rgba(210,153,34,.08);border-radius:4px;padding:1px 6px}
.svz-error .svz-errmsg{max-width:520px;font-size:11.5px;line-height:1.6;color:var(--svz-label2);word-break:break-word}
.svz-error .svz-searched{max-width:560px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:9.5px;color:var(--svz-label3);line-height:1.7;word-break:break-all}
.svz-banner{flex:none;display:flex;align-items:center;gap:6px;padding:3px 9px;font-size:10.5px;color:var(--dsw-alias-state-warn-label,#e0b155);background:rgba(210,153,34,.08);border-bottom:1px solid rgba(210,153,34,.28)}
.svz-statusbar{flex:none;display:flex;align-items:center;gap:9px;padding:3px 9px;border-top:1px solid var(--svz-border);font-size:10px;color:var(--svz-label3);background:var(--svz-layer1);overflow:hidden;white-space:nowrap}
.svz-statusbar .svz-sel{color:var(--svz-label2);overflow:hidden;text-overflow:ellipsis}
.svz-legend{display:flex;align-items:center;gap:7px;margin-left:auto;flex:none}
.svz-legend i{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:3px;vertical-align:middle}
.svz-legend .svz-lg-node i{background:#5b9dff}
.svz-legend .svz-lg-trace i{background:#3fb950}
.svz-legend .svz-lg-flow i{background:#d29922}
.svz-legend .svz-lg-state i{background:#8b95a1}
/* --------- 图稿（SVG） --------- */
.svz-svg text{font-family:inherit;user-select:none}
.svz-group .svz-gbg{fill:none;stroke:var(--dsw-alias-border-l3,#3a424e);stroke-width:1;stroke-dasharray:6 5;opacity:.85}
.svz-group .svz-glabel{font-size:10px;font-style:italic;fill:var(--svz-label3)}
.svz-node{cursor:pointer}
.svz-node .svz-nbg{fill:var(--svz-layer1,#1b1e24);stroke:var(--dsw-alias-border-l3,#3a424e);stroke-width:1.1;transition:stroke .12s}
.svz-node:hover .svz-nbg{stroke:var(--svz-label3,#6c7683)}
.svz-node.svz-hov .svz-nbg{stroke:#6ea8ff;stroke-width:1.8;filter:drop-shadow(0 0 3px rgba(76,141,255,.45))}
.svz-node.svz-sel .svz-nbg{stroke:#4c8dff;stroke-width:2}
.svz-node.svz-new .svz-nbg{animation:svzNew 1.5s ease-out 2}
@keyframes svzNew{0%{stroke:#4c8dff;stroke-width:2.6}100%{stroke:var(--dsw-alias-border-l3,#3a424e);stroke-width:1.1}}
.svz-node.svz-k-requirement .svz-nbg{stroke:#3e5c46}
.svz-node.svz-k-usage .svz-nbg{stroke-dasharray:5 4}
.svz-node.svz-k-state .svz-nbg{stroke:#485274}
.svz-node.svz-k-constraint .svz-nbg{stroke:#5a4a37}
.svz-node.svz-k-attr .svz-nbg{stroke:#3f4a57}
.svz-node.svz-k-trace .svz-nbg{fill:var(--svz-layer2,#20242b);stroke:#3a4450}
.svz-node.svz-k-init .svz-nbg{fill:#3fb950;stroke:#9fe8b0}
.svz-l-st{font-size:10.5px;font-style:italic;fill:#8fb6ff}
.svz-k-requirement .svz-l-st{fill:#79c98f}
.svz-k-constraint .svz-l-st{fill:#e0b155}
.svz-k-state .svz-l-st{fill:#a8a2ff}
.svz-k-attr .svz-l-st{fill:#9fb6cc}
.svz-k-usage .svz-l-st{fill:#9fb6cc}
.svz-l-ttl{font-size:13.5px;font-weight:600;fill:var(--svz-label,#eef1f5)}
.svz-l-sub{font-size:10px;fill:var(--svz-label3,#8792a0);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.svz-l-bd{font-size:10.5px;fill:var(--svz-label2,#b8c1cb)}
.svz-l-kv{font-size:10.5px;fill:var(--svz-label2,#9aa3ad);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.svz-l-val{font-size:12.5px;font-weight:600;fill:#9fd1ff;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.svz-l-note{font-size:10.5px;fill:var(--svz-label3,#8d97a3)}
.svz-l-chk{font-size:11px;font-weight:600;fill:#3fb950}
.svz-divline{stroke:var(--dsw-alias-border-l3,#2f3641);stroke-width:1}
.svz-ep{fill:none;stroke:#68727f;stroke-width:1.2;stroke-linejoin:round}
.svz-ep-comp{stroke:#6b7686;stroke-dasharray:4 4}
.svz-ep-dep{stroke:#7d8794;stroke-dasharray:4 4}
.svz-ep-trace{stroke:#3fb950;stroke-dasharray:5 4;stroke-width:1.15}
.svz-ep-verify{stroke:#4c8dff;stroke-dasharray:5 4;stroke-width:1.15}
.svz-ep-flow-el{stroke:#4c8dff;stroke-width:1.5}
.svz-ep-flow-mech{stroke:#d29922;stroke-width:1.5}
.svz-ep-trans{stroke:#8b95a1;stroke-width:1.15}
.svz-ep-link{stroke:#8f7cf0;stroke-dasharray:2 4;stroke-width:1.15}
.svz-arrow-dep{fill:#8b95a1}
.svz-arrow-comp{fill:#6b7686}
.svz-arrow-trace{fill:#3fb950}
.svz-arrow-verify{fill:#4c8dff}
.svz-arrow-flow-el{fill:#4c8dff}
.svz-arrow-flow-mech{fill:#d29922}
.svz-arrow-trans{fill:#8b95a1}
.svz-arrow-link{fill:#8f7cf0}
.svz-elabel{font-size:10px;fill:var(--svz-label2,#a4adba);paint-order:stroke;stroke:var(--dsw-alias-bg-base,#14161a);stroke-width:3px;stroke-linejoin:round}
.svz-elabel-flow-el{fill:#8fb6ff}
.svz-elabel-flow-mech{fill:#e0b155}
.svz-elabel-trace{fill:#7fd18f}
.svz-elabel-verify{fill:#8fb6ff}
.svz-esub{font-size:9px;fill:var(--svz-label3,#8a93a0);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;paint-order:stroke;stroke:var(--dsw-alias-bg-base,#14161a);stroke-width:3px}
/* --------- 过程（建模全过程） --------- */
.svz-badge.session{color:#79c98f;border-color:rgba(63,185,80,.45);background:rgba(63,185,80,.12);cursor:pointer}
.svz-badge.session:hover{background:rgba(63,185,80,.2)}
.svz-status.stale{color:var(--dsw-alias-state-warn-label,#e0b155)}
.svz-status.stale .svz-dot{background:#d29922}
.svz-viewchip.process .svz-kdot{background:#79c98f}
.svz-viewchip.process .svz-chipcount{font-size:9px;color:var(--svz-label3)}
.svz-process{flex:1 1 auto;display:flex;flex-direction:column;gap:8px;min-height:0;padding:8px 10px;overflow:auto}
.svz-proc-toolbar{flex:none;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.svz-proc-title{font-weight:600;font-size:12px;color:var(--svz-label)}
.svz-proc-meta{font-size:9.5px;color:var(--svz-label3);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.svz-proc-hint{color:var(--svz-label3);font-size:10.5px;padding:18px 12px;text-align:center;line-height:1.6}
.svz-proc-steps{flex:0 1 auto;max-height:44%;min-height:56px;overflow:auto;border:1px solid var(--svz-border);border-radius:6px;background:var(--svz-layer1)}
.svz-step{display:flex;align-items:flex-start;gap:8px;padding:6px 8px;border-top:1px solid var(--svz-border);font-size:11px}
.svz-step:first-child{border-top:none}
.svz-step.this{background:rgba(63,185,80,.06)}
.svz-swatch{width:12px;height:12px;border-radius:3px;flex:none;margin-top:2px}
.svz-step-main{display:flex;flex-direction:column;gap:2px;min-width:0}
.svz-step-head{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.svz-step-name{font-weight:600;color:var(--svz-label);white-space:nowrap}
.svz-step-time{color:var(--svz-label3);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:9.5px;white-space:nowrap}
.svz-chip{display:inline-flex;align-items:center;gap:3px;height:15px;padding:0 4px;border-radius:3px;font-size:9px;border:1px solid var(--svz-border);color:var(--svz-label3);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
.svz-chip.add{color:#79c98f;border-color:rgba(63,185,80,.3)}
.svz-chip.chg{color:#e0b155;border-color:rgba(210,153,34,.3)}
.svz-chip.del{color:#e07a7a;border-color:rgba(224,122,122,.3)}
.svz-chip.sess{color:#8fb6ff;border-color:rgba(76,141,255,.3)}
.svz-chip.now{color:#79c98f;border-color:rgba(63,185,80,.45);background:rgba(63,185,80,.1)}
.svz-step-names{color:var(--svz-label2);font-size:10px;word-break:break-word;line-height:1.5}
.svz-proc-image{flex:1 1 auto;min-height:140px;border:1px solid var(--svz-border);border-radius:6px;background:#fff;overflow:auto;display:flex;align-items:flex-start;justify-content:center;padding:4px}
.svz-proc-image img{max-width:100%;height:auto;display:block}
.svz-node.svz-session .svz-nbg{stroke:#79c98f;stroke-width:1.8;stroke-dasharray:5 3}
`

    /** header 按钮的最小样式（不依赖 tab 正文是否已挂载）。 */
    const HEADER_CSS = `
.svz-hbtn{display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 7px;border-radius:6px;border:1px solid transparent;background:transparent;color:var(--dsw-alias-label-secondary,#9aa3ad);font-family:inherit;font-size:11.5px;line-height:1;white-space:nowrap;cursor:pointer}
.svz-hbtn:hover{color:var(--dsw-alias-label-primary,#e6e8eb);background:var(--dsw-alias-interactive-bg-hover,#262b34);border-color:var(--dsw-alias-border-l3,#333a45)}
.svz-hbtn:focus-visible{outline:2px solid #4c8dff;outline-offset:1px}
.svz-hbtn .svz-hico{font-size:11px;line-height:1;color:#8fb6ff}
`

    /* ============================================================ *
     * 几何 / 绘制辅助
     * ============================================================ */

    const LINE_H = { st: 13, ttl: 19, sub: 13, div: 10, bd: 14, kv: 13, val: 18, note: 13, chk: 15 }
    const EDGE_KINDS = ['comp', 'dep', 'trace', 'verify', 'flow-el', 'flow-mech', 'trans', 'link']
    const VIEW_KIND_COLOR = {
      structure: '#5b9dff',
      ibd: '#d29922',
      requirement: '#3fb950',
      state: '#8b95a1',
      param: '#8f7cf0',
      action: '#4c8dff',
    }
    const NODE_ICON = {
      requirement: '≡',
      state: '◉',
      trace: '⌁',
      attr: 'ƒ',
      constraint: '∑',
      usage: '▪',
      block: '▣',
      action: '▶',
      init: '●',
    }

    const fmt = (number) => {
      const value = Math.round(number * 10) / 10
      return Number.isInteger(value) ? String(value) : value.toFixed(1)
    }

    function dedupePoints(points) {
      const out = []
      for (const point of points) {
        if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) continue
        const previous = out[out.length - 1]
        if (previous && Math.abs(previous.x - point.x) < 0.5 && Math.abs(previous.y - point.y) < 0.5) continue
        out.push(point)
      }
      return out
    }

    function roundedPath(points, radius) {
      const pts = dedupePoints(points)
      if (pts.length === 0) return ''
      if (pts.length === 1) return `M${fmt(pts[0].x)},${fmt(pts[0].y)}`
      let d = `M${fmt(pts[0].x)},${fmt(pts[0].y)}`
      for (let index = 1; index < pts.length - 1; index += 1) {
        const previous = pts[index - 1]
        const current = pts[index]
        const next = pts[index + 1]
        const inLength = Math.hypot(current.x - previous.x, current.y - previous.y)
        const outLength = Math.hypot(next.x - current.x, next.y - current.y)
        if (inLength < 0.01 || outLength < 0.01) continue
        const r = Math.min(radius, inLength / 2, outLength / 2)
        if (r < 1) {
          d += ` L${fmt(current.x)},${fmt(current.y)}`
          continue
        }
        const inX = (current.x - previous.x) / inLength
        const inY = (current.y - previous.y) / inLength
        const outX = (next.x - current.x) / outLength
        const outY = (next.y - current.y) / outLength
        d += ` L${fmt(current.x - inX * r)},${fmt(current.y - inY * r)}`
        d += ` Q${fmt(current.x)},${fmt(current.y)} ${fmt(current.x + outX * r)},${fmt(current.y + outY * r)}`
      }
      const last = pts[pts.length - 1]
      d += ` L${fmt(last.x)},${fmt(last.y)}`
      return d
    }

    function anchorOf(node, side, offset) {
      const off = Math.min(0.95, Math.max(0.05, Number.isFinite(offset) ? offset : 0.5))
      if (side === 't') return { x: node.x + node.w * off, y: node.y }
      if (side === 'b') return { x: node.x + node.w * off, y: node.y + node.h }
      if (side === 'l') return { x: node.x, y: node.y + node.h * off }
      return { x: node.x + node.w, y: node.y + node.h * off }
    }

    function outwardPoint(point, side, distance) {
      if (side === 'r') return { x: point.x + distance, y: point.y }
      if (side === 'l') return { x: point.x - distance, y: point.y }
      if (side === 'b') return { x: point.x, y: point.y + distance }
      return { x: point.x, y: point.y - distance }
    }

    function sideAxis(side) {
      return side === 'l' || side === 'r' ? 'h' : 'v'
    }

    function chooseSides(a, b) {
      const dx = (a.x + a.w / 2) - (b.x + b.w / 2)
      const dy = (a.y + a.h / 2) - (b.y + b.h / 2)
      if (Math.abs(dx) >= Math.abs(dy)) {
        return dx > 0 ? { fromSide: 'l', toSide: 'r' } : { fromSide: 'r', toSide: 'l' }
      }
      return dy > 0 ? { fromSide: 't', toSide: 'b' } : { fromSide: 'b', toSide: 't' }
    }

    function routePoints(fromNode, toNode, fromSide, toSide) {
      const start = anchorOf(fromNode, fromSide, 0.5)
      const end = anchorOf(toNode, toSide, 0.5)
      const stub = 14
      const p1 = outwardPoint(start, fromSide, stub)
      const p2 = outwardPoint(end, toSide, stub)
      const points = [start, p1]
      const axisA = sideAxis(fromSide)
      const axisB = sideAxis(toSide)
      if (axisA === 'h' && axisB === 'h') {
        const middleX = (p1.x + p2.x) / 2
        points.push({ x: middleX, y: p1.y }, { x: middleX, y: p2.y })
      } else if (axisA === 'v' && axisB === 'v') {
        const middleY = (p1.y + p2.y) / 2
        points.push({ x: p1.x, y: middleY }, { x: p2.x, y: middleY })
      } else if (axisA === 'h') {
        points.push({ x: p2.x, y: p1.y })
      } else {
        points.push({ x: p1.x, y: p2.y })
      }
      points.push(p2, end)
      return dedupePoints(points)
    }

    function pointOnPolyline(points, ratio) {
      if (points.length === 0) return { x: 0, y: 0 }
      if (points.length === 1) return points[0]
      let total = 0
      for (let index = 1; index < points.length; index += 1) {
        total += Math.hypot(points[index].x - points[index - 1].x, points[index].y - points[index - 1].y)
      }
      let target = total * ratio
      for (let index = 1; index < points.length; index += 1) {
        const previous = points[index - 1]
        const current = points[index]
        const length = Math.hypot(current.x - previous.x, current.y - previous.y)
        if (target <= length || index === points.length - 1) {
          const t = length === 0 ? 0 : Math.min(1, target / length)
          return { x: previous.x + (current.x - previous.x) * t, y: previous.y + (current.y - previous.y) * t }
        }
        target -= length
      }
      return points[points.length - 1]
    }

    function truncate(text, maxLength) {
      const value = String(text ?? '')
      if (value.length <= maxLength) return value
      return `${value.slice(0, maxLength - 1)}…`
    }

    const CANVAS_PADDING = 22

    /** 树节点的元素 id：elementId 优先，兼容 def:/el: 前缀 id。 */
    function treeNodeElementId(node) {
      if (!node) return null
      if (node.elementId) return String(node.elementId)
      const id = typeof node.id === 'string' ? node.id : ''
      if (id.startsWith('def:')) return id.slice(4)
      if (id.startsWith('el:')) return id.slice(3)
      return null
    }

    /** 画布 fit 比例：保持不超过自然尺寸，超大图允许缩到 8%。 */
    function computeFitScale(view, size) {
      if (!view) return 1
      const availableW = Math.max(80, size.w - CANVAS_PADDING * 2)
      const availableH = Math.max(80, size.h - CANVAS_PADDING * 2)
      return Math.max(0.08, Math.min(1, Math.min(
        availableW / Math.max(1, view.width),
        availableH / Math.max(1, view.height),
      )))
    }

    function centeredPan(view, size, scale) {
      return {
        x: (size.w - view.width * scale) / 2,
        y: (size.h - view.height * scale) / 2,
      }
    }

    /** 近自由平移：只要求内容至少留 keep 像素可见，范围以居中位置为轴左右对称。 */
    function clampPan(view, size, scale, pan) {
      const contentW = Math.max(1, view.width * scale)
      const contentH = Math.max(1, view.height * scale)
      const keep = Math.max(32, Math.min(120, Math.round(Math.min(size.w, size.h) * 0.15)))
      const axis = (value, viewport, content) => {
        const lo = keep - content
        const hi = viewport - keep
        return Math.min(hi, Math.max(lo, value))
      }
      return { x: axis(pan.x, size.w, contentW), y: axis(pan.y, size.h, contentH) }
    }

    function edgeGeometry(edge, nodeMap) {
      const fromNode = nodeMap.get(edge.from)
      const toNode = nodeMap.get(edge.to)
      if (!fromNode || !toNode) return null
      if (edge.self || edge.from === edge.to) {
        const centerX = fromNode.x + fromNode.w / 2
        const top = fromNode.y
        const points = [
          { x: centerX - 20, y: top },
          { x: centerX - 20, y: top - 34 },
          { x: centerX + 20, y: top - 34 },
          { x: centerX + 20, y: top },
        ]
        const labelAt = Array.isArray(edge.labelAt)
          ? { x: edge.labelAt[0], y: edge.labelAt[1] }
          : { x: centerX, y: top - 46 }
        return { points, labelAt }
      }
      const sides = edge.fromSide && edge.toSide
        ? { fromSide: edge.fromSide, toSide: edge.toSide }
        : chooseSides(fromNode, toNode)
      let points
      if (Array.isArray(edge.via) && edge.via.length > 0) {
        const start = anchorOf(fromNode, sides.fromSide, edge.fromOff)
        const end = anchorOf(toNode, sides.toSide, edge.toOff)
        points = dedupePoints([start, ...edge.via.map((point) => ({ x: point[0], y: point[1] })), end])
      } else {
        const start = anchorOf(fromNode, sides.fromSide, edge.fromOff)
        const end = anchorOf(toNode, sides.toSide, edge.toOff)
        const stub = 14
        const p1 = outwardPoint(start, sides.fromSide, stub)
        const p2 = outwardPoint(end, sides.toSide, stub)
        const routed = [start, p1]
        if (sideAxis(sides.fromSide) === 'h' && sideAxis(sides.toSide) === 'h') {
          const middleX = (p1.x + p2.x) / 2
          routed.push({ x: middleX, y: p1.y }, { x: middleX, y: p2.y })
        } else if (sideAxis(sides.fromSide) === 'v' && sideAxis(sides.toSide) === 'v') {
          const middleY = (p1.y + p2.y) / 2
          routed.push({ x: p1.x, y: middleY }, { x: p2.x, y: middleY })
        } else if (sideAxis(sides.fromSide) === 'h') {
          routed.push({ x: p2.x, y: p1.y })
        } else {
          routed.push({ x: p1.x, y: p2.y })
        }
        routed.push(p2, end)
        points = dedupePoints(routed)
      }
      const labelAt = Array.isArray(edge.labelAt)
        ? { x: edge.labelAt[0], y: edge.labelAt[1] }
        : pointOnPolyline(points, 0.5)
      return { points, labelAt }
    }

    function renderGroup(group) {
      return h('g', { key: group.id, className: 'svz-group' }, [
        h('rect', { key: 'bg', className: 'svz-gbg', x: group.x, y: group.y, width: group.w, height: group.h, rx: 8 }),
        group.label
          ? h('text', { key: 'label', className: 'svz-glabel', x: group.x + 10, y: group.y + 16 }, group.label)
          : null,
      ])
    }

    function renderEdge(edge, nodeMap) {
      const geometry = edgeGeometry(edge, nodeMap)
      if (!geometry) return null
      const label = String(edge.label ?? '')
      const sub = String(edge.sub ?? '')
      const labelY = geometry.labelAt.y - (sub ? 6 : 0)
      return h('g', { key: edge.id, className: 'svz-edge' }, [
        h('path', {
          key: 'path',
          className: `svz-ep svz-ep-${edge.kind}`,
          d: roundedPath(geometry.points, 9),
          markerEnd: `url(#svz-arrow-${edge.kind})`,
        }),
        label
          ? h('text', {
            key: 'label',
            className: `svz-elabel svz-elabel-${edge.kind}`,
            x: geometry.labelAt.x,
            y: labelY,
            textAnchor: 'middle',
          }, truncate(label, 30))
          : null,
        sub
          ? h('text', {
            key: 'sub',
            className: 'svz-esub',
            x: geometry.labelAt.x,
            y: labelY + 12,
            textAnchor: 'middle',
          }, truncate(sub, 38))
          : null,
      ])
    }

    function renderNodeLines(node) {
      const lines = Array.isArray(node.lines) ? node.lines : []
      const total = lines.reduce((sum, line) => sum + (line.c === 'div' ? LINE_H.div : LINE_H[line.c] ?? LINE_H.bd), 0)
      const centered = node.kind === 'state'
      const top = centered ? Math.max(8, (node.h - total) / 2) : 12
      const elements = []
      let offset = top
      lines.forEach((line, index) => {
        if (line.c === 'div') {
          elements.push(h('line', {
            key: `div-${index}`,
            className: 'svz-divline',
            x1: node.x + 12,
            x2: node.x + node.w - 12,
            y1: node.y + offset + 5,
            y2: node.y + offset + 5,
          }))
          offset += LINE_H.div
          return
        }
        const fontSize = line.c === 'ttl' ? 13.5 : (line.c === 'val' ? 12.5 : (line.c === 'st' ? 10.5 : 10.5))
        const text = line.c === 'kv' ? truncate(line.t, Math.max(8, Math.floor((node.w - 24) / fontSize * 1.7))) : line.t
        elements.push(h('text', {
          key: `line-${index}`,
          className: `svz-l-${line.c}`,
          x: centered ? node.x + node.w / 2 : node.x + 12,
          y: node.y + offset + (LINE_H[line.c] ?? LINE_H.bd) - 2,
          textAnchor: centered ? 'middle' : 'start',
        }, String(text)))
        offset += LINE_H[line.c] ?? LINE_H.bd
      })
      return elements
    }

    function renderNode(node, selectedNodeId, addedElementIds, sessionAddedIds, hoveredNodeId, onSelect, onHover) {
      const classes = ['svz-node', `svz-k-${node.kind}`]
      if (selectedNodeId === node.id) classes.push('svz-sel')
      if (hoveredNodeId === node.id) classes.push('svz-hov')
      if (node.elementId && addedElementIds.has(node.elementId)) classes.push('svz-new')
      if (node.elementId && sessionAddedIds.has(node.elementId)) classes.push('svz-session')
      const shape = node.kind === 'state'
        ? h('rect', {
          key: 'bg', className: 'svz-nbg',
          x: node.x, y: node.y, width: node.w, height: node.h, rx: 12,
        })
        : h('rect', {
          key: 'bg', className: 'svz-nbg',
          x: node.x, y: node.y, width: node.w, height: node.h, rx: 7,
        })
      return h('g', {
        key: node.id,
        className: classes.join(' '),
        'data-element-id': node.elementId || undefined,
        onClick: (event) => {
          event.stopPropagation()
          onSelect(node, event)
        },
        onMouseEnter: () => onHover(node),
        onMouseLeave: () => onHover(null, node),
      }, [shape, ...renderNodeLines(node)])
    }

    function renderSvg(view, selectedNodeId, addedElementIds, sessionAddedIds, hoveredNodeId, onSelect, onHover, onBackground) {
      const nodeMap = new Map((view.nodes || []).map((node) => [node.id, node]))
      const groups = Array.isArray(view.groups) ? view.groups : []
      const edges = Array.isArray(view.edges) ? view.edges : []
      const markers = EDGE_KINDS.map((kind) => h('marker', {
        key: kind,
        id: `svz-arrow-${kind}`,
        viewBox: '0 0 8 8',
        refX: 7.4,
        refY: 4,
        markerWidth: 7,
        markerHeight: 7,
        orient: 'auto-start-reverse',
      }, h('path', { d: 'M0,0 L8,4 L0,8 Z', className: `svz-arrow-${kind}` })))
      const children = [
        h('defs', { key: 'defs' }, markers),
        ...groups.map((group) => renderGroup(group)),
        ...edges.map((edge) => renderEdge(edge, nodeMap)).filter(Boolean),
        ...(view.nodes || []).map((node) => renderNode(node, selectedNodeId, addedElementIds, sessionAddedIds, hoveredNodeId, onSelect, onHover)),
      ]
      return h('svg', {
        className: 'svz-svg',
        width: view.width,
        height: view.height,
        viewBox: `0 0 ${view.width} ${view.height}`,
        preserveAspectRatio: 'xMinYMin meet',
        role: 'img',
        'aria-label': view.title,
        onClick: onBackground,
        onMouseLeave: () => onHover(null),
      }, children)
    }

    /* ============================================================ *
     * 主组件
     * ============================================================ */

    function ModelViewBody(props) {
      const safeProps = props && typeof props === 'object' ? props : {}
      // tab 正文由 DSH 传入 sessionId；host 端据此从 ~/.dsh/storages/workspace.json
      // 反查会话真正的工作区（桌面端进程 cwd 是 profile 目录，不能当工作区用）。
      const sessionId = typeof safeProps.sessionId === 'string' ? safeProps.sessionId : ''
      const propT = safeProps.t
      const t = useCallback((key, params) => {
        if (typeof propT === 'function') {
          try {
            const value = propT(key, params)
            if (typeof value === 'string' && value !== key) return value
          } catch {
            /* locale 服务不可用时退回内置字典 */
          }
        }
        return dictText(key, params)
      }, [propT])

      const [model, setModel] = useState(null)
      const [error, setError] = useState(null)
      const [loading, setLoading] = useState(true)
      const [viewId, setViewId] = useState(null)
      const [treeMode, setTreeMode] = useState('hierarchy')
      const [treeOpen, setTreeOpen] = useState(true)
      const [collapsed, setCollapsed] = useState(() => new Set())
      const [selectedNodeId, setSelectedNodeId] = useState(null)
      const [viewTransform, setViewTransform] = useState({ zoom: 1, x: 0, y: 0 })
      const [dragging, setDragging] = useState(false)
      const [hovered, setHovered] = useState(null)
      const [narrow, setNarrow] = useState(false)
      const [canvasSize, setCanvasSize] = useState({ w: 640, h: 480 })
      const [refreshTick, setRefreshTick] = useState(0)
      const [nowTick, setNowTick] = useState(0)
      const [panel, setPanel] = useState('graph')
      const [history, setHistory] = useState(null)
      const [historyError, setHistoryError] = useState(null)
      const [historyTick, setHistoryTick] = useState(0)
      const [timeline, setTimeline] = useState(null)
      const [timelineBusy, setTimelineBusy] = useState(false)
      const revisionRef = useRef(null)
      const rootRef = useRef(null)
      const canvasRef = useRef(null)
      const canvasObserverRef = useRef(null)
      const treeRef = useRef(null)
      const treeTouchedRef = useRef(false)
      const aliveRef = useRef(true)
      const dragRef = useRef(null)
      const suppressClickUntilRef = useRef(0)
      const viewIdRef = useRef(null)
      const activeViewRef = useRef(null)
      const canvasSizeRef = useRef(canvasSize)
      const fitScaleRef = useRef(1)
      const transformRef = useRef(viewTransform)
      const autoExpandedRef = useRef(new Set())
      const hoverRestoreTimerRef = useRef(null)
      const hoverScrollTopRef = useRef(null)

      /** 画布挂载/卸载时接管尺寸观察；模型加载后画布才出现，不能用一次性的 effect。 */
      const setCanvasNode = useCallback((element) => {
        canvasRef.current = element
        if (canvasObserverRef.current) {
          canvasObserverRef.current.disconnect()
          canvasObserverRef.current = null
        }
        if (!element) return
        const apply = (width, height) => {
          if (!(width > 0) || !(height > 0)) return
          setCanvasSize((previous) => (
            Math.abs(previous.w - width) < 1 && Math.abs(previous.h - height) < 1
              ? previous
              : { w: Math.max(120, width), h: Math.max(120, height) }
          ))
        }
        const rect = element.getBoundingClientRect()
        apply(rect.width, rect.height)
        if (typeof ResizeObserver === 'undefined') return
        const observer = new ResizeObserver((entries) => {
          for (const entry of entries) {
            const { width, height } = entry.contentRect
            apply(width, height)
          }
        })
        observer.observe(element)
        canvasObserverRef.current = observer
      }, [])

      // 轮询：2s（host 可配置），失败不清空已有数据
      const pollMs = Math.max(500, Number(model?.config?.pollMs) || FALLBACK_POLL_MS)
      useEffect(() => {
        aliveRef.current = true
        let timer = null
        let aborter = null
        let cancelled = false
        const run = async () => {
          if (cancelled) return
          try {
            if (typeof AbortController !== 'undefined') aborter = new AbortController()
            const revision = revisionRef.current
            const params = []
            if (sessionId) params.push(`sessionId=${encodeURIComponent(sessionId)}`)
            if (revision) params.push(`rev=${encodeURIComponent(revision)}`)
            const url = params.length > 0 ? `${API_MODEL}?${params.join('&')}` : API_MODEL
            const controller = aborter
            const timeout = setTimeout(() => {
              try {
                controller?.abort()
              } catch {
                /* 忽略 */
              }
            }, 8000)
            const response = await fetch(url, { cache: 'no-store', signal: controller?.signal })
            clearTimeout(timeout)
            if (cancelled) return
            const payload = await response.json()
            if (cancelled) return
            if (payload && payload.ok === true && payload.changed === false) {
              revisionRef.current = payload.revision || revisionRef.current
              setModel((previous) => (previous ? {
                ...previous,
                modeling: payload.modeling || previous.modeling,
                config: payload.config || previous.config,
                generatedAt: payload.generatedAt || previous.generatedAt,
                diff: payload.diff ?? previous.diff,
              } : previous))
              setError(null)
            } else if (payload && payload.ok === true) {
              revisionRef.current = payload.modelRef?.revision || revisionRef.current
              setModel(payload)
              setError(null)
              setLoading(false)
              return
            } else {
              setError(payload?.error ? payload : { code: 'UNKNOWN_ERROR', message: dictText('error.network') })
              setLoading(false)
            }
          } catch (failure) {
            if (cancelled) return
            if (failure && failure.name === 'AbortError') {
              setError({ code: 'TIMEOUT', message: dictText('error.network') })
            } else {
              setError({ code: 'NETWORK_ERROR', message: dictText('error.network') })
            }
            setLoading(false)
          } finally {
            if (!cancelled) timer = setTimeout(run, pollMs)
          }
        }
        run()
        return () => {
          cancelled = true
          aliveRef.current = false
          if (timer) clearTimeout(timer)
          try {
            aborter?.abort()
          } catch {
            /* 忽略 */
          }
        }
      }, [pollMs, refreshTick, sessionId])

      // 每秒刷新一次「x 秒前更新」显示
      useEffect(() => {
        const timer = setInterval(() => setNowTick((value) => value + 1), 1000)
        return () => clearInterval(timer)
      }, [])

      // 建模过程记录：模型修订变化 / 切到「过程」/ 手动刷新时同步（低频，不跟 2s 轮询）
      useEffect(() => {
        let cancelled = false
        const load = async () => {
          try {
            const params = []
            if (sessionId) params.push(`sessionId=${encodeURIComponent(sessionId)}`)
            const url = params.length > 0 ? `${API_HISTORY}?${params.join('&')}` : API_HISTORY
            const response = await fetch(url, { cache: 'no-store' })
            const payload = await response.json()
            if (cancelled) return
            if (payload && payload.ok === true) {
              setHistory(payload)
              setHistoryError(null)
            } else {
              setHistoryError(payload?.error?.message || `HTTP ${response.status}`)
            }
          } catch (failure) {
            if (!cancelled) setHistoryError(String(failure?.message ?? failure))
          }
        }
        load()
        return () => {
          cancelled = true
        }
      }, [sessionId, model?.modelRef?.revision, historyTick, panel])

      // 视图选中项回落
      const views = Array.isArray(model?.views) ? model.views : []
      useEffect(() => {
        if (views.length === 0) {
          if (viewId !== null) setViewId(null)
          return
        }
        if (!viewId || !views.some((view) => view.viewId === viewId)) {
          setViewId(views[0].viewId)
          setSelectedNodeId(null)
        }
      }, [views, viewId])

      const activeView = views.find((view) => view.viewId === viewId) || views[0] || null

      // 窄宽度：自动收起模型树
      useEffect(() => {
        const element = rootRef.current
        if (!element || typeof ResizeObserver === 'undefined') return undefined
        const observer = new ResizeObserver((entries) => {
          for (const entry of entries) {
            const width = entry.contentRect.width
            setNarrow(width < 560)
            if (!treeTouchedRef.current) setTreeOpen(width >= 560)
          }
        })
        observer.observe(element)
        return () => observer.disconnect()
      }, [])

      // 视图切换时回到 fit；尺寸变化时保持用户缩放，只夹紧平移
      useEffect(() => {
        if (!activeView) return
        const nextFit = computeFitScale(activeView, canvasSize)
        const viewChanged = viewIdRef.current !== activeView.viewId
        viewIdRef.current = activeView.viewId
        setViewTransform((previous) => {
          if (viewChanged || Math.abs(previous.zoom - 1) < 0.001) {
            return { zoom: 1, ...centeredPan(activeView, canvasSize, nextFit) }
          }
          const nextScale = Math.max(0.05, Math.min(4, nextFit * previous.zoom))
          const nextPan = clampPan(activeView, canvasSize, nextScale, previous)
          return { ...previous, x: nextPan.x, y: nextPan.y }
        })
      }, [activeView?.viewId, activeView?.width, activeView?.height, canvasSize.w, canvasSize.h])

      // 切视图/切面板时清掉拖拽与悬停
      useEffect(() => {
        dragRef.current = null
        setDragging(false)
        setHovered(null)
      }, [activeView?.viewId, panel])

      // 滚轮缩放：原生监听（React 的 onWheel 不能可靠 preventDefault）
      useEffect(() => {
        if (panel !== 'graph') return undefined
        const element = canvasRef.current
        if (!element) return undefined
        const onWheel = (event) => {
          const view = activeViewRef.current
          if (!view) return
          event.preventDefault()
          const rawDelta = event.deltaY || event.deltaX
          if (!rawDelta) return
          const delta = event.deltaMode === 1 ? rawDelta * 16 : (event.deltaMode === 2 ? rawDelta * 100 : rawDelta)
          const factor = Math.exp(-delta * 0.0015)
          const rect = element.getBoundingClientRect()
          const anchorX = event.clientX - rect.left
          const anchorY = event.clientY - rect.top
          setViewTransform((previous) => {
            const nextZoom = Math.max(0.25, Math.min(4, previous.zoom * factor))
            const oldScale = Math.max(0.05, Math.min(4, fitScaleRef.current * previous.zoom))
            const nextScale = Math.max(0.05, Math.min(4, fitScaleRef.current * nextZoom))
            const ratio = nextScale / oldScale
            const x = anchorX - (anchorX - previous.x) * ratio
            const y = anchorY - (anchorY - previous.y) * ratio
            const nextPan = clampPan(view, canvasSizeRef.current, nextScale, { x, y })
            return { zoom: nextZoom, x: nextPan.x, y: nextPan.y }
          })
        }
        element.addEventListener('wheel', onWheel, { passive: false })
        return () => element.removeEventListener('wheel', onWheel)
      }, [panel, activeView?.viewId, views.length])

      const diff = model?.diff && model.diff.at ? model.diff : null
      const diffFresh = diff ? (Date.now() - Date.parse(diff.at)) < NEW_HIGHLIGHT_MS : false
      const addedElementIds = useMemo(() => {
        if (!diffFresh || !diff || !Array.isArray(diff.added)) return new Set()
        return new Set(diff.added)
      }, [diffFresh, diff?.at, diff?.added?.join(','), nowTick])
      // 本会话新增/修改的元素：来自 /history 的持久会话归属（不是 20s 闪现）
      const sessionAddedIds = useMemo(
        () => new Set(Array.isArray(history?.session?.addedIds) ? history.session.addedIds : []),
        [history?.session?.addedIds?.join(',')],
      )
      const sessionAddedCount = sessionAddedIds.size
      // 元素 id → 展示名（过程面板里把 id 翻成名字）
      const elementLabels = useMemo(() => {
        const map = new Map()
        for (const view of views) {
          for (const node of view.nodes || []) {
            if (node.elementId && !map.has(node.elementId)) map.set(node.elementId, node.label || node.elementId)
          }
        }
        return map
      }, [views])

      const tree = model?.tree && typeof model.tree === 'object' ? model.tree : null
      const activeTree = treeMode === 'category' ? tree?.category : tree?.hierarchy

      // 树索引：elementId → 节点/祖先路径；viewId → 视图行
      const treeIndex = useMemo(() => {
        const byElement = new Map()
        const byView = new Map()
        const walk = (node, ancestors) => {
          if (!node) return
          const elementId = treeNodeElementId(node)
          if (elementId) {
            if (!byElement.has(elementId)) byElement.set(elementId, [])
            byElement.get(elementId).push({ node, ancestors })
          }
          if (node.view) byView.set(node.view, { node, ancestors })
          const children = Array.isArray(node.children) ? node.children : []
          for (const child of children) walk(child, [...ancestors, node])
        }
        if (activeTree) walk(activeTree, [])
        return { byElement, byView }
      }, [activeTree])

      const hoverHighlight = useMemo(() => {
        const ids = new Set()
        const hiddenAncestors = new Set()
        if (!hovered) return { ids, hiddenAncestors }
        if (treeMode === 'hierarchy' && hovered.elementId) {
          for (const entry of treeIndex.byElement.get(hovered.elementId) || []) {
            ids.add(entry.node.id)
            for (const ancestor of entry.ancestors) {
              if (collapsed.has(ancestor.id)) hiddenAncestors.add(ancestor.id)
            }
          }
        } else if (treeMode === 'category' && hovered.viewId) {
          const entry = treeIndex.byView.get(hovered.viewId)
          if (entry) {
            ids.add(entry.node.id)
            for (const ancestor of entry.ancestors) {
              if (collapsed.has(ancestor.id)) hiddenAncestors.add(ancestor.id)
            }
          }
        }
        return { ids, hiddenAncestors }
      }, [hovered, treeMode, treeIndex, collapsed])

      // 折叠分支里的目标：延迟展开祖先，并记下是哪些被临时展开
      useEffect(() => {
        if (!hovered || hoverHighlight.hiddenAncestors.size === 0) return undefined
        const timer = setTimeout(() => {
          if (hoverScrollTopRef.current === null && treeRef.current) {
            hoverScrollTopRef.current = treeRef.current.scrollTop
          }
          setCollapsed((previous) => {
            let changed = false
            const next = new Set(previous)
            for (const id of hoverHighlight.hiddenAncestors) {
              if (next.delete(id)) {
                autoExpandedRef.current.add(id)
                changed = true
              }
            }
            return changed ? next : previous
          })
        }, 150)
        return () => clearTimeout(timer)
      }, [hovered, hoverHighlight])

      // 鼠标离开图后，把为了高亮而临时展开的分支收回；防抖避免节点间移动时闪烁
      useEffect(() => {
        if (hoverRestoreTimerRef.current) {
          clearTimeout(hoverRestoreTimerRef.current)
          hoverRestoreTimerRef.current = null
        }
        if (hovered) return undefined
        if (autoExpandedRef.current.size === 0) return undefined
        hoverRestoreTimerRef.current = setTimeout(() => {
          hoverRestoreTimerRef.current = null
          const ids = autoExpandedRef.current
          autoExpandedRef.current = new Set()
          const scrollTop = hoverScrollTopRef.current
          hoverScrollTopRef.current = null
          setCollapsed((previous) => {
            let changed = false
            const next = new Set(previous)
            for (const id of ids) {
              if (!next.has(id)) {
                next.add(id)
                changed = true
              }
            }
            return changed ? next : previous
          })
          if (scrollTop !== null) {
            const restoreScroll = () => {
              if (treeRef.current) treeRef.current.scrollTop = scrollTop
            }
            if (typeof requestAnimationFrame === 'function') requestAnimationFrame(restoreScroll)
            else setTimeout(restoreScroll, 0)
          }
        }, 180)
        return () => {
          if (hoverRestoreTimerRef.current) {
            clearTimeout(hoverRestoreTimerRef.current)
            hoverRestoreTimerRef.current = null
          }
        }
      }, [hovered])

      // 树行已在 DOM 里时滚到最近可见位置（展开后下一轮渲染会再触发）
      useEffect(() => {
        if (!hovered || !treeOpen || hoverHighlight.ids.size === 0) return
        const root = treeRef.current
        if (!root) return
        const target = Array.from(root.querySelectorAll('[data-tree-id]'))
          .find((element) => hoverHighlight.ids.has(element.getAttribute('data-tree-id')))
        if (target) target.scrollIntoView({ block: 'nearest', inline: 'nearest' })
      }, [hovered, treeOpen, hoverHighlight, treeMode, collapsed])

      const hoveredNodeId = hovered?.nodeId || null

      const zoomAt = useCallback((factor, anchorX, anchorY) => {
        const view = activeViewRef.current
        if (!view) return
        setViewTransform((previous) => {
          const nextZoom = Math.max(0.25, Math.min(4, previous.zoom * factor))
          const oldScale = Math.max(0.05, Math.min(4, fitScaleRef.current * previous.zoom))
          const nextScale = Math.max(0.05, Math.min(4, fitScaleRef.current * nextZoom))
          const ratio = nextScale / oldScale
          const x = anchorX - (anchorX - previous.x) * ratio
          const y = anchorY - (anchorY - previous.y) * ratio
          const nextPan = clampPan(view, canvasSizeRef.current, nextScale, { x, y })
          return { zoom: nextZoom, x: nextPan.x, y: nextPan.y }
        })
      }, [])

      const fitCanvas = useCallback(() => {
        const view = activeViewRef.current
        if (!view) return
        const nextFit = computeFitScale(view, canvasSizeRef.current)
        setViewTransform({ zoom: 1, ...centeredPan(view, canvasSizeRef.current, nextFit) })
      }, [])

      const handleNodeSelect = useCallback((node, event) => {
        if (Date.now() < suppressClickUntilRef.current) {
          if (event && typeof event.stopPropagation === 'function') event.stopPropagation()
          return
        }
        setSelectedNodeId(node.id)
      }, [])

      const handleBackgroundClick = useCallback((event) => {
        if (Date.now() < suppressClickUntilRef.current) {
          if (event && typeof event.stopPropagation === 'function') event.stopPropagation()
          return
        }
        setSelectedNodeId(null)
      }, [])

      const handleNodeHover = useCallback((node, leaving) => {
        if (dragRef.current?.moved) return
        if (!node) {
          setHovered((previous) => {
            if (!previous) return previous
            if (leaving && previous.nodeId !== leaving.id) return previous
            return null
          })
          return
        }
        setHovered({
          nodeId: node.id,
          elementId: node.elementId || null,
          viewId: activeViewRef.current?.viewId || null,
        })
      }, [])

      const handlePointerDown = useCallback((event) => {
        if (event.button !== 0 && event.button !== 1) return
        if (event.button === 1) event.preventDefault()
        const transform = transformRef.current
        dragRef.current = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          originX: transform.x,
          originY: transform.y,
          moved: false,
        }
        suppressClickUntilRef.current = 0
        setHovered(null)
      }, [])

      const handlePointerMove = useCallback((event) => {
        const drag = dragRef.current
        if (!drag || drag.pointerId !== event.pointerId) return
        const dx = event.clientX - drag.startX
        const dy = event.clientY - drag.startY
        if (!drag.moved && Math.hypot(dx, dy) < 4) return
        if (!drag.moved) {
          drag.moved = true
          // 超过阈值才算拖拽；此时才捕获指针，避免普通点击被重定向到画布容器。
          try {
            event.currentTarget.setPointerCapture(event.pointerId)
          } catch {
            /* 不支持 pointer capture 时退回普通拖拽 */
          }
        }
        event.preventDefault()
        setDragging(true)
        const view = activeViewRef.current
        if (!view) return
        const nextScale = Math.max(0.05, Math.min(4, fitScaleRef.current * transformRef.current.zoom))
        const nextPan = clampPan(view, canvasSizeRef.current, nextScale, {
          x: drag.originX + dx,
          y: drag.originY + dy,
        })
        setViewTransform((previous) => ({ ...previous, x: nextPan.x, y: nextPan.y }))
      }, [])

      const finishDrag = useCallback((event, cancelled) => {
        const drag = dragRef.current
        if (!drag || drag.pointerId !== event.pointerId) return
        if (drag.moved && !cancelled) {
          suppressClickUntilRef.current = Date.now() + 350
        }
        dragRef.current = null
        setDragging(false)
        try {
          event.currentTarget.releasePointerCapture(event.pointerId)
        } catch {
          /* 已释放 */
        }
      }, [])

      const handleLostPointerCapture = useCallback((event) => {
        const drag = dragRef.current
        if (!drag || drag.pointerId !== event.pointerId) return
        dragRef.current = null
        setDragging(false)
      }, [])

      // 模型更新后悬停节点已消失时清理
      useEffect(() => {
        if (!hovered) return
        const exists = (activeView?.nodes || []).some((node) => node.id === hovered.nodeId)
        if (!exists) setHovered(null)
      }, [activeView, hovered])

      const toggleTreeNode = useCallback((node) => {
        if (!node) return
        if (node.view) {
          setViewId(node.view)
          setSelectedNodeId(null)
          return
        }
        const hasChildren = Array.isArray(node.children) && node.children.length > 0
        // 有子节点的定义节点仍然点击展开/折叠；无子节点的元素叶子才跳到图上
        if (!hasChildren && node.elementId) {
          const target = views.find((view) => (view.nodes || []).some((item) => item.elementId === node.elementId))
          if (target) {
            setViewId(target.viewId)
            setSelectedNodeId(`el:${node.elementId}`)
            const nodeInView = (target.nodes || []).find((item) => item.elementId === node.elementId)
            if (nodeInView) setSelectedNodeId(nodeInView.id)
            return
          }
        }
        if (hasChildren) {
          autoExpandedRef.current.delete(node.id)
          setCollapsed((previous) => {
            const next = new Set(previous)
            if (next.has(node.id)) next.delete(node.id)
            else next.add(node.id)
            return next
          })
        }
      }, [views])

      /** 生成 / 重新生成全过程图：host 调 timeline.py 出 SVG，浏览器侧转 blob 显示。 */
      const loadTimeline = useCallback(async () => {
        setTimelineBusy(true)
        setTimeline((previous) => (previous?.url ? previous : { error: null }))
        try {
          const params = []
          if (sessionId) params.push(`sessionId=${encodeURIComponent(sessionId)}`)
          params.push(`t=${Date.now()}`)
          const response = await fetch(`${API_TIMELINE}?${params.join('&')}`, { cache: 'no-store' })
          const contentType = String(response.headers?.get?.('content-type') || '')
          if (!response.ok || !contentType.includes('svg')) {
            let detail = `HTTP ${response.status}`
            try {
              const payload = await response.json()
              detail = payload?.error?.message || payload?.error?.code || detail
            } catch {
              /* 非 JSON 错误响应 */
            }
            throw new Error(detail)
          }
          const text = await response.text()
          const blob = new Blob([text], { type: 'image/svg+xml;charset=utf-8' })
          const url = URL.createObjectURL(blob)
          setTimeline((previous) => {
            if (previous?.url) {
              try {
                URL.revokeObjectURL(previous.url)
              } catch {
                /* 已释放 */
              }
            }
            return { url, at: Date.now(), size: text.length }
          })
        } catch (failure) {
          setTimeline({ error: String(failure?.message ?? failure) })
        } finally {
          setTimelineBusy(false)
        }
      }, [sessionId])

      /** 清空过程记录（DELETE /history）：不会动模型文件，清空后当前模型重新记为基线。 */
      const resetHistory = useCallback(async () => {
        try {
          if (typeof window !== 'undefined' && typeof window.confirm === 'function'
            && !window.confirm(t('process.reset.confirm'))) return
        } catch {
          /* 确认框不可用就继续 */
        }
        try {
          const params = []
          if (sessionId) params.push(`sessionId=${encodeURIComponent(sessionId)}`)
          const url = params.length > 0 ? `${API_HISTORY}?${params.join('&')}` : API_HISTORY
          const response = await fetch(url, { method: 'DELETE', cache: 'no-store' })
          if (!response.ok) throw new Error(`HTTP ${response.status}`)
          setTimeline((previous) => {
            if (previous?.url) {
              try {
                URL.revokeObjectURL(previous.url)
              } catch {
                /* 已释放 */
              }
            }
            return null
          })
          setHistoryTick((value) => value + 1)
        } catch (failure) {
          setHistoryError(String(failure?.message ?? failure))
        }
      }, [sessionId, t])

      const renderTreeNode = (node, depth) => {
        if (!node) return null
        const children = Array.isArray(node.children) ? node.children : []
        const hasChildren = children.length > 0
        const isCollapsed = collapsed.has(node.id)
        const isViewLeaf = Boolean(node.view)
        const isSelected = isViewLeaf && node.view === activeView?.viewId
        const isHovered = hoverHighlight.ids.has(node.id)
        const index = `${node.id || 'node'}@${depth}`
        const row = h('div', {
          key: `${index}:row`,
          className: `svz-tnode${isViewLeaf ? ' view' : ''}${isSelected ? ' sel' : ''}${isHovered ? ' hov' : ''}`,
          'data-tree-id': node.id,
          style: { paddingLeft: `${5 + depth * 11}px` },
          title: node.label,
          onClick: (event) => {
            event.stopPropagation()
            toggleTreeNode(node)
          },
        }, [
          h('span', { key: 'caret', className: 'svz-caret' }, hasChildren ? (isCollapsed ? '▸' : '▾') : ''),
          h('span', { key: 'icon', className: 'svz-ico' }, node.icon || '·'),
          h('span', { key: 'label', className: 'svz-lbl' }, String(node.label ?? '')),
          node.count ? h('span', { key: 'count', className: 'svz-cnt' }, String(node.count)) : null,
        ])
        const childRows = hasChildren && !isCollapsed
          ? children.map((child) => renderTreeNode(child, depth + 1))
          : []
        return h('div', { key: index, className: 'svz-tbranch' }, [row, ...childRows])
      }

      const selectedNode = activeView && selectedNodeId
        ? (activeView.nodes || []).find((node) => node.id === selectedNodeId)
        : null

      /** 过程面板：步骤列表（颜色 + 会话 + 增删改）+ 全过程图。 */
      const renderProcessPanel = () => {
        const steps = Array.isArray(history?.steps) ? history.steps : []
        const available = history?.available === true
        const historyErr = historyError || history?.historyError || null
        const stepRows = steps.map((step, index) => {
          const color = stepColorOf(index, step.source)
          const added = Array.isArray(step.added) ? step.added : []
          const changed = Array.isArray(step.changed) ? step.changed : []
          const removed = Array.isArray(step.removed) ? step.removed : []
          const touchIds = [...added, ...changed]
          const names = touchIds.slice(0, 4).map((id) => elementLabels.get(id) || id)
          const more = touchIds.length > names.length ? ` 等 ${touchIds.length} 个` : ''
          const thisSession = Boolean(history?.session?.id && step.sessionId === history.session.id)
          const chips = []
          if (step.sessionId) {
            chips.push(h('span', {
              key: 'sess',
              className: `svz-chip sess${thisSession ? ' now' : ''}`,
              title: thisSession ? t('process.session.tip') : String(step.sessionId),
            }, thisSession ? t('process.session.now') : t('process.session', { id: step.sessionId })))
          }
          if (Number.isFinite(step.turn)) {
            chips.push(h('span', { key: 'turn', className: 'svz-chip' }, t('process.turn', { n: step.turn })))
          }
          if (step.source && step.source !== 'baseline' && step.source !== 'change') {
            chips.push(h('span', { key: 'src', className: 'svz-chip', title: String(step.source) }, t('process.reconstructed')))
          }
          if (added.length > 0) chips.push(h('span', { key: 'add', className: 'svz-chip add' }, t('process.added', { n: added.length })))
          if (changed.length > 0) chips.push(h('span', { key: 'chg', className: 'svz-chip chg' }, t('process.changed', { n: changed.length })))
          if (removed.length > 0) chips.push(h('span', { key: 'del', className: 'svz-chip del' }, t('process.removed', { n: removed.length })))
          return h('div', { key: `step-${step.seq}`, className: `svz-step${thisSession ? ' this' : ''}` }, [
            h('span', { key: 'sw', className: 'svz-swatch', style: { background: color } }),
            h('div', { key: 'main', className: 'svz-step-main' }, [
              h('div', { key: 'head', className: 'svz-step-head' }, [
                h('span', { key: 'name', className: 'svz-step-name' }, step.source === 'baseline'
                  ? t('process.baseline')
                  : t('process.step', { n: step.seq })),
                h('span', { key: 'time', className: 'svz-step-time' }, formatClock(step.at)),
                ...chips,
              ]),
              names.length > 0
                ? h('div', { key: 'names', className: 'svz-step-names' }, `${names.join('、')}${more}`)
                : null,
            ]),
          ])
        })
        const toolbar = h('div', { key: 'toolbar', className: 'svz-proc-toolbar' }, [
          h('span', { key: 'title', className: 'svz-proc-title' }, t('process.title')),
          h('span', { key: 'steps', className: 'svz-badge' }, t('process.steps', { n: history?.stepCount ?? 0 })),
          history?.updatedAt
            ? h('span', { key: 'meta', className: 'svz-proc-meta' }, t('process.updated', { time: formatClock(history.updatedAt) }))
            : null,
          h('span', { key: 'spacer', className: 'svz-spacer' }),
          h('button', {
            key: 'gen',
            className: 'svz-btn',
            disabled: timelineBusy || !available,
            onClick: loadTimeline,
          }, timelineBusy ? t('process.image.loading') : (timeline?.url ? t('process.regenerate') : t('process.generate'))),
          timeline?.url
            ? h('button', {
              key: 'open',
              className: 'svz-btn',
              onClick: () => {
                try {
                  window.open(timeline.url, '_blank', 'noopener')
                } catch {
                  /* 弹窗被拦截 */
                }
              },
            }, t('process.open'))
            : null,
          h('button', { key: 'reset', className: 'svz-btn', onClick: resetHistory }, t('process.reset')),
        ])
        let listBody
        if (historyErr) {
          listBody = h('div', { key: 'err', className: 'svz-proc-hint' }, t('process.history.error', { error: historyErr }))
        } else if (!available) {
          listBody = h('div', { key: 'empty', className: 'svz-proc-hint' }, t('process.empty'))
        } else {
          listBody = h('div', { key: 'steps', className: 'svz-proc-steps' }, stepRows)
        }
        let imageBody
        if (timeline?.url) {
          imageBody = h('img', { key: 'img', src: timeline.url, alt: t('process.title') })
        } else if (timelineBusy) {
          imageBody = h('div', { key: 'loading', className: 'svz-proc-hint' }, t('process.image.loading'))
        } else if (timeline?.error) {
          imageBody = h('div', { key: 'err', className: 'svz-proc-hint' }, t('process.image.failed', { error: timeline.error }))
        } else {
          imageBody = h('div', { key: 'hint', className: 'svz-proc-hint' }, t('process.image.empty'))
        }
        return h('div', { key: 'process', className: 'svz-process' }, [
          toolbar,
          h('div', { key: 'hint', className: 'svz-proc-meta' }, t('process.hint')),
          listBody,
          h('div', { key: 'image', className: 'svz-proc-image' }, [imageBody]),
        ])
      }

      const fitScale = activeView ? computeFitScale(activeView, canvasSize) : 1
      const scale = activeView
        ? Math.max(0.05, Math.min(4, fitScale * viewTransform.zoom))
        : 1
      activeViewRef.current = activeView
      canvasSizeRef.current = canvasSize
      fitScaleRef.current = fitScale
      transformRef.current = viewTransform

      const canvasSvg = useMemo(() => {
        if (!activeView) return null
        return renderSvg(
          activeView,
          selectedNodeId,
          addedElementIds,
          sessionAddedIds,
          hoveredNodeId,
          handleNodeSelect,
          handleNodeHover,
          handleBackgroundClick,
        )
      }, [
        activeView,
        selectedNodeId,
        addedElementIds,
        sessionAddedIds,
        hoveredNodeId,
        handleNodeSelect,
        handleNodeHover,
        handleBackgroundClick,
      ])

      const modelPath = model?.modelRef?.path || ''
      const baselineName = modelPath.split(/[\\/]/).pop() || ''

      /** 秒数 → 紧凑年龄（<60s 用 s，<60m 用 m，其余用 h）。 */
      const fmtAge = (seconds) => {
        const total = Math.max(0, Math.round(Number(seconds) || 0))
        if (total < 60) return `${total}s`
        const minutes = Math.floor(total / 60)
        if (minutes < 60) return `${minutes}m${pad2(total % 60)}s`
        const hours = Math.floor(minutes / 60)
        return `${hours}h${pad2(minutes % 60)}m`
      }

      const statusLine = (() => {
        const modeling = model?.modeling
        const revision = model?.modelRef?.revision || ''
        if (!modeling) return null
        const age = Math.max(0, Math.round((modeling.ageMs || 0) / 1000))
        return { modeling, revision, age }
      })()

      const header = h('div', { className: 'svz-header' }, [
        h('div', { key: 'title', className: 'svz-title' }, [
          h('span', { key: 'logo', className: 'svz-logo' }, '▦'),
          h('span', { key: 'text' }, t('title')),
        ]),
        statusLine && statusLine.revision
          ? h('span', { key: 'rev', className: 'svz-badge rev', title: t('rev.tip', { sha: model?.modelRef?.irSha256 || statusLine.revision }) }, `rev ${statusLine.revision}`)
          : null,
        model
          ? h('span', { key: 'stats', className: 'svz-badge' }, t('stats', {
            elements: model.stats?.elements ?? '?',
            relations: model.stats?.relations ?? '?',
          }))
          : null,
        statusLine
          ? h('span', {
            key: 'status',
            className: `svz-status${statusLine.modeling.active ? ' modeling' : ''}${error && model ? ' stale' : ''}`,
            title: t('status.tip', { ms: pollMs }),
          }, [
            h('span', { key: 'dot', className: 'svz-dot' }),
            h('span', { key: 'label' }, statusLine.modeling.active ? t('status.modeling') : t('status.synced')),
            h('span', { key: 'age' }, t('status.age', { age: fmtAge(statusLine.age) })),
          ])
          : null,
        diffFresh && diff
          ? h('span', {
            key: 'added',
            className: 'svz-badge new',
            title: t('status.added.tip'),
          }, t('status.added', { count: diff.added?.length ?? 0 }))
          : null,
        sessionAddedCount > 0
          ? h('span', {
            key: 'session',
            className: 'svz-badge session',
            title: t('process.session.tip'),
            onClick: () => setPanel('process'),
          }, t('process.session.added', { n: sessionAddedCount }))
          : null,
        h('span', { key: 'spacer', className: 'svz-spacer' }),
        h('button', {
          key: 'tree',
          className: `svz-btn${treeOpen ? ' on' : ''}`,
          title: t('tree.toggle'),
          onClick: () => {
            treeTouchedRef.current = true
            setTreeOpen((value) => !value)
          },
        }, ['☰ ', t('tree.toggle')]),
        h('button', {
          key: 'refresh',
          className: 'svz-btn',
          title: t('refresh'),
          onClick: () => setRefreshTick((value) => value + 1),
        }, '↻'),
      ])

      let body = null
      if (!model) {
        if (error) {
          const rawError = error.error && typeof error.error === 'object' ? error.error : error
          const searched = Array.isArray(rawError.searched) ? rawError.searched : []
          const roots = Array.isArray(rawError.workspaceRoots) ? rawError.workspaceRoots : []
          body = h('div', { className: 'svz-error' }, [
            h('div', { key: 'title', className: 'svz-title', style: { fontSize: '13px' } }, t('error.title')),
            h('code', { key: 'code', className: 'svz-errcode' }, String(rawError.code || 'ERROR')),
            h('div', { key: 'msg', className: 'svz-errmsg' }, String(rawError.message || t('error.network'))),
            searched.length > 0
              ? h('div', { key: 'searched' }, [
                h('div', { key: 'label', style: { fontSize: '10px', marginBottom: '2px' } }, t('error.searched')),
                h('div', { key: 'list', className: 'svz-searched' }, searched.slice(0, 6).join('  ·  ')),
              ])
              : null,
            roots.length > 0
              ? h('div', { key: 'roots', style: { fontSize: '10px', marginTop: '6px', opacity: 0.75 } },
                `${t('error.searched')} ${roots.slice(0, 3).join('  ·  ')}`)
              : null,
            h('button', {
              key: 'retry',
              className: 'svz-btn',
              onClick: () => setRefreshTick((value) => value + 1),
            }, t('error.retry')),
          ])
        } else {
          body = h('div', { className: 'svz-loading' }, [
            h('div', { key: 'spin', className: 'svz-spin' }),
            h('div', { key: 'text' }, t('loading')),
          ])
        }
      } else if (views.length === 0) {
        body = h('div', { className: 'svz-empty' }, [
          h('div', { key: 'title', className: 'svz-tnode' }, t('empty.title')),
          h('div', { key: 'hint' }, t('empty.hint')),
        ])
      } else {
        body = h('div', { className: 'svz-main', style: { flexDirection: narrow ? 'column' : 'row' } }, [
          treeOpen
            ? h('div', {
              key: 'tree',
              className: 'svz-tree',
              ref: treeRef,
              style: narrow ? { width: '100%', maxWidth: '100%', maxHeight: '210px', borderRight: 'none', borderBottom: '1px solid var(--svz-border)' } : undefined,
            }, [
              h('div', { key: 'head', className: 'svz-treehead' }, [
                h('button', {
                  key: 'hierarchy',
                  className: `svz-tab-btn${treeMode === 'hierarchy' ? ' on' : ''}`,
                  onClick: () => setTreeMode('hierarchy'),
                }, t('tree.hierarchy')),
                h('button', {
                  key: 'category',
                  className: `svz-tab-btn${treeMode === 'category' ? ' on' : ''}`,
                  onClick: () => setTreeMode('category'),
                }, t('tree.category')),
              ]),
              activeTree ? renderTreeNode(activeTree, 0) : h('div', { key: 'none', className: 'svz-tnode' }, t('empty.title')),
            ])
            : null,
          h('div', { key: 'canvas-col', className: 'svz-canvas-col' }, [
            h('div', { key: 'viewbar', className: 'svz-viewbar' }, [
              h('div', { key: 'chips', className: 'svz-viewchips' }, [
                ...views.map((view) => h('button', {
                  key: `chip-${view.viewId}`,
                  className: `svz-viewchip${panel === 'graph' && view.viewId === activeView.viewId ? ' on' : ''}`,
                  title: view.title,
                  onClick: () => {
                    setPanel('graph')
                    setViewId(view.viewId)
                  },
                }, [
                  h('span', { key: 'dot', className: 'svz-kdot', style: { background: VIEW_KIND_COLOR[view.kind] || '#8fb6ff' } }),
                  h('span', { key: 'text' }, view.title),
                ])),
                h('button', {
                  key: 'chip-process',
                  className: `svz-viewchip process${panel === 'process' ? ' on' : ''}`,
                  title: t('process.hint'),
                  onClick: () => setPanel(panel === 'process' ? 'graph' : 'process'),
                }, [
                  h('span', { key: 'dot', className: 'svz-kdot' }),
                  h('span', { key: 'text' }, t('process.tab')),
                  history?.stepCount
                    ? h('span', { key: 'count', className: 'svz-chipcount' }, String(history.stepCount))
                    : null,
                ]),
              ]),
              panel === 'process' ? null : h('div', { key: 'zoom', className: 'svz-zoombar' }, [
                h('button', {
                  key: 'out',
                  className: 'svz-btn',
                  title: t('zoom.out'),
                  onClick: () => zoomAt(1 / 1.15, canvasSize.w / 2, canvasSize.h / 2),
                }, '−'),
                h('span', { key: 'value', className: 'svz-zoomval' }, `${Math.round(scale * 100)}%`),
                h('button', {
                  key: 'in',
                  className: 'svz-btn',
                  title: t('zoom.in'),
                  onClick: () => zoomAt(1.15, canvasSize.w / 2, canvasSize.h / 2),
                }, '+'),
                h('button', {
                  key: 'fit',
                  className: 'svz-btn',
                  title: t('zoom.fit'),
                  onClick: fitCanvas,
                }, t('zoom.fit')),
              ]),
            ]),
            panel === 'process'
              ? renderProcessPanel()
              : h('div', {
                key: 'wrap',
                className: `svz-canvas-wrap${dragging ? ' dragging' : ''}`,
                ref: setCanvasNode,
                onPointerDown: handlePointerDown,
                onPointerMove: handlePointerMove,
                onPointerUp: (event) => finishDrag(event, false),
                onPointerCancel: (event) => finishDrag(event, true),
                onLostPointerCapture: handleLostPointerCapture,
                onMouseLeave: () => handleNodeHover(null),
                onClick: (event) => {
                  if (event.target === event.currentTarget) handleBackgroundClick(event)
                },
              }, [
                h('div', {
                  key: 'stage',
                  className: 'svz-canvas-stage',
                  style: {
                    width: activeView.width,
                    height: activeView.height,
                    transform: `translate(${viewTransform.x.toFixed(2)}px, ${viewTransform.y.toFixed(2)}px) scale(${scale.toFixed(4)})`,
                  },
                }, canvasSvg),
              ]),
            panel === 'process' ? null : h('div', { key: 'status', className: 'svz-statusbar' }, [
              h('span', { key: 'view', className: 'svz-view' }, `${activeView.title} · ${t('view.nodes', {
                nodes: activeView.nodes?.length ?? 0,
                edges: activeView.edges?.length ?? 0,
              })}`),
              selectedNode
                ? h('span', { key: 'sel', className: 'svz-sel', title: selectedNode.elementId || '' }, t('selected', { label: selectedNode.label || selectedNode.elementId || selectedNode.id }))
                : h('span', { key: 'hint', className: 'svz-sel' }, t('canvas.hint')),
              h('span', { key: 'spacer', className: 'svz-spacer' }),
              h('span', { key: 'source' }, model.source === 'python' ? t('source.python') : t('source.js')),
              h('span', { key: 'poll' }, t('poll', { ms: pollMs })),
              h('span', { key: 'path', title: modelPath }, t('model.path', { path: truncate(baselineName || '?', 26) })),
              h('span', { key: 'legend', className: 'svz-legend' }, [
                h('span', { key: 'node', className: 'svz-lg-node' }, [h('i', { key: 'i' }), t('legend.node')]),
                h('span', { key: 'trace', className: 'svz-lg-trace' }, [h('i', { key: 'i' }), t('legend.trace')]),
                h('span', { key: 'flow', className: 'svz-lg-flow' }, [h('i', { key: 'i' }), t('legend.flow')]),
                h('span', { key: 'state', className: 'svz-lg-state' }, [h('i', { key: 'i' }), t('legend.state')]),
                sessionAddedCount > 0
                  ? h('span', { key: 'session', className: 'svz-lg-node' }, [h('i', { key: 'i', style: { background: '#79c98f' } }), t('legend.session')])
                  : null,
              ]),
            ]),
          ]),
        ])
      }

      return h('div', { className: 'svz-root', ref: rootRef }, [
        h('style', { key: 'style' }, CSS),
        header,
        error && model ? h('div', { key: 'banner', className: 'svz-banner' }, ['⚠ ', t('error.poll')]) : null,
        body,
      ])
    }

    /* ============================================================ *
     * 当前会话 preset / 自动打开 / header 按钮
     * ============================================================ */

    /** 本次页面加载内已处理过自动打开的会话（避免切回时重复打开）。 */
    const autoOpenSessions = new Set()

    /** 用户显式关闭过的标记（按会话）：关闭后不再自动打开，header 按钮仍可手动打开。 */
    function dismissedKeyFor(sessionId) {
      return `${DISMISS_PREFIX}${String(sessionId ?? 'unknown')}`
    }

    let hostConfigPromise = null

    /** 读取 host 的 autoOpen / pollMs 配置（同一页面只请求一次；失败时按默认值打开）。 */
    function loadHostConfig() {
      if (hostConfigPromise) return hostConfigPromise
      hostConfigPromise = (async () => {
        const fallback = { autoOpen: true, pollMs: FALLBACK_POLL_MS }
        try {
          const response = await fetch(API_HEALTH, { cache: 'no-store' })
          if (!response || !response.ok) return fallback
          const health = await response.json()
          return {
            autoOpen: health?.autoOpen !== false,
            pollMs: Math.max(500, Number(health?.pollMs) || FALLBACK_POLL_MS),
          }
        } catch {
          return fallback
        }
      })()
      return hostConfigPromise
    }

    /**
     * 会话 header 的「模型视图」按钮 + 自动打开逻辑。
     *
     * 自动打开只在「当前会话的 agent preset 是 sysml-v2」时发生（preset 只影响工具/提示词，
     * UI 通道由本插件自己决定）；用户显式关闭过（localStorage 按会话记忆）或窗口过窄（<768px，
     * 打开右栏会自动全屏）时不自动打开；header 按钮永远保留，关掉后可以点回来。
     */
    function ModelViewHeaderButton(props) {
      const safeProps = props && typeof props === 'object' ? props : {}
      const { sessionId, useSessions, openModelView } = safeProps
      const propT = safeProps.t
      const t = useCallback((key, params) => {
        if (typeof propT === 'function') {
          try {
            const value = propT(key, params)
            if (typeof value === 'string' && value !== key) return value
          } catch {
            /* locale 不可用时退回内置字典 */
          }
        }
        return dictText(key, params)
      }, [propT])

      const presetSelector = useCallback((state) => {
        try {
          const value = state?.byId?.[sessionId]?.projectionValues?.agentPreset
          return typeof value === 'string' ? value : undefined
        } catch {
          return undefined
        }
      }, [sessionId])
      const fallbackSelector = useCallback(() => undefined, [])
      const readStore = typeof useSessions === 'function' ? useSessions : fallbackSelector
      const preset = readStore(presetSelector)

      const [hostConfig, setHostConfig] = useState(null)
      useEffect(() => {
        let cancelled = false
        loadHostConfig().then((config) => {
          if (!cancelled) setHostConfig(config)
        })
        return () => {
          cancelled = true
        }
      }, [])

      useEffect(() => {
        if (!hostConfig || hostConfig.autoOpen === false) return undefined
        if (!sessionId || preset !== 'sysml-v2') return undefined
        if (typeof openModelView !== 'function') return undefined
        if (autoOpenSessions.has(sessionId)) return undefined
        const dismissKey = dismissedKeyFor(sessionId)
        const dismissed = () => {
          try {
            return localStorage.getItem(dismissKey) === '1'
          } catch {
            return false
          }
        }
        if (dismissed()) return undefined
        try {
          if (typeof window !== 'undefined' && Number(window.innerWidth) > 0 && Number(window.innerWidth) < 768) {
            return undefined
          }
        } catch {
          /* 无法读取窗口宽度时按宽窗处理 */
        }
        let cancelled = false
        let timer = null
        let attempts = 0
        const attempt = () => {
          if (cancelled || dismissed()) return
          attempts += 1
          if (attempts > 20) return
          if (openModelView(sessionId) === true) {
            autoOpenSessions.add(sessionId)
            return
          }
          timer = setTimeout(attempt, 800)
        }
        timer = setTimeout(attempt, 350)
        return () => {
          cancelled = true
          if (timer) clearTimeout(timer)
        }
      }, [hostConfig, preset, sessionId, openModelView])

      const open = (event) => {
        if (event && typeof event.stopPropagation === 'function') event.stopPropagation()
        // 手动打开视为“重新接受自动打开”，清掉该会话的关闭记忆
        try {
          localStorage.removeItem(dismissedKeyFor(sessionId))
        } catch {
          /* 隐私模式等场景忽略 */
        }
        if (typeof openModelView === 'function') openModelView(sessionId)
      }

      // 入口只在 SysML 会话显示；其他预设仍可从右栏默认页的「模型视图」卡片进入。
      if (preset !== 'sysml-v2') return null

      return h(React.Fragment, null, [
        h('style', { key: 'css' }, HEADER_CSS),
        h('button', {
          key: 'button',
          type: 'button',
          className: 'svz-hbtn',
          title: t('header.open'),
          onClick: open,
        }, [
          h('span', { key: 'icon', className: 'svz-hico' }, '▦'),
          h('span', { key: 'label' }, t('type.label')),
        ]),
      ])
    }

    /* ============================================================ *
     * 插件入口
     * ============================================================ */

    function apply(ctx) {
      /**
       * 打开（或聚焦）当前会话的「模型视图」tab。
       *
       * 注意：openTab 不带 replaceTab（否则会顶掉文件预览/guide）；不主动播种 files tab，
       * 右栏为空时只打开模型视图。openTab 作用于「屏幕上已挂载」的会话，因此调用方必须
       * 传入 sessionId，避免后台 SysML 会话把 tab 开到当前的非 SysML 会话里。
       * @param {string} sessionId - 发起打开的会话 id。
       * @returns {boolean} 是否已打开成功；会话尚未挂载/store 未铸造时返回 false 供调用方重试。
       */
      function openModelView(sessionId) {
        try {
          let mounted
          try {
            mounted = ctx.sidebarRight.mounted.getSnapshot()
          } catch {
            mounted = undefined
          }
          if (mounted && sessionId && mounted !== sessionId) return false
          const tabs = (ctx.sidebarRight.openTabs.getSnapshot() ?? [])
            .filter((tab) => mounted === undefined || tab.sessionId === mounted)
          if (tabs.some((tab) => tab.kind === TAB_KIND)) {
            ctx.sidebarRight.openTab(TAB_KIND)
            return true
          }
          ctx.sidebarRight.openTab(TAB_KIND)
          return true
        } catch {
          return false
        }
      }

      let t = (key, params) => dictText(key, params)
      ctx.inject(['locale'], (inner) => {
        try {
          inner.effect(() => inner.locale.register(NS, DICTS), 'sysml-viz: 文案字典')
          const bound = inner.locale.bind(NS)
          if (typeof bound === 'function') {
            t = (key, params) => {
              try {
                const value = bound(key, params)
                return typeof value === 'string' && value ? value : dictText(key, params)
              } catch {
                return dictText(key, params)
              }
            }
          }
        } catch (failure) {
          console.warn('[dsh-sysml-viz] locale 注册失败，使用内置中文文案', failure)
        }
      })

      ctx.effect(() => ctx.sidebarRightTabs.register({
        id: PACKAGE_ID,
        kind: TAB_KIND,
        priority: 'extension',
        keepMounted: true,
        title: () => t('type.label'),
        guide: [{
          id: 'sysml-model-view',
          order: 30,
          title: () => t('guide.title'),
          description: () => t('guide.description'),
        }],
      }), 'sysml-viz: tab 类型')

      ctx.effect(() => ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({
        name: 'sidebar.right.pane.tab',
        key: PACKAGE_ID,
        locale: NS,
      }, ModelViewBody)), 'sysml-viz: tab 正文')

      // 用户显式关闭：按会话记忆，不再自动打开；header 按钮仍能点回来
      ctx.effect(() => ctx.sidebarRight.registerCloseHandler(TAB_KIND, (sessionId) => {
        try {
          localStorage.setItem(dismissedKeyFor(sessionId), '1')
        } catch {
          /* 隐私模式等场景忽略 */
        }
      }), 'sysml-viz: 关闭标记')

      // 会话 header 的常驻入口：同时承载「按 preset 自动打开」逻辑
      ctx.effect(() => ctx.slots.inject('conversation.session.header.actions', () => ctx.slots.register({
        name: 'conversation.session.header.actions',
        id: 'sysml-viz-open',
        order: 30,
        locale: NS,
        inject: () => ({ openModelView }),
      }, ModelViewHeaderButton)), 'sysml-viz: 会话 header 按钮')

      return undefined
    }

    return {
      inject: ['slots', 'sidebarRightTabs', 'sidebarRight'],
      apply,
    }
  },
})
