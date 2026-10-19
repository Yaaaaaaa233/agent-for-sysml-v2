#!/usr/bin/env node
/**
 * smoke-test.mjs — dsh-sysml-viz 的自检脚本（不装插件、不改 profile）。
 *
 * 覆盖：
 *   1. host apply 在 mock ctx 上注册 5 条路由（health / model / history / timeline.svg / diagnostics）；
 *   2. GET /api/sysml-viz/health / diagnostics 返回 ok=true（diagnostics 还做 MCP 进程内握手自检）；
 *   3. GET /api/sysml-viz/model 读取 golden IR（JS 兜底）→ ok=true 且 ≥4 个 view，
 *      结构 / IBD / 需求 / 状态四类齐全，stats.elements=34，revision=sha8，tree 完整；
 *   4. ?rev=<revision> 返回 changed=false（客户端轮询的轻量分支）；
 *   5. preferPython=true 时优先调用 sysml-modeling-agent/mcp-server/tools/graph.py
 *      （若本机 python3/graph.py 不可用则跳过并打印 SKIP，不误判失败）；
 *   6. 建模过程记录：模型语义变化 → history/index.json 追加步骤（含增删改 id），
 *      DELETE /history 清空后自动重建基线；timeline.svg 调 timeline.py 出图（缺工具时 SKIP）；
 *   7. 错误降级：显式 path 不存在 → MODEL_NOT_FOUND；非法 IR → MODEL_INVALID_IR；
 *      非法 JSON → MODEL_PARSE_ERROR；非 GET → 405；
 *   8. 静态检查：client.js 无 http(s) 外链、模块加载形态正确、package.json/preset/locale/icon 完整、
 *      index.js 没有写死 golden 数据。
 *
 * 用法：node smoke-test.mjs
 */

import { spawnSync } from 'node:child_process'
import {
  existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  agentRootCandidates, apply, archiveRevision, DIAGNOSTICS_ROUTE, HEALTH_ROUTE, HISTORY_ROUTE, historyPayload,
  MODEL_ROUTE, TIMELINE_SVG_ROUTE, PLUGIN_ID, GRAPH_SCHEMA, VERSION,
} from './index.js'

const here = dirname(fileURLToPath(import.meta.url))
/** agent 仓库根：现场安装（<ws>/proposal/q2-plugin）与仓库内副本（<repo>/integrations/<name>）都适用。 */
const agentRoot = agentRootCandidates(here)[0] ?? join(here, '..', '..', 'sysml-modeling-agent')
/** 工作区根：仓库在 <ws>/sysml-modeling-agent 时取 <ws>；仓库自己当工作区时取仓库根。 */
const repoRoot = existsSync(join(agentRoot, '..', 'sysml-modeling-agent', 'mcp-server', 'run_server.py'))
  ? resolve(agentRoot, '..')
  : agentRoot
const goldenIr = join(agentRoot, 'examples', 'golden-coaxial-power-chain', 'golden-coaxial-power-chain.ir.json')
const graphScript = join(agentRoot, 'mcp-server', 'tools', 'graph.py')

const results = []
let failed = 0

function check(name, fn) {
  try {
    const detail = fn()
    results.push({ ok: true, name, detail })
    console.log(`PASS  ${name}${detail ? ` — ${detail}` : ''}`)
  } catch (error) {
    failed += 1
    results.push({ ok: false, name, detail: error })
    console.error(`FAIL  ${name}\n      ${error && error.message ? error.message : error}`)
  }
}

