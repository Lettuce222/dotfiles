// Hands the orchestrator a line from the panel: what the user wants done about a project's latest
// action. The orchestrator is an interactive Claude Code session in an Orca terminal of the hub
// workspace, so the line is typed there the way orca-milestone sends a next step (stash the draft,
// then `orca terminal send --enter --wait-submit`).
//
// It is typed only into the one terminal that is surely the orchestrator, and only while the
// orchestrator waits for a prompt:
//   - the hub workspace has exactly one writable Claude terminal titled `orchestrator` (the title
//     `claude -n orchestrator` sets), and `claude agents` lists exactly one running interactive
//     session named orchestrator, in the hub folder;
//   - Orca says that agent is done (its turn is over). Not waiting: a question or a permission menu
//     would take the typed text as its answer. While it works, this waits for it, up to a bound.
// Every line starts with the panel's prefix, which says it is no approval: the orchestrator still
// asks the user (AskUserQuestion) and writes the record for anything that needs one.
import { PREFIX } from './deliver.mjs'

export const ORCHESTRATOR = 'orchestrator'
export const LINE_MAX = 1500
const STASH_KEY = '\u0013'
const STASH_WAIT_MS = 400
const SUBMIT_WAIT_SECONDS = '8'
const SEND_TIMEOUT_MS = 20_000
const BUSY_WAIT_MS = 180_000
const BUSY_POLL_MS = 2_000
const CONTROL = /[\u0000-\u001f\u007f​-‏‪-‮⁦-⁩]/g

/** One line: a newline typed into the terminal would submit early. */
export function orchestratorLine(body) {
  const line = `${PREFIX} ${String(body).replace(/\s+/g, ' ').replace(CONTROL, '').trim()}`
  return line.length > LINE_MAX ? null : line
}

/**
 * Where the orchestrator is, and whether it takes a line now.
 * @returns {{ ok: boolean, reason: string | null, handle?: string }}
 */
export async function findOrchestrator({ run, readSessions, hubRoot }) {
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
  if (agent.state === 'working') return { ok: false, reason: 'busy' }
  if (agent.state !== 'done') return { ok: false, reason: 'asking' }
  return { ok: true, reason: null, handle: terminal.handle }
}

/**
 * @param deps { run (Orca CLI args -> JSON), readSessions, hubRoot, sleep, now }
 * @returns resolves { sent, reason }
 */
export function createOrchestratorSender({ run, readSessions, hubRoot, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), now = Date.now }) {
  async function press(handle, key) {
    const reply = await run(['terminal', 'send', '--terminal', handle, '--text', key, '--json'])
    if (!reply.result?.send?.accepted) throw new Error('the terminal did not accept the key')
  }

  return async function send(body) {
    const line = orchestratorLine(body)
    if (!line) return { sent: false, reason: 'invalid' }
    const until = now() + BUSY_WAIT_MS
    let found = await findOrchestrator({ run, readSessions, hubRoot })
    while (found.reason === 'busy' && now() < until) {
      await sleep(BUSY_POLL_MS)
      found = await findOrchestrator({ run, readSessions, hubRoot })
    }
    if (!found.ok) return { sent: false, reason: found.reason }
    await press(found.handle, STASH_KEY)
    await sleep(STASH_WAIT_MS)
    const reply = await run(['terminal', 'send', '--terminal', found.handle, '--text', line, '--enter', '--wait-submit', SUBMIT_WAIT_SECONDS, '--json'], SEND_TIMEOUT_MS)
    if (!reply.result?.send?.accepted) return { sent: false, reason: 'refused' }
    return { sent: true, reason: null }
  }
}
