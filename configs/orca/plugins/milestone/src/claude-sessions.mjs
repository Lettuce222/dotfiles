// Reads Claude Code's task lists (~/.claude/tasks/<list-id>/<n>.json) and the session
// transcripts (~/.claude/projects/<project>/<session-id>.jsonl) they belong to.
//
// Adapted from andoshin11/orca-milestone src/claude-sessions.mjs (MIT, see ../LICENSE and
// ../NOTICE.md). Left out: reading a pending AskUserQuestion or permission call for the cards.
//
// A plain session names its list by its session id. A session that leads an agent team
// (`claude --teammate-mode`, which Orca's Agent Teams launch uses) names it after the team,
// `session-<first 8 hex of the session id>`.
import { createReadStream } from 'node:fs'
import { open, readdir, readFile, stat } from 'node:fs/promises'
import { createInterface } from 'node:readline'
import { join } from 'node:path'

const SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const TEAM_LIST_ID = /^session-([0-9a-f]{8})$/
// The first user prompt sits near the top; big transcripts are never read whole.
const TRANSCRIPT_HEAD_BYTES = 512 * 1024
const TRANSCRIPT_CHUNK_BYTES = 1024 * 1024
// The end of a turn is among the last lines of its transcript.
const TRANSCRIPT_TAIL_BYTES = 1024 * 1024

export function claudePaths(home) {
  return {
    tasksRoot: join(home, '.claude', 'tasks'),
    projectsRoot: join(home, '.claude', 'projects'),
    teamsRoot: join(home, '.claude', 'teams'),
    sessionsRoot: join(home, '.claude', 'sessions')
  }
}

export function isSessionId(name) {
  return SESSION_ID.test(name)
}

export function isTaskListId(name) {
  return SESSION_ID.test(name) || TEAM_LIST_ID.test(name)
}

function isRunning(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    // EPERM: the process exists but belongs to someone else.
    return error.code === 'EPERM'
  }
}

/**
 * Ids of the Claude sessions running now. Each running session keeps
 * ~/.claude/sessions/<pid>.json, removed when it exits; the pid is checked in case it crashed.
 */
export async function readRunningSessionIds(sessionsRoot) {
  let names
  try {
    names = await readdir(sessionsRoot)
  } catch {
    return new Set()
  }
  const ids = new Set()
  for (const name of names) {
    if (!/^\d+\.json$/.test(name)) continue
    const entry = await readJson(join(sessionsRoot, name))
    if (entry && isSessionId(entry.sessionId) && Number.isInteger(entry.pid) && isRunning(entry.pid)) {
      ids.add(entry.sessionId)
    }
  }
  return ids
}

/** Whether the session that owns a task list (by its id, or a team's id prefix) is running. */
export function isListRunning(listId, runningIds) {
  if (isSessionId(listId)) return runningIds.has(listId)
  const prefix = TEAM_LIST_ID.exec(listId)?.[1]
  return Boolean(prefix) && [...runningIds].some((id) => id.startsWith(`${prefix}-`))
}

async function readJson(path) {
  try {
    return JSON.parse(await readFile(path, 'utf8'))
  } catch {
    return null
  }
}

/** Tasks of one list, ordered by their numeric id. Unreadable files are skipped. */
export async function readTaskList(dir) {
  let names
  try {
    names = await readdir(dir)
  } catch {
    return []
  }
  const tasks = await Promise.all(
    names.filter((name) => name.endsWith('.json')).map((name) => readJson(join(dir, name)))
  )
  return tasks
    .filter((task) => task && typeof task.subject === 'string' && typeof task.status === 'string')
    .sort((a, b) => Number(a.id) - Number(b.id))
}