async function checkAsync(name, fn) {
  try {
    const detail = await fn()
    results.push({ ok: true, name, detail })
    console.log(`PASS  ${name}${detail ? ` — ${detail}` : ''}`)
  } catch (error) {
    failed += 1
    results.push({ ok: false, name, detail: error })
    console.error(`FAIL  ${name}\n      ${error && error.message ? error.message : error}`)
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function createMockCtx() {
  const routes = new Map()
  const cleanups = []
  const ctx = {
    webServer: {
      register(route) {
        if (routes.has(route.path)) throw new Error(`duplicate route ${route.path}`)
        routes.set(route.path, route)
        const dispose = () => routes.delete(route.path)
        cleanups.push(dispose)
        return dispose
      },
    },
    effect(fn) {
      const result = fn()
      if (typeof result === 'function') cleanups.push(result)
      return () => {}
    },
    logger: { info() {}, warn() {}, error() {} },
  }
  return {
    ctx,
    routes,
    cleanup() {
      for (const dispose of cleanups.splice(0).reverse()) {
        try {
          dispose()
        } catch {
          /* 清理阶段忽略 */
        }
      }
    },
  }
}

async function callRoute(route, { method = 'GET', path = route.path, search = '' } = {}) {
  const req = { method, url: `${path}${search}`, headers: {} }
  const response = {
    statusCode: 0,
    headers: {},
    body: '',
    headersSent: false,
    setHeader(name, value) {
      this.headers[String(name).toLowerCase()] = value
    },
    end(chunk) {
      this.body = chunk === undefined || chunk === null ? '' : String(chunk)
    },
    destroy() {},
  }
  await route.handler(req, response)
  let json = null
  try {
    json = JSON.parse(response.body)
  } catch {
    json = null
  }
  return { status: response.statusCode, headers: response.headers, body: response.body, json }
}

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'))
}

/* ------------------------------------------------------------------ *
 * 1. mock ctx 注册 + health + model（JS 兜底）
 * ------------------------------------------------------------------ */

const jsSession = createMockCtx()
apply(jsSession.ctx, {
  model: goldenIr,
  workspace: repoRoot,
  preferPython: false,
  autoOpen: false,
  history: false,
})
const jsRoutes = jsSession.routes

check('apply 在 mock ctx 上注册 health/model/history/timeline/diagnostics 五条路由', () => {
  assert(jsRoutes.size === 5, `routes=${jsRoutes.size}`)
  assert(jsRoutes.has(HEALTH_ROUTE), `missing ${HEALTH_ROUTE}`)
  assert(jsRoutes.has(MODEL_ROUTE), `missing ${MODEL_ROUTE}`)
  assert(jsRoutes.has(HISTORY_ROUTE), `missing ${HISTORY_ROUTE}`)
  assert(jsRoutes.has(TIMELINE_SVG_ROUTE), `missing ${TIMELINE_SVG_ROUTE}`)
  assert(jsRoutes.has(DIAGNOSTICS_ROUTE), `missing ${DIAGNOSTICS_ROUTE}`)
  return [...jsRoutes.keys()].join(', ')
})

let jsHealth = null
await checkAsync('GET /api/sysml-viz/health → ok=true 且识别到模型', async () => {
  const result = await callRoute(jsRoutes.get(HEALTH_ROUTE))
  assert(result.status === 200, `status=${result.status}`)
  assert(result.headers['content-type']?.includes('application/json'), 'content-type 不是 JSON')
  assert(result.json?.ok === true, 'health.ok 不是 true')
  assert(result.json.plugin === PLUGIN_ID, 'plugin id 不匹配')
  assert(result.json.model?.found === true, 'health.model.found 不是 true')
  assert(String(result.json.model.path).endsWith('golden-coaxial-power-chain.ir.json'), `model.path=${result.json.model.path}`)
  jsHealth = result.json
  return `model=${result.json.model.source}`
})

await checkAsync('GET /api/sysml-viz/diagnostics → 服务缺失时优雅降级', async () => {
  const result = await callRoute(jsRoutes.get(DIAGNOSTICS_ROUTE))
  assert(result.status === 200, `status=${result.status}`)
  assert(result.json?.ok === true, 'diagnostics.ok 不是 true')
  assert(result.json.routes.includes(DIAGNOSTICS_ROUTE), 'routes 未列出 diagnostics')
  assert(result.json.presets?.available === false, 'mock 环境应报告 presets 不可用')
  assert(result.json.tools?.available === false, 'mock 环境应报告 tools 不可用')
  assert(result.json.services?.hasGet === false, 'mock ctx 没有 get()，services.hasGet 应为 false')
  assert(result.json.loader?.available === false, 'mock ctx 没有 loader，loader.available 应为 false')
  assert(result.json.profilePatch && typeof result.json.profilePatch.file === 'string', '缺少 profilePatch.file')
  return `presets=${result.json.presets.available} tools=${result.json.tools.available} loader=${result.json.loader.available}`
})

if (existsSync(join(agentRoot, '.venv', 'bin', 'python'))) {
  await checkAsync('diagnostics?mcpSelfTest=1 → Host 进程拉起 MCP server 并列出工具', async () => {
    const result = await callRoute(jsRoutes.get(DIAGNOSTICS_ROUTE), { search: '?mcpSelfTest=1' })
    const probe = result.json.mcpSelfTest
    assert(probe?.ok === true, `selfTest=${JSON.stringify(probe)}`)
    assert(Array.isArray(probe.toolNames) && probe.toolNames.length >= 8, `tools=${probe.toolNames?.length}`)
    assert(probe.toolNames.includes('validate_model_json'), 'missing validate_model_json')
    return `${probe.protocolVersion} ${probe.toolNames.length} tools ${probe.latencyMs}ms`
  })
} else {
  console.log('SKIP  diagnostics?mcpSelfTest=1（仓库内没有 .venv/bin/python）')
}

let jsModel = null
await checkAsync('GET /api/sysml-viz/model（JS 兜底）→ ok=true、≥4 view、四类图齐全、34 元素', async () => {
  const result = await callRoute(jsRoutes.get(MODEL_ROUTE))
  assert(result.status === 200, `status=${result.status}`)
  const model = result.json
  assert(model?.ok === true, `ok=${model?.ok}`)
  assert(model.schema === GRAPH_SCHEMA, `schema=${model.schema}`)
  assert(Array.isArray(model.views) && model.views.length >= 4, `views=${model.views?.length}`)
  const kinds = new Set(model.views.map((view) => view.kind))
  for (const kind of ['structure', 'ibd', 'requirement', 'state']) {
    assert(kinds.has(kind), `缺少 ${kind} 视图`)
  }
  assert(model.stats?.elements === 34, `elements=${model.stats?.elements}`)
  assert(/^[0-9a-f]{8}$/.test(model.modelRef?.revision ?? ''), `revision=${model.modelRef?.revision}`)
  assert(/^[0-9a-f]{64}$/.test(model.modelRef?.irSha256 ?? ''), 'irSha256 不是 64 位 hex')
  assert(model.tree?.hierarchy && model.tree?.category, '缺少 tree.hierarchy/category')
  assert(typeof model.modeling?.active === 'boolean', '缺少 modeling.active')
  assert(model.config?.autoOpen === false, 'autoOpen 配置没有透传')
  jsModel = model
  return `views=${model.views.length} [${[...kinds].join(',')}] elements=${model.stats.elements} sha=${model.modelRef.revision}`
})

await checkAsync('?rev=<revision> → changed=false（轮询轻量分支）', async () => {
  const revision = jsModel?.modelRef?.revision
  assert(revision, '没有可用的 revision')
  const result = await callRoute(jsRoutes.get(MODEL_ROUTE), { search: `?rev=${revision}` })
  assert(result.json?.ok === true, 'ok 不是 true')
  assert(result.json.changed === false, `changed=${result.json.changed}`)
  assert(Array.isArray(result.json.modeling) !== true, 'modeling 不应是数组')
  assert(typeof result.json.modeling?.active === 'boolean', 'delta 缺少 modeling.active')
  return `revision=${result.json.revision}`
})

await checkAsync('非 GET 方法 → 405', async () => {
  const result = await callRoute(jsRoutes.get(MODEL_ROUTE), { method: 'POST' })
  assert(result.status === 405, `status=${result.status}`)
  return 'POST 被拒绝'
})

/* ------------------------------------------------------------------ *
 * 1.5 会话工作区定位（?sessionId= → workspace.json → 工作区）
 * ------------------------------------------------------------------ */

const fixtureDir = mkdtempSync(join(tmpdir(), 'dsh-sysml-viz-session-'))
const fixtureStore = join(fixtureDir, 'workspace.json')
writeFileSync(fixtureStore, JSON.stringify({
  tables: {
    workspaces: {
      'w-fixture': {
        path: repoRoot,
        title: 'fixture',
        sessionIds: ['session-fixture-0001'],
        updatedAt: new Date().toISOString(),
      },
    },
  },
}), 'utf8')
const previousStore = process.env.SYSML_VIZ_WORKSPACE_STORE
process.env.SYSML_VIZ_WORKSPACE_STORE = fixtureStore

const sessionCtx = createMockCtx()
apply(sessionCtx.ctx, { preferPython: false, autoOpen: false, history: false })

await checkAsync('?sessionId= 按 workspace.json 定位到会话工作区并出图', async () => {
  const result = await callRoute(sessionCtx.routes.get(MODEL_ROUTE), {
    search: '?sessionId=session-fixture-0001',
  })
  assert(result.json?.ok === true, `ok=${result.json?.ok} error=${JSON.stringify(result.json?.error ?? {})}`)
  assert(result.json.modelRef.path.startsWith(`${repoRoot}/`), `path=${result.json.modelRef.path}`)
  return `${result.json.source} ${result.json.modelRef.path}`
})

await checkAsync('health?sessionId= → workspace.sessionWorkspace = 会话工作区', async () => {
  const result = await callRoute(sessionCtx.routes.get(HEALTH_ROUTE), {
    search: '?sessionId=session-fixture-0001',
  })
  const health = result.json
  assert(health?.ok === true, 'health.ok 不是 true')
  assert(health.workspace.sessionId === 'session-fixture-0001', `sessionId=${health.workspace.sessionId}`)
  assert(health.workspace.sessionWorkspace === repoRoot, `sessionWorkspace=${health.workspace.sessionWorkspace}`)
  assert(health.workspace.sessionWorkspaceSource === 'session-store', `source=${health.workspace.sessionWorkspaceSource}`)
  assert(health.model.found === true, 'model.found 不是 true')
  return `source=${health.workspace.sessionWorkspaceSource}`
})

await checkAsync('无 sessionId / 未知 sessionId → 最近工作区兜底仍出图', async () => {
  const bare = await callRoute(sessionCtx.routes.get(MODEL_ROUTE))
  assert(bare.json?.ok === true, `no-sessionId ok=${bare.json?.ok}`)
  const unknown = await callRoute(sessionCtx.routes.get(MODEL_ROUTE), {
    search: '?sessionId=session-missing-9999',
  })
  assert(unknown.json?.ok === true, `unknown ok=${unknown.json?.ok}`)
  return 'bare + unknown 都命中'
})

if (previousStore === undefined) delete process.env.SYSML_VIZ_WORKSPACE_STORE
else process.env.SYSML_VIZ_WORKSPACE_STORE = previousStore
rmSync(fixtureDir, { recursive: true, force: true })
sessionCtx.cleanup()

/* ------------------------------------------------------------------ *
 * 1.6 建模过程记录 / 全过程图（temp workspace，不写真实工作区）
 * ------------------------------------------------------------------ */

const historyWorkspace = mkdtempSync(join(tmpdir(), 'dsh-sysml-viz-history-'))
const historyModelDir = join(historyWorkspace, 'model-output', 'demo')
mkdirSync(historyModelDir, { recursive: true })
const historyModel = join(historyModelDir, 'demo.ir.json')
const goldenModel = readJson(goldenIr)
writeFileSync(historyModel, JSON.stringify(goldenModel, null, 2), 'utf8')
const timelineScript = join(agentRoot, 'mcp-server', 'tools', 'timeline.py')
const historySession = createMockCtx()
apply(historySession.ctx, {
  model: historyModel,
  workspace: historyWorkspace,
  preferPython: false,
  autoOpen: false,
  history: true,
  python: process.env.PYTHON || 'python3',
  timelineScript: existsSync(timelineScript) ? timelineScript : '',
})

await checkAsync('第一次读取模型 → 自动记为基线步骤（<workspace>/.sysml-viz/history/index.json）', async () => {
  const result = await callRoute(historySession.routes.get(MODEL_ROUTE))
  assert(result.json?.ok === true, `model ok=${result.json?.ok} error=${JSON.stringify(result.json?.error ?? {})}`)
  const indexFile = join(historyWorkspace, '.sysml-viz', 'history', 'index.json')
  assert(existsSync(indexFile), `missing ${indexFile}`)
  const index = readJson(indexFile)
  assert(index.schema === 'sysml-viz-history/v1', `schema=${index.schema}`)
  assert(index.steps.length === 1, `steps=${index.steps.length}`)
  assert(index.steps[0].source === 'baseline', `source=${index.steps[0].source}`)
  assert(index.steps[0].elements === 34, `elements=${index.steps[0].elements}`)
  const history = await callRoute(historySession.routes.get(HISTORY_ROUTE))
  assert(history.json?.ok === true, 'history.ok 不是 true')
  assert(history.json.available === true, 'available 不是 true')
  assert(history.json.stepCount === 1, `stepCount=${history.json.stepCount}`)
  return `baseline elements=${index.steps[0].elements}`
})

await checkAsync('模型语义变化 → 追加步骤并记录 added id（同内容重复读取不重复记步）', async () => {
  // 同内容重复读取：不新增步骤
  const same = await callRoute(historySession.routes.get(MODEL_ROUTE))
  assert(same.json?.ok === true, 'same read ok 不是 true')
  // 修改模型（保证 size 变化触发缓存失效）
  const model = readJson(historyModel)
  model.elements.push({
    id: 'REQ-SMOKE-TEST',
    kind: 'Requirement',
    name: 'REQ_SMOKE_TEST',
    owner: model.package ?? 'Model',
    properties: {
      text: 'smoke test requirement',
      acceptanceCriteria: 'n/a',
      verifyMethod: 'analysis',
      priority: 'low',
    },
  })
  writeFileSync(historyModel, JSON.stringify(model, null, 2), 'utf8')
  const changed = await callRoute(historySession.routes.get(MODEL_ROUTE))
  assert(changed.json?.ok === true, `changed read ok=${changed.json?.ok}`)
  const history = await callRoute(historySession.routes.get(HISTORY_ROUTE))
  assert(history.json.stepCount === 2, `stepCount=${history.json.stepCount}`)
  const last = history.json.steps[history.json.steps.length - 1]
  assert(last.added.includes('REQ-SMOKE-TEST'), `added=${JSON.stringify(last.added)}`)
  assert(last.source === 'change', `source=${last.source}`)
  assert(last.elements === 35, `elements=${last.elements}`)
  return `steps=${history.json.stepCount} added=${last.added.join(',')}`
})

await checkAsync('GET /api/sysml-viz/history → 步列表 + 当前模型 + 会话字段结构', async () => {
  const result = await callRoute(historySession.routes.get(HISTORY_ROUTE))
  assert(result.json?.ok === true, 'ok 不是 true')
  assert(result.json.schema === 'sysml-viz-history/v1', `schema=${result.json.schema}`)
  assert(Array.isArray(result.json.steps), 'steps 不是数组')
  assert(result.json.current?.elements === 35, `current.elements=${result.json.current?.elements}`)
  assert(result.json.session === null, '无 sessionId 时应为 null')
  return `stepCount=${result.json.stepCount} elements=${result.json.current.elements}`
})

await checkAsync('DELETE /history → 清空后自动重建基线（模型仍存在）', async () => {
  const result = await callRoute(historySession.routes.get(HISTORY_ROUTE), { method: 'DELETE' })
  assert(result.json?.ok === true, `ok=${result.json?.ok}`)
  assert(result.json.cleared === true, 'cleared 不是 true')
  assert(result.json.stepCount === 1, `stepCount=${result.json.stepCount}`)
  const again = await callRoute(historySession.routes.get(HISTORY_ROUTE))
  assert(again.json.stepCount === 1, `after stepCount=${again.json.stepCount}`)
  return 'cleared -> baseline'
})

if (existsSync(timelineScript)) {
  await checkAsync('GET /api/sysml-viz/timeline.svg → 生成 SVG（timeline.py）', async () => {
    const result = await callRoute(historySession.routes.get(TIMELINE_SVG_ROUTE))
    assert(result.status === 200, `status=${result.status} body=${result.body.slice(0, 240)}`)
    assert(String(result.headers['content-type']).includes('svg'), `content-type=${result.headers['content-type']}`)
    assert(result.body.includes('<svg'), 'SVG 内容缺少 <svg')
    assert(result.body.includes('建模全过程'), 'SVG 缺少标题「建模全过程」')
    const svgFile = join(historyWorkspace, '.sysml-viz', 'history', 'timeline.svg')
    assert(existsSync(svgFile), 'timeline.svg 未落盘')
    return `bytes=${result.body.length}`
  })
} else {
  console.log('SKIP  timeline.svg（仓库内没有 mcp-server/tools/timeline.py）')
}

historySession.cleanup()
rmSync(historyWorkspace, { recursive: true, force: true })

await checkAsync('historyPayload：按 sessionId 汇总本会话新增元素（added + changed）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'dsh-sysml-viz-attr-'))
  const ir1 = {
    schema: 'sysml-ir/v1',
    package: 'AttrDemo',
    elements: [{ id: 'A', kind: 'PartDefinition', name: 'A', owner: 'AttrDemo', properties: {} }],
  }
  const ir2 = JSON.parse(JSON.stringify(ir1))
  ir2.elements.push({ id: 'B', kind: 'Requirement', name: 'B', owner: 'AttrDemo', properties: {} })
  archiveRevision({}, {
    dir,
    modelPath: '/tmp/attr/model.ir.json',
    text: JSON.stringify(ir1),
    ir: ir1,
    irSha256: 'a'.repeat(64),
    sessionId: 'session-11112222',
  })
  archiveRevision({}, {
    dir,
    modelPath: '/tmp/attr/model.ir.json',
    text: JSON.stringify(ir2),
    ir: ir2,
    irSha256: 'b'.repeat(64),
    sessionId: 'session-33334444',
  })
  const second = historyPayload(dir, { sessionId: 'session-33334444' })
  const first = historyPayload(dir, { sessionId: 'session-11112222' })
  const anonymous = historyPayload(dir, {})
  assert(second.session?.count === 1, `second.count=${second.session?.count}`)
  assert(second.session.addedIds.includes('B'), `second.added=${second.session.addedIds}`)
  assert(first.session?.count === 0, `first.count=${first.session?.count}`)
  assert(anonymous.session === null, '无 sessionId 时 session 应为 null')
  assert(anonymous.stepCount === 2, `stepCount=${anonymous.stepCount}`)
  rmSync(dir, { recursive: true, force: true })
  return 'added/changed 归属 ok'
})

