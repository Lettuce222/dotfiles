// Reads every Claude Code session this computer runs: `claude agents --json --all` lists the
// background sessions (`claude --bg`, finished ones included) and the interactive ones, and each
// background session keeps its state in ~/.claude/jobs/<id>/state.json (what it is doing, what it
// needs from the user). Read only: `agents --json` is the one command run.
import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

const JOB_ID = /^[0-9a-f]{8}$/

/**
 * The claude CLI. Orca starts the plugin worker from the app, whose PATH may lack the folders
 * a shell adds, so the usual install places are tried before `claude` on PATH.
 */
export function resolveClaudeCli(home, exists = existsSync) {
  const candidates = [
    join(home, '.local', 'bin', 'claude'),
    join(home, '.claude', 'local', 'claude'),
    '/opt/homebrew/bin/claude',
    '/usr/local/bin/claude'
  ]
  return candidates.find((path) => exists(path)) ?? 'claude'
}

export function runClaude(cli, args, timeout = 15_000) {
  return new Promise((resolve, reject) => {
    execFile(cli, args, { timeout, maxBuffer: 16 * 1024 * 1024 }, (error, stdout) => {
      if (error) {
        reject(error)
        return
      }
      try {
        resolve(JSON.parse(stdout))
      } catch (parseError) {
        reject(parseError)
      }
    })
  })
}

function text(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

/** The entries of `claude agents --json --all` with the fields the panel uses; malformed ones are skipped. */
export function parseAgents(list) {
  if (!Array.isArray(list)) return []
  return list
    .filter((entry) => entry && typeof entry === 'object' && text(entry.sessionId))
    .map((entry) => ({
      sessionId: entry.sessionId,
      id: JOB_ID.test(entry.id ?? '') ? entry.id : null,
      name: text(entry.name),
      kind: entry.kind === 'background' ? 'background' : 'interactive',
      cwd: text(entry.cwd),
      state: text(entry.state),
      status: text(entry.status),
      waitingFor: text(entry.waitingFor),
      alive: Number.isInteger(entry.pid),
      startedAt: Number.isFinite(entry.startedAt) ? entry.startedAt : 0
    }))
}

export async function readAgents(cli, run = runClaude) {
  return parseAgents(await run(cli, ['agents', '--json', '--all']))
}

/**
 * What a background session says about itself, or null when its state file cannot be read.
 * The file is Claude Code's own, so any field may be missing.
 */
export async function readJobState(home, id) {
  if (!JOB_ID.test(id ?? '')) return null
  let data
  try {
    data = JSON.parse(await readFile(join(home, '.claude', 'jobs', id, 'state.json'), 'utf8'))
  } catch {
    return null
  }
  if (!data || typeof data !== 'object') return null
  return {
    state: text(data.state),
    detail: text(data.detail),
    needs: text(data.needs),
    intent: text(data.intent),
    inFlight: Number.isInteger(data.inFlight?.tasks) ? data.inFlight.tasks : 0,
    updatedAt: Date.parse(data.updatedAt) || 0
  }
}
