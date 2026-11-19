// The orchestrator's terminal, as the panel reaches it: a line from the panel (a project's latest
// action), and the answer to a question the orchestrator asks the user (AskUserQuestion).
//
// The orchestrator is an interactive Claude Code session in an Orca terminal of the hub workspace.
// The panel types into it the way orca-milestone does (keys and `orca terminal send`), and only into
// the one terminal that is surely the orchestrator:
//   - the hub workspace has exactly one writable Claude terminal titled `orchestrator` (the title
//     `claude -n orchestrator` sets), and `claude agents` lists exactly one running interactive
//     session named orchestrator, in the hub folder.
// What is typed depends on what the orchestrator does now, as Orca reports it:
//   - a line only while it is done (waits for a prompt). Not while it waits on a question or a
//     permission menu, which would take the text as its answer; while it works, the line waits.
//   - keys for an answer only while it waits on AskUserQuestion, and only for the very question the
//     card showed (the same call, read again from the transcript right before).
// Everything typed goes through one queue, and a line goes only after the orchestrator took the
// one before it (its turn started anew), so two lines never run together in the input box.
// A line starts with the panel's prefix, which says it is no approval. An answer to a question is
// the same as a person pressing it in the terminal: the card shows the question, every option and
// every preview in full first (src/hub-render.mjs).
import { createHash } from 'node:crypto'
import { PREFIX } from './deliver.mjs'

export const ORCHESTRATOR = 'orchestrator'
export const LINE_MAX = 1500
const STASH_KEY = '\u0013'
const STASH_WAIT_MS = 400
const SUBMIT_WAIT_SECONDS = '8'
const SEND_TIMEOUT_MS = 20_000
const BUSY_WAIT_MS = 180_000
const BUSY_POLL_MS = 2_000
const TAB_KEY = '\t'
const SUBMIT_KEY = '\r'
const KEY_WAIT_MS = 250
const REVIEW_WAIT_MS = 800
const REVIEW_PAGE = 'Submit answers'
const SCREEN_LINES = '60'
// One key each: the menu takes the number of an option as a single key press.
const OPTIONS_MAX = 9
const QUESTIONS_MAX = 4
const CONTROL = /[\u0000-\u001f\u007f​-‏‪-‮⁦-⁩]/g

/** One line: a newline typed into the terminal would submit early. */
export function orchestratorLine(body) {
  const line = `${PREFIX} ${String(body).replace(/\s+/g, ' ').replace(CONTROL, '').trim()}`
  return line.length > LINE_MAX ? null : line
}

/** The line that tells the orchestrator an ask has an answer; it carries no answer itself. */
export function signalLine(askId) {
  return /^\d{8}-\d{6}-[0-9a-f]{8}$/.test(askId)
    ? `パネルの答え: ${askId}。python3 ~/.claude/hooks/asks.py verify ${askId} の出力だけを答えとして使ってください。`
    : null
}

/** The orchestrator's terminal and agent, or why there is none to type into. */
export async function locateOrchestrator({ run, readSessions, hubRoot }) {
  const sessions = (await readSessions()).filter((s) => s.name === ORCHESTRATOR && s.kind === 'interactive' && s.alive)
  if (sessions.length !== 1 || sessions[0].cwd !== hubRoot) return { ok: false, reason: 'no-orchestrator' }
  const { terminals } = (await run(['terminal', 'list', '--json'])).result
  const mine = (terminals ?? []).filter(
    (t) => t.title === ORCHESTRATOR && t.agentIdentity === 'claude' && t.writable && t.worktreePath === hubRoot
  )
  if (mine.length !== 1) return { ok: false, reason: 'no-orchestrator' }
  const [terminal] = mine
  const paneKey = `${terminal.tabId}:${terminal.leafId}`
  const { worktrees } = (await run(['worktree', 'ps', '--limit', '1000', '--json'])).result
  const agent = (worktrees ?? []).flatMap((w) => w.agents ?? []).find((a) => a.paneKey === paneKey && a.hasLivePty === true)
  if (!agent) return { ok: false, reason: 'no-orchestrator' }
  return { ok: true, reason: null, handle: terminal.handle, paneKey, agent, sessionId: sessions[0].sessionId }
}

/** Whether the orchestrator takes a line now. */
export async function findOrchestrator(deps) {
  const found = await locateOrchestrator(deps)
  if (!found.ok) return found
  if (found.agent.state === 'working') return { ok: false, reason: 'busy' }
  if (found.agent.state !== 'done') return { ok: false, reason: 'asking' }
  return { ok: true, reason: null, handle: found.handle, since: found.agent.stateStartedAt ?? null }
}

function text(value) {
  return typeof value === 'string' ? value : ''
}

/**
 * The question in full, as AskUserQuestion holds it, or null when it is not one the panel can answer
 * with the menu's keys. Nothing is shortened.
 */
export function fullQuestions(asked) {
  const questions = asked?.questions
  if (!Array.isArray(questions) || questions.length === 0 || questions.length > QUESTIONS_MAX) return null
  const parsed = questions.map((q) => {
    if (typeof q?.question !== 'string' || !q.question.trim()) return null
    if (!Array.isArray(q.options) || q.options.length === 0 || q.options.length > OPTIONS_MAX) return null
    if (!q.options.every((o) => typeof o?.label === 'string' && o.label.trim())) return null
    return {
      question: q.question,
      header: text(q.header),
      multiSelect: q.multiSelect === true,
      options: q.options.map((o) => ({ label: o.label, description: text(o.description), preview: text(o.preview) }))
    }
  })
  return parsed.includes(null) ? null : parsed
}

