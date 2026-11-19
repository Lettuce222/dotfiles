// Turns every Claude Code session, the task lists found on disk and the agents Orca runs into the
// one list the Hub panel shows. Pure: the same input gives the same model, so the worker posts only
// real changes.

export const WATCHER = 'chore-hub-watch'
const ORCHESTRATOR = 'orchestrator'
const DONE_MAX = 8
const DONE_MAX_AGE_MS = 3 * 24 * 60 * 60 * 1000
const TEAM_LIST_ID = /^session-([0-9a-f]{8})$/
// An Orca agent needs the user when it asks for input or for a permission.
const ORCA_NEEDS_USER = new Set(['waiting', 'blocked', 'permission'])

export function isInside(path, root) {
  if (!path || !root) return false
  return path === root || path.startsWith(root.endsWith('/') ? root : `${root}/`)
}

function listOf(sessionId, lists) {
  return (
    lists.find((list) => list.listId === sessionId) ??
    lists.find((list) => TEAM_LIST_ID.exec(list.listId)?.[1] === sessionId.slice(0, 8)) ??
    null
  )
}

function progress(list) {
  if (!list) return { goal: null, done: 0, total: 0, tasks: [], step: null }
  const tasks = list.tasks.filter((task) => task.status !== 'deleted')
  const current = tasks.find((task) => task.status === 'in_progress')
  return {
    goal: list.goal ?? null,
    done: tasks.filter((task) => task.status === 'completed').length,
    total: tasks.length,
    tasks,
    step: current ? (current.activeForm || current.subject) : null
  }
}

function shortPath(path, home) {
  if (!path) return ''
  return home && isInside(path, home) ? `~${path.slice(home.length)}` : path
}

/** Which group a session belongs in: attention (the user's turn), working, idle or done. */
function stateOf(agent, orcaAgent) {
  const job = agent.job
  if (agent.waitingFor || agent.state === 'blocked' || job?.state === 'blocked') return 'attention'
  if (orcaAgent && ORCA_NEEDS_USER.has(orcaAgent.state)) return 'attention'
  if (agent.status === 'busy' || agent.state === 'working' || job?.state === 'working') return 'working'
  if (agent.kind === 'background' && (agent.state === 'done' || job?.state === 'done' || !agent.alive)) return 'done'
  return 'idle'
}

/** Pairs each interactive session with the Orca agent of the workspace it works in, innermost first. */
function pairOrca(agents, orcaAgents) {
  const paired = new Map()
  const used = new Set()
  const interactive = agents
    .filter((agent) => agent.kind === 'interactive' && agent.cwd)
    .toSorted((a, b) => b.cwd.length - a.cwd.length)
  for (const agent of interactive) {
    const match = orcaAgents
      .filter((orcaAgent, index) => !used.has(index) && isInside(agent.cwd, orcaAgent.path))
      .toSorted((a, b) => b.path.length - a.path.length)[0]
    if (!match) continue
    used.add(orcaAgents.indexOf(match))
    paired.set(agent.sessionId, match)
  }
  return { paired, rest: orcaAgents.filter((_, index) => !used.has(index)) }
}

function sessionRow(agent, orcaAgent, lists, home, focusedPath) {
  const job = agent.job ?? null
  const state = stateOf(agent, orcaAgent)
  const counts = progress(listOf(agent.sessionId, lists))
  const name = agent.name ?? (orcaAgent ? orcaAgent.workspace : shortPath(agent.cwd, home))
  return {
    key: `session\n${agent.sessionId}`,
    kind: agent.kind === 'background' ? 'worker' : orcaAgent ? 'orca' : 'session',
    name,
    where: shortPath(agent.cwd, home),
    state,
    // A finished or blocked worker says what it needs; a working one what it is doing.
    detail: (state === 'attention' ? job?.needs ?? agent.waitingFor : null) ?? job?.detail ?? (counts.total === 0 ? job?.intent : null) ?? null,
    ...counts,
    report: agent.report ?? null,
    open: orcaAgent ? orcaAgent.path : null,
    // A worker that is not working can be handed a line from its row (it resumes with it).
    say: agent.kind === 'background' && agent.name && agent.name !== ORCHESTRATOR && state !== 'working' ? agent.sessionId : null,
    focused: Boolean(focusedPath && agent.cwd && isInside(agent.cwd, focusedPath)),
    since: job?.updatedAt || agent.startedAt || 0
  }
}

/** An Orca workspace whose agent no Claude session listed (Codex, or a session Claude cannot see). */
function workspaceRow(orcaAgent, lists, home, focusedPath) {
  const list = lists.find((candidate) => candidate.cwd && isInside(candidate.cwd, orcaAgent.path)) ?? null
  return {
    key: `orca\n${orcaAgent.path}`,
    kind: 'orca',
    name: orcaAgent.workspace,
    where: shortPath(orcaAgent.path, home),
    state: ORCA_NEEDS_USER.has(orcaAgent.state) ? 'attention' : orcaAgent.state === 'working' ? 'working' : 'idle',
    detail: null,
    ...progress(list),
    report: null,
    open: orcaAgent.path,
    say: null,
    focused: Boolean(focusedPath && isInside(orcaAgent.path, focusedPath)),
    since: orcaAgent.since ?? 0
  }
}

