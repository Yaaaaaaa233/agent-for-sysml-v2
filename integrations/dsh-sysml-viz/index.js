/**
 * dsh-sysml-viz — Host half.
 *
 * Serves the right-sidebar "模型视图" tab with data:
 *   GET /api/sysml-viz/health       → 插件/工作区/模型/图生成器状态
 *   GET /api/sysml-viz/model        → sysml-graph/v1 投影（视图 + 模型树 + 统计 + 建模中状态）
 *   GET /api/sysml-viz/history      → 建模过程（每次 IR 语义变化的修订快照 + 相对上一步的增删改 + 会话归属）
 *   DELETE /api/sysml-viz/history   → 清空本工作区的过程记录（下一次建模重新从基线开始记录）
 *   GET /api/sysml-viz/timeline.svg → 调用 mcp-server/tools/timeline.py 生成「建模全过程」SVG（按步骤着色）
 *   GET /api/sysml-viz/diagnostics  → 只读诊断：preset roster/broken、preset 子行 state、
 *                                     Host 工具名；?mcpSelfTest=1 还会从 Host 进程直接拉起
 *                                     MCP server 做一次 stdio 握手（排查 mcp__sysml-agent__* 缺失）
 *
 * 过程记录（<workspace>/.sysml-viz/history/）：
 *   - 每次 IR 的「语义内容」变化（schema/package/elements 的规范化哈希变化）才记一步，
 *     纯格式/缩进变化不产生噪声步骤；
 *   - index.json 记录每步的 revision / irSha256 / 增删改 id / 会话短 id / 快照文件名；
 *   - step-NNNN-<rev>.ir.json 是该步的完整 IR 快照；
 *   - 这些步骤既供右栏「过程」面板追溯，也供 timeline.py 画全过程图，
 *     不改 IR、不改模型文件。
 *
 * 数据来源（按优先级）：
 *   1. 显式路径：config.model / env SYSML_VIZ_MODEL / 请求 ?path=
 *   2. 自动发现：<workspace>/.sysml-viz/model.ir.json、<workspace>/.sysml-agent/…/model.ir.json、
 *      <workspace>/model-output/<包名>/<包名>.ir.json，最后是深度受限的 *.ir.json（排除 node_modules 等）
 *   3. 图投影：优先调用 sysml-modeling-agent/mcp-server/tools/graph.py（--input <ir> --output -）；
 *      不存在/失败/输出不可解析时，用本文件内置的 JS 兜底生成（结构 / IBD / 需求 / 状态 / 参数）。
 *
 * 本插件只读工作区，不写模型；没有任何外部 npm 依赖（只用 node: 内置模块）。
 */

import { createHash } from 'node:crypto'
import {
  existsSync, mkdirSync, readFileSync, renameSync, rmSync, watch, writeFileSync,
} from 'node:fs'
import { readFile, readdir, stat, writeFile } from 'node:fs/promises'
import { spawn } from 'node:child_process'
import { homedir } from 'node:os'
import { basename, dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const PLUGIN_ID = 'dsh-sysml-viz'
export const VERSION = '0.1.7'
export const GRAPH_SCHEMA = 'sysml-graph/v1'
export const IR_SCHEMA = 'sysml-ir/v1'
export const HISTORY_SCHEMA = 'sysml-viz-history/v1'
export const MODEL_ROUTE = '/api/sysml-viz/model'
export const HEALTH_ROUTE = '/api/sysml-viz/health'
export const HISTORY_ROUTE = '/api/sysml-viz/history'
export const TIMELINE_SVG_ROUTE = '/api/sysml-viz/timeline.svg'
export const DIAGNOSTICS_ROUTE = '/api/sysml-viz/diagnostics'
export const MCP_DIAGNOSTICS_ROUTE = '/api/sysml-viz/mcp-diagnostics'

/** Host 插件需要的服务：HTTP 路由注册表。 */
export const inject = ['webServer']

/** 本文件所在目录，即插件根。 */
const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url))

/**
 * 按优先级列出「agent 仓库根」候选（判定条件：含 `mcp-server/run_server.py`）。
 *
 * 插件有两种摆放方式，都要能自己找到仓库，不依赖写死的绝对路径：
 *   1. 现场安装：`<ws>/proposal/q2-plugin` → 仓库在 `<ws>/sysml-modeling-agent`（同级兜底）；
 *   2. 仓库内副本：`<repo>/integrations/dsh-sysml-viz` → 仓库就是往上两级。
 *
 * @param {string} [start] - 起点目录，默认插件目录。
 * @returns {string[]} 存在的仓库根，按优先级排序；找不到时为空数组。
 */
export function agentRootCandidates(start = PLUGIN_DIR) {
  const found = []
  const push = (candidate) => {
    const root = resolve(candidate)
    if (!found.includes(root) && existsSync(join(root, 'mcp-server', 'run_server.py'))) found.push(root)
  }
  let dir = resolve(start)
  for (let depth = 0; depth < 8; depth += 1) {
    push(dir)
    const parent = resolve(dir, '..')
    if (parent === dir) break
    dir = parent
  }
  push(join(start, '..', '..', 'sysml-modeling-agent'))
  return found
}

const SKIP_DIRS = new Set([
  'node_modules', '.git', '.venv', 'venv', '__pycache__', 'dist', 'build',
  'target', '.cache', '.next', '.turbo', '.DS_Store',
])
const IR_SUFFIX = '.ir.json'
const MAX_WALK_DIRS = 4000

/* ------------------------------------------------------------------ *
 * 配置
 * ------------------------------------------------------------------ */

function pickString(...values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim() !== '') return value.trim()
  }
  return ''
}

function pickBool(value, fallback) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    if (/^(1|true|yes|on)$/i.test(value.trim())) return true
    if (/^(0|false|no|off)$/i.test(value.trim())) return false
  }
  return fallback
}

function pickNumber(value, fallback, min, max) {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  if (number < min) return min
  if (number > max) return max
  return number
}

/**
 * 合并 patch 配置、环境变量与默认值。
 * @param {Record<string, unknown>} raw - patch 行里的 config。
 * @returns 规范化后的配置。
 */
export function readConfig(raw) {
  const config = raw && typeof raw === 'object' ? raw : {}
  const env = process.env
  return {
    model: pickString(config.model, env.SYSML_VIZ_MODEL),
    workspace: pickString(config.workspace, env.SYSML_VIZ_WORKSPACE),
    autoOpen: pickBool(config.autoOpen ?? env.SYSML_VIZ_AUTO_OPEN, true),
    pollMs: pickNumber(config.pollMs ?? env.SYSML_VIZ_POLL_MS, 2000, 500, 60000),
    modelingWindowMs: pickNumber(
      config.modelingWindowMs ?? env.SYSML_VIZ_MODELING_WINDOW_MS, 8000, 500, 3600000,
    ),
    preferPython: pickBool(config.preferPython ?? env.SYSML_VIZ_PREFER_PYTHON, true),
    python: pickString(config.python, env.SYSML_VIZ_PYTHON, 'python3'),
    graphScript: pickString(config.graphScript, env.SYSML_VIZ_GRAPH_SCRIPT),
    pythonTimeoutMs: pickNumber(config.pythonTimeoutMs, 5000, 1000, 60000),
    workspaceDepth: pickNumber(config.workspaceDepth, 4, 1, 8),
    // 建模过程记录：默认开启（只写 <workspace>/.sysml-viz/history/，不碰 IR 本身）。
    history: pickBool(config.history ?? env.SYSML_VIZ_HISTORY, true),
    timelineScript: pickString(config.timelineScript, env.SYSML_VIZ_TIMELINE_SCRIPT),
    timelineTimeoutMs: pickNumber(config.timelineTimeoutMs, 20000, 2000, 120000),
  }
}

/* ------------------------------------------------------------------ *
 * 工作区 / 模型文件发现
 * ------------------------------------------------------------------ */

function isWorkspaceLikely(root) {
  return ['model-output', 'sysml-modeling-agent', '.sysml-viz', '.sysml-agent', '.git']
    .some((name) => existsSync(join(root, name)))
}

/* ------------------------------------------------------------------ *
 * 会话工作区（DSH 桌面端进程 cwd 是 profile 目录，不是会话工作区）
 * ------------------------------------------------------------------ */

/** DSH 把「会话 → 工作区」记录在 ~/.dsh/storages/workspace.json。 */
function sessionStorePath() {
  // 测试/自定义部署可以用 SYSML_VIZ_WORKSPACE_STORE 指向别的 workspace.json
  const override = pickString(process.env.SYSML_VIZ_WORKSPACE_STORE)
  if (override) return override
  return join(homedir(), '.dsh', 'storages', 'workspace.json')
}

const SESSION_STORE_TTL_MS = 1500
let sessionStoreCache = { at: 0, path: '', value: null }

/** 读取并缓存（1.5s）workspace 存储；读不到时返回 null。 */
async function readSessionStore() {
  const path = sessionStorePath()
  const now = Date.now()
  if (
    sessionStoreCache.value !== null
    && sessionStoreCache.path === path
    && now - sessionStoreCache.at < SESSION_STORE_TTL_MS
  ) {
    return sessionStoreCache.value
  }
  let value = null
  try {
    value = JSON.parse(await readFile(path, 'utf8'))
  } catch {
    value = null
  }
  sessionStoreCache = { at: now, path, value }
  return value
}

function sessionIdVariants(raw) {
  const value = String(raw).trim()
  if (!value) return []
  const variants = new Set([value, `session-${value}`])
  if (value.startsWith('session-')) variants.add(value.slice('session-'.length))
  return [...variants]
}

function workspaceRows(store) {
  const tables = store && typeof store === 'object' ? store.tables : null
  const workspaces = tables && typeof tables === 'object' ? tables.workspaces : null
  if (!workspaces || typeof workspaces !== 'object') return []
  return Object.values(workspaces).filter((row) => row && typeof row.path === 'string' && row.path)
}

/**
 * sessionId → 该会话在 DSH 里的工作区路径。
 *
 * 客户端 tab 正文能拿到 props.sessionId，请求时通过 ?sessionId= 带上来；
 * 命中 workspace.json 里的 sessionIds 即返回对应 path（多个命中取 updatedAt 最新）。
 * @param {string} [sessionId] - 会话 id（带不带 session- 前缀都可以）。
 * @returns {Promise<{path:string,source:string,title:string|null}|null>} 工作区信息。
 */
export async function workspaceForSession(sessionId) {
  const variants = sessionIdVariants(sessionId ?? '')
  if (variants.length === 0) return null
  const store = await readSessionStore()
  let best = null
  for (const row of workspaceRows(store)) {
    const ids = Array.isArray(row.sessionIds) ? row.sessionIds : []
    const matched = ids.some((id) => typeof id === 'string' && variants.includes(id))
    if (!matched) continue
    const updatedAt = Date.parse(row.updatedAt ?? '') || 0
    if (best === null || updatedAt > best.updatedAt) {
      best = { path: row.path, updatedAt, title: typeof row.title === 'string' ? row.title : null }
    }
  }
  if (best === null || !existsSync(best.path)) return null
  return { path: best.path, source: 'session-store', title: best.title }
}

/**
 * 没拿到 sessionId 时的兜底：取 workspace.json 里 updatedAt 最新的工作区。
 * @returns {Promise<{path:string,source:string,title:string|null}|null>} 工作区信息。
 */
export async function recentWorkspace() {
  const store = await readSessionStore()
  let best = null
  for (const row of workspaceRows(store)) {
    const updatedAt = Date.parse(row.updatedAt ?? '') || 0
    if (best === null || updatedAt > best.updatedAt) {
      best = { path: row.path, updatedAt, title: typeof row.title === 'string' ? row.title : null }
    }
  }
  if (best === null || !existsSync(best.path)) return null
  return { path: best.path, source: 'recent-workspace', title: best.title }
}

/**
 * 解析一次请求应该优先用的工作区。
 * ?workspace=（绝对路径）> ?sessionId= → workspace.json > 最近工作区（仅无 sessionId 时）。
 * @param {URLSearchParams} query - 请求查询串。
 * @returns {Promise<{extraRoots:string[],sessionId:string|null,sessionWorkspace:object|null}>} 解析结果。
 */
export async function workspaceContextForQuery(query) {
  const extraRoots = []
  const workspaceParam = query?.get?.('workspace') ?? ''
  if (workspaceParam && isAbsolute(workspaceParam) && existsSync(workspaceParam)) {
    extraRoots.push(workspaceParam)
  }
  const sessionId = (query?.get?.('sessionId') ?? '').trim() || null
  let sessionWorkspace = null
  if (sessionId) {
    sessionWorkspace = await workspaceForSession(sessionId)
  } else {
    sessionWorkspace = await recentWorkspace()
  }
  if (sessionWorkspace?.path && !extraRoots.includes(sessionWorkspace.path)) {
    extraRoots.push(sessionWorkspace.path)
  }
  return { extraRoots, sessionId, sessionWorkspace }
}


/**
 * 计算候选工作区根（去重、只保留存在的目录）。
 * @param {ReturnType<typeof readConfig>} cfg - 插件配置。
 * @param {string[]} [extraRoots] - 本次请求解析出的会话工作区（优先级仅次于显式配置）。
 * @returns {Promise<string[]>} 绝对路径列表，按优先级排列。
 */
export async function workspaceRoots(cfg, extraRoots = []) {
  const candidates = []
  const push = (value) => {
    if (typeof value !== 'string' || value.trim() === '') return
    const absolute = resolve(value)
    if (!candidates.includes(absolute)) candidates.push(absolute)
  }
  push(cfg.workspace)
  for (const root of Array.isArray(extraRoots) ? extraRoots : []) push(root)
  push(process.env.SYSML_VIZ_WORKSPACE)
  push(process.env.INIT_CWD)
  push(process.cwd())
  let cursor = process.cwd()
  for (let index = 0; index < 3; index += 1) {
    const parent = dirname(cursor)
    if (parent === cursor) break
    cursor = parent
    push(cursor)
  }
  const existing = []
  for (const candidate of candidates) {
    try {
      const info = await stat(candidate)
      if (info.isDirectory()) existing.push(candidate)
    } catch {
      /* 不存在的工作区根直接跳过 */
    }
  }
  return existing.slice(0, 6)
}

async function listIrUnder(directory) {
  try {
    const entries = await readdir(directory, { withFileTypes: true })
    return entries
      .filter((entry) => entry.isFile() && entry.name.endsWith(IR_SUFFIX))
      .map((entry) => join(directory, entry.name))
  } catch {
    return []
  }
}

async function newestOf(paths) {
  const rows = []
  for (const path of paths) {
    try {
      const info = await stat(path)
      rows.push({ path, mtimeMs: info.mtimeMs })
    } catch {
      /* 忽略读不到的文件 */
    }
  }
  rows.sort((a, b) => b.mtimeMs - a.mtimeMs)
  return rows
}

/** 某个路径在发现打分里的优先级。 */
function pathScore(root, path) {
  const relative = path.startsWith(root) ? path.slice(root.length + 1) : path
  if (relative.startsWith('.sysml-viz/')) return 1000
  if (relative.startsWith('.sysml-agent/')) {
    return relative.includes('_evidence') ? 300 : 950
  }
  if (relative.startsWith('model-output/')) {
    return relative.includes('/_evidence/') ? 320 : 800
  }
  if (relative.includes('/examples/')) return 50
  if (relative.includes('/skills/')) return 100
  if (relative.includes('/docs/demo/')) return 200
  if (relative.includes('_evidence')) return 20
  if (/(^|[-_.])(draft|before|baseline\.min|step\d|imported|patched)([-_.]|$)/i.test(path)) return 260
  return 400
}

async function walkIrFiles(root, maxDepth) {
  if (!isWorkspaceLikely(root)) return []
  const files = []
  let visited = 0
  const queue = [{ directory: root, depth: 0 }]
  while (queue.length > 0 && visited < MAX_WALK_DIRS) {
    const { directory, depth } = queue.shift()
    let entries
    try {
      entries = await readdir(directory, { withFileTypes: true })
    } catch {
      continue
    }
    for (const entry of entries) {
      visited += 1
      if (visited >= MAX_WALK_DIRS) break
      const name = entry.name
      if (name.startsWith('.') && name !== '.sysml-viz' && name !== '.sysml-agent') continue
      const path = join(directory, name)
      if (entry.isDirectory()) {
        if (SKIP_DIRS.has(name)) continue
        if (depth + 1 <= maxDepth) queue.push({ directory: path, depth: depth + 1 })
      } else if (entry.isFile() && name.endsWith(IR_SUFFIX)) {
        files.push(path)
      }
    }
  }
  return files
}

/**
 * 在一个工作区根下按优先级找一个 IR 文件。
 * @param {string} root - 工作区根。
 * @param {number} maxDepth - 递归深度上限。
 * @returns {Promise<{path:string, source:string, score:number}|null>} 命中的模型。
 */
async function discoverUnder(root, maxDepth) {
  const direct = []
  const dotModel = join(root, '.sysml-viz', 'model.ir.json')
  if (existsSync(dotModel)) direct.push({ path: dotModel, source: 'dotdir', score: 1000 })
  const storeModel = join(root, '.sysml-agent', 'model.ir.json')
  if (existsSync(storeModel)) direct.push({ path: storeModel, source: 'store', score: 950 })
  try {
    const storeDirs = await readdir(join(root, '.sysml-agent'), { withFileTypes: true })
    for (const entry of storeDirs) {
      if (!entry.isDirectory()) continue
      const candidate = join(root, '.sysml-agent', entry.name, 'model.ir.json')
      if (existsSync(candidate)) direct.push({ path: candidate, source: 'store', score: 940 })
    }
  } catch {
    /* 没有 .sysml-agent 目录 */
  }
  try {
    const packages = await readdir(join(root, 'model-output'), { withFileTypes: true })
    for (const entry of packages) {
      if (!entry.isDirectory() || entry.name.startsWith('_') || entry.name.startsWith('.')) continue
      const files = await listIrUnder(join(root, 'model-output', entry.name))
      for (const path of files) direct.push({ path, source: 'model-output', score: 800 })
    }
  } catch {
    /* 没有 model-output 目录 */
  }

  let picked = null
  const consider = (row) => {
    if (picked === null || row.score > picked.score) {
      picked = row
    } else if (row.score === picked.score) {
      if ((row.mtimeMs ?? 0) > (picked.mtimeMs ?? 0)) picked = row
    }
  }
  const directRows = await newestOf(direct.map((row) => row.path))
  const mtimeOf = new Map(directRows.map((row) => [row.path, row.mtimeMs]))
  for (const row of direct) consider({ ...row, mtimeMs: mtimeOf.get(row.path) ?? 0 })

  if (picked === null) {
    const walked = await walkIrFiles(root, maxDepth)
    const sorted = await newestOf(walked)
    for (const row of sorted) {
      const score = pathScore(root, row.path)
      const candidate = { path: row.path, source: 'walk', score, mtimeMs: row.mtimeMs }
      if (picked === null || candidate.score > picked.score) picked = candidate
    }
  }
  return picked
}

/**
 * 解析要加载的 IR 文件。
 * @param {ReturnType<typeof readConfig>} cfg - 插件配置。
 * @param {string} [explicitPath] - 请求 ?path= 传入的显式路径。
 * @param {string[]} [extraRoots] - 本次请求的会话工作区（见 workspaceContextForQuery）。
 * @returns {Promise<{path:string|null, source:string, roots:string[], searched:string[]}>} 解析结果。
 */