/** Task lists named by a session or a team that changed within maxAgeMs, newest first. */
export async function listRecentTaskLists(tasksRoot, { now = Date.now(), maxAgeMs }) {
  let entries
  try {
    entries = await readdir(tasksRoot, { withFileTypes: true })
  } catch {
    return []
  }
  const lists = await Promise.all(
    entries
      .filter((entry) => entry.isDirectory() && isTaskListId(entry.name))
      .map(async (entry) => {
        const dir = join(tasksRoot, entry.name)
        try {
          // Claude replaces task files by rename, which bumps the directory's mtime.
          const { mtimeMs } = await stat(dir)
          return { listId: entry.name, dir, updatedAt: mtimeMs }
        } catch {
          return null
        }
      })
  )
  return lists
    .filter((list) => list && now - list.updatedAt <= maxAgeMs)
    .sort((a, b) => b.updatedAt - a.updatedAt)
}

export async function findTranscript(projectsRoot, sessionId) {
  let projects
  try {
    projects = await readdir(projectsRoot, { withFileTypes: true })
  } catch {
    return null
  }
  for (const project of projects) {
    if (!project.isDirectory()) continue
    const path = join(projectsRoot, project.name, `${sessionId}.jsonl`)
    try {
      await stat(path)
      return path
    } catch {}
  }
  return null
}

async function findTranscriptByPrefix(projectsRoot, prefix) {
  let projects
  try {
    projects = await readdir(projectsRoot, { withFileTypes: true })
  } catch {
    return null
  }
  for (const project of projects) {
    if (!project.isDirectory()) continue
    let names
    try {
      names = await readdir(join(projectsRoot, project.name))
    } catch {
      continue
    }
    const name = names.find(
      (file) => file.startsWith(prefix) && file.endsWith('.jsonl') && isSessionId(file.slice(0, -'.jsonl'.length))
    )
    if (name) return join(projectsRoot, project.name, name)
  }
  return null
}

/** The transcript of the session that owns a task list, or null. */
export async function findListTranscript({ projectsRoot, teamsRoot }, listId) {
  if (isSessionId(listId)) return findTranscript(projectsRoot, listId)
  const prefix = TEAM_LIST_ID.exec(listId)?.[1]
  if (!prefix) return null
  // The team config names the lead session only while the team runs; afterwards only the
  // prefix in the list id is left to go on.
  const lead = (await readJson(join(teamsRoot, listId, 'config.json')))?.leadSessionId
  if (typeof lead === 'string' && isSessionId(lead) && lead.startsWith(prefix)) {
    const transcript = await findTranscript(projectsRoot, lead)
    if (transcript) return transcript
  }
  return findTranscriptByPrefix(projectsRoot, `${prefix}-`)
}

function promptText(message) {
  const content = message?.content
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    const text = content.find((part) => part?.type === 'text' && typeof part.text === 'string')
    return text?.text ?? null
  }
  return null
}

/** What the user typed in a transcript entry, or null for tool results, reminders and summaries. */
function userPrompt(entry) {
  if (entry.type !== 'user' || entry.isMeta || entry.isCompactSummary || entry.message?.role !== 'user') {
    return null
  }
  const prompt = promptText(entry.message)?.trim()
  // Command wrappers, caveats and system reminders start with a tag, interruptions with a bracket.
  if (!prompt || prompt.startsWith('<') || prompt.startsWith('[Request interrupted')) return null
  return prompt
}

function writtenGoal(task) {
  const goal = task.metadata?.goal
  return typeof goal === 'string' && goal.trim() ? goal.trim() : null
}

/**
 * The goal Claude wrote on its tasks (metadata.goal) and the tasks that belong to it. The newest
 * task with a goal names the current one; tasks of earlier goals are left out, while tasks
 * without a goal stay once they come after the current goal's first task. Without any goal,
 * every task is kept.
 */
export function currentGoal(tasks) {
  const last = tasks.findLast((task) => writtenGoal(task))
  if (!last) return { goal: null, tasks }
  const goal = writtenGoal(last)
  const first = tasks.findIndex((task) => writtenGoal(task) === goal)
  return {
    goal,
    tasks: tasks.filter((task, index) => {
      const written = writtenGoal(task)
      return written ? written === goal : index > first
    })
  }
}