/* ------------------------------------------------------------------ *
 * 2. 错误降级
 * ------------------------------------------------------------------ */

await checkAsync('显式 ?path= 不存在 → ok=false + MODEL_NOT_FOUND', async () => {
  const result = await callRoute(jsRoutes.get(MODEL_ROUTE), { search: '?path=/nonexistent/definitely-missing.ir.json' })
  assert(result.json?.ok === false, 'ok 不是 false')
  assert(result.json.error?.code === 'MODEL_NOT_FOUND', `code=${result.json.error?.code}`)
  assert(Array.isArray(result.json.error.searched), '缺少 searched 数组')
  return `code=${result.json.error.code}`
})

const invalidIrPath = join(here, '.tmp-invalid-ir.json')
const brokenJsonPath = join(here, '.tmp-broken-ir.json')
writeFileSync(invalidIrPath, JSON.stringify({ schema: 'sysml-ir/v1', package: 'Tmp' }), 'utf8')
writeFileSync(brokenJsonPath, '{ this is not json', 'utf8')
const errorSession = createMockCtx()
apply(errorSession.ctx, { model: invalidIrPath, workspace: here, preferPython: false, history: false })
const errorRoutes = errorSession.routes

await checkAsync('非法 IR（缺 elements）→ MODEL_INVALID_IR', async () => {
  const result = await callRoute(errorRoutes.get(MODEL_ROUTE))
  assert(result.json?.ok === false, 'ok 不是 false')
  assert(result.json.error?.code === 'MODEL_INVALID_IR', `code=${result.json.error?.code}`)
  return `code=${result.json.error.code}`
})