const FOCUSED_SESSIONS_MAX = 3

/**
 * The focused workspace as orca-milestone shows it at the top: its agent's state, the goal and tasks
 * of its newest lists, and what its agent offers to choose from.
 * Adapted from andoshin11/orca-milestone src/model.mjs (MIT, see ../LICENSE and ../NOTICE.md).
 */
function focusedView(workspace, lists, offers, workers) {
  if (!workspace) return { kind: 'no-workspace' }
  // A background worker that works inside the folder (~/hub/workers/<name>) is not this workspace's
  // agent; it has its own row below.
  const mine = lists
    .filter((list) => list.cwd && isInside(list.cwd, workspace.path) && list.tasks.length > 0 && !workers.has(list.listId))
    .slice(0, FOCUSED_SESSIONS_MAX)
    .map((list) => ({ listId: list.listId, ...progress(list) }))
  const states = workspace.agentStates ?? []
  return {
    kind: mine.length > 0 ? 'sessions' : 'no-tasks',
    workspace: workspace.displayName,
    agent: states.includes('working')
      ? 'working'
      : states.includes('blocked') || states.includes('waiting')
        ? 'waiting'
        : states.length > 0
          ? workspace.background ? 'background' : 'idle'
          : 'none',
    sessions: mine,
    next: offers.find((offer) => offer.path === workspace.path) ?? null
  }
}

function watcherLine(agents) {
  const watcher = agents
    .filter((agent) => agent.name === WATCHER && agent.kind === 'background')
    .toSorted((a, b) => b.startedAt - a.startedAt)[0]
  if (!watcher) return { state: 'missing', detail: null }
  if (!watcher.alive || watcher.state === 'done') return { state: 'stopped', detail: watcher.job?.detail ?? null }
  if (watcher.state === 'blocked' || watcher.job?.state === 'blocked') {
    return { state: 'blocked', detail: watcher.job?.needs ?? watcher.job?.detail ?? null }
  }
  return null
}

/**
 * @param agents     [{ sessionId, id, name, kind, cwd, state, status, waitingFor, alive, startedAt, job, report }]
 * @param lists      [{ listId, cwd, goal, tasks, updatedAt }] of the running sessions that keep tasks
 * @param orcaAgents [{ workspace, repo, path, focused, state, background, since }] of `orca worktree ps`
 * @param options    { home, focusedPath, now, cards, focused, offers }; cards are the open asks
 *   (src/asks.mjs) with `check` (checkAsk) and `pressed`, oldest first; focused is the focused
 *   workspace ({ path, displayName, agentStates, background }) and offers what Orca's agents offer
 *   (src/next-actions.mjs)
 */
export function buildHubModel(agents, lists, orcaAgents = [], { home = null, focusedPath = null, now = 0, cards = [], focused = null, offers = [] } = {}) {
  const { paired, rest } = pairOrca(agents, orcaAgents)
  // A worker's ask shows in its row, which then waits for the user whatever the session says.
  const cardOf = new Map(cards.map((card) => [card.sessionId, card]))
  const withCard = (row, sessionId) => {
    const card = cardOf.get(sessionId)
    return card ? { ...row, state: 'attention', card } : row
  }
  const rows = [
    ...agents
      .filter((agent) => agent.name !== WATCHER)
      .map((agent) => withCard(sessionRow(agent, paired.get(agent.sessionId), lists, home, focusedPath), agent.sessionId)),
    ...rest.map((orcaAgent) => workspaceRow(orcaAgent, lists, home, focusedPath))
  ]
  const listed = new Set(agents.filter((agent) => agent.name !== WATCHER).map((agent) => agent.sessionId))
  const group = (state) => rows.filter((row) => row.state === state)
  // The focused workspace first, then the oldest wait or the newest change.
  const byFocus = (a, b) => Number(b.focused) - Number(a.focused)
  return {
    focused: focusedView(focused, lists, offers, new Set(agents.filter((agent) => agent.kind === 'background').map((agent) => agent.sessionId))),
    // Asks of a session no longer listed (removed without closing them) show on their own.
    cards: cards.filter((card) => !listed.has(card.sessionId)).map((card) => ({ ...card, where: shortPath(card.cwd, home) })),
    attention: group('attention').toSorted((a, b) => byFocus(a, b) || a.since - b.since),
    working: group('working').toSorted((a, b) => byFocus(a, b) || b.since - a.since),
    idle: group('idle').toSorted((a, b) => byFocus(a, b) || b.since - a.since),
    done: group('done')
      .filter((row) => !now || !row.since || now - row.since <= DONE_MAX_AGE_MS)
      .toSorted((a, b) => b.since - a.since)
      .slice(0, DONE_MAX),
    watcher: watcherLine(agents)
  }
}
