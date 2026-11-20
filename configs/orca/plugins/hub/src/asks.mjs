// Reads the asks workers write with ~/.claude/hooks/asks.py (<hub>/state/asks/<id>.json) and turns
// each open one into what a card shows. An ask is checked again here with the limits asks.py
// writes it under, so a hand-written or damaged file shows no buttons rather than odd ones.
//
// The card carries the sha256 of the file it was made from. When a button is pressed the file is
// read again and must still have it, so a card never answers an ask that changed after it showed.
import { createHash } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { isDangerous } from './dangerous.mjs'
import { riskOf, whereOf } from './risk.mjs'

export const ASK_ID = /^\d{8}-\d{6}-[0-9a-f]{8}$/
export const SHA256 = /^[0-9a-f]{64}$/
// Line breaks are allowed where asks.py allows them; these never are.
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f​-‏‪-‮⁦-⁩]/
const LIMITS = {
  question: 1000,
  optionLabel: 60,
  optionDescription: 300,
  suggestLabel: 30,
  suggestPrompt: 300,
  suggestReason: 80
}
// Levels a card may show the body of. Orca shows information up to level B.
const SHOWABLE = new Set(['B', 'C'])
const NOT_WORKERS = new Set(['orchestrator', 'chore-hub-watch'])

export function asksDirOf(hubRoot) {
  return join(hubRoot, 'state', 'asks')
}

function text(value, limit, { multiline = false } = {}) {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed || trimmed.length > limit || CONTROL.test(trimmed)) return null
  if (!multiline && trimmed.includes('\n')) return null
  return trimmed
}

function option(raw) {
  const label = text(raw?.label, LIMITS.optionLabel)
  const description = text(raw?.description, LIMITS.optionDescription, { multiline: true })
  return label && description ? { label, description } : null
}

/** A suggested next step, by the rules of orca-milestone's parseSuggestions. */
export function suggestion(raw) {
  const label = text(raw?.label, LIMITS.suggestLabel)
  const prompt = text(raw?.prompt, LIMITS.suggestPrompt)
  const reason = text(raw?.reason, LIMITS.suggestReason)
  return label && prompt && reason && !prompt.startsWith('-') ? { label, prompt, reason } : null
}

/** The fields of an ask a card uses, or null when the ask is not one asks.py would write. */
export function parseAsk(raw) {
  if (!raw || typeof raw !== 'object' || !ASK_ID.test(raw.id ?? '')) return null
  const worker = text(raw.worker, 100)
  const sessionId = text(raw.session_id, 100)
  if (!worker || !sessionId) return null
  // The orchestrator's own question (panel-mode): only the orchestrator writes it.
  if (raw.kind === 'question') return parseQuestion(raw, worker, sessionId)
  // A permission dialog of the orchestrator, written by approval-gate.py while it waits.
  if (raw.kind === 'permission') return parsePermission(raw, worker, sessionId)
  if (NOT_WORKERS.has(worker)) return null
  const base = {
    id: raw.id,
    kind: raw.kind,
    worker,
    sessionId,
    cwd: text(raw.cwd, 1000),
    case: typeof raw.case === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(raw.case) ? raw.case : null,
    report: text(raw.report, 1000),
    level: typeof raw.level === 'string' ? raw.level : 'B',
    createdAt: Number.isFinite(raw.created_at) ? raw.created_at * 1000 : 0
  }
  if (raw.kind === 'decide') {
    const question = text(raw.question, LIMITS.question, { multiline: true })
    const options = Array.isArray(raw.options) ? raw.options.map(option) : []
    if (!question || options.length < 2 || options.length > 4 || options.includes(null)) return null
    const recommended = Number.isInteger(raw.recommended) && raw.recommended >= 1 && raw.recommended <= options.length ? raw.recommended : null
    return { ...base, question, options, recommended }
  }
  if (raw.kind === 'next') {
    const suggestions = Array.isArray(raw.suggestions) ? raw.suggestions.map(suggestion) : []
    if (suggestions.length < 1 || suggestions.length > 3 || suggestions.includes(null)) return null
    return { ...base, suggestions }
  }
  return null
}

export function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

const QUESTION_MAX = 4000
const BODY_MAX = 50000