const brokenSession = createMockCtx()
apply(brokenSession.ctx, { model: brokenJsonPath, workspace: here, preferPython: false, history: false })

await checkAsync('非法 JSON → MODEL_PARSE_ERROR', async () => {
  const result = await callRoute(brokenSession.routes.get(MODEL_ROUTE))
  assert(result.json?.ok === false, 'ok 不是 false')
  assert(result.json.error?.code === 'MODEL_PARSE_ERROR', `code=${result.json.error?.code}`)
  return `code=${result.json.error.code}`
})

/* ------------------------------------------------------------------ *
 * 3. graph.py 优先路径
 * ------------------------------------------------------------------ */

const pythonVersion = spawnSync('python3', ['--version'], { encoding: 'utf8' })
const pythonAvailable = pythonVersion.status === 0
const canUsePython = pythonAvailable && existsSync(graphScript)

if (!canUsePython) {
  console.log(`SKIP  graph.py 优先路径（python3=${pythonAvailable} script=${existsSync(graphScript)}）`)
} else {
  const pySession = createMockCtx()
  apply(pySession.ctx, {
    model: goldenIr,
    workspace: repoRoot,
    preferPython: true,
    python: 'python3',
    autoOpen: true,
    history: false,
  })
  await checkAsync('preferPython=true → 调用 graph.py 得到 4 个投影视图（+参数视图）', async () => {
    const result = await callRoute(pySession.routes.get(MODEL_ROUTE))
    const model = result.json
    assert(model?.ok === true, `ok=${model?.ok}`)
    assert(model.source === 'python', `source=${model.source} pythonError=${model.python?.error ?? ''}`)
    assert(model.python?.used === true, 'python.used 不是 true')
    assert(/graph\.py$/.test(model.python?.script ?? ''), `script=${model.python?.script}`)
    assert(typeof model.python?.graphMeta?.contentSha256 === 'string', '缺少 graphMeta.contentSha256')
    const kinds = new Set(model.views.map((view) => view.kind))
    for (const kind of ['structure', 'ibd', 'requirement', 'state']) {
      assert(kinds.has(kind), `缺少 ${kind} 视图`)
    }
    assert(model.views.length >= 4, `views=${model.views.length}`)
    const stateView = model.views.find((view) => view.kind === 'state')
    assert(stateView.nodes.some((node) => String(node.id).includes('::')), '状态节点不是 graph.py 的 <id>::<state> 形态')
    assert(model.views.find((view) => view.kind === 'ibd')?.edges.some((edge) => edge.kind === 'flow-mech' || edge.kind === 'flow-el'), 'IBD 缺少连接边')
    return `views=${model.views.length} meta=${model.python.graphMeta.contentSha256.slice(0, 8)}`
  })
  await checkAsync('preferPython=true 时 health 报告 pythonAvailable=true', async () => {
    const result = await callRoute(pySession.routes.get(HEALTH_ROUTE))
    assert(result.json?.graph?.pythonAvailable === true, 'pythonAvailable 不是 true')
    assert(String(result.json.graph.pythonScript).endsWith('graph.py'), `script=${result.json.graph.pythonScript}`)
    return 'ok'
  })
  pySession.cleanup()
}

