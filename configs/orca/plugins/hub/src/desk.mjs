// What the desk does: the state it shows (gtd.py json and cases, with each item's worker and its
// asks from the panel's own view of the sessions), the writes (each one gtd.py command, --by user),
// opening files in Orca's editor and switching Orca's agent view to a worker. Also the two jobs the
// design gives the plugin's worker for hub v2:
// - the change log: an item saved from Orca's editor (no gtd.py line for it) gets a line in
//   <gtd>/.log/changes.jsonl, by user, and every change tells the open desks to read again;
// - the recorder: once a minute, `gtd.py record --quiet 600` commits what people changed, 10 minutes
//   after their last change (an agent's write commits at once, and first folds people's changes).
import { appendFile, readFile, realpath, stat } from 'node:fs/promises'
import { watch } from 'node:fs'
import { isAbsolute, join, normalize, relative, sep } from 'node:path'
import { deskOrchestratorCards, orchestratorAnswer, orchestratorResult, resignalResult, waitingCount } from './desk-asks.mjs'
import { ASK_ID } from './asks.mjs'
import { unassignedAgentItems } from './agent-items.mjs'
import { talkState } from '../desk/talk.mjs'
import { DeskError } from './desk-server.mjs'
import { EXIT_CONFLICT } from './gtd.mjs'

const ID = /^[a-z0-9][a-z0-9-]{0,63}$/
const SLUG = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
const LISTS = new Set(['inbox', 'next', 'planned', 'project', 'waiting', 'someday', 'reference', 'done'])
const SECTIONS = new Set(['TODO', 'Waiting', 'Later', '予定', '資料'])
const FROM_CASE_TO = new Set(['inbox', 'next', 'step', 'waiting', 'someday', 'reference', 'gcal', 'drop'])
const TITLE_MAX = 300
const DEBOUNCE_MS = 200
const RECORD_MS = 60_000
const QUIET_S = 600
// A save with no gtd.py line for its item this recently is an edit from Orca's editor.
const OWN_WRITE_MS = 5_000
// A reply to an item goes into this section of its body, next to 「あなたの番」 that gtd.py handback
// writes (and to 「メモ」 and 「メモへの返事」): one line, `MM/DD HH:MM: <text>`, by user, with gtd.py
// say, which also marks that the user waits for the orchestrator's answer (asked).
export const REPLY_SECTION = 'あなたの番への返事'
const REPLY_MAX = 2000
// The levels of information the desk may show, as on the panel (src/asks.mjs): Orca shows up to B.
const SHOWABLE_LEVELS = new Set(['B', 'C'])

function text(value, max = TITLE_MAX) {
  if (typeof value !== 'string') return null
  const trimmed = value.replace(/\s+/g, ' ').trim()
  return trimmed && trimmed.length <= max ? trimmed : null
}

function bad(message) {
  return new DeskError(400, message)
}

/** The answer a failed gtd.py call becomes: 409 for a conflict, 400 for a wrong value, else 404. */
function fromGtd(error) {
  if (error?.code === EXIT_CONFLICT) return new DeskError(409, error.message)
  if (error?.code === 2) return new DeskError(400, error.message)
  if (error?.code === 1) return new DeskError(404, error.message)
  return error
}

const ASK_MESSAGES = {
  pressed: 'もう答えを送っている',
  stale: '問いが変わった（読み直してください）',
  expired: '問いの期限が切れた',
  unverified: 'worker を確かめられなかった',
  busy: 'worker が動いていて渡せなかった',
  invalid: '答えの形が違う'
}

/**
 * @param gtd runs gtd.py (src/gtd.mjs)
 * @param snapshot () => ({ workers: [{ name, sessionId, kind, state, done, total, tasks, orcaPath }],
 *   asks: [{ id, sha, kind, worker, question, options, suggestions, recommended }], orchestrator:
 *   the orchestrator's cards as the panel shows them (src/desk-asks.mjs) })
 * @param openFile (absolutePath) => Promise<boolean>, in Orca's editor
 * @param focusWorker (worker summary) => Promise<{ focused, reason? }>
 * @param answerAsk ({ id, sha, choice, text?, confirmed? }) => Promise<{ ok, reason?, message? }>
 * @param resignalNow (askId) => Promise<{ ok, reason? }>: tells the orchestrator of a kept answer now
 * @param onReply (itemId) => void: the user replied to an item; the orchestrator is told of it
 */
