// Keeps the Hub panel in step with every Claude Code session (`claude agents`), their task lists and
// the agents Orca runs. The worker renders the body of the panel and posts it; the panel patches its
// DOM, so an update keeps the frame, the scroll position and a row's expansion.
//
// Adapted from andoshin11/orca-milestone src/milestone-worker.mjs (MIT, see ../LICENSE and
// ../NOTICE.md). Left out: Codex progress, answers to questions and permissions, "allow the rest
// of this turn", restarting a session. Added: the sessions of `claude agents`, background ones
// included, and the cards of the asks workers write (src/asks.mjs), whose answers reach the worker
// through src/deliver.mjs. And the orchestrator's permission dialogs, which approval-gate.py writes
// as asks while it waits: a card answers one in place of the dialog (answerPermission).
import { watch } from 'node:fs'
import { mkdir, stat } from 'node:fs/promises'
import { join, relative, resolve } from 'node:path'
import { ASK_ID, PERMISSION_CHOICES, SHA256, asksDirOf, checkAsk, readAsk, readAsks } from './asks.mjs'
import { casesScriptOf, readCases as readCasesJson } from './cases.mjs'
import { readAgents, readJobState, runClaude } from './claude-agents.mjs'
import { answerText, cleanText, createDelivery, resolvePython, writtenAnswerText } from './deliver.mjs'
import {
  claudePaths,
  findListTranscript,
  currentGoal,
  isListRunning,
  readRunningSessionIds,
  readTasksFromTranscript,
  listRecentTaskLists,
  readPromptBeforeTask,
  readTaskList,
  readTranscriptHead,
  createPendingReader,
  pendingCall,
  pendingQuestion,
  readPendingOf,
  turnEnded
} from './claude-sessions.mjs'
import { createNextSender, readPaneScreen } from './next-actions.mjs'
import { actionText, latestAction } from './case-actions.mjs'
import { createOrchestratorChannel } from './orchestrator.mjs'
import { buildHubModel, isInside } from './hub-model.mjs'
import { readWorkspaces, runOrca } from './orca-cli.mjs'
import { ORCHESTRATOR_FAILURES, renderHub, renderLoading } from './hub-render.mjs'

const TASK_LIST_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000
// Events say when the focus or an agent changes. This catches what they do not, such as a session
// that ended without one.
const SYNC_MS = 10_000
const DEBOUNCE_MS = 150
const REQUEST_RETRY_MS = 30_000
// `claude agents` is asked again at most this often when only a task list changed.
const AGENTS_MIN_MS = 5_000
const REPORT_NAME = 'report.md'
const CASES_MAX_MS = 60_000
// How often a kept answer is told again while the orchestrator cannot take it.
const RESIGNAL_MS = 30_000
const PERMISSION_LABELS = { allow: '許可（今回だけ）', deny: '拒否', terminal: 'ターミナルで確かめる' }

/** 11/19 */
function dayOf(ms) {
  const date = new Date(ms)
  return `${date.getMonth() + 1}/${date.getDate()}`
}