/* ------------------------------------------------------------------ *
 * 4. client 模块装配（只验证插件装配形态，不做 React/DOM 渲染）
 * ------------------------------------------------------------------ */

const clientSourceForWiring = readFileSync(join(here, 'client.js'), 'utf8')

await checkAsync('client.js factory → {inject, apply}，注册 tab 类型 / 正文 slot / header 按钮 / 关闭标记', async () => {
  const captured = {}
  const fakeWindow = { __ModuleLoader__: { load(spec) { captured.spec = spec } } }
  // client.js 是浏览器经典脚本（无 import/export），以 window 为参数执行即可载入模块
  const run = new Function('window', clientSourceForWiring)
  run(fakeWindow)
  assert(captured.spec && captured.spec.id === 'dsh-sysml-viz', '模块 id 不是包名')
  const stubReact = {
    createElement: () => ({}),
    Fragment: 'Fragment',
    useCallback: (fn) => fn,
    useEffect() {},
    useMemo: (fn) => fn(),
    useRef: (value) => ({ current: value }),
    useState: (value) => [value, () => {}],
  }
  const exportsObject = captured.spec.factory((id) => {
    assert(id === 'react', `factory 只应 require('react')，实际 ${id}`)
    return stubReact
  })
  assert(Array.isArray(exportsObject.inject), 'inject 不是数组')
  for (const service of ['slots', 'sidebarRightTabs', 'sidebarRight']) {
    assert(exportsObject.inject.includes(service), `inject 缺少 ${service}`)
  }
  assert(typeof exportsObject.apply === 'function', 'apply 不是函数')

  const storage = new Map()
  globalThis.localStorage = {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  }

  const record = { registrations: [], ownerKeys: [], openTabCalls: [], definition: null, closeHandler: null }
  const tabs = []
  const disposers = []
  const ctx = {
    effect(fn) {
      const result = fn()
      if (typeof result === 'function') disposers.push(result)
      return () => {}
    },
    inject(deps, callback) {
      if (!deps.includes('locale')) return
      callback({
        effect(fn) {
          const result = fn()
          if (typeof result === 'function') disposers.push(result)
          return () => {}
        },
        locale: { register() {}, bind: () => (key) => key },
      })
    },
    sidebarRightTabs: {
      register(definition) {
        record.definition = definition
        return () => {}
      },
    },
    slots: {
      inject(ownerKey, callback) {
        record.ownerKeys.push(ownerKey)
        callback()
      },
      register(options, component) {
        record.registrations.push({ options, component })
        return () => {}
      },
    },
    sidebarRight: {
      registerCloseHandler(kind, handler) {
        record.closeKind = kind
        record.closeHandler = handler
        return () => {}
      },
      openTabs: { getSnapshot: () => tabs.slice() },
      mounted: { getSnapshot: () => 'session-1' },
      openTab(kind) {
        record.openTabCalls.push(kind)
        if (!tabs.some((tab) => tab.kind === kind)) tabs.push({ kind, sessionId: 'session-1', tabId: kind })
      },
    },
    logger: { info() {}, warn() {} },
  }
  try {
    exportsObject.apply(ctx)
    assert(record.definition?.id === 'dsh-sysml-viz', 'tab 类型 id 不是包名')
    assert(record.definition?.kind === 'sysml-viz', 'kind 不是 sysml-viz')
    assert(record.definition?.priority === 'extension', 'priority 不是 extension')
    assert(record.definition?.keepMounted === true, 'keepMounted 不是 true')
    assert(record.definition?.guide?.length === 1, 'guide 入口不是 1 个')

    const body = record.registrations.find((entry) => entry.options.name === 'sidebar.right.pane.tab')
    assert(body, '缺少 sidebar.right.pane.tab 正文注册')
    assert(body.options.key === 'dsh-sysml-viz', '正文 slot key 错误')
    assert(typeof body.component === 'function', '正文组件不是函数')

    const header = record.registrations.find((entry) => entry.options.name === 'conversation.session.header.actions')
    assert(header, '缺少 conversation.session.header.actions 按钮注册')
    assert(header.options.id === 'sysml-viz-open', 'header id 错误')
    assert(typeof header.options.inject === 'function', 'header inject 不是函数')
    assert(typeof header.component === 'function', 'header 组件不是函数')
    const injected = header.options.inject()
    assert(typeof injected.openModelView === 'function', 'header 没有 openModelView')

    assert(record.closeKind === 'sysml-viz' && typeof record.closeHandler === 'function', 'close handler 未注册')
    record.closeHandler('session-1')
    assert(storage.get('dsh.sysml-viz.dismissed.session-1') === '1', '关闭标记没有按会话写入 localStorage')

    // 空右栏：先播种 files，再打开 sysml-viz（不顶掉默认页）
    assert(injected.openModelView() === true, 'openModelView 返回 false')
    assert(record.openTabCalls.join(',') === 'files,sysml-viz', `openTab 顺序=${record.openTabCalls.join(',')}`)

    // 已打开：再次点击只聚焦，不重复播种
    record.openTabCalls.length = 0
    assert(injected.openModelView() === true, '第二次 openModelView 返回 false')
    assert(record.openTabCalls.join(',') === 'sysml-viz', `已打开时 openTab=${record.openTabCalls.join(',')}`)
    assert(record.ownerKeys.includes('conversation.session.header.actions'), 'header slot inject 未被调用')
  } finally {
    for (const dispose of disposers.splice(0).reverse()) {
      try {
        dispose()
      } catch {
        /* 清理阶段忽略 */
      }
    }
    delete globalThis.localStorage
  }
  return 'tab 类型 / 正文 slot / header 按钮 / 按会话关闭标记 / 空栏播种 已装配'
})