export async function resolveModelPath(cfg, explicitPath, extraRoots = []) {
  const roots = await workspaceRoots(cfg, extraRoots)
  const searched = []
  if (explicitPath) {
    const absolute = isAbsolute(explicitPath) ? explicitPath : resolve(roots[0] ?? process.cwd(), explicitPath)
    searched.push(absolute)
    if (existsSync(absolute)) return { path: absolute, source: 'query', roots, searched }
    return { path: null, source: 'query', roots, searched }
  }
  if (cfg.model) {
    const absolute = isAbsolute(cfg.model) ? cfg.model : resolve(roots[0] ?? process.cwd(), cfg.model)
    searched.push(absolute)
    if (existsSync(absolute)) {
      return { path: absolute, source: 'config-or-env', roots, searched }
    }
  }
  for (const root of roots) {
    const hit = await discoverUnder(root, cfg.workspaceDepth)
    if (hit) {
      return { path: hit.path, source: hit.source, roots, searched: [...searched, hit.path] }
    }
    searched.push(join(root, 'model-output', '*', IR_SUFFIX))
  }
  return { path: null, source: 'discovery', roots, searched }
}

/* ------------------------------------------------------------------ *
 * 通用小工具
 * ------------------------------------------------------------------ */

const CJK = /[\u2190-\u21ff\u2b00-\u2bff\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/
const LATIN_WIDTH_RATIO = 0.6

function textWidth(text, fontSize) {
  let width = 0
  for (const char of String(text)) width += CJK.test(char) ? fontSize : fontSize * LATIN_WIDTH_RATIO
  return width
}

function wrapText(text, maxPx, fontSize) {
  const lines = []
  let current = ''
  let width = 0
  for (const char of String(text ?? '')) {
    const charWidth = CJK.test(char) ? fontSize : fontSize * LATIN_WIDTH_RATIO
    if (width + charWidth > maxPx && current) {
      lines.push(current)
      current = ''
      width = 0
    }
    current += char
    width += charWidth
  }
  if (current) lines.push(current)
  return lines
}

function wrapLimited(text, maxPx, fontSize, maxLines) {
  const lines = wrapText(text, maxPx, fontSize)
  if (lines.length <= maxLines) return lines.map((line) => ({ c: 'bd', t: line }))
  const kept = lines.slice(0, maxLines)
  kept[maxLines - 1] = `${kept[maxLines - 1].slice(0, -1)}…`
  return kept.map((line) => ({ c: 'bd', t: line }))
}

const LINE_HEIGHT = {
  st: 13, ttl: 19, sub: 13, div: 10, bd: 14, kv: 13, val: 18, note: 13, chk: 15,
}
/** 与 client.js 的 .svz-l-* 字号保持一致，换行估算不能再用「大概 10px」。 */
const LINE_FONT = {
  st: 10.5, ttl: 13.5, sub: 10, bd: 10.5, kv: 10.5, val: 12.5, note: 10.5, chk: 11,
}
const TEXT_PADDING = 12
const NODE_PADDING = TEXT_PADDING * 2
const DEF_WIDTH = 190
const REQUIREMENT_WIDTH = 300
const CONSTRAINT_WIDTH = 260
const STATE_DEF_WIDTH = 320

function measureLines(lines) {
  let height = NODE_PADDING
  for (const line of lines ?? []) {
    if (line.c === 'div') {
      height += LINE_HEIGHT.div
      continue
    }
    height += LINE_HEIGHT[line.c] ?? LINE_HEIGHT.bd
  }
  return Math.max(48, Math.round(height))
}

const ST = (t) => ({ c: 'st', t })
const TTL = (t) => ({ c: 'ttl', t })
const SUB = (t) => ({ c: 'sub', t })
const KV = (key, value) => ({ c: 'kv', t: `${key}  ${value}` })
const DIV = { c: 'div' }
const NOTE = (t) => ({ c: 'note', t })
const BD = (t) => ({ c: 'bd', t })

function kindCounts(elements) {
  const counts = {}
  for (const element of elements) counts[element.kind] = (counts[element.kind] ?? 0) + 1
  return counts
}

function relCount(elements) {
  return elements.reduce((total, element) => total + (Array.isArray(element.relations) ? element.relations.length : 0), 0)
}

function shortKind(kind) {
  const map = {
    Requirement: 'requirement',
    PartDefinition: 'part def',
    PartUsage: 'part',
    Connection: 'connection',
    Attribute: 'attribute',
    Constraint: 'constraint',
    StateDefinition: 'state def',
    ActionDefinition: 'action def',
    PortDefinition: 'port def',
  }
  return map[kind] ?? String(kind ?? 'element').toLowerCase()
}

function approxTextWidth(text, fontSize = 10) {
  return textWidth(text, fontSize)
}

function boundsOf(nodes, groups) {
  let maxX = 0
  let maxY = 0
  let minX = Infinity
  let minY = Infinity
  for (const node of nodes) {
    maxX = Math.max(maxX, node.x + node.w)
    maxY = Math.max(maxY, node.y + node.h)
    minX = Math.min(minX, node.x)
    minY = Math.min(minY, node.y)
  }
  for (const group of groups ?? []) {
    maxX = Math.max(maxX, group.x + group.w)
    maxY = Math.max(maxY, group.y + group.h)
    minX = Math.min(minX, group.x)
    minY = Math.min(minY, group.y)
  }
  if (!Number.isFinite(minX)) return { maxX: 640, maxY: 480 }
  return { maxX, maxY, minX, minY }
}

/* ------------------------------------------------------------------ *
 * JS 兜底图投影（sysml-graph/v1）
 * ------------------------------------------------------------------ */

function makeNode({ id, elementId = null, kind, lines, x, y, w, h }) {
  const measured = h ?? measureLines(lines)
  return {
    id: String(id),
    elementId: elementId ?? null,
    kind,
    x: Math.round(x ?? 0),
    y: Math.round(y ?? 0),
    w: Math.round(w),
    h: Math.round(measured),
    lines,
    label: labelOfLines(lines),
  }
}

function labelOfLines(lines) {
  const title = (lines ?? []).find((line) => line.c === 'ttl')
  if (title) return title.t
  const first = (lines ?? []).find((line) => typeof line.t === 'string' && line.t)
  return first ? first.t : ''
}

function defLines(element, attributes) {
  const lines = [ST('«part def»'), TTL(element.name ?? element.id), SUB(element.id)]
  const description = element.properties?.description
  if (typeof description === 'string' && description) {
    lines.push(DIV, ...wrapLimited(description, DEF_WIDTH - NODE_PADDING, LINE_FONT.bd, 2))
  }
  const owned = attributes.filter((attribute) => attribute.owner === element.id)
  if (owned.length > 0) {
    lines.push(DIV, KV('属性', `${owned.length} 个`))
  }
  return lines
}

function usageLines(element) {
  const properties = element.properties ?? {}
  const quantity = properties.quantity ?? 1
  return [
    ST('«part»'),
    TTL(element.name ?? element.id),
    KV(': ' + (properties.typeRef ?? '?'), `[${quantity}]`),
  ]
}

function requirementLines(element) {
  const properties = element.properties ?? {}
  const lines = [
    ST('«requirement def»'),
    TTL(element.name ?? element.id),
    SUB(element.id),
    DIV,
    ...wrapLimited(properties.text, REQUIREMENT_WIDTH - NODE_PADDING, LINE_FONT.bd, 2),
  ]
  if (properties.acceptanceCriteria) {
    lines.push(...wrapLimited('ac: ' + properties.acceptanceCriteria, REQUIREMENT_WIDTH - NODE_PADDING, LINE_FONT.bd, 2))
  }
  if (properties.verifyMethod) lines.push(KV('verify', properties.verifyMethod))
  if (properties.priority) lines.push(KV('priority', properties.priority))
  return lines
}

function actionLines(element) {
  const properties = element.properties ?? {}
  const lines = [ST('«action def»'), TTL(element.name ?? element.id), SUB(element.id)]
  for (const input of properties.inputs ?? []) {
    lines.push(KV('in ', `${input?.[0] ?? '?'} : ${input?.[1] ?? '?'}`))
  }
  for (const output of properties.outputs ?? []) {
    lines.push(KV('out', `${output?.[0] ?? '?'} : ${output?.[1] ?? '?'}`))
  }
  return lines
}

function connectionLines(element) {
  const properties = element.properties ?? {}
  const flow = properties.flowKind ?? 'connection'
  return [
    ST('«connection»'),
    TTL(element.name ?? element.id),
    KV('flowKind', flow),
    SUB(element.id),
  ]
}

function stateDefinitionLines(element) {
  const properties = element.properties ?? {}
  const states = Array.isArray(properties.states) ? properties.states : []
  const transitions = Array.isArray(properties.transitions) ? properties.transitions : []
  const lines = [ST('«state def»'), TTL(element.name ?? element.id), SUB(element.id)]
  lines.push(KV('states', String(states.length)), KV('transitions', String(transitions.length)))
  if (properties.description) {
    lines.push(DIV, ...wrapLimited(properties.description, STATE_DEF_WIDTH - NODE_PADDING, LINE_FONT.bd, 2))
  }
  return lines
}

function elementBoxLines(element) {
  switch (element.kind) {
    case 'Requirement': return requirementLines(element)
    case 'PartDefinition': return defLines(element, [])
    case 'PartUsage': return usageLines(element)
    case 'ActionDefinition': return actionLines(element)
    case 'Constraint': return constraintLines(element)
    case 'Attribute': return attributeLines(element)
    case 'Connection': return connectionLines(element)
    case 'StateDefinition': return stateDefinitionLines(element)
    default: return [ST(`«${shortKind(element.kind)}»`), TTL(element.name ?? element.id), SUB(element.id)]
  }
}

function attributeLines(element) {
  const properties = element.properties ?? {}
  const value = properties.defaultValue ?? properties.value ?? ''
  const unit = properties.unit ?? ''
  return [
    ST('«attribute»'),
    TTL(element.name ?? element.id),
    { c: 'val', t: `${value}${unit ? ' ' + unit : ''}` },
    SUB(element.id),
  ]
}

function constraintLines(element) {
  const properties = element.properties ?? {}
  const lines = [ST('«constraint def»'), TTL(element.name ?? element.id), SUB(element.id), DIV]
  const expression = properties.expression ?? ''
  for (const row of wrapText(expression, CONSTRAINT_WIDTH - NODE_PADDING, LINE_FONT.kv)) {
    lines.push({ c: 'kv', t: row })
  }
  const parameters = Array.isArray(properties.parameters) ? properties.parameters : []
  if (parameters.length > 0) lines.push(DIV, KV('parameters', String(parameters.length)))
  return lines
}

function traceLines(element) {
  const lines = elementBoxLines(element)
  return lines
}

function sidesFor(a, b) {
  const dx = (a.x + a.w / 2) - (b.x + b.w / 2)
  const dy = (a.y + a.h / 2) - (b.y + b.h / 2)
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx > 0 ? { fromSide: 'l', toSide: 'r' } : { fromSide: 'r', toSide: 'l' }
  }
  return dy > 0 ? { fromSide: 't', toSide: 'b' } : { fromSide: 'b', toSide: 't' }
}

function addEdge(list, from, to, options = {}) {
  if (!from || !to || from === to) {
    if (from === to && from) {
      list.push({ id: `e-${list.length + 1}`, from, to, self: true, kind: options.kind ?? 'dep', label: options.label ?? '', sub: options.sub ?? null, via: null, labelAt: null })
    }
    return
  }
  list.push({
    id: options.id ?? `e-${list.length + 1}`,
    from,
    to,
    kind: options.kind ?? 'dep',
    label: options.label ?? '',
    sub: options.sub ?? null,
    fromSide: options.fromSide,
    toSide: options.toSide,
    fromOff: options.fromOff ?? 0.5,
    toOff: options.toOff ?? 0.5,
    via: options.via ?? null,
    labelAt: options.labelAt ?? null,
  })
}

/**
 * PartDefinition 组合关系：decomposes 关系优先，其次由 PartUsage 的 owner/typeRef 推导。
 * @param {Array<object>} elements - IR 元素。
 * @returns {{definitions:object[], definitionIds:Set<string>, usages:object[], parentOf:Map<string,string>, edgeLabels:Map<string,string>}} 组合结构。
 */
export function compositionOf(elements) {
  const definitions = elements.filter((element) => element.kind === 'PartDefinition')
  const definitionIds = new Set(definitions.map((element) => element.id))
  const usages = elements.filter((element) => element.kind === 'PartUsage')
  const parentOf = new Map()
  const edgeLabels = new Map()
  const add = (parent, child, label) => {
    if (!definitionIds.has(parent) || !definitionIds.has(child) || parent === child) return
    if (parentOf.has(child)) return
    parentOf.set(child, parent)
    edgeLabels.set(`${parent}>${child}`, label)
  }
  for (const definition of definitions) {
    for (const relation of definition.relations ?? []) {
      if (relation.type !== 'decomposes') continue
      add(definition.id, relation.target, 'decomposes')
    }
  }
  for (const usage of usages) {
    const parent = definitionIds.has(usage.owner) ? usage.owner : null
    const child = definitionIds.has(usage.properties?.typeRef) ? usage.properties.typeRef : null
    if (parent && child) add(parent, child, `«part» ${usage.name ?? usage.id}`)
  }
  return { definitions, definitionIds, usages, parentOf, edgeLabels }
}

/**
 * 结构视图：PartDefinition 组合树 + 各定义下的 PartUsage（«type» 关系）。
 * @param {Array<object>} elements - IR 元素。
 * @param {Map<string, object>} byId - id → 元素。
 * @returns {object|null} 视图。
 */
function buildStructureView(elements, byId) {
  const composition = compositionOf(elements)
  const { definitions, definitionIds, usages } = composition
  if (definitions.length === 0) return null
  const attributes = elements.filter((element) => element.kind === 'Attribute')
  const parentOf = composition.parentOf
  const compEdge = composition.edgeLabels
  const childMap = new Map()
  for (const definition of definitions) {
    const parent = parentOf.get(definition.id)
    if (!parent) continue
    if (!childMap.has(parent)) childMap.set(parent, [])
    childMap.get(parent).push(definition.id)
  }
  for (const children of childMap.values()) {
    children.sort((a, b) => String(byId.get(a)?.name ?? a).localeCompare(String(byId.get(b)?.name ?? b)))
  }

  const roots = definitions.filter((definition) => !parentOf.has(definition.id))
  const root = roots[0] ?? definitions[0]
  for (const definition of roots) {
    if (definition === root || parentOf.has(definition.id)) continue
    parentOf.set(definition.id, root.id)
    compEdge.set(`${root.id}>${definition.id}`, '«package»')
    if (!childMap.has(root.id)) childMap.set(root.id, [])
    childMap.get(root.id).push(definition.id)
  }

  const depth = new Map([[root.id, 0]])
  const queue = [root.id]
  while (queue.length > 0) {
    const id = queue.shift()
    for (const child of childMap.get(id) ?? []) {
      if (depth.has(child)) continue
      depth.set(child, (depth.get(id) ?? 0) + 1)
      queue.push(child)
    }
  }
  for (const definition of definitions) if (!depth.has(definition.id)) depth.set(definition.id, 1)

  const usagesByDefinition = new Map()
  for (const usage of usages) {
    const typeRef = usage.properties?.typeRef
    const owner = usage.owner
    const attach = definitionIds.has(typeRef) ? typeRef : (definitionIds.has(owner) ? owner : null)
    if (!attach) continue
    if (!usagesByDefinition.has(attach)) usagesByDefinition.set(attach, [])
    usagesByDefinition.get(attach).push(usage)
  }
  for (const list of usagesByDefinition.values()) {
    list.sort((a, b) => String(a.name ?? a.id).localeCompare(String(b.name ?? b.id)))
  }

  const defWidth = 216
  const usageWidth = 168
  const usageHeight = 58
  const gapX = 44
  const levelGap = 56
  const levels = new Map()
  for (const definition of definitions) {
    const level = depth.get(definition.id) ?? 0
    if (!levels.has(level)) levels.set(level, [])
    levels.get(level).push(definition.id)
  }
  for (const ids of levels.values()) {
    ids.sort((a, b) => {
      const parentA = parentOf.get(a) ?? ''
      const parentB = parentOf.get(b) ?? ''
      if (parentA !== parentB) return parentA.localeCompare(parentB)
      return String(byId.get(a)?.name ?? a).localeCompare(String(byId.get(b)?.name ?? b))
    })
  }
  const maxLevel = Math.max(...levels.keys(), 0)
  let levelWidth = 640
  for (const ids of levels.values()) {
    levelWidth = Math.max(levelWidth, ids.length * defWidth + (ids.length - 1) * gapX + 120)
  }

  const nodes = []
  const edges = []
  let y = 54
  for (let level = 0; level <= maxLevel; level += 1) {
    const ids = levels.get(level) ?? []
    const x0 = (levelWidth - (ids.length * defWidth + (ids.length - 1) * gapX)) / 2
    let rowHeight = 0
    ids.forEach((id, index) => {
      const element = byId.get(id)
      const lines = defLines(element, attributes)
      const node = makeNode({
        id: `def:${id}`,
        elementId: id,
        kind: 'block',
        lines,
        x: x0 + index * (defWidth + gapX),
        y,
        w: defWidth,
      })
      nodes.push(node)
      rowHeight = Math.max(rowHeight, node.h)
      const attached = usagesByDefinition.get(id) ?? []
      attached.forEach((usage, usageIndex) => {
        const columns = attached.length <= 2 ? 1 : 2
        const rows = Math.ceil(attached.length / columns)
        const column = usageIndex % columns
        const row = Math.floor(usageIndex / columns)
        const usageX = node.x + (defWidth - (columns * usageWidth + (columns - 1) * 10)) / 2 + column * (usageWidth + 10)
        const usageY = node.y + node.h + 28 + row * (usageHeight + 12)
        const usageNode = makeNode({
          id: `usage:${usage.id}`,
          elementId: usage.id,
          kind: 'usage',
          lines: usageLines(usage),
          x: usageX,
          y: usageY,
          w: usageWidth,
          h: usageHeight,
        })
        nodes.push(usageNode)
        edges.push({
          id: `type:${usage.id}`,
          from: node.id,
          to: usageNode.id,
          kind: 'dep',
          label: '«type»',
          sub: null,
          fromSide: 'b',
          toSide: 't',
          fromOff: 0.5,
          toOff: 0.5,
          via: null,
          labelAt: null,
        })
        rowHeight = Math.max(rowHeight, usageNode.y + usageNode.h - y)
      })
    })
    y += rowHeight + levelGap
  }

  for (const [key, label] of compEdge.entries()) {
    const [fromId, toId] = key.split('>')
    edges.push({
      id: `comp:${fromId}>${toId}`,
      from: `def:${fromId}`,
      to: `def:${toId}`,
      kind: 'comp',
      label,
      sub: null,
      fromSide: 'b',
      toSide: 't',
      fromOff: 0.5,
      toOff: 0.5,
      via: null,
      labelAt: null,
    })
  }

  const bounds = boundsOf(nodes, [])
  const width = Math.max(levelWidth, bounds.maxX + 60)
  const height = Math.max(bounds.maxY + 48, 480)
  const groups = [{
    id: 'g-package',
    x: 16,
    y: 16,
    w: width - 32,
    h: height - 32,
    label: `«package» ${byId.get(root.id)?.owner || 'model'} · ${definitions.length} 个 part def`,
  }]
  return {
    viewId: 'structure',
    kind: 'structure',
    title: '结构（BDD）',
    scope: { element: root.id === undefined ? null : root.id },
    width: Math.round(width),
    height: Math.round(height),
    nodes,
    edges,
    groups,
  }
}

function inferFlowKind(fromElement, toElement) {
  const fromType = String(fromElement?.properties?.typeRef ?? fromElement?.name ?? '').toLowerCase()
  const toType = String(toElement?.properties?.typeRef ?? toElement?.name ?? '').toLowerCase()
  const battery = /batt|battery/.test(fromType)
  const esc = /esc|speedcontroller|regulator/.test(fromType) || /esc|speedcontroller|regulator/.test(toType)
  if (battery && esc) return 'electrical'
  if (/motor/.test(fromType) || /prop|rotor/.test(toType)) return 'mechanical'
  if (/esc/.test(fromType) || /motor/.test(toType)) return 'electrical'
  return 'connect'
}

