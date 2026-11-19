// What the panel does when a person presses a card or sends a line to a worker. This file holds
// every command the panel runs that changes something, so that the scan in test/main.test.mjs can
// hold it to a short list:
//   claude stop <id>                                        stop an idle worker so it can resume
//   claude --bg --resume <sessionId> --permission-mode auto <text>   hand the worker the text
//   python3 ~/.claude/hooks/asks.py answer <id> --by panel …        take the ask, once
//   python3 ~/.claude/skills/agents-orchestrator/scripts/cases.py log <case> <line>
// and it appends to <hub>/state/panel-log.jsonl. It never runs gh or git, never reaches the
// network and never writes an approval record: the text it sends is an instruction, and the
// worker's hooks still stop anything that needs an approval.
import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { appendFile, mkdir, unlink } from 'node:fs/promises'
import { join } from 'node:path'

// Sent before every text, so a worker never takes it for an approval.
export const PREFIX = 'パネルからの指示です（承認ではありません。承認が要る操作は今までどおり依頼してください）。'
export const TEXT_MAX = 2000
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f​-‏‪-‮⁦-⁩]/
const NOT_WORKERS = new Set(['orchestrator', 'chore-hub-watch'])
const STOP_WAIT_MS = 15_000
const STOP_POLL_MS = 500
const EXIT_TAKEN = 3

/** python3 for the hooks' scripts. Orca's PATH may lack the folders a shell adds. */
export function resolvePython(home, exists = existsSync) {
  const candidates = [
    join(home, '.local', 'share', 'mise', 'installs', 'python', 'latest', 'bin', 'python3'),
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    '/usr/bin/python3'
  ]
  return candidates.find((path) => exists(path)) ?? 'python3'
}

/** Runs a command without a shell; resolves { code, stdout, stderr } and never rejects on a nonzero exit. */
export function runCommand(file, args, { cwd, timeout = 30_000 } = {}) {
  return new Promise((resolve) => {
    execFile(file, args, { cwd, timeout, maxBuffer: 4 * 1024 * 1024 }, (error, stdout, stderr) => {
      const code = error ? (Number.isInteger(error.code) ? error.code : -1) : 0
      resolve({ code, stdout: String(stdout ?? ''), stderr: String(stderr ?? error?.message ?? '') })
    })
  })
}

/** A line a person wrote, checked; null when it is empty, too long or holds hidden characters. */
export function cleanText(value) {
  if (typeof value !== 'string') return null
  const trimmed = value.replace(/\r\n?/g, '\n').trim()
  if (!trimmed || trimmed.length > TEXT_MAX || CONTROL.test(trimmed)) return null
  return trimmed
}

export function withPrefix(body) {
  return `${PREFIX}\n${body}`
}

/** The text a pressed card sends: the chosen option of a question, or the prompt of a next step. */
export function answerText(ask, choice) {
  if (ask.kind === 'decide') {
    const picked = ask.options[choice - 1]
    if (!picked) return null
    return `要判断「${ask.question}」への答え: ${choice}. ${picked.label}: ${picked.description}`
  }
  if (ask.kind === 'next') return ask.suggestions[choice - 1]?.prompt ?? null
  return null
}

/** The text a written answer sends: the question it answers, then what the person wrote. */
export function writtenAnswerText(ask, text) {
  return `要判断「${ask.question}」への答え（選択肢ではなく、ユーザーが書いた答え）: ${text}`
}

/**
 * Why a session cannot take text from the panel now, or null when it can. Only background
 * workers do: the orchestrator and the watcher are spoken to in their own windows.
 */
export function refusal(session, job) {
  if (!session) return 'gone'
  if (session.kind !== 'background' || !session.name || NOT_WORKERS.has(session.name)) return 'not-worker'
  if (session.status === 'busy' || session.state === 'working') return 'busy'
  if (job && job.inFlight > 0) return 'busy'
  if (session.alive && !session.id) return 'busy'
  return null
}

/**
 * @param deps { home, hubRoot, claudeCli, python, readSessions, readJob, run, sleep, now }
 *   readSessions resolves the entries of `claude agents --json --all` (parseAgents)
 */
export function createDelivery({ home, hubRoot, claudeCli, python, readSessions, readJob, run = runCommand, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), now = Date.now }) {
  const asksScript = join(home, '.claude', 'hooks', 'asks.py')
  const casesScript = join(home, '.claude', 'skills', 'agents-orchestrator', 'scripts', 'cases.py')
  const logFile = join(hubRoot, 'state', 'panel-log.jsonl')

  async function sessionOf(sessionId) {
    const sessions = await readSessions()
    const session = sessions.find((candidate) => candidate.sessionId === sessionId) ?? null
    const job = session?.id ? await readJob(session.id) : null
    return { session, job }
  }

  /** Whether the session could take text now: { ok, reason }. */
  async function check(sessionId) {
    const { session, job } = await sessionOf(sessionId)
    const reason = refusal(session, job)
    return { ok: reason === null, reason, session }
  }

  /** Stops an idle worker that still runs, then waits until `claude agents` no longer lists it running. */
  async function stopIfRunning(session) {
    if (!session.alive) return true
    const stopped = await run(claudeCli, ['stop', session.id])
    if (stopped.code !== 0) return false
    const until = now() + STOP_WAIT_MS
    while (now() < until) {
      await sleep(STOP_POLL_MS)
      const { session: again } = await sessionOf(session.sessionId)
      if (!again?.alive) return true
    }
    return false
  }

  /** Hands a worker the text: resumes it in the background with the text as its next prompt. */
  async function send(sessionId, body) {
    const { ok, reason, session } = await check(sessionId)
    if (!ok) return { sent: false, reason }
    if (!(await stopIfRunning(session))) return { sent: false, reason: 'stop-failed' }
    const resumed = await run(claudeCli, ['--bg', '--resume', sessionId, '--permission-mode', 'auto', withPrefix(body)], { cwd: session.cwd ?? undefined })
    return resumed.code === 0 ? { sent: true, reason: null } : { sent: false, reason: 'resume-failed', detail: resumed.stderr.slice(0, 300) }
  }

  /** Takes an ask through asks.py, so the panel and the orchestrator never both answer it. */
  async function take(ask, choice) {
    const taken = await run(python, [asksScript, 'answer', ask.id, '--by', 'panel', '--choice', String(choice), '--shown', ask.sha])
    if (taken.code === 0) return 'taken'
    return taken.code === EXIT_TAKEN ? 'answered' : 'stale'
  }

  /** Gives an ask back when the text could not be sent, so its card shows again. */
  async function release(asksDir, ask) {
    await unlink(join(asksDir, `${ask.id}.answer.json`)).catch(() => {})
  }

  async function log(entry) {
    try {
      await mkdir(join(hubRoot, 'state'), { recursive: true })
      await appendFile(logFile, `${JSON.stringify({ at: new Date(now()).toISOString(), ...entry })}\n`)
    } catch {
      // The history is a convenience; a failed write must not undo what was sent.
    }
  }

  async function logCase(caseName, line) {
    if (!caseName) return
    await run(python, [casesScript, 'log', caseName, line])
  }

  return { check, send, take, release, log, logCase }
}