/**
 * The task list as Claude left it, replayed from the TaskCreate and TaskUpdate calls in a
 * transcript. Claude deletes a list's files once every task is completed; this brings it back.
 */
export async function readTasksFromTranscript(path) {
  const created = new Map()
  const tasks = new Map()
  const lines = createInterface({ input: createReadStream(path), crlfDelay: Infinity })
  for await (const line of lines) {
    if (!line.includes('"Task')) continue
    let entry
    try {
      entry = JSON.parse(line)
    } catch {
      continue
    }
    const content = Array.isArray(entry.message?.content) ? entry.message.content : []
    if (entry.type === 'assistant') {
      for (const part of content) {
        if (part?.type !== 'tool_use') continue
        if (part.name === 'TaskCreate') created.set(part.id, part.input ?? {})
        if (part.name === 'TaskUpdate') {
          const { taskId, status, subject, description, activeForm, metadata } = part.input ?? {}
          const task = tasks.get(String(taskId))
          if (!task) continue
          if (status === 'deleted') {
            tasks.delete(task.id)
            continue
          }
          Object.assign(task, Object.fromEntries(
            Object.entries({ status, subject, description, activeForm }).filter(([, v]) => typeof v === 'string')
          ))
          if (metadata && typeof metadata === 'object') task.metadata = { ...task.metadata, ...metadata }
        }
      }
    } else if (entry.type === 'user' && entry.toolUseResult?.task?.id) {
      const result = content.find((part) => part?.type === 'tool_result' && created.has(part.tool_use_id))
      if (!result) continue
      const input = created.get(result.tool_use_id)
      const id = String(entry.toolUseResult.task.id)
      // Claude clears a list once all of it is completed, so new tasks start a new list.
      if ([...tasks.values()].every((task) => task.status === 'completed')) tasks.clear()
      tasks.set(id, {
        id,
        subject: input.subject ?? entry.toolUseResult.task.subject ?? '',
        description: input.description ?? '',
        ...(input.activeForm ? { activeForm: input.activeForm } : {}),
        status: 'pending',
        blocks: [],
        blockedBy: [],
        ...(input.metadata ? { metadata: input.metadata } : {})
      })
    }
  }
  return [...tasks.values()].sort((a, b) => Number(a.id) - Number(b.id))
}

/** Lines of a file from the last to the first, read in chunks from the end. */
async function* linesFromEnd(path) {
  const file = await open(path, 'r')
  try {
    let position = (await file.stat()).size
    let carry = Buffer.alloc(0)
    while (position > 0) {
      const size = Math.min(TRANSCRIPT_CHUNK_BYTES, position)
      position -= size
      const chunk = Buffer.alloc(size)
      await file.read(chunk, 0, size, position)
      const buffer = Buffer.concat([chunk, carry])
      // Split on bytes so a multi-byte character cut by the chunk edge is joined first.
      let end = buffer.length
      for (let i = buffer.length - 1; i >= 0; i -= 1) {
        if (buffer[i] !== 0x0a) continue
        if (i + 1 < end) yield buffer.subarray(i + 1, end).toString('utf8')
        end = i
      }
      carry = buffer.subarray(0, end)
    }
    if (carry.length > 0) yield carry.toString('utf8')
  } finally {
    await file.close()
  }
}

/**
 * The prompt the user sent last before Claude created the task titled `subject`, read from the
 * end of the transcript: the request a list of tasks was made for. Null when not found.
 */
export async function readPromptBeforeTask(path, subject) {
  let created = false
  for await (const line of linesFromEnd(path)) {
    if (!created && !line.includes('"TaskCreate"')) continue
    if (created && !line.includes('"user"')) continue
    let entry
    try {
      entry = JSON.parse(line)
    } catch {
      continue
    }
    if (!created) {
      const content = entry.type === 'assistant' ? entry.message?.content : null
      created = Array.isArray(content) && content.some(
        (part) => part?.type === 'tool_use' && part.name === 'TaskCreate' && part.input?.subject === subject
      )
      continue
    }
    const prompt = userPrompt(entry)
    if (prompt) return prompt
  }
  return null
}