export function createHubWorker({
  orca,
  home,
  hubRoot = join(home, 'hub'),
  cli,
  claudeCli = 'claude',
  readOrca = readWorkspaces,
  runCli = runOrca,
  readClaude = (claude) => readAgents(claude, runClaude),
  readJob = (id) => readJobState(home, id),
  now = Date.now,
  watchDir = (dir, onChange) => watch(dir, { recursive: true }, onChange),
  delivery = null,
  readCases = () => readCasesJson(resolvePython(home), casesScriptOf(home), { AGENT_ORCHESTRATOR_HOME: hubRoot })
}) {
  const asksDir = asksDirOf(hubRoot)
  const casesDir = join(hubRoot, 'state', 'cases')
  let projects = []
  // Read again when a case changes, and once a minute for the dates.
  let casesAt = -Infinity
  let casesChanged = true
  const deliver =
    delivery ??
    createDelivery({
      home,
      hubRoot,
      claudeCli,
      python: resolvePython(home),
      readSessions: () => readClaude(claudeCli),
      readJob
    })
  let asks = []
  // Asks being answered, with the answer pressed: their cards show it as being delivered, and a
  // second press does nothing. Asks whose answer could not be delivered, with why, until pressed again.
  const pressed = new Map()
  const failures = new Map()
  // Answers to the orchestrator's questions that are written but that the orchestrator was not told
  // of, by ask id, with why. The answer file stays (the orchestrator's list of asks shows it
  // answered), and the panel tells the orchestrator again once it can take a line.
  const unsignaled = new Map()
  let signalling = null
  let signalledAt = -Infinity
  const paths = claudePaths(home)
  const { tasksRoot } = paths
  // Transcript heads never change once written; null entries are retried on the next refresh.
  const heads = new Map()
  // The request a list was made for, keyed by list and the subject of its first task.
  const requests = new Map()
  // Claude deletes a list's task files once every task is completed. The last tasks seen per
  // list keep a finished goal on screen as done instead of letting it vanish.
  const lastTasks = new Map()
  // Lists already replayed from a transcript, by list and the time it last changed.
  const replayed = new Map()
  let workspace = null
  let agents = []
  let sessions = []
  let sessionsAt = 0
  let offers = []
  const runArgs = (args, timeout) => runCli(cli, args, timeout)
  // A question or a call waiting for permission is read from the transcript of Claude's session.
  const readers = {
    readQuestion: createPendingReader(home, pendingQuestion),
    readCall: createPendingReader(home, pendingCall),
    readPane: (paneKey) => readPaneScreen(runArgs, paneKey),
    // Orca calls an agent working while its background shells run, even after its turn.
    readTurnEnded: createPendingReader(home, turnEnded)
  }
  // What was pressed for a project's latest action, while it is being delivered, and why it failed.
  const caseSending = new Map()
  const caseFailures = new Map()
  const orchestrator = createOrchestratorChannel({
    run: runArgs,
    // The sessions of the last refresh: the orchestrator's name and folder do not change between them.
    readSessions: async () => (sessions.length > 0 ? sessions : readClaude(claudeCli)),
    hubRoot,
    readPending: (sessionId) => readPendingOf(home, sessionId, pendingQuestion)
  })
  const sendToOrchestrator = orchestrator.send
  // The question the orchestrator waits on, shown in full above everything else.
  let orchestratorQuestion = null
  const sendOffer = createNextSender({
    readOffers: async () => (await readOrca(cli, runCli, readers)).offers ?? [],
    run: runArgs
  })
  let lastHtml = null
  let started = null
  let timer = null
  let pendingFocus = false
  let running = null
  let rerun = false
  // The last state heard per pane. Agents repeat a state with every hook they fire.
  const paneStates = new Map()

  async function headOf(listId) {
    if (heads.has(listId)) return heads.get(listId)
    const transcript = await findListTranscript(paths, listId)
    const head = transcript ? await readTranscriptHead(transcript).catch(() => null) : null
    if (head) heads.set(listId, { ...head, transcript })
    return heads.get(listId) ?? null
  }

  /**
   * What a list is for right now. A session moves on to new goals, so its first prompt is only
   * a last resort: the goal Claude wrote on the tasks comes first, then the request the first
   * task was created for.
   */
  async function goalOf(listId, head, tasks) {
    const current = currentGoal(tasks)
    if (current.goal) return current
    const key = `${listId}\n${tasks[0].subject}`
    let request = requests.get(key)
    // A miss is retried later: the transcript can trail the task files, and a teammate's tasks
    // are not in the lead's transcript at all, so a whole read is not repeated every refresh.
    if (!request || (request.prompt === null && now() - request.at > REQUEST_RETRY_MS)) {
      const prompt = await readPromptBeforeTask(head.transcript, tasks[0].subject).catch(() => null)
      request = { prompt, at: now() }
      requests.set(key, request)
    }
    return { goal: request.prompt ?? head.goal, tasks }
  }

  function isFinished(tasks) {
    return tasks.length > 0 && tasks.every((task) => task.status === 'completed')
  }

  /**
   * A finished list whose files Claude already deleted, replayed from its transcript. That
   * happens when the worker starts after the list was finished, as after a restart.
   */
  async function replayFinished(list) {
    const key = `${list.listId}\n${list.updatedAt}`
    if (replayed.has(key)) return
    replayed.set(key, true)
    // Only a list that ever had tasks keeps a high-water mark.
    if (!(await stat(join(list.dir, '.highwatermark')).catch(() => null))) return
    const head = await headOf(list.listId)
    if (!head?.transcript) return
    const tasks = await readTasksFromTranscript(head.transcript).catch(() => [])
    if (isFinished(tasks)) lastTasks.set(list.listId, tasks)
  }

  async function allSessions() {
    const running = await readRunningSessionIds(paths.sessionsRoot)
    const lists = await listRecentTaskLists(tasksRoot, { maxAgeMs: TASK_LIST_MAX_AGE_MS })
    const sessions = []
    for (const list of lists) {
      // A list shows only while its session runs: ending the session or removing its
      // workspace takes it off the panel.
      if (!isListRunning(list.listId, running)) {
        lastTasks.delete(list.listId)
        continue
      }
      const files = await readTaskList(list.dir)
      if (files.length === 0 && !lastTasks.has(list.listId)) await replayFinished(list)
      const tasks = currentTasks(list.listId, files)
      // A team creates its list when it starts, and most stay empty; they are not looked up.
      if (tasks.length === 0) continue
      const head = await headOf(list.listId)
      if (!head?.cwd) continue
      sessions.push({ ...list, cwd: head.cwd, ...(await goalOf(list.listId, head, tasks)) })
    }
    return sessions.sort((a, b) => b.updatedAt - a.updatedAt)
  }

  function currentTasks(listId, tasks) {
    if (tasks.length > 0) {
      lastTasks.set(listId, tasks)
      return tasks
    }
    const previous = lastTasks.get(listId) ?? []
    // A list emptied before it was finished was cleared on purpose; show nothing for it.
    return isFinished(previous) ? previous : []
  }

  function publish(html) {
    if (html === lastHtml) return
    lastHtml = html
    orca.panels.post('view.changed', { html })
  }

  /** What a panel shows when it opens; it starts the worker's refreshes if nothing has yet. */
  async function view() {
    await start()
    return { html: lastHtml ?? renderLoading() }
  }

  /** The report of a hub worker, `<hub>/workers/<name>/report.md`, when it exists. */
  async function reportOf(name) {
    if (!name || !/^[a-z0-9][a-z0-9-]*$/.test(name)) return null
    const path = join(hubRoot, 'workers', name, REPORT_NAME)
    return (await stat(path).catch(() => null))?.isFile() ? path : null
  }

  /** Every Claude session with the state file of a background one and the report of a hub worker. */
  async function readSessions() {
    const listed = await readClaude(claudeCli)
    return Promise.all(
      listed.map(async (agent) => ({
        ...agent,
        job: agent.kind === 'background' ? await readJob(agent.id) : null,
        report: await reportOf(agent.name)
      }))
    )
  }

  /** A hub worker's report, or a case file: the only paths a pressed row may open. */
  function openable(target) {
    const workers = join(hubRoot, 'workers')
    if (isInside(target, workers)) return target.endsWith(`/${REPORT_NAME}`) && target.split('/').length === workers.split('/').length + 2
    const cases = join(hubRoot, 'state', 'cases')
    return isInside(target, cases) && target.endsWith('.md') && target.split('/').length === cases.split('/').length + 1
  }

  /** Opens a hub worker's report or a case in an editor tab of the workspace that holds it. Other paths are refused. */
  async function openReport(path) {
    const target = typeof path === 'string' ? resolve(path) : ''
    if (!openable(target)) return { opened: false }
    try {
      const { workspaces } = await orca.host.call('workspace.list')
      const holder = workspaces
        .filter((candidate) => isInside(target, candidate.path))
        .toSorted((a, b) => b.path.length - a.path.length)[0]
      if (!holder) {
        orca.log(`hub: no workspace holds ${target}`)
        return { opened: false }
      }
      // Orca opens a file by its path inside the workspace, and shows it in that workspace.
      await orca.host.call('workspace.open', { workspaceId: holder.id })
      await orca.host.call('editor.open', { workspaceId: holder.id, path: relative(holder.path, target) })
      return { opened: true }
    } catch (error) {
      orca.log(`hub: could not open the report: ${error.message}`)
      return { opened: false }
    }
  }

  /** Shows the workspace at a path. A pressed row may be stale by now, so a miss is only logged. */
  async function openWorkspace(path) {
    try {
      const { workspaces } = await orca.host.call('workspace.list')
      const target = workspaces.find((candidate) => candidate.path === path)
      if (!target) {
        orca.log(`hub: no workspace to open at ${path}`)
        return { opened: false }
      }
      await orca.host.call('workspace.open', { workspaceId: target.id })
      return { opened: true }
    } catch (error) {
      orca.log(`hub: could not open the workspace: ${error.message}`)
      return { opened: false }
    }
  }

  async function refreshOnce(askOrca) {
    if (askOrca || !workspace) {
      try {
        let found
        ;({ active: workspace, agents, offers: found } = await readOrca(cli, runCli, readers))
        offers = found ?? []
      } catch (error) {
        orca.log(`hub: could not read the workspaces: ${error.message}`)
      }
    }
    if (askOrca || now() - sessionsAt >= AGENTS_MIN_MS) {
      try {
        sessions = await readSessions()
        sessionsAt = now()
      } catch (error) {
        orca.log(`hub: could not read the Claude sessions: ${error.message}`)
      }
    }
    if (askOrca) {
      // After the sessions, which tell where the orchestrator is.
      orchestratorQuestion = await orchestrator.readQuestion().catch((error) => {
        orca.log(`hub: could not read the orchestrator's question: ${error.message}`)
        return null
      })
      // The orchestrator's question has its own card; no shortened copy of it in the workspace's.
      if (orchestratorQuestion) offers = offers.filter((offer) => offer.paneKey !== orchestratorQuestion.paneKey)
    }
    const lists = await allSessions()
    if (casesChanged || now() - casesAt >= CASES_MAX_MS) {
      casesChanged = false
      try {
        projects = await readCases()
        casesAt = now()
      } catch (error) {
        orca.log(`hub: could not read the cases: ${error.message}`)
      }
    }
    asks = await readAsks(asksDir)
    const shownAsk = (ask) => ({ ...ask, check: checkAsk(ask, sessions, now()), pressed: pressed.get(ask.id) ?? null, failure: failures.get(ask.id) ?? null })
    const forOrchestrator = (ask) => ask.kind === 'question' || ask.kind === 'permission'
    const cards = asks.filter((ask) => !forOrchestrator(ask)).map(shownAsk)
    // A permission past its time is the terminal's again: its card goes.
    const permissions = asks.filter((ask) => ask.kind === 'permission' && ask.expiresAt > now())
    const orchestratorAsks = [
      ...permissions.map(shownAsk),
      ...[...unsignaled.values()].map((entry) => ({ ...entry, kept: true })),
      ...asks.filter((ask) => ask.kind === 'question').map(shownAsk)
    ]
    // While the orchestrator waits on the panel, its menu is not up: no card that types into it.
    const shownOffers = permissions.length > 0 ? offers.filter((offer) => !(offer.kind === 'permission' && resolve(offer.path ?? '') === resolve(hubRoot))) : offers
    publish(renderHub(buildHubModel(sessions, lists, agents, { home, focusedPath: workspace?.path ?? null, now: now(), cards, orchestratorAsks, focused: workspace, offers: shownOffers, orchestratorQuestion, projects: projects.map((project) => ({ ...project, sending: caseSending.get(project.slug) ?? null, failure: caseFailures.get(project.slug) ?? null })) })))
  }

  async function exists(name) {
    return stat(join(asksDir, name)).then(() => true, () => false)
  }

  /** Tells the orchestrator of the answers it was not told of, one try at a time. */
  function resignal() {
    if (signalling || unsignaled.size === 0 || now() - signalledAt < RESIGNAL_MS) return signalling
    signalledAt = now()
    signalling = (async () => {
      for (const entry of [...unsignaled.values()]) {
        // Closed, or its answer given back: there is nothing left to tell.
        if (!(await exists(`${entry.id}.json`)) || !(await exists(`${entry.id}.answer.json`))) {
          unsignaled.delete(entry.id)
          continue
        }
        const sent = await orchestrator.send(entry.id, { signal: true }).catch(() => ({ sent: false, reason: 'failed' }))
        if (sent.sent) {
          unsignaled.delete(entry.id)
          orca.log(`hub: told the orchestrator of the kept answer to ${entry.id}`)
        } else {
          unsignaled.set(entry.id, { ...entry, reason: sent.reason })
        }
      }
    })().finally(() => {
      signalling = null
      schedule()
    })
    return signalling
  }

  /** Runs refreshes one at a time; a request during a run starts one more afterwards. */
  async function refresh(focusChanged = false) {
    pendingFocus ||= focusChanged
    if (running) {
      rerun = true
      return running
    }
    running = (async () => {
      do {
        rerun = false
        const focus = pendingFocus
        pendingFocus = false
        try {
          await refreshOnce(focus)
          void resignal()
        } catch (error) {
          orca.log(`hub: refresh failed: ${error.message}`)
        }
      } while (rerun)
    })()
    try {
      await running
    } finally {
      running = null
    }
  }

  function schedule(focusChanged = false) {
    pendingFocus ||= focusChanged
    clearTimeout(timer)
    timer = setTimeout(() => void refresh(), DEBOUNCE_MS)
  }

  /**
   * A pressed card, or an answer written for it: takes the ask once and hands the answer to the
   * worker. The ask is read again and must be the one the card showed (same hash), from the worker
   * it names.
   */
  async function answerAsk({ id, sha, choice, text, confirmed = false } = {}) {
    const written = text === undefined ? null : cleanText(text)
    if (!ASK_ID.test(id ?? '') || !SHA256.test(sha ?? '')) return { ok: false, reason: 'invalid' }
    if (text === undefined ? !(Number.isInteger(choice) || PERMISSION_CHOICES.includes(choice)) : !written) return { ok: false, reason: 'invalid' }
    if (pressed.has(id)) return { ok: false, reason: 'pressed' }
    pressed.set(id, written ?? '')
    failures.delete(id)
    schedule()
    const fail = (reason, detail = '') => {
      failures.set(id, reason)
      orca.log(`hub: the answer to ${id} was not delivered: ${reason}${detail ? ` (${detail})` : ''}`)
      return { ok: false, reason }
    }
    try {
      const ask = await readAsk(asksDir, id)
      if (!ask || ask.sha !== sha) return fail('stale')
      const current = await readClaude(claudeCli)
      const check = checkAsk(ask, current, now())
      if (!check.ok) return fail(check.reason === 'expired' ? 'expired' : 'unverified')
      if (ask.kind === 'permission') return await answerPermission(ask, choice, written, confirmed, fail)
      if (!written && !Number.isInteger(choice)) return fail('invalid')
      if (ask.kind === 'question') return await answerQuestion(ask, choice, written, fail)
      if (written && ask.kind !== 'decide') return fail('invalid')
      const answer = written ? writtenAnswerText(ask, written) : answerText(ask, choice)
      if (!answer) return fail('invalid')
      const label = written ? `書いた答え: ${written}` : ask.kind === 'decide' ? ask.options[choice - 1].label : ask.suggestions[choice - 1].label
      pressed.set(id, label)
      schedule()
      // Taken first, so the orchestrator stops asking it while the worker finishes its turn.
      const taken = await deliver.take(ask, written ? 'written' : choice)
      if (taken !== 'taken') return fail(taken)
      const sent = await deliver.send(ask.sessionId, answer)
      if (!sent.sent) {
        await deliver.release(asksDir, ask)
        return fail(sent.reason, sent.detail)
      }
      orca.log(`hub: delivered the answer to ${id} to ${ask.worker}`)
      await deliver.log({ ask: ask.id, worker: ask.worker, card: ask.kind, choice: written ? 'written' : choice, label, ...(written ? { text: written } : {}), shown_sha256: ask.sha })
      const what = ask.kind === 'decide' ? `「${ask.question.split('\n')[0].slice(0, 60)}」に「${label}」と答えた` : `次の作業「${label}」を頼んだ`
      const report = ask.report ? ` [report.md](file://${ask.report})` : ''
      await deliver.logCase(ask.case, `${dayOf(now())} パネルで ${ask.worker} に${what}${report}`)
      return { ok: true }
    } catch (error) {
      return fail('failed', error.message)
    } finally {
      pressed.delete(id)
      schedule()
    }
  }

  /**
   * The orchestrator's question: the panel writes the answer file (asks.py checks that it runs from
   * Orca), then tells the orchestrator with a line that carries no answer. The orchestrator reads the
   * answer with `asks.py verify`, which checks the file against the question as it is now.
   */
  async function answerQuestion(ask, choice, written, fail) {
    const label = written ? `書いた答え: ${written}` : ask.options[choice - 1]?.label
    if (!label) return fail('invalid')
    pressed.set(ask.id, label)
    schedule()
    const taken = await deliver.take(ask, written ? 'written' : choice, written)
    if (taken !== 'taken') return fail(taken)
    const sent = await orchestrator.send(ask.id, { signal: true })
    if (!sent.sent) {
      // The answer is written and stays: only telling the orchestrator is tried again.
      unsignaled.set(ask.id, { id: ask.id, question: ask.question, label, reason: sent.reason })
      signalledAt = now()
      orca.log(`hub: the answer to ${ask.id} is kept; the orchestrator was not told yet: ${sent.reason}`)
      const why = ORCHESTRATOR_FAILURES[sent.reason] ?? ORCHESTRATOR_FAILURES.failed
      return { ok: false, reason: 'kept', message: `答えは残しました。まだ窓口に知らせられていません: ${why} 窓口が受け取れるようになったら、パネルが自動で知らせます。` }
    }
    orca.log(`hub: answered the orchestrator's question ${ask.id} (${written ? 'written' : `option ${choice}`})`)
    await deliver.log({ ask: ask.id, worker: ask.worker, card: 'question', approval: ask.approval, choice: written ? 'written' : choice, label, ...(written ? { text: written } : {}), shown_sha256: ask.sha })
    return { ok: true }
  }

  /**
   * The orchestrator's permission dialog: the panel writes the answer file, which approval-gate.py
   * waits on and checks against the ask it wrote. Nothing is typed into the orchestrator. A call that
   * reaches past this machine is never allowed here, and a dangerous one only when pressed twice.
   */
  async function answerPermission(ask, choice, written, confirmed, fail) {
    const picked = written ? 'deny' : choice
    if (!PERMISSION_CHOICES.includes(picked)) return fail('invalid')
    if (picked === 'allow' && ask.risk === 'outside') return fail('invalid')
    if (picked === 'allow' && ask.dangerous && confirmed !== true) return { ok: false, reason: 'confirm' }
    const label = written ? `拒否: ${written}` : PERMISSION_LABELS[picked]
    pressed.set(ask.id, label)
    schedule()
    const taken = await deliver.take(ask, picked, written)
    if (taken !== 'taken') return fail(taken)
    orca.log(`hub: answered the orchestrator's permission ${ask.id} (${ask.toolName}): ${picked}`)
    await deliver.log({ ask: ask.id, worker: ask.worker, card: 'permission', tool: ask.toolName, choice: picked, ...(written ? { text: written } : {}), shown_sha256: ask.sha })
    return { ok: true }
  }

  /** Sends a pressed card of an Orca agent (src/next-actions.mjs); the panel shows what went wrong. */
  async function sendNext(request) {
    try {
      const isOrchestrator = orchestratorQuestion && request?.offer === orchestratorQuestion.id
      const result = isOrchestrator ? await orchestrator.answer(request) : await sendOffer(request)
      // Every press is logged with how it went, so a card that did nothing can be traced.
      orca.log(`hub: card ${request?.offer} (${isOrchestrator ? "the orchestrator's question" : 'an agent'}): ${result.sent ? 'sent' : `not sent, ${result.reason}`}`)
      if (result.sent) schedule(true)
      return result
    } catch (error) {
      orca.log(`hub: could not send the card: ${error.message}`)
      return { sent: false, reason: 'failed' }
    }
  }

  /**
   * A choice or a note for a project's latest action, handed to the orchestrator. The cases are read
   * again: the action must still be the latest one the row showed.
   */
  async function actOnCase({ slug, kind, text, choice, note } = {}) {
    const written = note === undefined ? undefined : cleanText(note)
    if (typeof slug !== 'string' || typeof text !== 'string' || (note !== undefined && !written)) return { ok: false, reason: 'invalid' }
    if (caseSending.has(slug)) return { ok: false, reason: 'pressed' }
    caseSending.set(slug, written ? `指示: ${written}` : '')
    caseFailures.delete(slug)
    schedule()
    const fail = (reason, detail = '') => {
      caseFailures.set(slug, reason)
      orca.log(`hub: the action for ${slug} was not delivered: ${reason}${detail ? ` (${detail})` : ''}`)
      return { ok: false, reason }
    }
    try {
      projects = await readCases()
      casesAt = now()
      const project = projects.find((p) => p.slug === slug)
      const action = project ? latestAction(project) : null
      if (!action || action.kind !== kind || action.text !== text) return fail('stale')
      const line = actionText(project, action, written ? { note: written } : { choice })
      if (!line) return fail('invalid')
      caseSending.set(slug, written ? `指示: ${written}` : line.slice(line.lastIndexOf(': ') + 2))
      schedule()
      const sent = await sendToOrchestrator(line)
      if (!sent.sent) {
        const result = fail(sent.reason)
        const why = ORCHESTRATOR_FAILURES[sent.reason]
        return why ? { ...result, message: `窓口に届けられませんでした: ${why}` } : result
      }
      orca.log(`hub: delivered the action for ${slug} to the orchestrator`)
      await deliver.log({ case: slug, card: 'case', kind, item: text, ...(written ? { text: written } : { choice }) })
      return { ok: true }
    } catch (error) {
      return fail('failed', error.message)
    } finally {
      caseSending.delete(slug)
      schedule()
    }
  }

  /** A line a person wrote to a worker from its row. */
  async function sendToSession({ sessionId, text } = {}) {
    const body = cleanText(text)
    if (typeof sessionId !== 'string' || !body) return { ok: false, reason: 'invalid' }
    const sent = await deliver.send(sessionId, body)
    if (!sent.sent) {
      orca.log(`hub: the line to ${sessionId} was not delivered: ${sent.reason}`)
      return { ok: false, reason: sent.reason }
    }
    const session = sessions.find((candidate) => candidate.sessionId === sessionId)
    await deliver.log({ session: sessionId, worker: session?.name ?? null, card: 'free', text: body })
    schedule()
    return { ok: true }
  }

  function agentChanged({ paneKey, state, mainAgent }) {
    const key = `${state}\n${mainAgent?.state ?? ''}`
    if (paneStates.get(paneKey) === key) return
    paneStates.set(paneKey, key)
    schedule(true)
  }

  function start() {
    started ??= (async () => {
      await mkdir(tasksRoot, { recursive: true })
      watchDir(tasksRoot, (_event, name) => {
        if (name && !String(name).endsWith('.lock')) schedule()
      })
      await mkdir(asksDir, { recursive: true })
      watchDir(asksDir, () => schedule())
      await mkdir(casesDir, { recursive: true })
      watchDir(casesDir, () => {
        casesChanged = true
        schedule()
      })
      setInterval(() => schedule(true), SYNC_MS)
      await refresh(true)
    })()
    return started
  }

  return { start, refresh, resignal, schedule, agentChanged, view, openWorkspace, openReport, answerAsk, sendToSession, sendNext, actOnCase }
}
