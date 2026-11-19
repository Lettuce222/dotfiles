// Reads the orchestrator's cases (<hub>/state/cases/*.md) as projects, through the script that owns
// their format: `cases.py json` of the agents-orchestrator skill. Read only: it is the one command run.
import { execFile } from 'node:child_process'
import { join } from 'node:path'

const SLUG = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
const DATE = /^\d{4}-\d{2}-\d{2}$/
const WORKER = /^[A-Za-z0-9][A-Za-z0-9._-]*$/

export function casesScriptOf(home) {
  return join(home, '.claude', 'skills', 'agents-orchestrator', 'scripts', 'cases.py')
}

export function runCases(python, script, env, timeout = 15_000) {
  return new Promise((resolve, reject) => {
    execFile(python, [script, 'json'], { timeout, maxBuffer: 8 * 1024 * 1024, env: { ...process.env, ...env } }, (error, stdout) => {
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

/** The projects of `cases.py json`, with the fields the panel uses; malformed entries are skipped. */
export function parseCases(data) {
  if (!data || !Array.isArray(data.cases)) return []
  return data.cases
    .filter((entry) => entry && SLUG.test(entry.slug ?? ''))
    .map((entry) => ({
      slug: entry.slug,
      title: text(entry.title) ?? entry.slug,
      short: text(entry.short) ?? entry.slug,
      path: text(entry.path),
      todo: (Array.isArray(entry.todo) ? entry.todo : [])
        .filter((item) => text(item?.text))
        .map((item) => ({
          text: item.text.trim(),
          due: DATE.test(item.due ?? '') ? item.due : null,
          bang: item.bang === true,
          overdue: item.overdue === true,
          today: item.today === true
        })),
      waiting: (Array.isArray(entry.waiting) ? entry.waiting : [])
        .filter((item) => text(item?.text))
        .map((item) => ({ text: item.text.trim(), next: text(item.next) })),
      later: Number.isInteger(entry.later) ? entry.later : 0,
      workers: (Array.isArray(entry.workers) ? entry.workers : []).filter((name) => typeof name === 'string' && WORKER.test(name))
    }))
}

export async function readCases(python, script, env = {}, run = runCases) {
  return parseCases(await run(python, script, env))
}