export function createDesk({ gtd, hubRoot, snapshot, openFile, focusWorker, answerAsk, resignalNow = async () => ({ ok: false, reason: 'failed' }), onReply = () => {}, log = () => {}, watchDir = (dir, onChange) => watch(dir, { recursive: true }, onChange), now = Date.now, onChange = () => {} }) {
  const gtdRoot = join(hubRoot, 'gtd')
  const itemsDir = join(gtdRoot, 'items')
  const changes = join(gtdRoot, '.log', 'changes.jsonl')
  const casesDir = join(hubRoot, 'state', 'cases')
  let cache = null
  let reading = null
  let server = null
  let timer = null
  let recorder = null
  let recording = false
  const watchers = []
  const touched = new Set()

  async function read() {
    if (cache) return cache
    if (!reading) {
      reading = (async () => {
        const [items, cases] = await Promise.all([gtd(['json']), gtd(['cases']).catch((error) => {
          log(`desk: could not read the cases: ${error.message}`)
          return { cases: [], total: 0, done: 0 }
        })])
        cache = { items, cases }
        return cache
      })().finally(() => {
        reading = null
      })
    }
    return reading
  }

  function agentOf(item, workers) {
    if (!item.worker) return null
    const found = workers.get(item.worker)
    if (!found) return { name: item.worker, state: null, done: 0, total: 0, tasks: [], inOrca: false }
    return {
      name: found.name,
      state: found.state,
      done: found.done,
      total: found.total,
      step: found.step ?? null,
      tasks: (found.tasks ?? []).map((task) => ({ subject: task.subject, status: task.status })),
      inOrca: found.kind !== 'background' && Boolean(found.orcaPath)
    }
  }

  // A worker's ask that holds information above level B is asked at the orchestrator, as on the panel:
  // the desk shows neither its text nor its buttons.
  const showable = (ask) => SHOWABLE_LEVELS.has(ask.level ?? 'B')

  function askCards(asks, worker) {
    return asks
      .filter((ask) => ask.worker === worker && (ask.kind === 'decide' || ask.kind === 'next') && showable(ask))
      .map((ask) => ({
        id: ask.id,
        // The page sends it back, so that an answer is for the ask it showed.
        sha: ask.sha,
        kind: ask.kind,
        question: ask.kind === 'decide' ? ask.question : '次にどれを進めますか',
        recommended: ask.recommended ?? null,
        options: ask.kind === 'decide' ? ask.options.map(({ label, description }) => ({ label, description })) : (ask.suggestions ?? []).map(({ label, prompt }) => ({ label, description: prompt }))
      }))
  }

  async function state() {
    const { items, cases } = await read()
    const { workers: list = [], asks = [], orchestrator = [] } = snapshot() ?? {}
    const workers = new Map(list.filter((worker) => worker.name).map((worker) => [worker.name, worker]))
    const shown = items.items.map((item) => {
      const agent = agentOf(item, workers)
      const cards = item.worker && item.list !== 'done' ? askCards(asks, item.worker) : []
      let mine = item.mine
      if (item.list !== 'done') {
        if (cards.length || agent?.state === 'attention') mine = 'ask'
        else if (!mine && item.actor === 'agent' && agent?.state === 'done') mine = 'agent_done'
      }
      return { ...item, mine, agent, asks: cards, talk: talkState(item) }
    })
    // talk: the items with an answer of the orchestrator not read yet.
    const counts = { ...items.counts, mine: shown.filter((item) => item.mine).length, talk: shown.filter((item) => item.list !== 'done' && item.talk.unread).length }
    const live = shown.filter((item) => item.agent && item.list !== 'done')
    return {
      today: items.today,
      counts,
      migrate: { done: cases.done ?? 0, total: cases.total ?? 0 },
      agents: {
        working: live.filter((item) => item.agent.state === 'working').length,
        done: live.filter((item) => item.agent.state === 'done').length,
        attention: live.filter((item) => item.mine === 'ask').length
      },
      // The orchestrator's questions, approvals and permission dialogs: the top of あなたの番.
      orchestrator: deskOrchestratorCards(orchestrator),
      items: shown,
      cases: cases.cases ?? [],
      broken: items.broken ?? []
    }
  }

  async function write(args) {
    try {
      const result = await gtd([...args, '--by', 'user'])
      // The page reads the state again as soon as the write answers.
      cache = null
      changed()
      return result
    } catch (error) {
      throw fromGtd(error)
    }
  }

  function id(value) {
    if (typeof value !== 'string' || !ID.test(value)) throw bad('項目の id が違う')
    return value
  }

  function hash(value) {
    if (value === undefined || value === null) return []
    if (typeof value !== 'string' || !/^[0-9a-f]{16}$/.test(value)) throw bad('hash の形が違う')
    return [`--hash=${value}`]
  }

  async function itemOf(itemId) {
    const { items } = await read()
    const found = items.items.find((item) => item.id === itemId)
    if (!found) throw new DeskError(404, `項目が無い: ${itemId}`)
    return found
  }

  /** items/<id>.md, or a file under items/<id>/; null when the path leaves that folder. */
  function fileOf(itemId, path) {
    if (path === undefined || path === null || path === '') return join(itemsDir, `${itemId}.md`)
    if (typeof path !== 'string' || isAbsolute(path) || path.includes('\0')) return null
    const folder = join(itemsDir, itemId)
    const target = normalize(join(folder, path))
    const rel = relative(folder, target)
    if (!rel || rel.startsWith('..') || rel.split(sep).includes('..')) return null
    return target
  }

  const handlers = {
    state,
    async add(body) {
      const title = text(body.title)
      if (!title) throw bad(`1 行で ${TITLE_MAX} 字まで`)
      return write(['add', `--title=${title}`])
    },
    async move(body) {
      if (!LISTS.has(body.list)) throw bad('移す先が違う')
      return write(['move', id(body.id), body.list, ...hash(body.hash)])
    },
    async done(body) {
      return write(['done', id(body.id), ...hash(body.hash)])
    },
    // The user opened an item with an answer of the orchestrator not read yet: it is read now.
    async read(body) {
      const itemId = id(body.id)
      const { items } = await read()
      const item = items.items.find((candidate) => candidate.id === itemId)
      if (!item || !talkState(item).unread) return { changed: false }
      return write(['read', itemId])
    },
    // The user's reply to an item (what it asks in 「あなたの番」): a line of its body, and the
    // orchestrator is told that there is one, never what it says.
    async reply(body) {
      const itemId = id(body.id)
      if (typeof body.text !== 'string' || body.text.length > REPLY_MAX) throw bad(`返事は ${REPLY_MAX} 字まで`)
      const said = body.text.replace(/\s+/g, ' ').trim()
      if (!said) throw bad('返事が空')
      // --text=: gtd.py reads no flag out of the text, whatever it starts with.
      const result = await write(['say', itemId, `--text=${said}`])
      try {
        onReply(itemId)
      } catch (error) {
        log(`desk: could not tell the orchestrator of the reply to ${itemId}: ${error.message}`)
      }
      return result
    },
    async open(body) {
      const itemId = id(body.id)
      const target = fileOf(itemId, body.path)
      if (!target) throw bad('開けるのは項目と、その成果物だけ')
      const found = await stat(target).catch(() => null)
      if (!found?.isFile()) throw new DeskError(404, 'ファイルが無い')
      // A symbolic link may point outside the items: what it points at must be inside too.
      const real = await realpath(target)
      const items = await realpath(itemsDir)
      if (relative(items, real).startsWith('..') || isAbsolute(relative(items, real))) throw bad('開けるのは項目と、その成果物だけ')
      return { opened: await openFile(target) }
    },
    async focus(body) {
      const item = await itemOf(id(body.id))
      if (!item.worker) return { focused: false, reason: 'no-worker' }
      const worker = (snapshot()?.workers ?? []).find((candidate) => candidate.name === item.worker)
      if (!worker) return { focused: false, reason: 'no-session' }
      if (worker.kind === 'background' || !worker.orcaPath) return { focused: false, reason: 'not-in-orca' }
      return focusWorker(worker)
    },
    async 'from-case'(body) {
      if (typeof body.slug !== 'string' || !SLUG.test(body.slug)) throw bad('案件の名前が違う')
      if (!SECTIONS.has(body.section)) throw bad('節が違う')
      if (!Number.isInteger(body.index) || body.index < 0) throw bad('行の番号が違う')
      if (!FROM_CASE_TO.has(body.to)) throw bad('移す先が違う')
      if (typeof body.text !== 'string') throw bad('元の行の文が要る')
      const project = body.project === undefined || body.project === null ? [] : [`--project=${id(body.project)}`]
      // Values as --flag=value: a value that looks like a flag is never read as one.
      return write(['from-case', body.slug, body.section, String(body.index), body.to, `--text=${body.text}`, ...project])
    },
    async 'case-project'(body) {
      if (typeof body.slug !== 'string' || !SLUG.test(body.slug)) throw bad('案件の名前が違う')
      return write(['case-project', body.slug])
    },
    // A kept answer of the orchestrator's question: tell the orchestrator now.
    async resignal(body) {
      const kept = (snapshot()?.orchestrator ?? []).find((card) => card.kept && card.id === body?.askId)
      if (!ASK_ID.test(body?.askId ?? '') || !kept) throw new DeskError(409, 'もう窓口に知らせてある（読み直してください）')
      return resignalResult(await resignalNow(kept.id))
    },
    async answer(body) {
      // The orchestrator's card first: its question, approval or permission dialog, answered the
      // panel's way (the answer file, then a line that tells the orchestrator of it).
      const forOrchestrator = orchestratorAnswer(body, snapshot()?.orchestrator ?? [])
      if (forOrchestrator) return orchestratorResult(await answerAsk(forOrchestrator))
      if (!Number.isInteger(body.choice) || body.choice < 1) throw bad('答えの番号が違う')
      // A worker's question or its next steps.
      const ask = (snapshot()?.asks ?? []).find((candidate) => candidate.id === body.askId && (candidate.kind === 'decide' || candidate.kind === 'next') && showable(candidate))
      if (!ask) throw new DeskError(409, '問いが見つからない（もう答えたか、閉じた）')
      if (body.sha !== undefined && body.sha !== ask.sha) throw new DeskError(409, ASK_MESSAGES.stale)
      const result = await answerAsk({ id: ask.id, sha: ask.sha, choice: body.choice })
      if (!result?.ok) throw new DeskError(409, ASK_MESSAGES[result?.reason] ?? `答えを渡せなかった（${result?.reason ?? '不明'}）`)
      return {}
    }
  }

  /** Something changed: read again, tell the pages, and log saves made outside gtd.py. */
  function changed(file = null) {
    if (file) touched.add(file)
    clearTimeout(timer)
    timer = setTimeout(() => {
      cache = null
      const files = [...touched]
      touched.clear()
      void logEditorSaves(files).catch((error) => log(`desk: could not log a change: ${error.message}`))
      server?.notify()
      onChange()
    }, DEBOUNCE_MS)
  }

  async function logEditorSaves(files) {
    const ids = [...new Set(files.map((file) => /^items[/\\]([a-z0-9][a-z0-9-]*)\.md$/.exec(file)?.[1]).filter(Boolean))]
    if (!ids.length) return
    const tail = await readFile(changes, 'utf8').then((data) => data.slice(-8192), () => '')
    const recent = new Set()
    for (const line of tail.split('\n')) {
      try {
        const entry = JSON.parse(line)
        if (now() - Date.parse(entry.at) < OWN_WRITE_MS) recent.add(entry.id)
      } catch {
        // a cut first line
      }
    }
    const lines = ids.filter((itemId) => !recent.has(itemId)).map((itemId) => JSON.stringify({ at: new Date(now()).toISOString(), id: itemId, action: 'edit', by: 'user' }) + '\n')
    if (lines.length) await appendFile(changes, lines.join(''))
  }

  async function recordOnce() {
    if (recording) return
    recording = true
    try {
      const result = await gtd(['record', '--quiet', String(QUIET_S), '--by', 'user'])
      if (result?.committed) log('desk: the recorder committed what people changed')
    } catch (error) {
      log(`desk: the recorder failed: ${error.message}`)
    } finally {
      recording = false
    }
  }

  function start(deskServer) {
    server = deskServer
    for (const [dir, filter] of [
      [gtdRoot, (file) => file && !file.startsWith('.git') && !file.startsWith('.log') && !file.endsWith('.lock') && !file.endsWith('.tmp')],
      [casesDir, (file) => file && file.endsWith('.md')]
    ]) {
      try {
        watchers.push(watchDir(dir, (_event, file) => {
          const name = file ? String(file) : ''
          if (filter(name)) changed(dir === gtdRoot ? name : null)
        }))
      } catch (error) {
        log(`desk: cannot watch ${dir}: ${error.message}`)
      }
    }
    recorder = setInterval(() => void recordOnce(), RECORD_MS)
    recorder.unref?.()
  }

  function stop() {
    clearInterval(recorder)
    clearTimeout(timer)
    for (const watcher of watchers.splice(0)) watcher?.close?.()
  }

  /** What the panel and the status bar show: the counts, or null before the first read. */
  async function counts() {
    const shown = await state()
    // `orchestrator`: the orchestrator's cards that wait on the user (a permission lapses to the
    // terminal in a few minutes, so the status bar shows them first).
    // `agentItems`: the items in next by an agent with no worker, which the orchestrator is told of.
    return { ...shown.counts, migrate: shown.migrate, agents: shown.agents, orchestrator: waitingCount(snapshot()?.orchestrator ?? []), agentItems: unassignedAgentItems(shown.items) }
  }

  return { handlers, state, counts, start, stop, changed, recordOnce, fileOf }
}