/* ------------------------------------------------------------------ *
 * 4. 静态检查
 * ------------------------------------------------------------------ */

const clientSource = readFileSync(join(here, 'client.js'), 'utf8')
const hostSource = readFileSync(join(here, 'index.js'), 'utf8')

check('client.js 不引用 http(s) 外链', () => {
  const matches = clientSource.match(/https?:\/\//g) ?? []
  assert(matches.length === 0, `发现外部链接 ${matches.length} 处`)
  return '0 处外链'
})

check('client.js 使用 __ModuleLoader__ 懒加载形态 + require("react")', () => {
  assert(clientSource.includes('window.__ModuleLoader__.load('), '缺少 __ModuleLoader__.load')
  assert(clientSource.includes("id: 'dsh-sysml-viz'"), '模块 id 不是包名')
  assert(clientSource.includes("require('react')"), '缺少 require("react")')
  assert(clientSource.includes('sidebar.right.pane.tab'), '缺少右栏正文 slot')
  assert(clientSource.includes('sidebarRightTabs.register'), '缺少 tab 类型注册')
  return 'ok'
})

check('client.js 注册可关闭的新 tab 类型（不接管 files/text）', () => {
  assert(clientSource.includes("kind: TAB_KIND") && clientSource.includes("const TAB_KIND = 'sysml-viz'"), 'kind 不是 sysml-viz')
  assert(clientSource.includes('keepMounted: true'), '缺少 keepMounted')
  assert(clientSource.includes('registerCloseHandler'), '缺少关闭标记处理')
  assert(!clientSource.includes('replaceTab:'), 'openTab 不得使用 replaceTab（会顶掉文件预览）')
  return 'kind=sysml-viz, closeable'
})

check('client.js 含 preset 自动打开 / header 手动入口 / 空栏播种逻辑', () => {
  assert(clientSource.includes('conversation.session.header.actions'), '缺少会话 header 按钮 slot')
  assert(clientSource.includes('projectionValues?.agentPreset'), '缺少读当前会话 preset')
  assert(clientSource.includes("preset !== 'sysml-v2'"), '自动打开未按 sysml-v2 preset 判断')
  assert(clientSource.includes('dsh.sysml-viz.dismissed.'), '缺少按会话的关闭记忆 key')
  assert(clientSource.includes('innerWidth') && clientSource.includes('768'), '缺少窄窗不自动打开判断')
  assert(clientSource.includes("kind of ['files', 'guide']"), '缺少空右栏先播种 files 的逻辑')
  return 'preset 自动打开 / header 按钮 / 播种 / 窄窗'
})

check('client.js 含「过程」面板装配（history/timeline + 本会话标记）', () => {
  for (const marker of ['API_HISTORY', 'API_TIMELINE', 'svz-process', 'stepColorOf', 'process.tab', "method: 'DELETE'"]) {
    assert(clientSource.includes(marker), `缺少 ${marker}`)
  }
  assert(!clientSource.includes("'status.synced': '已同步'"), '状态文案「已同步」应已改为「模型更新」')
  assert(clientSource.includes('svz-session'), '缺少本会话元素的持久描边样式')
  return 'process panel wired'
})

check('index.js 只 import node: 内置模块（无外部 npm 依赖）', () => {
  const imports = [...hostSource.matchAll(/^import[\s\S]*?from\s+['"]([^'"]+)['"]/gm)].map((match) => match[1])
  const external = imports.filter((specifier) => !specifier.startsWith('node:'))
  assert(external.length === 0, `发现外部依赖：${external.join(', ')}`)
  return `${imports.length} 个 node: 内置模块`
})

check('index.js 没有写死 golden 数据（必须从 IR 读取）', () => {
  for (const marker of ['REQ-MISSION-ENDURANCE', 'PART-USAGE-BATTERY', 'golden-coaxial-power-chain', 'CoaxialOctoRotor']) {
    assert(!hostSource.includes(marker), `发现写死数据：${marker}`)
  }
  return 'no hard-coded IR data'
})

check('package.json：bundle patch 数组 + client 导出 + files 完整', () => {
  const manifest = readJson(join(here, 'package.json'))
  assert(manifest.name === 'dsh-sysml-viz', `name=${manifest.name}`)
  assert(manifest.version === VERSION, `package.version=${manifest.version} 与代码 VERSION=${VERSION} 不一致`)
  assert(Array.isArray(manifest.dsh?.bundle?.patch) && manifest.dsh.bundle.patch.length === 2, 'dsh.bundle.patch 不是 2 项数组')
  assert(manifest.dsh.bundle.patch.includes('./cordis.patch.yml'), '缺少 cordis.patch.yml')
  assert(manifest.dsh.bundle.patch.includes('./preset-sysml-v2.patch.yml'), '缺少 preset patch')
  assert(manifest.exports?.['./client'] === './client.js', '缺少 ./client 导出')
  assert(manifest.exports?.['./icon'] === './icon.svg', '缺少 ./icon 导出')
  for (const file of ['index.js', 'client.js', 'cordis.patch.yml', 'preset-sysml-v2.patch.yml', 'icon.svg', 'README.md', 'install.md']) {
    assert(manifest.files.includes(file), `files 缺少 ${file}`)
  }
  assert(manifest.dsh?.client?.platform === 'web', 'client.platform 不是 web')
  return 'manifest ok'
})

check('cordis.patch.yml / preset patch / locale / icon 齐全', () => {
  const patch = readFileSync(join(here, 'cordis.patch.yml'), 'utf8')
  assert(patch.includes('id: sysml-viz') && patch.includes('name: dsh-sysml-viz'), 'cordis.patch.yml 行不完整')
  const preset = readFileSync(join(here, 'preset-sysml-v2.patch.yml'), 'utf8')
  assert(preset.includes('id: sysml-v2'), 'preset patch 缺少 id: sysml-v2')
  assert(preset.includes("'@deepseek-ai/dsh-agent-preset'"), 'preset patch 缺少 agent-preset 引用')
  for (const locale of ['en.json', 'zh.json']) {
    const dict = readJson(join(here, 'locale', locale))
    assert(typeof dict.meta?.title === 'string' && dict.meta.title.length > 0, `${locale} 缺少 meta.title`)
    assert(typeof dict.meta?.description === 'string' && dict.meta.description.length > 0, `${locale} 缺少 meta.description`)
  }
  const icon = readFileSync(join(here, 'icon.svg'), 'utf8')
  assert(icon.trimStart().startsWith('<svg'), 'icon.svg 不是 SVG')
  assert(icon.includes('viewBox="0 0 64 64"'), 'icon.svg viewBox 不是 64x64')
  return 'ok'
})

check('node --check 通过（index.js / client.js / smoke-test.mjs）', () => {
  for (const file of ['index.js', 'client.js', 'smoke-test.mjs']) {
    const result = spawnSync(process.execPath, ['--check', join(here, file)], { encoding: 'utf8' })
    assert(result.status === 0, `${file}: ${result.stderr}`)
  }
  return '3 files'
})

/* ------------------------------------------------------------------ *
 * 清理 + 汇总
 * ------------------------------------------------------------------ */

jsSession.cleanup()
errorSession.cleanup()
brokenSession.cleanup()
for (const path of [invalidIrPath, brokenJsonPath]) {
  try {
    if (existsSync(path)) unlinkSync(path)
  } catch {
    /* 清理失败不阻断 */
  }
}

check('dispose 后路由被移除', () => {
  assert(jsRoutes.size === 0, `残留路由 ${[...jsRoutes.keys()].join(', ')}`)
  return 'clean'
})

console.log('')
const passed = results.filter((item) => item.ok).length
if (failed > 0) {
  console.error(`✗ smoke-test 失败：${failed} 项失败，${passed} 项通过`)
  process.exit(1)
}
console.log(`✓ smoke-test 全部通过：${passed} 项检查`)
if (jsHealth) console.log(`  health.model.path = ${jsHealth.model.path}`)
if (jsModel) console.log(`  JS 兜底视图 = ${jsModel.views.map((view) => `${view.title}(${view.nodes.length})`).join(' / ')}`)