/**
 * IBD 视图：PartUsage + Connection / connects 关系。
 * @param {Array<object>} elements - IR 元素。
 * @param {Map<string, object>} byId - id → 元素。
 * @returns {object|null} 视图。
 */
function buildIbdView(elements, byId) {
  const usages = elements.filter((element) => element.kind === 'PartUsage')
  if (usages.length === 0) return null
  const usageIds = new Set(usages.map((usage) => usage.id))
  const connections = elements.filter((element) => element.kind === 'Connection')
  const rawEdges = []
  const seen = new Set()
  const pushRaw = (from, to, label, sub, kind) => {
    if (!usageIds.has(from) || !usageIds.has(to) || from === to) return
    const key = `${from}>${to}>${kind}`
    if (seen.has(key)) return
    seen.add(key)
    rawEdges.push({ from, to, label, sub, kind })
  }
  for (const connection of connections) {
    const properties = connection.properties ?? {}
    const flow = String(properties.flowKind ?? '').toLowerCase()
    const kind = flow === 'mechanical' ? 'flow-mech' : (flow === 'electrical' ? 'flow-el' : 'dep')
    pushRaw(properties.sourceRef, properties.targetRef, properties.flowKind ?? 'connection', connection.name, kind)
  }
  for (const usage of usages) {
    for (const relation of usage.relations ?? []) {
      if (relation.type !== 'connects') continue
      if (!usageIds.has(relation.target)) continue
      const kind = inferFlowKind(usage, byId.get(relation.target)) === 'mechanical' ? 'flow-mech' : 'flow-el'
      pushRaw(usage.id, relation.target, inferFlowKind(usage, byId.get(relation.target)), null, kind)
    }
  }

  const involved = new Set()
  for (const edge of rawEdges) {
    involved.add(edge.from)
    involved.add(edge.to)
  }
  const display = usages.filter((usage) => involved.has(usage.id))
  const shown = display.length >= 2 ? display : usages.slice(0, 8)
  const shownIds = new Set(shown.map((usage) => usage.id))
  const edgesRaw = rawEdges.filter((edge) => shownIds.has(edge.from) && shownIds.has(edge.to))

  // 分层：最长路径分层（对环有迭代上限）
  const layer = new Map(shown.map((usage) => [usage.id, 0]))
  for (let pass = 0; pass < shown.length + 2; pass += 1) {
    let changed = false
    for (const edge of edgesRaw) {
      const next = (layer.get(edge.from) ?? 0) + 1
      if ((layer.get(edge.to) ?? 0) < next && next < shown.length + 2) {
        layer.set(edge.to, next)
        changed = true
      }
    }
    if (!changed) break
  }
  const byLayer = new Map()
  for (const usage of shown) {
    const value = layer.get(usage.id) ?? 0
    if (!byLayer.has(value)) byLayer.set(value, [])
    byLayer.get(value).push(usage.id)
  }
  for (const ids of byLayer.values()) {
    ids.sort((a, b) => String(byId.get(a)?.name ?? a).localeCompare(String(byId.get(b)?.name ?? b)))
  }

  const nodeWidth = 190
  const nodeHeight = 82
  const columnGap = 66
  const rowGap = 40
  const nodes = []
  const nodeMap = new Map()
  const maxLayer = Math.max(...byLayer.keys(), 0)
  let maxRows = 1
  for (const ids of byLayer.values()) maxRows = Math.max(maxRows, ids.length)
  const contentHeight = maxRows * nodeHeight + (maxRows - 1) * rowGap
  for (const [layerIndex, ids] of [...byLayer.entries()].sort((a, b) => a[0] - b[0])) {
    const columnHeight = ids.length * nodeHeight + (ids.length - 1) * rowGap
    const y0 = 84 + (contentHeight - columnHeight) / 2
    ids.forEach((id, index) => {
      const usage = byId.get(id)
      const node = makeNode({
        id: `usage:${id}`,
        elementId: id,
        kind: 'usage',
        lines: usageLines(usage),
        x: 48 + layerIndex * (nodeWidth + columnGap),
        y: y0 + index * (nodeHeight + rowGap),
        w: nodeWidth,
        h: nodeHeight,
      })
      nodes.push(node)
      nodeMap.set(id, node)
    })
  }
  const edges = []
  for (const edge of edgesRaw) {
    const fromNode = nodeMap.get(edge.from)
    const toNode = nodeMap.get(edge.to)
    if (!fromNode || !toNode) continue
    const sides = sidesFor(fromNode, toNode)
    edges.push({
      id: `conn:${edge.from}>${edge.to}`,
      from: fromNode.id,
      to: toNode.id,
      kind: edge.kind,
      label: edge.label || '',
      sub: edge.sub ?? null,
      fromSide: sides.fromSide,
      toSide: sides.toSide,
      fromOff: 0.5,
      toOff: 0.5,
      via: null,
      labelAt: null,
    })
  }

  const ownerId = shown[0]?.owner
  const frameUsage = usages.find((usage) => usage.properties?.typeRef === ownerId) ?? null
  const frameLabel = frameUsage
    ? `«part» ${frameUsage.name} : ${byId.get(frameUsage.properties?.typeRef)?.name ?? ownerId} [${frameUsage.properties?.quantity ?? 1}]`
    : `«package» ${byId.get(shown[0]?.id)?.owner ?? 'model'}`
  const width = 48 * 2 + (maxLayer + 1) * nodeWidth + maxLayer * columnGap
  const height = 84 + contentHeight + 72
  const groups = [{ id: 'g-ibd', x: 18, y: 18, w: width - 36, h: height - 36, label: frameLabel }]
  return {
    viewId: 'ibd',
    kind: 'ibd',
    title: '互联（IBD）',
    scope: { element: ownerId ?? null },
    width: Math.round(width),
    height: Math.round(height),
    nodes,
    edges,
    groups,
  }
}

/**
 * 需求视图：Requirement 分层 + trace 卫星节点。
 * @param {Array<object>} elements - IR 元素。
 * @param {Map<string, object>} byId - id → 元素。
 * @returns {object|null} 视图。
 */
function buildRequirementView(elements, byId) {
  const requirements = elements.filter((element) => element.kind === 'Requirement')
  if (requirements.length === 0) return null
  const reqIds = new Set(requirements.map((requirement) => requirement.id))
  const parentOf = new Map()
  const hierarchyEdges = []
  for (const requirement of requirements) {
    for (const relation of requirement.relations ?? []) {
      if (!reqIds.has(relation.target) || relation.target === requirement.id) continue
      if (relation.type === 'decomposes') {
        if (!parentOf.has(relation.target)) parentOf.set(relation.target, requirement)
        hierarchyEdges.push({ from: requirement.id, to: relation.target, label: 'decomposes' })
      } else if (relation.type === 'refines') {
        if (!parentOf.has(requirement.id)) parentOf.set(requirement.id, byId.get(relation.target))
        hierarchyEdges.push({ from: requirement.id, to: relation.target, label: 'refines' })
      }
    }
  }
  const depth = new Map()
  const depthOf = (requirement, guard = new Set()) => {
    if (depth.has(requirement.id)) return depth.get(requirement.id)
    if (guard.has(requirement.id)) return 0
    guard.add(requirement.id)
    const parent = parentOf.get(requirement.id)
    const value = parent && reqIds.has(parent.id) ? depthOf(parent, guard) + 1 : 0
    depth.set(requirement.id, value)
    return value
  }
  for (const requirement of requirements) depthOf(requirement)
  const byDepth = new Map()
  for (const requirement of requirements) {
    const value = depth.get(requirement.id) ?? 0
    if (!byDepth.has(value)) byDepth.set(value, [])
    byDepth.get(value).push(requirement)
  }
  for (const list of byDepth.values()) {
    list.sort((a, b) => String(a.name ?? a.id).localeCompare(String(b.name ?? b.id)))
  }

  const cardWidth = 316
  const columnGap = 62
  const rowGap = 26
  const nodes = []
  const reqNodeId = new Map()
  const maxDepth = Math.max(...byDepth.keys(), 0)
  let maxRows = 1
  for (const list of byDepth.values()) maxRows = Math.max(maxRows, list.length)
  // 先量出每张卡片高度，用于本列的堆叠
  const measured = new Map()
  for (const requirement of requirements) {
    const lines = requirementLines(requirement)
    measured.set(requirement.id, measureLines(lines))
  }
  for (const [level, list] of [...byDepth.entries()].sort((a, b) => a[0] - b[0])) {
    const columnHeight = list.reduce((total, requirement) => total + (measured.get(requirement.id) ?? 180), 0)
      + (list.length - 1) * rowGap
    let y = 60 + Math.max(0, (maxRows * 180 - columnHeight) / 2)
    for (const requirement of list) {
      const lines = requirementLines(requirement)
      const node = makeNode({
        id: `req:${requirement.id}`,
        elementId: requirement.id,
        kind: 'requirement',
        lines,
        x: 40 + level * (cardWidth + columnGap),
        y,
        w: cardWidth,
      })
      nodes.push(node)
      reqNodeId.set(requirement.id, node)
      y += node.h + rowGap
    }
  }
  const edges = []
  for (const edge of hierarchyEdges) {
    const fromNode = reqNodeId.get(edge.from)
    const toNode = reqNodeId.get(edge.to)
    if (!fromNode || !toNode) continue
    const sides = sidesFor(fromNode, toNode)
    edges.push({
      id: `rel:${edge.from}>${edge.to}`,
      from: fromNode.id,
      to: toNode.id,
      kind: 'trace',
      label: edge.label,
      sub: null,
      fromSide: sides.fromSide,
      toSide: sides.toSide,
      fromOff: 0.5,
      toOff: 0.5,
      via: null,
      labelAt: null,
    })
  }

  // trace 卫星：satisfiedBy / verifies 提供方
  const satellites = new Map()
  const satelliteTargets = []
  const considerSatellite = (providerId, requirementId, relationType) => {
    if (!reqIds.has(requirementId)) return
    const provider = byId.get(providerId)
    if (!provider || reqIds.has(providerId)) return
    const key = `${providerId}>${requirementId}`
    if (satellites.has(key)) return
    satellites.set(key, { providerId, requirementId, relationType })
    satelliteTargets.push({ providerId, requirementId, relationType })
  }
  for (const requirement of requirements) {
    for (const relation of requirement.relations ?? []) {
      if (relation.type === 'satisfiedBy' || relation.type === 'verifies') {
        considerSatellite(relation.target, requirement.id, relation.type)
      }
    }
  }
  for (const element of elements) {
    for (const relation of element.relations ?? []) {
      if (relation.type === 'satisfiedBy' || relation.type === 'verifies') {
        considerSatellite(element.id, relation.target, relation.type)
      }
    }
  }
  const limited = satelliteTargets.slice(0, 14)
  const satelliteNodes = new Map()
  const satelliteX = 40 + (maxDepth + 1) * (cardWidth + columnGap)
  let satelliteY = 60
  for (const satellite of limited) {
    const provider = byId.get(satellite.providerId)
    if (!provider) continue
    const lines = traceLines(provider)
    const node = makeNode({
      id: `trace:${satellite.providerId}`,
      elementId: satellite.providerId,
      kind: 'trace',
      lines,
      x: satelliteX,
      y: satelliteY,
      w: 206,
    })
    satelliteY += node.h + 18
    if (!satelliteNodes.has(satellite.providerId)) {
      satelliteNodes.set(satellite.providerId, node)
      nodes.push(node)
    }
  }
  for (const satellite of limited) {
    const node = satelliteNodes.get(satellite.providerId)
    const reqNode = reqNodeId.get(satellite.requirementId)
    if (!node || !reqNode) continue
    edges.push({
      id: `trace:${satellite.providerId}>${satellite.requirementId}`,
      from: node.id,
      to: reqNode.id,
      kind: satellite.relationType === 'verifies' ? 'verify' : 'trace',
      label: satellite.relationType,
      sub: null,
      fromSide: 'l',
      toSide: 'r',
      fromOff: 0.5,
      toOff: 0.5,
      via: null,
      labelAt: null,
    })
  }

  const bounds = boundsOf(nodes, [])
  const width = Math.max(bounds.maxX + 50, 660)
  const height = Math.max(bounds.maxY + 60, 480)
  const groups = [{
    id: 'g-req',
    x: 16,
    y: 16,
    w: width - 32,
    h: height - 32,
    label: `«package» ${requirements[0]?.owner || 'requirements'} · ${requirements.length} 条需求 · ${relCount(elements)} 条关系`,
  }]
  return {
    viewId: 'requirement',
    kind: 'requirement',
    title: '需求视图',
    scope: { element: null },
    width: Math.round(width),
    height: Math.round(height),
    nodes,
    edges,
    groups,
  }
}

/**
 * 状态机视图（每个 StateDefinition 一张，最多 3 张）。
 * @param {Array<object>} elements - IR 元素。
 * @returns {object[]} 视图列表。
 */
function buildStateViews(elements) {
  const definitions = elements.filter((element) => element.kind === 'StateDefinition').slice(0, 3)
  const views = []
  for (const definition of definitions) {
    const properties = definition.properties ?? {}
    const states = Array.isArray(properties.states) ? properties.states.map(String) : []
    if (states.length === 0) continue
    const transitions = Array.isArray(properties.transitions) ? properties.transitions : []
    const columns = states.length <= 3 ? states.length : Math.min(4, Math.ceil(Math.sqrt(states.length * 1.6)))
    const rows = Math.ceil(states.length / columns)
    const stateWidth = 158
    const stateHeight = 68
    const colGap = 52
    const rowGap = 84
    const nodes = []
    const nodeByState = new Map()
    const indexOf = new Map(states.map((state, index) => [state, index]))
    states.forEach((state, index) => {
      const column = index % columns
      const row = Math.floor(index / columns)
      const node = makeNode({
        id: `state:${state}`,
        elementId: definition.id,
        kind: 'state',
        lines: [
          { c: 'st', t: indexOf.get(state) === 0 ? '«state»' : '«state»' },
          TTL(state),
        ],
        x: 76 + column * (stateWidth + colGap),
        y: 96 + row * (stateHeight + rowGap),
        w: stateWidth,
        h: stateHeight,
      })
      nodes.push(node)
      nodeByState.set(state, node)
      if (properties.initial === state) {
        nodes.push({
          id: 'init',
          elementId: definition.id,
          kind: 'init',
          x: node.x - 34,
          y: node.y + stateHeight / 2 - 8,
          w: 16,
          h: 16,
          lines: [],
          label: 'initial',
        })
      }
    })
    const edges = []
    for (const transition of transitions) {
      const fromState = String(transition?.from ?? '')
      const toState = String(transition?.to ?? '')
      const fromNode = nodeByState.get(fromState)
      const toNode = nodeByState.get(toState)
      if (!fromNode || !toNode) continue
      const trigger = transition?.trigger ? String(transition.trigger) : ''
      const guard = transition?.guard ? String(transition.guard) : ''
      if (fromState === toState) {
        edges.push({
          id: `trans:${fromState}>${toState}`,
          from: fromNode.id,
          to: fromNode.id,
          self: true,
          kind: 'trans',
          label: trigger,
          sub: guard || null,
          fromSide: 't',
          toSide: 't',
          via: null,
          labelAt: [fromNode.x + fromNode.w / 2, fromNode.y - 44],
        })
        continue
      }
      const sides = sidesFor(fromNode, toNode)
      edges.push({
        id: `trans:${fromState}>${toState}`,
        from: fromNode.id,
        to: toNode.id,
        kind: 'trans',
        label: trigger,
        sub: guard || null,
        fromSide: sides.fromSide,
        toSide: sides.toSide,
        fromOff: 0.5,
        toOff: 0.5,
        via: null,
        labelAt: null,
      })
    }
    if (properties.initial && nodeByState.has(properties.initial)) {
      const initialNode = nodeByState.get(properties.initial)
      edges.push({
        id: 'trans:init',
        from: 'init',
        to: initialNode.id,
        kind: 'trans',
        label: '',
        sub: null,
        fromSide: 'r',
        toSide: 'l',
        via: null,
        labelAt: null,
      })
    }
    const width = 76 + columns * stateWidth + (columns - 1) * colGap + 76
    const height = 96 + rows * stateHeight + (rows - 1) * rowGap + 70
    const groups = [{
      id: 'g-state',
      x: 18,
      y: 18,
      w: width - 36,
      h: height - 36,
      label: `«state def» ${definition.name ?? definition.id}（initial: ${properties.initial ?? '?'} · ${states.length} 状态 / ${transitions.length} 迁移）`,
    }]
    views.push({
      viewId: `state:${definition.id}`,
      kind: 'state',
      title: '状态机',
      scope: { element: definition.id },
      width: Math.round(width),
      height: Math.round(height),
      nodes,
      edges,
      groups,
    })
  }
  return views
}

/**
 * 参数视图：Attribute 卡片 + Constraint 卡片 + parameters 连线。
 * @param {Array<object>} elements - IR 元素。
 * @returns {object|null} 视图。
 */
function buildParamView(elements) {
  const attributes = elements.filter((element) => element.kind === 'Attribute')
  const constraints = elements.filter((element) => element.kind === 'Constraint')
  if (attributes.length === 0 && constraints.length === 0) return null
  const sorted = [...attributes].sort((a, b) => {
    const ownerA = String(a.owner ?? '')
    const ownerB = String(b.owner ?? '')
    if (ownerA !== ownerB) return ownerA.localeCompare(ownerB)
    return String(a.name ?? a.id).localeCompare(String(b.name ?? b.id))
  })
  const columns = sorted.length <= 4 ? 1 : 2
  const attrWidth = 232
  const attrGapY = 16
  const columnGap = 34
  const nodes = []
  const attrNodes = new Map()
  const startX = 40
  const startY = 56
  let columnHeights = []
  let row = 0
  let column = 0
  let y = startY
  for (const attribute of sorted) {
    const lines = attributeLines(attribute)
    const height = measureLines(lines)
    const node = makeNode({
      id: `attr:${attribute.id}`,
      elementId: attribute.id,
      kind: 'attr',
      lines,
      x: startX + column * (attrWidth + columnGap),
      y,
      w: attrWidth,
      h: height,
    })
    nodes.push(node)
    attrNodes.set(attribute.id, node)
    y += height + attrGapY
    row += 1
    if (row >= 6) {
      columnHeights.push(y)
      row = 0
      column += 1
      y = startY
    }
  }
  if (row > 0) columnHeights.push(y)
  const leftWidth = Math.max(attrWidth, columns * attrWidth + (columns - 1) * columnGap)
  const constraintX = startX + leftWidth + 60
  let constraintY = 56
  const edges = []
  for (const constraint of constraints) {
    const lines = constraintLines(constraint)
    const node = makeNode({
      id: `constraint:${constraint.id}`,
      elementId: constraint.id,
      kind: 'constraint',
      lines,
      x: constraintX,
      y: constraintY,
      w: 300,
    })
    nodes.push(node)
    for (const parameter of constraint.properties?.parameters ?? []) {
      const target = attrNodes.get(parameter)
      if (!target) continue
      edges.push({
        id: `param:${constraint.id}>${parameter}`,
        from: node.id,
        to: target.id,
        kind: 'link',
        label: 'parameter',
        sub: null,
        fromSide: 'l',
        toSide: 'r',
        via: null,
        labelAt: null,
      })
    }
    constraintY += node.h + 28
  }
  const bounds = boundsOf(nodes, [])
  const width = Math.max(bounds.maxX + 50, 660)
  const height = Math.max(bounds.maxY + 60, 520)
  const groups = [{
    id: 'g-param',
    x: 16,
    y: 16,
    w: width - 32,
    h: height - 32,
    label: `«package» ${attributes[0]?.owner || 'parameters'} · ${attributes.length} 个属性 · ${constraints.length} 个约束`,
  }]
  return {
    viewId: 'param',
    kind: 'param',
    title: '参数视图',
    scope: { element: null },
    width: Math.round(width),
    height: Math.round(height),
    nodes,
    edges,
    groups,
  }
}