function parseQuestion(raw, worker, sessionId) {
  if (worker !== 'orchestrator') return null
  const question = typeof raw.question === 'string' && raw.question.trim() && raw.question.length <= QUESTION_MAX ? raw.question : null
  const options = Array.isArray(raw.options) ? raw.options : []
  const valid = options.length >= 2 && options.length <= 9 && options.every((o) => typeof o?.label === 'string' && o.label.trim() && typeof o.description === 'string')
  const body = raw.body === null || raw.body === undefined ? null : typeof raw.body === 'string' && raw.body.length <= BODY_MAX ? raw.body : undefined
  if (!question || !valid || body === undefined) return null
  return {
    id: raw.id,
    kind: 'question',
    worker,
    sessionId,
    question,
    body,
    options: options.map((o) => ({ label: o.label, description: o.description })),
    recommended: Number.isInteger(raw.recommended) && raw.recommended >= 1 && raw.recommended <= options.length ? raw.recommended : null,
    approval: raw.approval === true,
    case: null,
    level: 'B',
    createdAt: Number.isFinite(raw.created_at) ? raw.created_at * 1000 : 0
  }
}

export const PERMISSION_CHOICES = ['allow', 'deny', 'terminal']
const TOOL_NAME = /^[A-Za-z0-9_.:-]{1,200}$/

function parsePermission(raw, worker, sessionId) {
  if (worker !== 'orchestrator') return null
  const toolName = typeof raw.tool_name === 'string' && TOOL_NAME.test(raw.tool_name) ? raw.tool_name : null
  const input = raw.tool_input && typeof raw.tool_input === 'object' && !Array.isArray(raw.tool_input) ? raw.tool_input : null
  if (!toolName || !input || JSON.stringify(input).length > BODY_MAX) return null
  if (!Number.isFinite(raw.created_at) || !Number.isFinite(raw.expires_at)) return null
  const call = { name: toolName, input }
  const cwd = text(raw.cwd, 1000)
  return {
    id: raw.id,
    kind: 'permission',
    worker,
    sessionId,
    toolName,
    input,
    agentType: text(raw.agent_type, 100),
    risk: riskOf(call),
    dangerous: isDangerous(call),
    where: cwd ? whereOf(call, cwd, { cwd }) : '',
    cwd,
    case: null,
    level: 'B',
    createdAt: raw.created_at * 1000,
    expiresAt: raw.expires_at * 1000
  }
}

/** One ask file, with the hash of its bytes; null when it is gone, answered or not an ask. */
export async function readAsk(dir, id) {
  if (!ASK_ID.test(id ?? '')) return null
  let bytes
  try {
    bytes = await readFile(join(dir, `${id}.json`))
  } catch {
    return null
  }
  const answered = await readFile(join(dir, `${id}.answer.json`)).then(() => true, () => false)
  if (answered) return null
  let raw
  try {
    raw = JSON.parse(bytes.toString('utf8'))
  } catch {
    return null
  }
  const ask = parseAsk(raw)
  return ask && ask.id === id ? { ...ask, sha: sha256(bytes) } : null
}

/** Every open ask, oldest first. */
export async function readAsks(dir) {
  let names
  try {
    names = await readdir(dir)
  } catch {
    return []
  }
  const ids = names.filter((name) => name.endsWith('.json') && !name.endsWith('.answer.json')).map((name) => name.slice(0, -5))
  const asks = await Promise.all(ids.filter((id) => ASK_ID.test(id)).map((id) => readAsk(dir, id)))
  return asks.filter(Boolean).toSorted((a, b) => a.createdAt - b.createdAt || a.id.localeCompare(b.id))
}

/**
 * Whether a card may offer buttons: the session the ask names is the worker it names, as
 * `claude agents` lists it, and the ask holds nothing above level B.
 * @returns {{ ok: boolean, reason: string | null }}
 */
export function checkAsk(ask, sessions, now = Date.now()) {
  if (!SHOWABLE.has(ask.level)) return { ok: false, reason: 'level' }
  const session = sessions.find((candidate) => candidate.sessionId === ask.sessionId)
  if (ask.kind === 'permission') {
    if (ask.expiresAt <= now) return { ok: false, reason: 'expired' }
    return session?.name === 'orchestrator' ? { ok: true, reason: null } : { ok: false, reason: 'identity' }
  }
  if (ask.kind === 'question') {
    return session?.name === 'orchestrator' ? { ok: true, reason: null } : { ok: false, reason: 'identity' }
  }
  if (!session || session.name !== ask.worker || session.kind !== 'background') return { ok: false, reason: 'identity' }
  return { ok: true, reason: null }
}
