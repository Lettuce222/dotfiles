// Runs gtd.py, the script that owns the format of hub v2's items (<hub>/gtd/items/<id>.md), from the
// agents-orchestrator skill. The desk never writes an item itself: every write is one gtd.py command
// with --by user, so the desk, the editor and the agents all go through the same checks and history.
import { execFile } from 'node:child_process'
import { join } from 'node:path'

export const EXIT_CONFLICT = 3

export function gtdScriptOf(home) {
  return join(home, '.claude', 'skills', 'agents-orchestrator', 'scripts', 'gtd.py')
}

export class GtdError extends Error {
  constructor(message, code) {
    super(message)
    this.code = code
  }
}

/**
 * Runs `gtd.py <args>` and resolves its JSON output. A nonzero exit rejects with a GtdError whose
 * message is gtd.py's one line to the person (the part after `gtd.py <command>: `) and whose code
 * is the exit code (3 for a conflict).
 */
export function createGtd({ python, script, env = {}, timeout = 20_000, exec = execFile }) {
  return function run(args) {
    return new Promise((resolve, reject) => {
      exec(python, [script, ...args], { timeout, maxBuffer: 16 * 1024 * 1024, env: { ...process.env, ...env } }, (error, stdout, stderr) => {
        if (error) {
          const code = Number.isInteger(error.code) ? error.code : -1
          const line = String(stderr ?? '').trim().split('\n').pop() || error.message
          reject(new GtdError(line.replace(/^gtd\.py [\w-]+: /, ''), code))
          return
        }
        const text = String(stdout ?? '').trim()
        if (!text) {
          resolve({})
          return
        }
        try {
          // Commands that print one JSON line per entry (sweep) give the last one.
          resolve(JSON.parse(text.split('\n').pop()))
        } catch (parseError) {
          reject(new GtdError(`gtd.py の出力を読めない: ${parseError.message}`, -1))
        }
      })
    })
  }
}