/* ------------------------------------------------------------------ *
 * 模型树
 * ------------------------------------------------------------------ */

function viewLeaf(view) {
  return {
    id: `view:${view.viewId}`,
    label: view.title,
    icon: '◇',
    view: view.viewId,
    count: `${view.nodes.length} 节点`,
  }
}

function elementLeaf(element) {
  return {
    id: `el:${element.id}`,
    label: element.name ?? element.id,
    icon: elementIcon(element.kind),
    elementId: element.id,
  }
}

function elementIcon(kind) {
  const map = {
    Requirement: '≡',
    PartDefinition: '▣',
    PartUsage: '▪',
    Connection: '⌁',
    Attribute: 'ƒ',
    Constraint: '∑',
    StateDefinition: '◉',
    ActionDefinition: '▶',
  }
  return map[kind] ?? '·'
}

/**
 * 构建模型树（层级 + 类别两种分组）。
 * @param {string} packageName - IR package 名。
 * @param {Array<object>} elements - IR 元素。
 * @param {Array<object>} views - 视图列表。
 * @returns {{hierarchy:object, category:object}} 两种树。
 */
function buildTree(packageName, elements, views) {
  const viewsOf = (kinds) => views.filter((view) => kinds.includes(view.kind)).map(viewLeaf)
  const withViews = (groupViews, elementLeaves) => [...groupViews, ...elementLeaves]

  const structureViews = viewsOf(['structure', 'ibd'])
  const behaviorViews = viewsOf(['state', 'action'])
  const requirementViews = viewsOf(['requirement'])
  const paramViews = viewsOf(['param'])

  const composition = compositionOf(elements)
  const { definitions, definitionIds, usages } = composition
  const usagesByOwner = new Map()
  for (const usage of usages) {
    const owner = definitionIds.has(usage.owner)
      ? usage.owner
      : (definitionIds.has(usage.properties?.typeRef) ? usage.properties.typeRef : null)
    if (!owner) continue
    if (!usagesByOwner.has(owner)) usagesByOwner.set(owner, [])
    usagesByOwner.get(owner).push(usage)
  }
  const parentOf = composition.parentOf
  const childrenOf = new Map()
  for (const definition of definitions) {
    const parent = parentOf.get(definition.id)
    if (!parent) continue
    if (!childrenOf.has(parent)) childrenOf.set(parent, [])
    childrenOf.get(parent).push(definition)
  }
  const buildDefinitionNode = (definition, depth) => {
    const children = depth >= 5
      ? []
      : (childrenOf.get(definition.id) ?? [])
        .sort((a, b) => String(a.name ?? a.id).localeCompare(String(b.name ?? b.id)))
        .map((child) => buildDefinitionNode(child, depth + 1))
    const usageLeaves = (usagesByOwner.get(definition.id) ?? [])
      .sort((a, b) => String(a.name ?? a.id).localeCompare(String(b.name ?? b.id)))
      .slice(0, 12)
      .map(elementLeaf)
    return {
      id: `def:${definition.id}`,
      label: definition.name ?? definition.id,
      icon: '▣',
      elementId: definition.id,
      count: `${usageLeaves.length} usage`,
      children: [...usageLeaves, ...children],
    }
  }
  const roots = definitions.filter((definition) => !parentOf.has(definition.id))
  const structureChildren = roots.length > 0
    ? roots.map((definition) => buildDefinitionNode(definition, 0))
    : definitions.slice(0, 8).map((definition) => buildDefinitionNode(definition, 0))

  const requirementElements = elements.filter((element) => element.kind === 'Requirement').map(elementLeaf).slice(0, 24)
  const stateElements = elements.filter((element) => element.kind === 'StateDefinition').map(elementLeaf)
  const actionElements = elements.filter((element) => element.kind === 'ActionDefinition').map(elementLeaf).slice(0, 12)
  const attributeElements = elements.filter((element) => element.kind === 'Attribute').map(elementLeaf).slice(0, 24)
  const constraintElements = elements.filter((element) => element.kind === 'Constraint').map(elementLeaf)
  const connectionElements = elements.filter((element) => element.kind === 'Connection').map(elementLeaf).slice(0, 12)

  const hierarchy = {
    id: 'pkg',
    label: packageName,
    icon: '▦',
    count: `${elements.length} 元素`,
    children: [
      {
        id: 'group:structure',
        label: '结构',
        icon: '▣',
        children: withViews(structureViews, [...structureChildren, ...connectionElements]),
      },
      {
        id: 'group:behavior',
        label: '行为',
        icon: '◉',
        children: withViews(behaviorViews, [...stateElements, ...actionElements]),
      },
      {
        id: 'group:requirement',
        label: '需求',
        icon: '≡',
        children: withViews(requirementViews, requirementElements),
      },
      {
        id: 'group:param',
        label: '参数',
        icon: 'ƒ',
        children: withViews(paramViews, [...attributeElements, ...constraintElements]),
      },
    ],
  }
  const category = {
    id: 'cat',
    label: packageName,
    icon: '▦',
    count: `${views.length} 张图`,
    children: [
      { id: 'cat:structure', label: '结构', icon: '▣', children: structureViews },
      { id: 'cat:behavior', label: '行为', icon: '◉', children: behaviorViews },
      { id: 'cat:requirement', label: '需求', icon: '≡', children: requirementViews },
      { id: 'cat:param', label: '参数', icon: 'ƒ', children: paramViews },
    ],
  }
  return { hierarchy, category }
}

/**
 * 内置 JS 投影入口。
 * @param {object} ir - sysml-ir/v1 文档。
 * @returns {{views:object[], tree:object, stats:object}} 图投影。
 */
export function buildFallbackGraph(ir) {
  const elements = (Array.isArray(ir?.elements) ? ir.elements : []).filter(
    (element) => element && typeof element.id === 'string',
  )
  const byId = new Map(elements.map((element) => [element.id, element]))
  const views = []
  const structure = buildStructureView(elements, byId)
  if (structure) views.push(structure)
  const ibd = buildIbdView(elements, byId)
  if (ibd) views.push(ibd)
  const requirement = buildRequirementView(elements, byId)
  if (requirement) views.push(requirement)
  for (const state of buildStateViews(elements)) views.push(state)
  const param = buildParamView(elements)
  if (param) views.push(param)
  const packageName = typeof ir.package === 'string' && ir.package ? ir.package : 'Model'
  const tree = buildTree(packageName, elements, views)
  const stats = {
    elements: elements.length,
    relations: relCount(elements),
    kinds: kindCounts(elements),
    views: views.length,
  }
  return { views, tree, stats }
}

/* ------------------------------------------------------------------ *
 * graph.py 桥接 + 外部图规范化
 * ------------------------------------------------------------------ */

async function findGraphScript(cfg, state, extraRoots = []) {
  const now = Date.now()
  const rootsKey = Array.isArray(extraRoots) ? extraRoots.join('|') : ''
  if (state.scriptCheckedAt && now - state.scriptCheckedAt < 5000 && state.scriptRootsKey === rootsKey) {
    return state.scriptPath
  }
  state.scriptCheckedAt = now
  state.scriptRootsKey = rootsKey
  state.scriptPath = null
  if (cfg.graphScript) {
    const absolute = isAbsolute(cfg.graphScript) ? cfg.graphScript : resolve(process.cwd(), cfg.graphScript)
    if (existsSync(absolute)) {
      state.scriptPath = absolute
      return absolute
    }
  }
  const agentDir = pickString(process.env.SYSML_AGENT_DIR)
  const relatives = [
    join('sysml-modeling-agent', 'mcp-server', 'tools', 'graph.py'),
    join('mcp-server', 'tools', 'graph.py'),
    join('tools', 'graph.py'),
    join('.sysml-agent', 'tools', 'graph.py'),
  ]
  if (agentDir) {
    const agentRoot = resolve(agentDir)
    for (const relative of relatives) {
      if (!relative.includes('sysml-modeling-agent')) {
        const candidate = join(agentRoot, relative)
        if (existsSync(candidate)) {
          state.scriptPath = candidate
          return candidate
        }
      }
    }
  }
  const roots = await workspaceRoots(cfg, extraRoots)
  // 插件自带位置推出的仓库根优先于工作区扫描：现场安装与仓库内副本两种布局都覆盖。
  for (const pluginRoot of agentRootCandidates()) {
    for (const relative of relatives) {
      const candidate = join(pluginRoot, relative)
      if (existsSync(candidate)) {
        state.scriptPath = candidate
        return candidate
      }
    }
  }
  for (const root of roots) {
    for (const relative of relatives) {
      const candidate = join(root, relative)
      if (existsSync(candidate)) {
        state.scriptPath = candidate
        return candidate
      }
    }
  }
  return null
}

/**
 * 优先用工作区自带 venv 的解释器（sysml-modeling-agent/.venv），
 * 否则用配置的 python（默认 python3）。
 * @param {ReturnType<typeof readConfig>} cfg - 插件配置。
 * @param {string[]} roots - 已解析的工作区根。
 * @returns {string} 可执行的 python 路径/命令。
 */
export function resolvePython(cfg, roots = []) {
  if (cfg.python && cfg.python !== 'python3') return cfg.python
  for (const root of roots) {
    const candidate = join(root, 'sysml-modeling-agent', '.venv', 'bin', 'python')
    if (existsSync(candidate)) return candidate
  }
  return cfg.python || 'python3'
}

function parseLooseJson(text) {
  try {
    return JSON.parse(text)
  } catch {
    const start = text.indexOf('{')
    const end = text.lastIndexOf('}')
    if (start >= 0 && end > start) {
      try {
        return JSON.parse(text.slice(start, end + 1))
      } catch {
        return null
      }
    }
    return null
  }
}

function runPythonGraph(cfg, scriptPath, modelPath) {
  return new Promise((resolvePromise) => {
    let settled = false
    const finish = (value) => {
      if (settled) return
      settled = true
      resolvePromise(value)
    }
    let child
    try {
      child = spawn(cfg.python, [scriptPath, '--input', modelPath, '--output', '-'], {
        cwd: dirname(dirname(scriptPath)),
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
        windowsHide: true,
      })
    } catch (error) {
      finish({ ok: false, error: String(error?.message ?? error) })
      return
    }
    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => {
      try {
        child.kill('SIGKILL')
      } catch {
        /* 进程可能已经退出 */
      }
      finish({ ok: false, error: 'graph.py 调用超时' })
    }, cfg.pythonTimeoutMs)
    child.stdout?.on('data', (chunk) => {
      stdout += String(chunk)
    })
    child.stderr?.on('data', (chunk) => {
      stderr += String(chunk)
    })
    child.on('error', (error) => {
      clearTimeout(timer)
      finish({ ok: false, error: String(error?.message ?? error) })
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      if (code !== 0) {
        finish({ ok: false, error: `graph.py 退出码 ${code}: ${stderr.trim().slice(0, 300)}` })
        return
      }
      const parsed = parseLooseJson(stdout)
      if (!parsed || typeof parsed !== 'object') {
        finish({ ok: false, error: 'graph.py 输出不是 JSON' })
        return
      }
      finish({ ok: true, raw: parsed })
    })
  })
}

function mapNodeKind(rawKind, element) {
  const text = String(rawKind ?? element?.kind ?? '').toLowerCase()
  if (/require|req\b|«requirement/.test(text)) return 'requirement'
  if (/state/.test(text)) return 'state'
  if (/action/.test(text)) return 'action'
  if (/constraint/.test(text)) return 'constraint'
  if (/attribute|param value|value/.test(text) && !/parametric/.test(text)) return 'attr'
  if (/part usage|part\b|«part»|instance/.test(text)) return 'usage'
  if (/part def|block|«block»|bdd|definition/.test(text)) return 'block'
  if (/connect|edge|flow/.test(text)) return 'trace'
  return element ? elementKindToNodeKind(element.kind) : 'block'
}

function elementKindToNodeKind(kind) {
  const map = {
    Requirement: 'requirement',
    PartDefinition: 'block',
    PartUsage: 'usage',
    StateDefinition: 'state',
    ActionDefinition: 'action',
    Constraint: 'constraint',
    Attribute: 'attr',
  }
  return map[kind] ?? 'block'
}

function mapViewKind(rawKind) {
  const text = String(rawKind ?? '').toLowerCase()
  if (/ibd|interconnect|internal/.test(text)) return 'ibd'
  if (/require|req\b/.test(text)) return 'requirement'
  if (/state|statemachine|state machine/.test(text)) return 'state'
  if (/param/.test(text)) return 'param'
  if (/action/.test(text)) return 'action'
  return 'structure'
}

function titleForKind(kind) {
  const map = {
    structure: '结构（BDD）',
    ibd: '互联（IBD）',
    requirement: '需求视图',
    state: '状态机',
    param: '参数视图',
    action: '动作流',
  }
  return map[kind] ?? kind
}

function numeric(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function normalizeExternalNode(rawNode, index, byId) {
  if (!rawNode || typeof rawNode !== 'object') return null
  const elementId = rawNode.elementId ?? rawNode.element ?? rawNode.id ?? null
  const element = elementId ? byId.get(String(elementId)) : undefined
  const rawLines = Array.isArray(rawNode.lines) ? rawNode.lines : null
  const lines = rawLines
    ? rawLines
      .map((line) => {
        if (typeof line === 'string') return { c: 'bd', t: line }
        if (!line || typeof line !== 'object') return null
        const text = line.t ?? line.text ?? ''
        if (text === '') return null
        return { c: line.c ?? 'bd', t: String(text) }
      })
      .filter(Boolean)
    : [
      ST(`«${shortKind(element?.kind ?? rawNode.kind ?? 'element')}»`),
      TTL(String(rawNode.label ?? rawNode.name ?? element?.name ?? elementId ?? `node-${index}`)),
      SUB(String(elementId ?? '')),
    ]
  const width = numeric(rawNode.w) ?? numeric(rawNode.width)
  const height = numeric(rawNode.h) ?? numeric(rawNode.height)
  const id = String(rawNode.id ?? elementId ?? `n-${index + 1}`)
  return {
    id,
    elementId: elementId === null ? null : String(elementId),
    kind: mapNodeKind(rawNode.kind ?? rawNode.type, element),
    x: numeric(rawNode.x) ?? numeric(rawNode.left),
    y: numeric(rawNode.y) ?? numeric(rawNode.top),
    w: width,
    h: height,
    lines,
    label: String(rawNode.label ?? rawNode.name ?? element?.name ?? id),
  }
}

function normalizeExternalEdge(rawEdge, index, nodeIds) {
  if (!rawEdge || typeof rawEdge !== 'object') return null
  const from = rawEdge.from ?? rawEdge.source ?? rawEdge.fromId ?? rawEdge.sourceId ?? rawEdge.start
  const to = rawEdge.to ?? rawEdge.target ?? rawEdge.toId ?? rawEdge.targetId ?? rawEdge.end
  if (!from || !to || !nodeIds.has(String(from)) || !nodeIds.has(String(to))) return null
  const rawKind = String(rawEdge.kind ?? rawEdge.type ?? 'dep').toLowerCase()
  let kind = 'dep'
  if (/flow.*(el|elec)|electrical/.test(rawKind)) kind = 'flow-el'
  else if (/flow.*(mech)|mechanical/.test(rawKind)) kind = 'flow-mech'
  else if (/trace|satisf/.test(rawKind)) kind = 'trace'
  else if (/verify/.test(rawKind)) kind = 'verify'
  else if (/trans/.test(rawKind)) kind = 'trans'
  else if (/comp|contain|decomp/.test(rawKind)) kind = 'comp'
  else if (/link|param/.test(rawKind)) kind = 'link'
  const via = Array.isArray(rawEdge.via)
    ? rawEdge.via
    : (Array.isArray(rawEdge.points) ? rawEdge.points : null)
  return {
    id: String(rawEdge.id ?? `e-${index + 1}`),
    from: String(from),
    to: String(to),
    self: String(from) === String(to),
    kind,
    label: String(rawEdge.label ?? rawEdge.name ?? rawEdge.type ?? ''),
    sub: rawEdge.sub != null ? String(rawEdge.sub) : (rawEdge.detail != null ? String(rawEdge.detail) : null),
    fromSide: rawEdge.fromSide ?? null,
    toSide: rawEdge.toSide ?? null,
    fromOff: numeric(rawEdge.fromOff) ?? 0.5,
    toOff: numeric(rawEdge.toOff) ?? 0.5,
    via: via && via.every((point) => Array.isArray(point) && point.length >= 2 && numeric(Number(point[0])) !== undefined && numeric(Number(point[1])) !== undefined)
      ? via.map((point) => [Number(point[0]), Number(point[1])])
      : null,
    labelAt: Array.isArray(rawEdge.labelAt) && rawEdge.labelAt.length >= 2
      ? [Number(rawEdge.labelAt[0]), Number(rawEdge.labelAt[1])]
      : null,
  }
}

function autoLayout(kind, nodes, edges) {
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  for (const node of nodes) {
    if (node.w === undefined || node.w <= 0) node.w = kind === 'state' ? 158 : 200
    if (node.h === undefined || node.h <= 0) node.h = measureLines(node.lines)
  }
  if (nodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y))) {
    return
  }
  if (kind === 'state') {
    const columns = Math.min(4, Math.ceil(Math.sqrt(nodes.length)))
    nodes.forEach((node, index) => {
      node.x = 60 + (index % columns) * 220
      node.y = 70 + Math.floor(index / columns) * 150
    })
    return
  }
  const layer = new Map(nodes.map((node) => [node.id, 0]))
  for (let pass = 0; pass < nodes.length + 2; pass += 1) {
    let changed = false
    for (const edge of edges) {
      if (edge.self) continue
      const next = (layer.get(edge.from) ?? 0) + 1
      if ((layer.get(edge.to) ?? 0) < next && next < nodes.length + 2) {
        layer.set(edge.to, next)
        changed = true
      }
    }
    if (!changed) break
  }
  const byLayer = new Map()
  for (const node of nodes) {
    const value = layer.get(node.id) ?? 0
    if (!byLayer.has(value)) byLayer.set(value, [])
    byLayer.get(value).push(node)
  }
  for (const [layerIndex, list] of [...byLayer.entries()].sort((a, b) => a[0] - b[0])) {
    list.forEach((node, index) => {
      node.x = 50 + layerIndex * 280
      node.y = 60 + index * 130
    })
  }
  // 回填 sides（按相对位置）
  for (const edge of edges) {
    if (edge.self) continue
    const fromNode = nodeById.get(edge.from)
    const toNode = nodeById.get(edge.to)
    if (!fromNode || !toNode) continue
    if (!edge.fromSide || !edge.toSide) {
      const sides = sidesFor(fromNode, toNode)
      edge.fromSide = edge.fromSide ?? sides.fromSide
      edge.toSide = edge.toSide ?? sides.toSide
    }
  }
}

/**
 * 把 graph.py 的输出规范化为本项目客户端可渲染的视图。
 * @param {object} raw - graph.py 的 JSON 输出。
 * @param {object} ir - 原始 IR。
 * @returns {{views:object[], tree:object, stats:object}|null} 规范化结果。
 */
/* ---- graph.py 投影（sysml-graph/v1，只做投影不做布局）→ 可渲染视图 ---- */

const PROJECTED_WIDTH = {
  block: DEF_WIDTH, usage: 170, requirement: REQUIREMENT_WIDTH, action: 230, state: 142,
  note: 280, trace: 210, attr: 210, constraint: CONSTRAINT_WIDTH,
}