/** The working directory, branch and first user prompt recorded at the top of a transcript. */
export async function readTranscriptHead(path) {
  let text
  const file = await open(path, 'r')
  try {
    const buffer = Buffer.alloc(TRANSCRIPT_HEAD_BYTES)
    const { bytesRead } = await file.read(buffer, 0, buffer.length, 0)
    text = buffer.subarray(0, bytesRead).toString('utf8')
  } finally {
    await file.close()
  }
  const head = { cwd: null, gitBranch: null, goal: null }
  for (const line of text.split('\n')) {
    let entry
    try {
      entry = JSON.parse(line)
    } catch {
      continue
    }
    head.cwd ??= typeof entry.cwd === 'string' ? entry.cwd : null
    head.gitBranch ??= typeof entry.gitBranch === 'string' ? entry.gitBranch : null
    head.goal ??= userPrompt(entry)
    if (head.cwd && head.goal) break
  }
  return head
}

/** The running Claude sessions with the folder each works in. */
export async function readRunningSessions(sessionsRoot) {
  let names
  try {
    names = await readdir(sessionsRoot)
  } catch {
    return []
  }
  const sessions = []
  for (const name of names) {
    if (!/^\d+\.json$/.test(name)) continue
    const entry = await readJson(join(sessionsRoot, name))
    if (entry && isSessionId(entry.sessionId) && Number.isInteger(entry.pid) && isRunning(entry.pid) && typeof entry.cwd === 'string') {
      sessions.push({ sessionId: entry.sessionId, cwd: entry.cwd, pid: entry.pid })
    }
  }
  return sessions
}

async function readTail(path) {
  const file = await open(path, 'r')
  try {
    const { size } = await file.stat()
    const length = Math.min(size, TRANSCRIPT_TAIL_BYTES)
    const buffer = Buffer.alloc(length)
    const { bytesRead } = await file.read(buffer, 0, length, size - length)
    return buffer.subarray(0, bytesRead).toString('utf8')
  } finally {
    await file.close()
  }
}

/**
 * Whether the last turn in a transcript is over: Claude Code writes `turn_duration` when a turn ends,
 * and a prompt or a tool result after it starts another; the summary of a compaction does not. Orca
 * keeps an agent "working" while shells it started in the background run, even when it waits for
 * the user.
 */
export function turnEnded(text) {
  for (const line of text.split('\n').toReversed()) {
    if (!line.includes('"type"')) continue
    let entry
    try {
      entry = JSON.parse(line)
    } catch {
      continue
    }
    // When it ended: Orca keeps the time the agent started working, which does not move while its
    // shells run, so this tells one turn from the next.
    if (entry.type === 'system' && entry.subtype === 'turn_duration') return Date.parse(entry.timestamp) || true
    // Compacting while idle writes the summary as a user entry, which no one typed.
    if (entry.type === 'user' && entry.isCompactSummary) continue
    if (entry.type === 'user' || entry.type === 'assistant') return null
  }
  return null
}

/**
 * Reads, for a workspace path, what `pick` finds in the transcript of the Claude session running
 * there. Null when none or more than one session there has one: another Claude in the same folder,
 * started outside Orca, could be the one asking.
 */
export function createPendingReader(home, pick) {
  const { projectsRoot, sessionsRoot } = claudePaths(home)
  return async function readPending(path) {
    const inside = (await readRunningSessions(sessionsRoot)).filter((entry) => entry.cwd === path || entry.cwd.startsWith(`${path}/`))
    const pending = []
    for (const { sessionId } of inside) {
      const transcript = await findTranscript(projectsRoot, sessionId)
      const found = transcript ? pick(await readTail(transcript).catch(() => '')) : null
      if (found) pending.push(found)
    }
    return pending.length === 1 ? pending[0] : null
  }
}
