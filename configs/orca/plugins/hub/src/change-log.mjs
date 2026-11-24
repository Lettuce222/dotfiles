// The Hub reads gtd's change log (<gtd>/.log/changes.jsonl: one line per write, from gtd.py and from
// the desk's own edit lines) for what the user did from any screen: the desk, lazygtd or gtd.py typed
// by hand. All of them write with gtd.py --by user, so the log is the one place to see them.
//
// - Only the lines added after the reader starts are read: what was there before was the user's
//   past, told or not then.
// - A log that grew shorter (rewritten or cut) is read again from its start.
// - A line not ended yet is read the next time, whole.
import { open, stat } from 'node:fs/promises'

const ID = /^[a-z0-9][a-z0-9-]{0,63}$/
// The most read at once: a log that grew by more is read from its last part only.
const READ_MAX = 1 << 20

/** What the user did in the entries: the items replied to (say) and the items added (add). */
export function userChanges(entries) {
  const replies = []
  const added = []
  for (const entry of Array.isArray(entries) ? entries : []) {
    if (entry?.by !== 'user' || !ID.test(entry.id ?? '')) continue
    if (entry.action === 'say' && !replies.includes(entry.id)) replies.push(entry.id)
    if (entry.action === 'add' && !added.includes(entry.id)) added.push(entry.id)
  }
  return { replies, added }
}

/** The entries of complete lines of text (each ended by a newline). */
export function parseLines(text) {
  const entries = []
  for (const line of String(text).split('\n')) {
    if (!line.trim()) continue
    try {
      entries.push(JSON.parse(line))
    } catch {
      // a line cut by a read that started in its middle, or not JSON
    }
  }
  return entries
}

/**
 * @param path the change log
 * @param deps { statFile, readRange: (path, start, length) => Promise<Buffer> } for tests
 */
export function createChangeLogReader(path, { statFile = (file) => stat(file), readRange = readFileRange } = {}) {
  let offset = null
  let reading = null

  const sizeOf = () => statFile(path).then((found) => found.size, () => 0)

  /** Starts at the end of the log as it is now. */
  async function start() {
    offset = await sizeOf()
  }

  /** The entries added since the last read, one read at a time. */
  function readNew() {
    const next = (reading ?? Promise.resolve()).catch(() => {}).then(async () => {
      if (offset === null) await start()
      const size = await sizeOf()
      if (size < offset) offset = 0
      if (size === offset) return []
      const from = Math.max(offset, size - READ_MAX)
      const bytes = await readRange(path, from, size - from)
      // Up to the last newline: a line not ended yet is read next time, whole.
      const end = bytes.lastIndexOf(0x0a)
      if (end < 0) return []
      offset = from + end + 1
      return parseLines(bytes.subarray(0, end).toString('utf8'))
    })
    reading = next
    return next
  }

  return { start, readNew }
}

async function readFileRange(path, start, length) {
  const file = await open(path, 'r')
  try {
    const buffer = Buffer.alloc(length)
    const { bytesRead } = await file.read(buffer, 0, length, start)
    return buffer.subarray(0, bytesRead)
  } finally {
    await file.close()
  }
}