function projectedNodeKind(rawKind, element) {
  if (element) {
    if (element.kind === 'StateDefinition') return 'note'
    if (element.kind === 'Connection') return 'trace'
    return elementKindToNodeKind(element.kind)
  }
  const text = String(rawKind ?? '')
  if (text === 'State') return 'state'
  return mapNodeKind(text, undefined)
}

function projectedLines(rawNode, element) {
  if (element) return elementBoxLines(element)
  if (String(rawNode.kind) === 'State') {
    const lines = [ST('«state»'), TTL(String(rawNode.label ?? rawNode.id))]
    if (rawNode.attrs?.initial) lines.push(KV('initial', 'true'))
    return lines
  }
  return [ST(`«${shortKind(rawNode.kind)}»`), TTL(String(rawNode.label ?? rawNode.id)), SUB(String(rawNode.id))]
}

function makeProjectedNode(rawNode, byId) {
  const element = byId.get(String(rawNode.id))
  const kind = projectedNodeKind(rawNode.kind, element)
  const lines = projectedLines(rawNode, element)
  return {
    id: String(rawNode.id),
    elementId: String(rawNode.id),
    kind,
    lines,
    x: 0,
    y: 0,
    w: PROJECTED_WIDTH[kind] ?? 200,
    h: measureLines(lines),
    label: String(rawNode.label ?? element?.name ?? rawNode.id),
    pyKind: String(rawNode.kind ?? ''),
    parent: rawNode.parent ?? null,
    owner: rawNode.owner ?? null,
    attrs: rawNode.attrs && typeof rawNode.attrs === 'object' ? rawNode.attrs : {},
  }
}

function flowKindForEdge(rawEdge, fromNode, toNode) {
  const text = `${rawEdge.label ?? ''} ${rawEdge.rationale ?? ''}`.toLowerCase()
  if (/mechanical|机械|轴功率/.test(text)) return 'flow-mech'
  if (/electrical|电气|直流/.test(text)) return 'flow-el'
  const fromType = String(fromNode?.attrs?.typeRef ?? fromNode?.attrs?.typeName ?? '')
  const toType = String(toNode?.attrs?.typeRef ?? toNode?.attrs?.typeName ?? '')
  if (/motor/i.test(fromType) && /rotor|prop/i.test(toType)) return 'flow-mech'
  if (/battery|esc/i.test(fromType) || /motor/i.test(toType)) return 'flow-el'
  return 'flow-el'
}

function mapProjectedEdge(rawEdge, viewKind, nodeMap) {
  if (!rawEdge || typeof rawEdge !== 'object') return null
  const from = String(rawEdge.source ?? rawEdge.from ?? '')
  const to = String(rawEdge.target ?? rawEdge.to ?? '')
  if (!nodeMap.has(from) || !nodeMap.has(to)) return null
  const rawKind = String(rawEdge.kind ?? rawEdge.type ?? 'dep')
  const fromNode = nodeMap.get(from)
  const toNode = nodeMap.get(to)
  let kind = 'dep'
  if (viewKind === 'ibd') {
    kind = (rawKind === 'connection' || rawKind === 'connects')
      ? flowKindForEdge(rawEdge, fromNode, toNode)
      : (rawKind === 'typeRef' ? 'dep' : 'flow-el')
  } else if (viewKind === 'structure') {
    kind = rawKind === 'decomposes' ? 'comp' : 'dep'
  } else if (viewKind === 'requirement') {
    if (rawKind === 'verifies') kind = 'verify'
    else if (rawKind === 'satisfiedBy' || rawKind === 'refines' || rawKind === 'decomposes') kind = 'trace'
    else kind = 'dep'
  } else if (viewKind === 'state') {
    kind = 'trans'
  } else if (rawKind === 'decomposes') {
    kind = 'comp'
  }
  let label = String(rawEdge.label ?? rawKind)
  let sub = rawEdge.rationale != null ? String(rawEdge.rationale) : null
  if (viewKind === 'state') {
    const match = /^(.*?)\s*\[(.*)\]$/.exec(label)
    if (match) {
      label = match[1]
      sub = match[2]
    }
  } else if (viewKind === 'structure' && rawKind === 'typeRef') {
    label = '«type»'
  }
  return {
    id: String(rawEdge.id ?? `e-${from}->${to}`),
    from,
    to,
    self: from === to,
    kind,
    label,
    sub,
    fromSide: null,
    toSide: null,
    fromOff: 0.5,
    toOff: 0.5,
    via: null,
    labelAt: null,
  }
}

function layoutStructureProjection(nodes, mappedEdges) {
  const definitions = nodes.filter((node) => node.kind === 'block')
  const usages = nodes.filter((node) => node.kind === 'usage')
  if (definitions.length === 0) {
    autoLayout('structure', nodes, mappedEdges)
    return { nodes, edges: mappedEdges, groups: [], width: undefined, height: undefined }
  }
  const definitionIds = new Set(definitions.map((node) => node.id))
  const parentOf = new Map()
  const composition = []
  const addParent = (parent, child, label) => {
    if (!definitionIds.has(parent) || !definitionIds.has(child) || parent === child) return
    if (parentOf.has(child)) return
    parentOf.set(child, parent)
    composition.push({ parent, child, label })
  }
  for (const edge of mappedEdges) {
    if (edge.kind === 'comp') addParent(edge.from, edge.to, edge.label)
  }
  const usagesByDefinition = new Map()
  for (const usage of usages) {
    const parent = usage.parent && definitionIds.has(usage.parent) ? usage.parent : null
    const typeRef = usage.attrs?.typeRef && definitionIds.has(usage.attrs.typeRef) ? usage.attrs.typeRef : null
    if (parent && typeRef) addParent(parent, typeRef, `«part» ${usage.label}`)
    const attach = typeRef ?? parent
    if (!attach) continue
    if (!usagesByDefinition.has(attach)) usagesByDefinition.set(attach, [])
    usagesByDefinition.get(attach).push(usage)
  }
  for (const list of usagesByDefinition.values()) {
    list.sort((a, b) => a.label.localeCompare(b.label))
  }
  const roots = definitions.filter((node) => !parentOf.has(node.id))
  const root = roots[0] ?? definitions[0]
  for (const other of roots) {
    if (other === root || parentOf.has(other.id)) continue
    parentOf.set(other.id, root.id)
    composition.push({ parent: root.id, child: other.id, label: '«package»' })
  }
  const childrenOf = new Map()
  for (const definition of definitions) {
    const parent = parentOf.get(definition.id)
    if (!parent) continue
    if (!childrenOf.has(parent)) childrenOf.set(parent, [])
    childrenOf.get(parent).push(definition.id)
  }
  const depth = new Map([[root.id, 0]])
  const queue = [root.id]
  while (queue.length > 0) {
    const id = queue.shift()
    for (const child of childrenOf.get(id) ?? []) {
      if (depth.has(child)) continue
      depth.set(child, (depth.get(id) ?? 0) + 1)
      queue.push(child)
    }
  }
  for (const definition of definitions) if (!depth.has(definition.id)) depth.set(definition.id, 1)
  const levels = new Map()
  for (const definition of definitions) {
    const level = depth.get(definition.id) ?? 0
    if (!levels.has(level)) levels.set(level, [])
    levels.get(level).push(definition)
  }
  for (const list of levels.values()) list.sort((a, b) => a.label.localeCompare(b.label))

  const definitionWidth = DEF_WIDTH
  const usageWidth = 160
  const usageHeight = 54
  const gapX = 36
  const levelGap = 52
  let levelWidth = 640
  for (const list of levels.values()) {
    levelWidth = Math.max(levelWidth, list.length * definitionWidth + (list.length - 1) * gapX + 120)
  }
  const maxLevel = Math.max(...levels.keys(), 0)
  const outNodes = []
  const outEdges = []
  let y = 62
  for (let level = 0; level <= maxLevel; level += 1) {
    const list = levels.get(level) ?? []
    const x0 = (levelWidth - (list.length * definitionWidth + (list.length - 1) * gapX)) / 2
    let rowHeight = 0
    list.forEach((definition, index) => {
      definition.w = definitionWidth
      definition.x = x0 + index * (definitionWidth + gapX)
      definition.y = y
      outNodes.push(definition)
      rowHeight = Math.max(rowHeight, definition.h)
      const attached = usagesByDefinition.get(definition.id) ?? []
      const columns = attached.length <= 2 ? 1 : 2
      attached.forEach((usage, usageIndex) => {
        usage.w = usageWidth
        usage.h = Math.max(usageHeight, measureLines(usage.lines))
        const column = usageIndex % columns
        const row = Math.floor(usageIndex / columns)
        usage.x = definition.x + (definitionWidth - (columns * usageWidth + (columns - 1) * 10)) / 2
          + column * (usageWidth + 10)
        usage.y = definition.y + definition.h + 26 + row * (usageHeight + 12)
        outNodes.push(usage)
        outEdges.push({
          id: `type-${usage.id}`,
          from: definition.id,
          to: usage.id,
          kind: 'dep',
          label: '«type»',
          sub: null,
          fromSide: 'b',
          toSide: 't',
          fromOff: 0.5,
          toOff: 0.5,
          via: null,
          labelAt: null,
        })
        rowHeight = Math.max(rowHeight, usage.y + usage.h - y)
      })
    })
    y += rowHeight + levelGap
  }
  for (const item of composition) {
    outEdges.push({
      id: `comp-${item.parent}-${item.child}`,
      from: item.parent,
      to: item.child,
      kind: 'comp',
      label: item.label,
      sub: null,
      fromSide: 'b',
      toSide: 't',
      fromOff: 0.5,
      toOff: 0.5,
      via: null,
      labelAt: null,
    })
  }
  const bounds = boundsOf(outNodes, [])
  const width = Math.max(levelWidth, bounds.maxX + 60)
  const height = Math.max(bounds.maxY + 52, 420)
  const groups = [{
    id: 'g-projection-structure',
    x: 16,
    y: 16,
    w: width - 32,
    h: height - 32,
    label: `«package» ${root.owner && root.owner !== root.id ? root.owner : ''} · PartDefinition ${definitions.length} / PartUsage ${usages.length}`,
  }]
  return { nodes: outNodes, edges: outEdges, groups, width, height }
}

function layoutLayered(nodes, edges, options = {}) {
  const nodeWidth = options.nodeWidth ?? 180
  const nodeHeight = options.nodeHeight ?? 78
  const columnGap = options.columnGap ?? 66
  const rowGap = options.rowGap ?? 38
  const layer = new Map(nodes.map((node) => [node.id, 0]))
  for (let pass = 0; pass < nodes.length + 2; pass += 1) {
    let changed = false
    for (const edge of edges) {
      if (edge.self) continue
      const next = (layer.get(edge.from) ?? 0) + 1
      if ((layer.get(edge.to) ?? 0) < next && next < nodes.length + 2) {
        layer.set(edge.to, next)
        changed = true
      }
    }
    if (!changed) break
  }
  const byLayer = new Map()
  for (const node of nodes) {
    const value = layer.get(node.id) ?? 0
    if (!byLayer.has(value)) byLayer.set(value, [])
    byLayer.get(value).push(node)
  }
  for (const list of byLayer.values()) list.sort((a, b) => a.label.localeCompare(b.label))
  const maxRows = Math.max(...[...byLayer.values()].map((list) => list.length), 1)
  const contentHeight = maxRows * nodeHeight + (maxRows - 1) * rowGap
  const maxLayer = Math.max(...byLayer.keys(), 0)
  for (const [layerIndex, list] of [...byLayer.entries()].sort((a, b) => a[0] - b[0])) {
    const columnHeight = list.length * nodeHeight + (list.length - 1) * rowGap
    const startY = 96 + (contentHeight - columnHeight) / 2
    list.forEach((node, index) => {
      node.w = nodeWidth
      node.h = Math.max(nodeHeight, node.h)
      node.x = 52 + layerIndex * (nodeWidth + columnGap)
      node.y = startY + index * (nodeHeight + rowGap)
    })
  }
  const nodeMap = new Map(nodes.map((node) => [node.id, node]))
  for (const edge of edges) {
    const fromNode = nodeMap.get(edge.from)
    const toNode = nodeMap.get(edge.to)
    if (!fromNode || !toNode) continue
    const sides = sidesFor(fromNode, toNode)
    edge.fromSide = edge.fromSide ?? sides.fromSide
    edge.toSide = edge.toSide ?? sides.toSide
  }
  return {
    width: 52 * 2 + (maxLayer + 1) * nodeWidth + maxLayer * columnGap,
    height: 96 + contentHeight + 76,
  }
}

function layoutIbdProjection(nodes, mappedEdges, rawView) {
  const usages = nodes.filter((node) => node.kind === 'usage')
  const definitions = nodes.filter((node) => node.kind === 'block')
  const display = usages.length > 0 ? usages : nodes
  if (display.length === 0) return null
  const ids = new Set(display.map((node) => node.id))
  const edges = mappedEdges.filter((edge) => ids.has(edge.from) && ids.has(edge.to))
  const size = layoutLayered(display, edges, { nodeWidth: 184, nodeHeight: 78, columnGap: 62, rowGap: 42 })
  const frameLabel = definitions.length > 0
    ? `«part» ${definitions[0].label}`
    : `«package» ${rawView?.scope ?? ''}`
  const groups = [{
    id: 'g-projection-ibd',
    x: 18,
    y: 18,
    w: size.width - 36,
    h: size.height - 36,
    label: frameLabel,
  }]
  return { nodes: display, edges, groups, width: size.width, height: size.height }
}