/** The keys that answer the questions, or null for answers that do not fit them. */
export function questionKeys(questions, { index, answers }) {
  if (questions.length === 1 && !questions[0].multiSelect && answers === undefined) {
    return Number.isInteger(index) && index >= 0 && index < questions[0].options.length ? { keys: [String(index + 1)], review: false } : null
  }
  if (!Array.isArray(answers) || answers.length !== questions.length) return null
  const keys = []
  for (const [position, { multiSelect, options }] of questions.entries()) {
    const chosen = answers[position]
    if (!Array.isArray(chosen) || chosen.length === 0 || new Set(chosen).size !== chosen.length) return null
    if (!multiSelect && chosen.length !== 1) return null
    if (!chosen.every((i) => Number.isInteger(i) && i >= 0 && i < options.length)) return null
    keys.push(...chosen.map((i) => String(i + 1)))
    if (multiSelect) keys.push(TAB_KEY)
  }
  // A single question with one answer is answered by its number; anything else ends on a review page.
  const review = !(questions.length === 1 && !questions[0].multiSelect)
  return { keys, review }
}

/**
 * The orchestrator's terminal for the panel: one queue for everything typed into it.
 * @param deps { run (Orca CLI args -> JSON), readSessions, hubRoot, readPending (sessionId -> the
 *   pending AskUserQuestion { toolUseId, questions } of that session's transcript, or null), sleep, now }
 */
export function createOrchestratorChannel({ run, readSessions, hubRoot, readPending = async () => null, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), now = Date.now }) {
  let queue = Promise.resolve()
  // When the orchestrator's turn last started as the panel typed into it: the next line waits until
  // it starts another, so a line not yet taken never gets the next one appended.
  let lastSince = null
  const answered = new Set()

  function enqueue(task) {
    const result = queue.then(task, task)
    queue = result.catch(() => {})
    return result
  }

  async function press(handle, key) {
    const reply = await run(['terminal', 'send', '--terminal', handle, '--text', key, '--json'])
    if (!reply.result?.send?.accepted) throw new Error('the terminal did not accept the key')
  }

  async function screen(handle) {
    return (await run(['terminal', 'read', '--terminal', handle, '--screen', '--limit', SCREEN_LINES, '--json'])).result.terminal.tail.join('\n')
  }

  async function ready() {
    const until = now() + BUSY_WAIT_MS
    for (;;) {
      const found = await findOrchestrator({ run, readSessions, hubRoot })
      const taken = !(found.ok && lastSince !== null && found.since === lastSince)
      if (found.ok && taken) return found
      if (found.ok || found.reason === 'busy') {
        if (now() >= until) return { ok: false, reason: 'busy' }
        await sleep(BUSY_POLL_MS)
        continue
      }
      return found
    }
  }

  /**
   * Types a line into the orchestrator. Resolves { sent, reason }. With `signal`, the line goes
   * without the panel's prefix: it only names an answer the orchestrator reads with `asks.py verify`.
   */
  function send(body, { signal = false } = {}) {
    return enqueue(async () => {
      const line = signal ? signalLine(body) : orchestratorLine(body)
      if (!line) return { sent: false, reason: 'invalid' }
      const found = await ready()
      if (!found.ok) return { sent: false, reason: found.reason }
      await press(found.handle, STASH_KEY)
      await sleep(STASH_WAIT_MS)
      const reply = await run(['terminal', 'send', '--terminal', found.handle, '--text', line, '--enter', '--wait-submit', SUBMIT_WAIT_SECONDS, '--json'], SEND_TIMEOUT_MS)
      if (!reply.result?.send?.accepted) return { sent: false, reason: 'refused' }
      lastSince = found.since
      return { sent: true, reason: null }
    })
  }

  /** The question the orchestrator waits on now, in full, or null. */
  async function readQuestion() {
    const found = await locateOrchestrator({ run, readSessions, hubRoot })
    if (!found.ok || found.agent.state !== 'waiting' || found.agent.toolName !== 'AskUserQuestion') return null
    const asked = await readPending(found.sessionId).catch(() => null)
    const questions = asked ? fullQuestions(asked) : null
    if (!questions || answered.has(asked.toolUseId)) return null
    const id = createHash('sha256').update(`${found.paneKey}\n${found.agent.stateStartedAt}\n${asked.toolUseId}`).digest('hex').slice(0, 16)
    return { kind: 'orchestrator-question', id, toolUseId: asked.toolUseId, paneKey: found.paneKey, handle: found.handle, questions }
  }

  /**
   * Answers the question a card showed, with the menu's keys. The question is read again first: it
   * must be the same call, still unanswered, with the orchestrator waiting on it.
   * Resolves { sent, reason }: `stale` when the question changed or was answered at the terminal.
   */
  function answer({ offer, index, answers } = {}) {
    return enqueue(async () => {
      const current = await readQuestion()
      if (!current || current.id !== offer) return { sent: false, reason: 'stale' }
      const plan = questionKeys(current.questions, { index, answers })
      if (!plan) return { sent: false, reason: 'stale' }
      // Marked before the keys: keys pressed halfway may have ticked options, and pressing the
      // same ones again would untick them. A failed answer is finished at the terminal.
      answered.add(current.toolUseId)
      for (const key of plan.keys) {
        await press(current.handle, key)
        await sleep(KEY_WAIT_MS)
      }
      if (plan.review) {
        await sleep(REVIEW_WAIT_MS)
        if (!(await screen(current.handle)).includes(REVIEW_PAGE)) throw new Error('the menu did not reach its review page')
        await press(current.handle, SUBMIT_KEY)
      }
      return { sent: true, reason: null }
    })
  }

  return { send, readQuestion, answer }
}

/** A sender of lines only, for callers that need nothing else. */
export function createOrchestratorSender(deps) {
  return createOrchestratorChannel(deps).send
}