function layoutRequirementProjection(nodes, mappedEdges) {
  const requirements = nodes.filter((node) => node.kind === 'requirement')
  if (requirements.length === 0) return null
  const requirementIds = new Set(requirements.map((node) => node.id))
  const parentOf = new Map()
  const hierarchy = new Map()
  const pairKey = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`)
  const pairs = new Map()
  for (const edge of mappedEdges) {
    if (!requirementIds.has(edge.from) || !requirementIds.has(edge.to)) continue
    if (edge.from === edge.to) continue
    const label = String(edge.label)
    if (label !== 'decomposes' && label !== 'refines') continue
    pairs.set(pairKey(edge.from, edge.to), edge)
  }
  const chosen = []
  for (const edge of mappedEdges) {
    if (!requirementIds.has(edge.from) || !requirementIds.has(edge.to)) continue
    const label = String(edge.label)
    if (label !== 'decomposes' && label !== 'refines') continue
    const reverse = pairs.get(pairKey(edge.from, edge.to))
    if (label === 'refines' && reverse && reverse !== edge && String(reverse.label) === 'decomposes') continue
    chosen.push(edge)
    if (label === 'decomposes') {
      if (!parentOf.has(edge.to)) parentOf.set(edge.to, edge.from)
    } else if (!parentOf.has(edge.from)) {
      parentOf.set(edge.from, edge.to)
    }
  }
  const depth = new Map()
  const depthOf = (id, guard = new Set()) => {
    if (depth.has(id)) return depth.get(id)
    if (guard.has(id)) return 0
    guard.add(id)
    const parent = parentOf.get(id)
    const value = parent && requirementIds.has(parent) ? depthOf(parent, guard) + 1 : 0
    depth.set(id, value)
    return value
  }
  for (const requirement of requirements) depthOf(requirement.id)
  const byDepth = new Map()
  for (const requirement of requirements) {
    const value = depth.get(requirement.id) ?? 0
    if (!byDepth.has(value)) byDepth.set(value, [])
    byDepth.get(value).push(requirement)
  }
  for (const list of byDepth.values()) list.sort((a, b) => a.label.localeCompare(b.label))
  const cardWidth = REQUIREMENT_WIDTH
  const columnGap = 54
  const rowGap = 26
  const outNodes = []
  const requirementNodes = new Map()
  const maxDepth = Math.max(...byDepth.keys(), 0)
  for (const [level, list] of [...byDepth.entries()].sort((a, b) => a[0] - b[0])) {
    let y = 58
    for (const requirement of list) {
      requirement.w = cardWidth
      requirement.x = 40 + level * (cardWidth + columnGap)
      requirement.y = y
      y += requirement.h + rowGap
      outNodes.push(requirement)
      requirementNodes.set(requirement.id, requirement)
    }
  }
  for (const edge of chosen) {
    const fromNode = requirementNodes.get(edge.from)
    const toNode = requirementNodes.get(edge.to)
    if (!fromNode || !toNode) continue
    const sides = sidesFor(fromNode, toNode)
    edge.fromSide = sides.fromSide
    edge.toSide = sides.toSide
  }
  const providerNodes = nodes.filter((node) => node.kind !== 'requirement')
  const providerX = 40 + (maxDepth + 1) * (cardWidth + columnGap)
  let providerY = 58
  const providerMap = new Map()
  for (const provider of providerNodes) {
    provider.w = provider.kind === 'note' ? STATE_DEF_WIDTH : Math.min(240, provider.w || 210)
    provider.x = providerX
    provider.y = providerY
    providerY += provider.h + 18
    providerMap.set(provider.id, provider)
    outNodes.push(provider)
  }
  const outEdges = []
  for (const edge of mappedEdges) {
    const fromNode = nodeMapEdgeLookup(edge.from, requirementNodes, providerMap)
    const toNode = nodeMapEdgeLookup(edge.to, requirementNodes, providerMap)
    if (!fromNode || !toNode) continue
    const sides = sidesFor(fromNode, toNode)
    outEdges.push({
      ...edge,
      id: `pe-${outEdges.length + 1}`,
      fromSide: edge.fromSide ?? sides.fromSide,
      toSide: edge.toSide ?? sides.toSide,
    })
  }
  const bounds = boundsOf(outNodes, [])
  const width = Math.max(bounds.maxX + 50, 660)
  const height = Math.max(bounds.maxY + 56, 460)
  const groups = [{
    id: 'g-projection-requirement',
    x: 16,
    y: 16,
    w: width - 32,
    h: height - 32,
    label: `需求追溯 · ${requirements.length} 条需求 · ${outEdges.length} 条追溯关系`,
  }]
  return { nodes: outNodes, edges: outEdges, groups, width, height }
}

function nodeMapEdgeLookup(id, requirementNodes, providerMap) {
  return requirementNodes.get(id) ?? providerMap.get(id) ?? null
}

function layoutStateProjection(nodes, mappedEdges) {
  const definitionNodes = nodes.filter((node) => node.kind === 'note')
  const states = nodes.filter((node) => node.kind === 'state')
  if (states.length === 0) return null
  const columns = states.length <= 3 ? states.length : Math.min(4, Math.ceil(Math.sqrt(states.length * 1.6)))
  const rows = Math.ceil(states.length / columns)
  const stateWidth = 142
  const stateHeight = 58
  const columnGap = 56
  const rowGap = 74
  const outNodes = []
  let headerBottom = 30
  for (const definition of definitionNodes) {
    definition.w = STATE_DEF_WIDTH
    definition.x = 40
    definition.y = 30
    headerBottom = definition.y + definition.h
    outNodes.push(definition)
  }
  const startY = headerBottom + 62
  const stateById = new Map()
  states.forEach((state, index) => {
    const column = index % columns
    const row = Math.floor(index / columns)
    state.w = stateWidth
    state.h = stateHeight
    state.x = 76 + column * (stateWidth + columnGap)
    state.y = startY + row * (stateHeight + rowGap)
    outNodes.push(state)
    stateById.set(state.id, state)
  })
  const stateIds = new Set(states.map((state) => state.id))
  const outEdges = []
  for (const edge of mappedEdges) {
    if (!stateIds.has(edge.from) || !stateIds.has(edge.to)) continue
    outEdges.push({ ...edge, id: `te-${outEdges.length + 1}` })
  }
  for (const state of states) {
    if (!state.attrs?.initial) continue
    const marker = {
      id: 'projection-init',
      elementId: null,
      kind: 'init',
      lines: [],
      label: 'initial',
      x: state.x - 34,
      y: state.y + stateHeight / 2 - 8,
      w: 16,
      h: 16,
    }
    outNodes.push(marker)
    outEdges.push({
      id: 'te-init',
      from: marker.id,
      to: state.id,
      kind: 'trans',
      label: '',
      sub: null,
      self: false,
      fromSide: 'r',
      toSide: 'l',
      fromOff: 0.5,
      toOff: 0.5,
      via: null,
      labelAt: null,
    })
    break
  }
  const width = 76 + columns * stateWidth + (columns - 1) * columnGap + 76
  const height = startY + rows * stateHeight + (rows - 1) * rowGap + 70
  const groups = [{
    id: 'g-projection-state',
    x: 18,
    y: 18,
    w: width - 36,
    h: height - 36,
    label: `«state def» ${definitionNodes[0]?.label ?? ''}（${states.length} 状态 / ${outEdges.length} 迁移）`,
  }]
  return { nodes: outNodes, edges: outEdges, groups, width, height }
}

function layoutProjectedView(kind, rawView, nodes, mappedEdges) {
  if (kind === 'structure') return layoutStructureProjection(nodes, mappedEdges)
  if (kind === 'ibd') return layoutIbdProjection(nodes, mappedEdges, rawView)
  if (kind === 'requirement') return layoutRequirementProjection(nodes, mappedEdges)
  if (kind === 'state') return layoutStateProjection(nodes, mappedEdges)
  autoLayout(kind, nodes, mappedEdges)
  return { nodes, edges: mappedEdges, groups: [] }
}

function normalizeProjectionView(rawView, kind, byId, index) {
  const rawNodes = Array.isArray(rawView.nodes) ? rawView.nodes : []
  if (rawNodes.length === 0) return null
  const nodes = rawNodes.map((rawNode) => makeProjectedNode(rawNode, byId))
  const nodeMap = new Map(nodes.map((node) => [node.id, node]))
  const rawEdges = (Array.isArray(rawView.edges) ? rawView.edges : [])
    .map((rawEdge) => mapProjectedEdge(rawEdge, kind, nodeMap))
    .filter(Boolean)
  const layout = layoutProjectedView(kind, rawView, nodes, rawEdges)
  if (!layout || !Array.isArray(layout.nodes) || layout.nodes.length === 0) return null
  const groups = Array.isArray(layout.groups) ? layout.groups : []
  const bounds = boundsOf(layout.nodes, groups)
  const width = layout.width ?? Math.max(480, bounds.maxX + 44)
  const height = layout.height ?? Math.max(360, bounds.maxY + 44)
  return {
    viewId: String(rawView.viewId ?? rawView.id ?? `${kind}-${index + 1}`),
    kind,
    title: String(rawView.title ?? rawView.name ?? titleForKind(kind)),
    description: typeof rawView.description === 'string' ? rawView.description : undefined,
    scope: rawView.scope && typeof rawView.scope === 'object' ? rawView.scope : {},
    width: Math.round(width),
    height: Math.round(height),
    nodes: layout.nodes,
    edges: layout.edges,
    groups,
  }
}

/**
 * 把 graph.py 输出（或其它 sysml-graph/v1 生成器）规范化为客户端可渲染的视图。
 * @param {object} raw - graph.py stdout 的 JSON（可能是 {ok, graph} 包装）。
 * @param {object} ir - 原始 IR。
 * @returns {{views:object[], tree:object, stats:object}|null} 规范化结果。
 */
export function normalizeExternalGraph(raw, ir) {
  if (raw && typeof raw === 'object' && raw.ok === false) {
    const inner = raw.graph && typeof raw.graph === 'object' ? raw.graph : null
    if (!inner || !Array.isArray(inner.views) || inner.views.length === 0) return null
  }
  const container = raw && typeof raw === 'object' && raw.graph && typeof raw.graph === 'object'
    ? raw.graph
    : raw
  const rawViews = Array.isArray(container?.views)
    ? container.views
    : (Array.isArray(container?.graphs) ? container.graphs : null)
  if (!rawViews || rawViews.length === 0) return null
  const elements = Array.isArray(ir?.elements) ? ir.elements : []
  const byId = new Map(elements.map((element) => [element.id, element]))
  const projection = rawViews.some((rawView) => Array.isArray(rawView?.nodes)
    && rawView.nodes.some((node) => node && typeof node === 'object' && ('attrs' in node || 'parent' in node || 'owner' in node)))
  const views = []
  for (const [index, rawView] of rawViews.entries()) {
    if (!rawView || typeof rawView !== 'object') continue
    const kind = mapViewKind(rawView.kind ?? rawView.type)
    let view = null
    if (projection) {
      view = normalizeProjectionView(rawView, kind, byId, index)
    }
    if (!view) {
      const nodes = (Array.isArray(rawView.nodes) ? rawView.nodes : [])
        .map((node, nodeIndex) => normalizeExternalNode(node, nodeIndex, byId))
        .filter(Boolean)
      if (nodes.length === 0) continue
      const ids = new Set(nodes.map((node) => node.id))
      const edges = (Array.isArray(rawView.edges) ? rawView.edges : [])
        .map((edge, edgeIndex) => normalizeExternalEdge(edge, edgeIndex, ids))
        .filter(Boolean)
      autoLayout(kind, nodes, edges)
      const groups = (Array.isArray(rawView.groups) ? rawView.groups : [])
        .filter((group) => group && typeof group === 'object')
        .map((group, groupIndex) => ({
          id: String(group.id ?? group.groupId ?? `g-${groupIndex + 1}`),
          x: Number(group.x ?? 16),
          y: Number(group.y ?? 16),
          w: Number(group.w ?? group.width ?? 320),
          h: Number(group.h ?? group.height ?? 160),
          label: String(group.label ?? group.name ?? ''),
        }))
      const bounds = boundsOf(nodes, groups)
      view = {
        viewId: String(rawView.viewId ?? rawView.id ?? `${kind}-${index + 1}`),
        kind,
        title: String(rawView.title ?? rawView.name ?? titleForKind(kind)),
        scope: rawView.scope && typeof rawView.scope === 'object' ? rawView.scope : {},
        width: Math.round(Number(rawView.width ?? rawView.w) > 0 ? Number(rawView.width ?? rawView.w) : Math.max(480, bounds.maxX + 44)),
        height: Math.round(Number(rawView.height ?? rawView.h) > 0 ? Number(rawView.height ?? rawView.h) : Math.max(360, bounds.maxY + 44)),
        nodes,
        edges,
        groups,
      }
    }
    if (view) views.push(view)
  }
  if (views.length === 0) return null
  const fallback = buildFallbackGraph(ir)
  const have = new Set(views.map((view) => view.kind))
  for (const kind of ['structure', 'ibd', 'requirement', 'state']) {
    if (have.has(kind)) continue
    const substitute = fallback.views.find((view) => view.kind === kind)
    if (substitute) {
      views.push(substitute)
      have.add(kind)
    }
  }
  if (!have.has('param')) {
    const param = fallback.views.find((view) => view.kind === 'param')
    if (param) {
      views.push(param)
      have.add('param')
    }
  }
  const seenIds = new Set()
  const deduped = views.filter((view) => {
    if (seenIds.has(view.viewId)) return false
    seenIds.add(view.viewId)
    return true
  })
  const packageName = typeof ir?.package === 'string' && ir.package ? ir.package : 'Model'
  return {
    views: deduped,
    tree: buildTree(packageName, elements, deduped),
    stats: {
      elements: elements.length,
      relations: relCount(elements),
      kinds: kindCounts(elements),
      views: deduped.length,
    },
  }
}


/* ------------------------------------------------------------------ *
 * 模型加载（缓存 / diff / 建模中）
 * ------------------------------------------------------------------ */

function errorPayload(code, message, extra = {}) {
  return {
    ok: false,
    schema: 'sysml-viz/error/v1',
    plugin: PLUGIN_ID,
    version: VERSION,
    generatedAt: new Date().toISOString(),
    error: { code, message, ...extra },
  }
}

function markerPresent(path) {
  if (!path) return false
  const directory = dirname(path)
  return existsSync(join(directory, '.sysml-viz', 'modeling'))
    || existsSync(join(directory, '.modeling'))
}

function withRuntime(model, cfg) {
  const now = Date.now()
  const mtimeMs = model.modelRef.mtimeMs
  const ageMs = Math.max(0, now - mtimeMs)
  const marker = markerPresent(model.modelRef.path)
  const active = marker || ageMs < cfg.modelingWindowMs
  return {
    ...model,
    generatedAt: new Date(now).toISOString(),
    modeling: {
      active,
      reason: marker ? 'marker' : (active ? 'recent-write' : 'idle'),
      ageMs,
      since: new Date(mtimeMs).toISOString(),
      windowMs: cfg.modelingWindowMs,
    },
    config: {
      autoOpen: cfg.autoOpen,
      pollMs: cfg.pollMs,
      modelingWindowMs: cfg.modelingWindowMs,
    },
  }
}

/**
 * 读取 / 缓存模型并生成图投影。
 * @param {object} context - {cfg, state}。
 * @param {string} [explicitPath] - 请求显式指定的路径。
 * @param {{extraRoots?: string[], sessionId?: string|null, archive?: boolean}} [options] - 本次请求解析出的会话工作区根 / 会话 id / 是否记录过程。
 * @returns {Promise<object>} 成功时 ok:true；失败时 ok:false（可安全序列化）。
 */
export async function loadModel(context, explicitPath, options = {}) {
  const { cfg, state } = context
  const extraRoots = Array.isArray(options?.extraRoots) ? options.extraRoots : []
  const resolved = await resolveModelPath(cfg, explicitPath, extraRoots)
  if (!resolved.path) {
    return errorPayload('MODEL_NOT_FOUND', '未找到 SysML IR JSON（*.ir.json）。请设置 SYSML_VIZ_MODEL，或把模型放到 <workspace>/.sysml-viz/model.ir.json 或 model-output/<包名>/*.ir.json。', {
      searched: resolved.searched,
      workspaceRoots: resolved.roots,
      hint: 'GET /api/sysml-viz/health 可查看解析详情；打开 tab 时需带 ?sessionId= 才能定位会话工作区',
    })
  }
  let info
  try {
    info = await stat(resolved.path)
  } catch (error) {
    return errorPayload('MODEL_READ_ERROR', `无法读取模型文件：${error?.message ?? error}`, { path: resolved.path })
  }
  const cacheKey = `${resolved.path}|${info.mtimeMs}|${info.size}`
  if (state.cache && state.cache.key === cacheKey) {
    ensureWatch(context, resolved.path)
    // 缓存命中也要补记（例如历史目录刚被清空）：同语义内容不会新增步骤。
    if (cfg.history && options.archive !== false && state.cache.text && state.cache.ir) {
      archiveRevision(state, {
        dir: historyDirFor(resolved.roots, resolved.path),
        modelPath: resolved.path,
        text: state.cache.text,
        ir: state.cache.ir,
        irSha256: state.cache.model.modelRef.irSha256,
        sessionId: options.sessionId,
      })
    }
    return state.cache.model
  }
  let text
  try {
    text = await readFile(resolved.path, 'utf8')
  } catch (error) {
    return errorPayload('MODEL_READ_ERROR', `无法读取模型文件：${error?.message ?? error}`, { path: resolved.path })
  }
  const irSha256 = createHash('sha256').update(text).digest('hex')
  let ir
  try {
    ir = JSON.parse(text.replace(/^\uFEFF/, ''))
  } catch (error) {
    return errorPayload('MODEL_PARSE_ERROR', `IR JSON 解析失败：${error?.message ?? error}`, { path: resolved.path })
  }
  const elements = Array.isArray(ir?.elements) ? ir.elements : null
  if (!elements) {
    return errorPayload('MODEL_INVALID_IR', 'IR 缺少 elements 数组，不是 sysml-ir/v1 文档。', { path: resolved.path })
  }

  let graph = null
  let source = 'js'
  let python = { enabled: cfg.preferPython, used: false, script: null, python: null, error: null, graphMeta: null }
  if (cfg.preferPython) {
    const script = await findGraphScript(cfg, state, extraRoots)
    python.script = script
    const pythonPath = resolvePython(cfg, resolved.roots)
    python.python = pythonPath
    if (script && !(state.pythonDisabledUntil && Date.now() < state.pythonDisabledUntil)) {
      const result = await runPythonGraph({ ...cfg, python: pythonPath }, script, resolved.path)
      const payload = result.ok ? result.raw : null
      if (payload && payload.ok === false) {
        const first = Array.isArray(payload.errors) && payload.errors.length > 0
          ? payload.errors[0]
          : null
        python.error = first
          ? `graph.py 报告 IR 不合法：${first.message ?? first.code ?? JSON.stringify(first)}`
          : 'graph.py 报告 IR 不合法（ok=false）'
        state.pythonDisabledUntil = Date.now() + 60000
      } else if (payload) {
        const normalized = normalizeExternalGraph(payload, ir)
        if (normalized) {
          graph = normalized
          source = 'python'
          python.used = true
          const inner = payload.graph && typeof payload.graph === 'object' ? payload.graph : payload
          python.graphMeta = {
            schema: inner.schema ?? GRAPH_SCHEMA,
            contentSha256: inner.modelRef?.contentSha256 ?? null,
            stats: inner.stats ?? null,
            warnings: Array.isArray(payload.warnings) ? payload.warnings : [],
          }
        } else {
          python.error = 'graph.py 输出缺少可用的 views'
          state.pythonDisabledUntil = Date.now() + 60000
        }
      } else {
        python.error = result.error
        state.pythonDisabledUntil = Date.now() + 60000
      }
    }
  }
  if (!graph) graph = buildFallbackGraph(ir)

  const ids = elements.map((element) => element.id).filter((id) => typeof id === 'string')
  let diff = null
  if (state.cache && state.cache.path === resolved.path && Array.isArray(state.cache.ids)) {
    const previous = new Set(state.cache.ids)
    const next = new Set(ids)
    const added = ids.filter((id) => !previous.has(id))
    const removed = state.cache.ids.filter((id) => !next.has(id))
    if (added.length > 0 || removed.length > 0) {
      diff = { added, removed, at: new Date().toISOString() }
    }
  }

  const modelRef = {
    schema: typeof ir.schema === 'string' ? ir.schema : IR_SCHEMA,
    package: typeof ir.package === 'string' ? ir.package : 'Model',
    revision: irSha256.slice(0, 8),
    irSha256,
    path: resolved.path,
    source: resolved.source,
    mtime: new Date(info.mtimeMs).toISOString(),
    mtimeMs: info.mtimeMs,
    size: info.size,
  }
  const model = {
    ok: true,
    schema: GRAPH_SCHEMA,
    plugin: PLUGIN_ID,
    version: VERSION,
    source,
    python,
    modelRef,
    stats: graph.stats,
    views: graph.views,
    tree: graph.tree,
    diff,
  }
  state.cache = { key: cacheKey, path: resolved.path, ids, model, text, ir }
  if (cfg.history && options.archive !== false) {
    archiveRevision(state, {
      dir: historyDirFor(resolved.roots, resolved.path),
      modelPath: resolved.path,
      text,
      ir,
      irSha256,
      sessionId: options.sessionId,
    })
  }
  ensureWatch(context, resolved.path)
  return model
}

/** 用 fs.watch 兜底监听当前模型文件（轮询请求本身也会按 mtime 失效缓存）。 */
function ensureWatch(context, path) {
  const { state } = context
  if (state.watchedPath === path) return
  closeWatch(state)
  state.watchedPath = path
  try {
    const watcher = watch(dirname(path), { persistent: false }, (_event, filename) => {
      if (filename && String(filename) !== path.split('/').pop() && String(filename) !== path.split('\\').pop()) return
      if (state.cache) state.cache.key = null
      state.changedAt = Date.now()
    })
    watcher.on('error', () => closeWatch(state))
    state.watcher = watcher
  } catch {
    state.watchedPath = null
  }
}

function closeWatch(state) {
  if (state.watcher) {
    try {
      state.watcher.close()
    } catch {
      /* watcher 可能已经关闭 */
    }
  }
  state.watcher = null
  state.watchedPath = null
}

/* ------------------------------------------------------------------ *
 * 建模过程记录（每步 IR 快照 + 增删改 + 会话归属）
 * ------------------------------------------------------------------ */

/** 递归排序对象键后序列化，得到与键序/缩进无关的稳定文本。 */
function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue)
  if (value && typeof value === 'object') {
    const out = {}
    for (const key of Object.keys(value).sort()) out[key] = canonicalValue(value[key])
    return out
  }
  return value
}

/** 稳定 JSON：对象键递归排序、数组保持顺序。 */
export function stableStringify(value) {
  return JSON.stringify(canonicalValue(value))
}

/** 参与"语义变化"判定的字段：schema / package / elements（meta 标题等不产生步骤）。 */
function semanticPayload(ir) {
  return {
    schema: typeof ir?.schema === 'string' ? ir.schema : IR_SCHEMA,
    package: typeof ir?.package === 'string' ? ir.package : 'Model',
    elements: Array.isArray(ir?.elements) ? ir.elements : [],
  }
}

/** IR 语义哈希：同模型无论文件怎么格式化都稳定。 */
export function semanticSha256(ir) {
  return createHash('sha256').update(stableStringify(semanticPayload(ir))).digest('hex')
}

function pad4(value) {
  return String(Math.max(0, Number(value) || 0)).padStart(4, '0')
}

/** 会话 id → 8 位短 id（显示/归属用）。 */
export function shortSessionId(value) {
  const text = String(value ?? '').trim()
  if (!text) return null
  const match = text.match(/([0-9a-f]{8})$/i)
  if (match) return match[1].toLowerCase()
  return text.slice(0, 8)
}

/**
 * 本次请求的工作区历史目录。
 * 优先会话工作区根（<root>/.sysml-viz/history）；没有工作区根时退回模型文件旁的 .sysml-viz/history。
 * @param {string[]} roots - 已解析工作区根。
 * @param {string} modelPath - IR 文件绝对路径。
 * @returns {string} 历史目录。
 */
export function historyDirFor(roots, modelPath) {
  const root = Array.isArray(roots) ? roots.find((item) => typeof item === 'string' && item) : null
  if (root) return join(root, '.sysml-viz', 'history')
  const directory = dirname(String(modelPath || ''))
  if (basename(directory) === '.sysml-viz') return join(directory, 'history')
  return join(directory, '.sysml-viz', 'history')
}

function readHistoryIndex(dir) {
  try {
    const parsed = JSON.parse(readFileSync(join(dir, 'index.json'), 'utf8'))
    return parsed && typeof parsed === 'object' && Array.isArray(parsed.steps) ? parsed : null
  } catch {
    return null
  }
}

/** health 用的轻量过程记录摘要（不返回步骤数组）。 */
function historyLite(dir) {
  const index = readHistoryIndex(dir)
  if (!index) return { available: false, dir, stepCount: 0, updatedAt: null }
  return {
    available: index.steps.length > 0,
    dir,
    stepCount: index.steps.length,
    updatedAt: index.updatedAt ?? null,
    modelPath: index.modelPath ?? null,
    timelineExists: existsSync(join(dir, 'timeline.svg')),
  }
}

function writeJsonAtomic(file, value) {
  const tmp = `${file}.tmp-${process.pid}-${Date.now()}`
  writeFileSync(tmp, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  renameSync(tmp, file)
}

/** 读快照里的元素数组（缺失/坏 JSON 返回 null）。 */
function readSnapshotElements(file) {
  try {
    const ir = JSON.parse(readFileSync(file, 'utf8'))
    return Array.isArray(ir?.elements) ? ir.elements : null
  } catch {
    return null
  }
}

function elementSignature(element) {
  return stableStringify(element)
}

/**
 * 记录一次 IR 修订（只在该修订的语义内容与上一步不同时追加）。
 *
 * 写入 <historyDir>/step-NNNN-<rev>.ir.json + index.json；全程同步写、失败只记日志，
 * 绝不影响模型路由本身。
 * @param {object} state - 插件运行态（记录 historyError）。
 * @param {{dir:string, modelPath:string, text:string, ir:object, irSha256:string, sessionId?:string|null}} options - 修订信息。
 * @returns {{ok:boolean, appended?:boolean, seq?:number, steps?:number, error?:string}} 归档结果。
 */
export function archiveRevision(state, options = {}) {
  const {
    dir, modelPath, text, ir, irSha256, sessionId = null,
  } = options
  try {
    if (!dir || !text || !ir) return { ok: false, error: '缺少归档参数' }
    mkdirSync(dir, { recursive: true })
    const now = new Date().toISOString()
    const semantic = semanticSha256(ir)
    let index = readHistoryIndex(dir)
    if (!index) {
      index = {
        schema: HISTORY_SCHEMA,
        workspace: dirname(dirname(dir)),
        modelPath,
        createdAt: now,
        updatedAt: now,
        steps: [],
      }
    }
    const last = index.steps.length > 0 ? index.steps[index.steps.length - 1] : null
    if (last && last.semanticSha256 === semantic) {
      // 同内容：只补记"哪次会话来过"，不新增步骤
      if (!last.sessionId && sessionId) {
        last.sessionId = shortSessionId(sessionId)
        index.updatedAt = now
        writeJsonAtomic(join(dir, 'index.json'), index)
      }
      return { ok: true, appended: false, seq: last.seq, steps: index.steps.length }
    }
    const elements = Array.isArray(ir.elements) ? ir.elements : []
    const ids = elements.map((element) => element.id).filter((id) => typeof id === 'string')
    const previousElements = last ? readSnapshotElements(join(dir, last.snapshot)) : null
    const previousById = new Map(
      (previousElements ?? []).filter((element) => element && typeof element.id === 'string')
        .map((element) => [element.id, elementSignature(element)]),
    )
    const currentIds = new Set(ids)
    const added = previousById.size > 0 || last ? ids.filter((id) => !previousById.has(id)) : []
    const removed = last ? [...previousById.keys()].filter((id) => !currentIds.has(id)) : []
    const changed = last
      ? ids.filter((id) => previousById.has(id) && previousById.get(id) !== elementSignature(elements.find((element) => element.id === id)))
      : []
    const seq = last ? Number(last.seq) + 1 : 0
    const revision = irSha256.slice(0, 8)
    const snapshot = `step-${pad4(seq)}-${revision}.ir.json`
    writeFileSync(join(dir, snapshot), text, 'utf8')
    index.steps.push({
      seq,
      at: now,
      revision,
      irSha256,
      semanticSha256: semantic,
      elements: ids.length,
      relations: relCount(elements),
      added,
      removed,
      changed,
      source: last ? 'change' : 'baseline',
      sessionId: shortSessionId(sessionId),
      snapshot,
    })
    index.modelPath = modelPath
    index.updatedAt = now
    writeJsonAtomic(join(dir, 'index.json'), index)
    if (state) state.historyError = null
    return { ok: true, appended: true, seq, steps: index.steps.length }
  } catch (error) {
    const message = String(error?.message ?? error)
    if (state) state.historyError = message
    return { ok: false, error: message }
  }
}

/**
 * 组装 /history 响应：步列表 + 当前模型 + 本会话新增元素（持久高亮用）。
 * @param {string} dir - 历史目录。
 * @param {{modelPath?:string|null, sessionId?:string|null, historyError?:string|null}} [meta] - 附加信息。
 * @returns {object} 可安全 JSON 化的响应。
 */
export function historyPayload(dir, meta = {}) {
  const index = readHistoryIndex(dir)
  const short = shortSessionId(meta.sessionId)
  const timelinePath = join(dir, 'timeline.svg')
  const base = {
    ok: true,
    schema: HISTORY_SCHEMA,
    plugin: PLUGIN_ID,
    version: VERSION,
    historyDir: dir,
    historyError: meta.historyError ?? null,
    timeline: { path: timelinePath, exists: existsSync(timelinePath) },
  }
  if (!index || index.steps.length === 0) {
    return {
      ...base,
      available: false,
      steps: [],
      stepCount: 0,
      current: null,
      session: short ? { id: short, addedIds: [], count: 0, steps: 0, firstSeq: null } : null,
    }
  }
  const steps = index.steps.map((step) => ({
    seq: Number(step.seq) || 0,
    at: step.at ?? null,
    revision: step.revision ?? null,
    irSha256: step.irSha256 ?? null,
    semanticSha256: step.semanticSha256 ?? null,
    elements: Number(step.elements) || 0,
    relations: Number(step.relations) || 0,
    added: Array.isArray(step.added) ? step.added : [],
    removed: Array.isArray(step.removed) ? step.removed : [],
    changed: Array.isArray(step.changed) ? step.changed : [],
    source: step.source ?? 'change',
    sessionId: step.sessionId ?? null,
    snapshot: step.snapshot ?? null,
    turn: Number.isFinite(Number(step.turn)) ? Number(step.turn) : null,
    note: typeof step.note === 'string' ? step.note : null,
  }))
  const last = steps[steps.length - 1]
  const sessionAdded = new Set()
  let sessionSteps = 0
  let firstSeq = null
  if (short) {
    for (const step of steps) {
      if (step.sessionId !== short) continue
      sessionSteps += 1
      if (firstSeq === null) firstSeq = step.seq
      for (const id of step.added) sessionAdded.add(id)
      for (const id of step.changed) sessionAdded.add(id)
    }
  }
  return {
    ...base,
    available: true,
    workspace: index.workspace ?? null,
    modelPath: index.modelPath ?? meta.modelPath ?? null,
    createdAt: index.createdAt ?? null,
    updatedAt: index.updatedAt ?? null,
    steps,
    stepCount: steps.length,
    current: {
      seq: last.seq,
      revision: last.revision,
      elements: last.elements,
      relations: last.relations,
      at: last.at,
    },
    session: short
      ? {
        id: short,
        addedIds: [...sessionAdded].sort(),
        count: sessionAdded.size,
        steps: sessionSteps,
        firstSeq,
      }
      : null,
  }
}

/** 找 timeline.py（工作区自带 / 环境变量 / 配置均可覆盖）。 */
async function findTimelineScript(cfg, state, extraRoots = []) {
  if (cfg.timelineScript) {
    const absolute = isAbsolute(cfg.timelineScript) ? cfg.timelineScript : resolve(process.cwd(), cfg.timelineScript)
    if (existsSync(absolute)) return absolute
  }
  const relatives = [
    join('sysml-modeling-agent', 'mcp-server', 'tools', 'timeline.py'),
    join('mcp-server', 'tools', 'timeline.py'),
    join('tools', 'timeline.py'),
  ]
  const agentDir = pickString(process.env.SYSML_AGENT_DIR)
  if (agentDir) {
    for (const relative of relatives) {
      if (relative.includes('sysml-modeling-agent')) continue
      const candidate = join(resolve(agentDir), relative)
      if (existsSync(candidate)) return candidate
    }
  }
  const roots = await workspaceRoots(cfg, extraRoots)
  // 插件自带位置推出的仓库根优先于工作区扫描（现场安装 / 仓库内副本都覆盖）。
  for (const pluginRoot of agentRootCandidates()) {
    for (const relative of relatives) {
      const candidate = join(pluginRoot, relative)
      if (existsSync(candidate)) return candidate
    }
  }
  for (const root of roots) {
    for (const relative of relatives) {
      const candidate = join(root, relative)
      if (existsSync(candidate)) return candidate
    }
  }
  return null
}

/** 让 timeline.py 读历史目录并把 SVG 写到 outPath（--json 输出机器可读摘要）。 */
function runPythonTimeline(cfg, scriptPath, historyDir, outPath) {
  return new Promise((resolvePromise) => {
    let settled = false
    const finish = (value) => {
      if (settled) return
      settled = true
      resolvePromise(value)
    }
    let child
    try {
      child = spawn(cfg.python, [scriptPath, '--history', historyDir, '--out', outPath, '--json'], {
        cwd: dirname(dirname(scriptPath)),
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
        windowsHide: true,
      })
    } catch (error) {
      finish({ ok: false, error: String(error?.message ?? error) })
      return
    }
    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => {
      try {
        child.kill('SIGKILL')
      } catch {
        /* 已退出 */
      }
      finish({ ok: false, error: `timeline.py 调用超时（${cfg.timelineTimeoutMs}ms）` })
    }, cfg.timelineTimeoutMs)
    child.stdout?.on('data', (chunk) => {
      stdout += String(chunk)
    })
    child.stderr?.on('data', (chunk) => {
      stderr += String(chunk)
    })
    child.on('error', (error) => {
      clearTimeout(timer)
      finish({ ok: false, error: String(error?.message ?? error) })
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      const payload = parseLooseJson(stdout)
      if (code !== 0) {
        finish({
          ok: false,
          payload,
          error: payload?.errors?.[0]?.message
            ? `timeline.py：${payload.errors[0].code ?? ''} ${payload.errors[0].message}`
            : `timeline.py 退出码 ${code}: ${stderr.trim().slice(0, 300)}`,
        })
        return
      }
      finish({ ok: true, payload, stderr: stderr.trim().slice(0, 400) })
    })
  })
}

/* ------------------------------------------------------------------ *
 * HTTP
 * ------------------------------------------------------------------ */

function sendJson(res, status, value) {
  const body = JSON.stringify(value)
  res.statusCode = status
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.setHeader('cache-control', 'no-store')
  res.end(body)
}

function queryOf(req) {
  try {
    return new URL(String(req.url ?? '/'), 'http://localhost').searchParams
  } catch {
    return new URLSearchParams()
  }
}

/* ------------------------------------------------------------------ *
 * 只读诊断（排查 preset / MCP 未生效）
 * ------------------------------------------------------------------ */

/** 把 loader 里的一个条目压成可序列化的快照。 */
function presetRowReport(entry) {
  const options = entry?.options ?? {}
  const row = {
    id: typeof options.id === 'string' ? options.id : null,
    name: typeof options.name === 'string' ? options.name : null,
    group: options.group === true,
    disabled: Boolean(entry?.disabled),
  }
  const fiber = entry?.fiber
  if (fiber) {
    row.fiber = {
      state: fiber.state ?? null,
      uid: fiber.uid ?? null,
      inject: fiber.inject && typeof fiber.inject === 'object' ? Object.keys(fiber.inject) : [],
      error: fiber._error ? String(fiber._error?.message ?? fiber._error) : null,
    }
  } else if (!row.group && !row.disabled) {
    row.fiber = { state: 'never-started' }
  }
  const config = options.config
  if (config && typeof config === 'object' && !Array.isArray(config)) {
    try {
      const clone = JSON.parse(JSON.stringify(config, (_key, value) => {
        if (value && typeof value === 'object' && '__jsExpr' in value) return `!!js ${value.__jsExpr}`
        if (typeof value === 'string' && value.length > 240) return `${value.slice(0, 240)}…`
        return value
      }))
      row.config = clone
    } catch {
      row.config = '(config 无法序列化)'
    }
  }
  return row
}

/** 读取一个 preset 已挂载的 plugin 树（若有）。 */
async function presetTreeReport(tree) {
  const rows = []
  for (const entry of tree.entries()) rows.push(presetRowReport(entry))
  return rows
}

/**
 * 汇总 agent preset 注册表：roster、broken 原因、已挂载子树的每行 state。
 * @param {object|null} registry - ctx.agentPresets 服务。
 * @returns {Promise<object>} 可安全 JSON 化的诊断。
 */
export async function describePresets(registry) {
  if (!registry) return { available: false, reason: 'agentPresets 服务未注入（插件可能未在 Host 作用域）' }
  const result = { available: true, presets: [], compositions: null, error: null }
  let listed = []
  try {
    // roster 读取会等每个 preset 的挂载诊断；卡住时降级，避免诊断路由被拖死
    listed = await Promise.race([
      registry.list(),
      new Promise((resolvePromise) => setTimeout(() => resolvePromise([]), 4000)),
    ])
  } catch (error) {
    result.error = String(error?.message ?? error)
  }
  try {
    result.compositions = registry.inspectCompositions()
  } catch (error) {
    result.compositionsError = String(error?.message ?? error)
  }
  const definitions = registry.definitions
  const records = definitions instanceof Map
    ? [...definitions.entries()]
    : Object.entries(definitions && typeof definitions === 'object' ? definitions : {})
  for (const [id, record] of records) {
    const info = Array.isArray(listed) ? listed.find((row) => row?.id === id) : undefined
    const row = {
      id,
      name: info?.name ?? record?.config?.name ?? null,
      broken: info?.broken ?? record?.broken ?? null,
      declaredRows: Array.isArray(record?.config?.plugins)
        ? record.config.plugins.map((item) => ({
          id: item && typeof item === 'object' ? item.id ?? null : null,
          name: item && typeof item === 'object' ? item.name ?? null : null,
          disabled: item && typeof item === 'object' ? item.disabled ?? null : null,
        }))
        : null,
      mountedRows: null,
    }
    try {
      const tree = record?.generation?.mount?.tree
      if (tree && typeof tree.entries === 'function') row.mountedRows = await presetTreeReport(tree)
    } catch (error) {
      row.mountError = String(error?.message ?? error)
    }
    result.presets.push(row)
  }
  return result
}

/**
 * 汇总 Host 工具注册表里当前可见的 tool 名（若工具服务可见）。
 * @param {object|null} tools - ctx.tools 服务。
 * @returns {object} 可安全 JSON 化的诊断。
 */
export function describeToolRegistry(tools) {
  if (!tools) return { available: false, reason: 'tools 服务未注入' }
  const result = { available: true, count: null, names: null, error: null }
  const attempts = [
    () => tools.schemas(),
    () => tools.schemas(undefined),
  ]
  for (const attempt of attempts) {
    try {
      const value = attempt()
      if (Array.isArray(value)) {
        result.count = value.length
        result.names = value.map((schema) => schema?.name ?? schema?.toolName ?? null).filter(Boolean)
        break
      }
    } catch (error) {
      result.error = String(error?.message ?? error)
    }
  }
  return result
}

/** 与 DSH mcp-client 近似地清洗父进程环境（去掉 DSH_* 与凭据型变量）。 */
function mcpChildEnv() {
  const env = {}
  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined) continue
    if (/^DSH_/i.test(key)) continue
    if (/(TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY)/i.test(key)) continue
    env[key] = value
  }
  env.PYTHONIOENCODING = 'utf-8'
  return env
}

/** 不走 inject、直接读一个服务（cordis `ctx.get(name)` 语义）；不存在时返回 null。 */
export function tryService(ctx, name) {
  try {
    const value = ctx?.get?.(name)
    return value ?? null
  } catch {
    return null
  }
}

/**
 * 找 agentPresets 服务：先直接 ctx.get，再从 loader 里 agent-preset-registry 行的 fiber 取。
 * （Desktop 下 Host 作用域可能看不到该服务，但注册表插件自身的 fiber.ctx 一定看得到。）
 * @param {object} ctx - Host 插件 context。
 * @returns {object|null} agentPresets 服务。
 */
export function findAgentPresetRegistry(ctx) {
  const direct = tryService(ctx, 'agentPresets')
  if (direct) return direct
  const loader = tryService(ctx, 'loader')
  if (!loader || typeof loader.entries !== 'function') return null
  try {
    for (const entry of loader.entries()) {
      const id = String(entry?.options?.id ?? '')
      const name = String(entry?.options?.name ?? '')
      if (id !== 'agent-preset-registry' && !/agent-preset-registry/.test(name)) continue
      const registry = tryService(entry?.fiber?.ctx, 'agentPresets')
      if (registry) return registry
    }
  } catch {
    /* 遍历失败时放弃 */
  }
  return null
}

const DIAGNOSTIC_SERVICE_NAMES = [
  'agentPresets', 'tools', 'loader', 'systemPrompt', 'mcpResources',
  'sessions', 'workspace', 'webServer', 'subagent', 'jobs', 'agentLoop',
]

/**
 * 逐个探测 Host 作用域里能不能取到关键服务（区分"服务不存在"与"注入没生效"）。
 * @param {object} ctx - Host 插件 context。
 * @returns {object} 每个服务的 available / type。
 */
export function describeServices(ctx) {
  const out = { hasGet: typeof ctx?.get === 'function', services: {} }
  for (const name of DIAGNOSTIC_SERVICE_NAMES) {
    const value = tryService(ctx, name)
    out.services[name] = value === null
      ? { available: false }
      : { available: true, type: typeof value, constructorName: value?.constructor?.name ?? null }
  }
  return out
}

/**
 * 枚举 Host loader 树里的每一条 plugin row：id / name / disabled / fiber.state / fiber error。
 *
 * 这是回答"profile patch 里的 mcp 行到底有没有被加载"最直接的证据。
 * @param {object} ctx - Host 插件 context。
 * @param {{includeConfig?: RegExp}} [options] - 只对匹配的 row 附带 config（避免 payload 过大）。
 * @returns {object} 可安全 JSON 化的诊断。
 */
export function describeLoaderRows(ctx, options = {}) {
  const out = {
    available: false,
    rowCount: 0,
    rows: [],
    error: null,
  }
  const loader = tryService(ctx, 'loader')
  if (!loader || typeof loader.entries !== 'function') {
    out.reason = 'loader 服务不可用或不是 EntryTree'
    return out
  }
  out.available = true
  const configFilter = options.includeConfig instanceof RegExp ? options.includeConfig : /(mcp|sysml|preset)/i
  try {
    for (const entry of loader.entries()) {
      const row = presetRowReport(entry)
      const label = `${row.id ?? ''} ${row.name ?? ''}`
      if (!configFilter.test(label)) delete row.config
      out.rows.push(row)
    }
    out.rowCount = out.rows.length
  } catch (error) {
    out.error = String(error?.message ?? error)
  }
  return out
}

/** 静态检查 profile 的 patch 文件里有没有 MCP / preset 行（不依赖 loader）。 */
export async function describeProfilePatch() {
  const profileDir = join(homedir(), '.dsh', 'profiles', process.env.DSH_PROFILE || 'desktop')
  const file = join(profileDir, 'cordis.patch.yml')
  const out = { file, available: false, hasGlobalMcpRow: false, rows: [], error: null }
  try {
    const text = await readFile(file, 'utf8')
    out.available = true
    out.hasGlobalMcpRow = /id:\s*["']?mcp-sysml-agent["']?/.test(text)
    out.lines = text
      .split('\n')
      .map((line, index) => ({ line: index + 1, text: line.trimEnd() }))
      .filter((row) => /mcp-sysml-agent|sysml-viz|dsh-sysml-viz|preset-sysml|dsh-mcp-client|agent-preset-registry/.test(row.text))
      .slice(0, 60)
  } catch (error) {
    out.error = String(error?.message ?? error)
  }
  return out
}

/** 把启动时的 Host 组合快照写到 /tmp（重启后无需 UI 就能取证）。 */
export function scheduleBootSnapshot(ctx, context) {
  const timer = setTimeout(async () => {
    try {
      const snapshot = {
        at: new Date().toISOString(),
        version: VERSION,
        pid: process.pid,
        cwd: process.cwd(),
        services: describeServices(ctx),
        loader: describeLoaderRows(ctx),
        tools: describeToolRegistry(tryService(ctx, 'tools')),
        presets: await describePresets(findAgentPresetRegistry(ctx)),
        profilePatch: await describeProfilePatch(),
      }
      await writeFile('/tmp/dsh-sysml-viz-boot.json', JSON.stringify(snapshot, null, 2))
    } catch {
      /* 取证失败不影响插件 */
    }
  }, 3000)
  timer.unref?.()
  return () => clearTimeout(timer)
}

/**
 * 从 Host 进程直接拉起 MCP server 做一次 stdio JSON-RPC 握手（只读自检）。
 *
 * 用来回答"到底是 server/路径/环境的问题，还是 DSH mcp-client 没接上"：
 * 如果这里能列出 9 个工具，而会话里没有 mcp__sysml-agent__*，问题就在 preset 行。
 * @param {number} [timeoutMs] - 整体超时。
 * @returns {Promise<object>} 自检结果（永不抛错）。
 */
export async function probeMcpServer(timeoutMs = 15000) {
  const agentRoot = pickString(process.env.SYSML_AGENT_ROOT, agentRootCandidates()[0])
  if (!agentRoot) {
    return {
      ok: false,
      command: '',
      server: '',
      cwd: '',
      exists: { command: false, server: false, cwd: false },
      protocolVersion: null,
      toolNames: [],
      latencyMs: null,
      stderrTail: '',
      error: '未找到 sysml-modeling-agent 仓库根（可设 SYSML_AGENT_ROOT 指向它）',
    }
  }
  const command = pickString(process.env.SYSML_AGENT_PY, join(agentRoot, '.venv', 'bin', 'python'))
  const server = pickString(process.env.SYSML_AGENT_SERVER, join(agentRoot, 'mcp-server', 'run_server.py'))
  const cwd = pickString(process.env.SYSML_AGENT_CWD, join(agentRoot, 'mcp-server'))
  const result = {
    ok: false,
    command,
    server,
    cwd,
    exists: { command: existsSync(command), server: existsSync(server), cwd: existsSync(cwd) },
    protocolVersion: null,
    toolNames: [],
    latencyMs: null,
    stderrTail: '',
    error: null,
  }
  if (!result.exists.command || !result.exists.server) {
    result.error = 'MCP 命令或 run_server.py 不存在'
    return result
  }
  return new Promise((resolvePromise) => {
    const startedAt = Date.now()
    const stderrChunks = []
    let child
    try {
      child = spawn(command, [server], {
        cwd,
        env: mcpChildEnv(),
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
      })
    } catch (error) {
      result.error = String(error?.message ?? error)
      result.latencyMs = Date.now() - startedAt
      resolvePromise(result)
      return
    }
    let settled = false
    let stage = 0
    let buffer = ''
    const finish = (error) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      result.latencyMs = Date.now() - startedAt
      result.stderrTail = stderrChunks.join('').slice(-2000)
      if (error) result.error = String(error?.message ?? error)
      try {
        child.kill('SIGKILL')
      } catch {
        /* 已退出 */
      }
      resolvePromise(result)
    }
    const timer = setTimeout(() => finish(`自检超时（${timeoutMs}ms）`), timeoutMs)
    child.on('error', (error) => finish(error))
    child.on('exit', (code) => {
      if (!settled) finish(`MCP server 提前退出（code=${code}）`)
    })
    child.stderr?.setEncoding('utf8')
    child.stderr?.on('data', (chunk) => {
      if (stderrChunks.length < 200) stderrChunks.push(String(chunk))
    })
    child.stdout?.setEncoding('utf8')
    child.stdout?.on('data', (chunk) => {
      buffer += chunk
      let index = buffer.indexOf('\n')
      while (index >= 0) {
        const line = buffer.slice(0, index).trim()
        buffer = buffer.slice(index + 1)
        index = buffer.indexOf('\n')
        if (!line) continue
        let message
        try {
          message = JSON.parse(line)
        } catch {
          continue
        }
        if (stage === 0 && message.id === 1 && (message.result || message.error)) {
          result.protocolVersion = message.result?.protocolVersion ?? null
          if (message.error) {
            finish(`initialize 失败：${message.error?.message ?? JSON.stringify(message.error)}`)
            return
          }
          stage = 1
          try {
            child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} })}\n`)
            child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} })}\n`)
          } catch (error) {
            finish(error)
          }
        } else if (stage === 1 && message.id === 2) {
          if (message.error) {
            finish(`tools/list 失败：${message.error?.message ?? JSON.stringify(message.error)}`)
            return
          }
          result.ok = Array.isArray(message.result?.tools)
          result.toolNames = (message.result?.tools ?? [])
            .map((tool) => tool?.name ?? null)
            .filter((name) => typeof name === 'string')
          finish(null)
        }
      }
    })
    try {
      child.stdin.write(`${JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
          protocolVersion: '2025-06-18',
          capabilities: {},
          clientInfo: { name: 'dsh-sysml-viz-diagnostics', version: VERSION },
        },
      })}\n`)
    } catch (error) {
      finish(error)
    }
  })
}

/**
 * 注册 HTTP 路由（由 smoke-test 的 mock ctx 直接调用验证）。
 * @param {object} ctx - host context（需要 webServer）。
 * @param {object} context - {cfg, state}。
 */
function registerRoutes(ctx, context) {
  const disposers = []
  disposers.push(ctx.webServer.register({
    kind: 'exact',
    path: HEALTH_ROUTE,
    handler: async (req, res) => {
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.statusCode = 405
        res.setHeader('allow', 'GET, HEAD')
        res.end('Method Not Allowed')
        return
      }
      let model = null
      let resolveInfo = null
      const query = queryOf(req)
      const workspaceInfo = await workspaceContextForQuery(query).catch(() => ({
        extraRoots: [], sessionId: null, sessionWorkspace: null,
      }))
      try {
        resolveInfo = await resolveModelPath(context.cfg, undefined, workspaceInfo.extraRoots)
        if (resolveInfo.path) {
          model = await loadModel(context, undefined, {
            extraRoots: workspaceInfo.extraRoots,
            sessionId: workspaceInfo.sessionId,
          })
        }
      } catch (error) {
        model = errorPayload('HEALTH_ERROR', String(error?.message ?? error))
      }
      const script = await findGraphScript(context.cfg, context.state, workspaceInfo.extraRoots).catch(() => null)
      const historyDir = resolveInfo?.path
        ? historyDirFor(resolveInfo.roots, resolveInfo.path)
        : null
      const payload = {
        ok: true,
        plugin: PLUGIN_ID,
        version: VERSION,
        now: new Date().toISOString(),
        routes: [HEALTH_ROUTE, MODEL_ROUTE, HISTORY_ROUTE, TIMELINE_SVG_ROUTE, DIAGNOSTICS_ROUTE],
        autoOpen: context.cfg.autoOpen,
        pollMs: context.cfg.pollMs,
        workspace: {
          roots: resolveInfo?.roots ?? [],
          cwd: process.cwd(),
          configWorkspace: context.cfg.workspace || null,
          sessionId: workspaceInfo.sessionId,
          sessionWorkspace: workspaceInfo.sessionWorkspace?.path ?? null,
          sessionWorkspaceSource: workspaceInfo.sessionWorkspace?.source ?? null,
          sessionWorkspaceTitle: workspaceInfo.sessionWorkspace?.title ?? null,
        },
        model: resolveInfo?.path
          ? {
            found: true,
            path: resolveInfo.path,
            source: resolveInfo.source,
            ok: model?.ok === true,
            revision: model?.ok ? model.modelRef.revision : null,
            error: model?.ok === false ? model.error : null,
          }
          : { found: false, source: resolveInfo?.source ?? 'discovery', searched: resolveInfo?.searched ?? [] },
        graph: {
          source: model?.ok ? model.source : null,
          pythonScript: script,
          pythonAvailable: Boolean(script),
          python: model?.ok ? model.python?.python ?? null : null,
          preferPython: context.cfg.preferPython,
          pythonError: model?.ok ? model.python?.error ?? null : null,
        },
        history: {
          enabled: context.cfg.history,
          ...(historyDir ? historyLite(historyDir) : { available: false, dir: null, stepCount: 0 }),
        },
      }
      if (req.method === 'HEAD') {
        res.statusCode = 200
        res.setHeader('content-type', 'application/json; charset=utf-8')
        res.end()
        return
      }
      sendJson(res, 200, payload)
    },
  }))
  disposers.push(ctx.webServer.register({
    kind: 'exact',
    path: MODEL_ROUTE,
    handler: async (req, res) => {
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.statusCode = 405
        res.setHeader('allow', 'GET, HEAD')
        res.end('Method Not Allowed')
        return
      }
      const query = queryOf(req)
      const explicitPath = query.get('path') || undefined
      const workspaceInfo = await workspaceContextForQuery(query).catch(() => ({
        extraRoots: [], sessionId: null, sessionWorkspace: null,
      }))
      let model
      try {
        model = await loadModel(context, explicitPath, {
          extraRoots: workspaceInfo.extraRoots,
          sessionId: workspaceInfo.sessionId,
        })
      } catch (error) {
        model = errorPayload('INTERNAL_ERROR', String(error?.message ?? error))
      }
      if (!model.ok) {
        model = {
          ...model,
          workspace: {
            sessionId: workspaceInfo.sessionId,
            sessionWorkspace: workspaceInfo.sessionWorkspace?.path ?? null,
            source: workspaceInfo.sessionWorkspace?.source ?? null,
          },
        }
        if (req.method === 'HEAD') {
          res.statusCode = 200
          res.end()
          return
        }
        sendJson(res, 200, model)
        return
      }
      const presented = withRuntime(model, context.cfg)
      const knownRevision = query.get('rev')
      if (knownRevision && knownRevision === presented.modelRef.revision) {
        const delta = {
          ok: true,
          schema: GRAPH_SCHEMA,
          changed: false,
          revision: presented.modelRef.revision,
          generatedAt: presented.generatedAt,
          modeling: presented.modeling,
          config: presented.config,
          diff: presented.diff,
        }
        if (req.method === 'HEAD') {
          res.statusCode = 200
          res.end()
          return
        }
        sendJson(res, 200, delta)
        return
      }
      if (req.method === 'HEAD') {
        res.statusCode = 200
        res.end()
        return
      }
      sendJson(res, 200, presented)
    },
  }))
  disposers.push(ctx.webServer.register({
    kind: 'exact',
    path: HISTORY_ROUTE,
    handler: async (req, res) => {
      const method = req.method === 'HEAD' ? 'GET' : req.method
      if (method !== 'GET' && method !== 'DELETE') {
        res.statusCode = 405
        res.setHeader('allow', 'GET, HEAD, DELETE')
        res.end('Method Not Allowed')
        return
      }
      const query = queryOf(req)
      const explicitPath = query.get('path') || undefined
      const workspaceInfo = await workspaceContextForQuery(query).catch(() => ({
        extraRoots: [], sessionId: null, sessionWorkspace: null,
      }))
      let resolveInfo = null
      try {
        resolveInfo = await resolveModelPath(context.cfg, explicitPath, workspaceInfo.extraRoots)
        if (resolveInfo.path) {
          // 先走一次模型加载：首次打开过程面板时自动把当前模型记成基线
          await loadModel(context, explicitPath, {
            extraRoots: workspaceInfo.extraRoots,
            sessionId: workspaceInfo.sessionId,
          })
        }
      } catch {
        /* 模型读不到时仍允许查看/清空历史 */
      }
      const dir = historyDirFor(resolveInfo?.roots ?? workspaceInfo.extraRoots, resolveInfo?.path ?? '')
      let payload
      if (method === 'DELETE') {
        try {
          rmSync(dir, { recursive: true, force: true })
        } catch (error) {
          sendJson(res, 200, errorPayload('HISTORY_RESET_ERROR', `清空过程记录失败：${error?.message ?? error}`, { historyDir: dir }))
          return
        }
        if (resolveInfo?.path) {
          // 清空后立即重建基线（同语义不会重复记步）
          await loadModel(context, explicitPath, {
            extraRoots: workspaceInfo.extraRoots,
            sessionId: workspaceInfo.sessionId,
          })
        }
        payload = {
          ...historyPayload(dir, { modelPath: resolveInfo?.path ?? null, sessionId: workspaceInfo.sessionId }),
          cleared: true,
        }
      } else {
        payload = historyPayload(dir, {
          modelPath: resolveInfo?.path ?? null,
          sessionId: workspaceInfo.sessionId,
          historyError: context.state.historyError ?? null,
        })
      }
      payload.generatedAt = new Date().toISOString()
      if (req.method === 'HEAD') {
        res.statusCode = 200
        res.setHeader('content-type', 'application/json; charset=utf-8')
        res.end()
        return
      }
      sendJson(res, 200, payload)
    },
  }))
  disposers.push(ctx.webServer.register({
    kind: 'exact',
    path: TIMELINE_SVG_ROUTE,
    handler: async (req, res) => {
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.statusCode = 405
        res.setHeader('allow', 'GET, HEAD')
        res.end('Method Not Allowed')
        return
      }
      const query = queryOf(req)
      const explicitPath = query.get('path') || undefined
      const workspaceInfo = await workspaceContextForQuery(query).catch(() => ({
        extraRoots: [], sessionId: null, sessionWorkspace: null,
      }))
      let resolveInfo = null
      try {
        resolveInfo = await resolveModelPath(context.cfg, explicitPath, workspaceInfo.extraRoots)
        if (resolveInfo.path) {
          await loadModel(context, explicitPath, {
            extraRoots: workspaceInfo.extraRoots,
            sessionId: workspaceInfo.sessionId,
          })
        }
      } catch {
        /* 下面按历史目录现状决定返回什么 */
      }
      const dir = historyDirFor(resolveInfo?.roots ?? workspaceInfo.extraRoots, resolveInfo?.path ?? '')
      if (!existsSync(join(dir, 'index.json'))) {
        sendJson(res, 404, errorPayload('HISTORY_EMPTY', '还没有建模步骤记录；模型下一次变动后会自动记录。', { historyDir: dir }))
        return
      }
      const script = await findTimelineScript(context.cfg, context.state, workspaceInfo.extraRoots).catch(() => null)
      if (!script) {
        sendJson(res, 503, errorPayload('TIMELINE_TOOL_MISSING', '未找到 timeline.py（sysml-modeling-agent/mcp-server/tools/timeline.py）。', { historyDir: dir }))
        return
      }
      const python = resolvePython(context.cfg, resolveInfo?.roots ?? [])
      const outPath = join(dir, 'timeline.svg')
      const result = await runPythonTimeline({ ...context.cfg, python }, script, dir, outPath)
      if (!result.ok) {
        sendJson(res, 500, errorPayload('TIMELINE_GENERATE_FAILED', result.error ?? '生成过程图失败', {
          historyDir: dir,
          script,
          python,
          timeline: result.payload ?? null,
        }))
        return
      }
      let svg = ''
      try {
        svg = readFileSync(outPath, 'utf8')
      } catch (error) {
        sendJson(res, 500, errorPayload('TIMELINE_READ_FAILED', `过程图已生成但读取失败：${error?.message ?? error}`, { historyDir: dir, outPath }))
        return
      }
      res.statusCode = 200
      res.setHeader('content-type', 'image/svg+xml; charset=utf-8')
      res.setHeader('cache-control', 'no-store')
      res.setHeader('x-sysml-viz-timeline', JSON.stringify({
        schema: result.payload?.schema ?? null,
        steps: result.payload?.summary?.steps ?? null,
      }))
      if (req.method === 'HEAD') {
        res.end()
        return
      }
      res.end(svg)
    },
  }))
  disposers.push(ctx.webServer.register({
    kind: 'exact',
    path: DIAGNOSTICS_ROUTE,
    handler: async (req, res) => {
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.statusCode = 405
        res.setHeader('allow', 'GET, HEAD')
        res.end('Method Not Allowed')
        return
      }
      const query = queryOf(req)
      const registry = findAgentPresetRegistry(ctx) ?? context.services?.presets ?? null
      const toolsService = tryService(ctx, 'tools') ?? context.services?.tools ?? null
      const payload = {
        ok: true,
        plugin: PLUGIN_ID,
        version: VERSION,
        now: new Date().toISOString(),
        routes: [HEALTH_ROUTE, MODEL_ROUTE, HISTORY_ROUTE, TIMELINE_SVG_ROUTE, DIAGNOSTICS_ROUTE],
        bootSnapshot: '/tmp/dsh-sysml-viz-boot.json',
        host: {
          cwd: process.cwd(),
          home: homedir(),
          platform: process.platform,
          node: process.version,
          env: {
            SYSML_AGENT_PY: process.env.SYSML_AGENT_PY ?? null,
            SYSML_AGENT_SERVER: process.env.SYSML_AGENT_SERVER ?? null,
            SYSML_AGENT_CWD: process.env.SYSML_AGENT_CWD ?? null,
            SYSML_VIZ_WORKSPACE: process.env.SYSML_VIZ_WORKSPACE ?? null,
          },
        },
        injected: context.services?.injected ?? null,
        services: describeServices(ctx),
        loader: describeLoaderRows(ctx),
        profilePatch: await describeProfilePatch(),
        presets: await describePresets(registry).catch((error) => ({
          available: false, reason: String(error?.message ?? error),
        })),
        tools: describeToolRegistry(toolsService),
        mcpSelfTest: null,
      }
      if (query.get('mcpSelfTest') === '1') {
        payload.mcpSelfTest = await probeMcpServer()
      }
      if (req.method === 'HEAD') {
        res.statusCode = 200
        res.end()
        return
      }
      sendJson(res, 200, payload)
    },
  }))
  return disposers
}

/* ------------------------------------------------------------------ *
 * 插件入口
 * ------------------------------------------------------------------ */

/**
 * Host 插件入口：注册只读 HTTP 路由。
 * @param {object} ctx - Cordis host context。
 * @param {Record<string, unknown>} rawConfig - patch 行配置。
 */
export function apply(ctx, rawConfig) {
  const cfg = readConfig(rawConfig)
  const state = {
    cache: null,
    watcher: null,
    watchedPath: null,
    changedAt: 0,
    scriptPath: null,
    scriptCheckedAt: 0,
    pythonDisabledUntil: 0,
    historyError: null,
  }
  // 诊断用：Host 作用域能看到的服务引用（存在才注入，不阻塞插件启动）。
  const services = {
    presets: null,
    tools: null,
    injected: { presets: 'pending', tools: 'pending', error: null },
  }
  for (const [key, name] of [['presets', 'agentPresets'], ['tools', 'tools']]) {
    try {
      ctx.inject([name], (inner) => {
        try {
          services[key] = inner[name] ?? null
          services.injected[key] = services[key] === null ? 'fired-but-empty' : 'fired'
        } catch (error) {
          services.injected[key] = `fired-but-threw: ${String(error?.message ?? error)}`
        }
      })
    } catch (error) {
      services.injected[key] = `register-failed: ${String(error?.message ?? error)}`
    }
  }
  const context = { cfg, state, services }
  ctx.effect(() => {
    const disposers = registerRoutes(ctx, context)
    return () => {
      closeWatch(state)
      for (const dispose of disposers) {
        try {
          dispose()
        } catch {
          /* 路由可能已被插件卸载流程清理 */
        }
      }
    }
  }, 'sysml-viz: HTTP 路由 / 模型监听')
  // 启动 3 秒后把 Host 组合快照落盘（/tmp/dsh-sysml-viz-boot.json），重启后可离线取证。
  ctx.effect(() => scheduleBootSnapshot(ctx, context), 'sysml-viz: 启动诊断快照')
  ctx.logger?.info?.(`[${PLUGIN_ID}] 已注册 ${HEALTH_ROUTE} / ${MODEL_ROUTE} / ${HISTORY_ROUTE} / ${TIMELINE_SVG_ROUTE} / ${DIAGNOSTICS_ROUTE}（workspace=${cfg.workspace || '(auto)'}，model=${cfg.model || '(auto)'}，history=${cfg.history ? 'on' : 'off'}）`)
}
