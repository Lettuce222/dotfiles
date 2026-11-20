import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { test } from 'node:test'
import { parseAgents, readJobState, resolveClaudeCli } from '../src/claude-agents.mjs'
import { WATCHER, buildHubModel } from '../src/hub-model.mjs'
import { renderHub } from '../src/hub-render.mjs'
import { createHubWorker } from '../src/hub-worker.mjs'
import { SESSION_A, SESSION_B, makeHome, task, writeTasks, writeTranscript } from './helpers.mjs'
import { renderMarkdown as md } from '../src/markdown.mjs'

const HOME = '/Users/me'

function agent(fields) {
  return { id: null, name: null, kind: 'interactive', cwd: null, state: null, status: null, waitingFor: null, alive: true, startedAt: 0, job: null, report: null, ...fields }
}

function fakeOrca(workspaces = []) {
  const posts = []
  const calls = []
  return {
    log: () => {},
    host: {
      call: async (method, params) => {
        calls.push({ method, params })
        if (method === 'workspace.list') return { workspaces }
        return { opened: true }
      }
    },
    panels: { post: (event, payload) => posts.push({ event, payload }) },
    posts,
    calls,
    shown: () => posts.at(-1).payload.html
  }
}

test('parseAgents keeps the fields the panel uses and skips entries without a session', () => {
  const parsed = parseAgents([
    { pid: 1, id: 'b282739f', cwd: '/w', kind: 'background', startedAt: 5, sessionId: SESSION_A, name: 'impl-x', status: 'idle', state: 'blocked' },
    { cwd: '/h', kind: 'interactive', sessionId: SESSION_B, name: 'orchestrator', status: 'busy' },
    { name: 'broken' },
    null
  ])
  assert.equal(parsed.length, 2)
  assert.deepEqual(parsed[0], { sessionId: SESSION_A, id: 'b282739f', name: 'impl-x', kind: 'background', cwd: '/w', state: 'blocked', status: 'idle', waitingFor: null, alive: true, startedAt: 5 })
  assert.equal(parsed[1].alive, false, 'no pid: the session is not running')
  assert.deepEqual(parseAgents({ not: 'a list' }), [])
})

test('readJobState reads what a background session says, and nothing for a bad id or file', async () => {
  const home = await makeHome()
  const dir = join(home, '.claude', 'jobs', 'abcdef12')
  await mkdir(dir, { recursive: true })
  await writeFile(join(dir, 'state.json'), JSON.stringify({ state: 'blocked', detail: 'waits', needs: 'approve the push', intent: '/agents-worker x', inFlight: { tasks: 2 }, updatedAt: '2026-11-19T05:00:00.000Z' }))
  assert.deepEqual(await readJobState(home, 'abcdef12'), { state: 'blocked', detail: 'waits', needs: 'approve the push', intent: '/agents-worker x', inFlight: 2, updatedAt: Date.parse('2026-11-19T05:00:00.000Z') })
  assert.equal(await readJobState(home, '../../etc'), null)
  assert.equal(await readJobState(home, 'deadbeef'), null)
})

test('resolveClaudeCli prefers the install places, then claude on PATH', () => {
  assert.equal(resolveClaudeCli(HOME, (p) => p === `${HOME}/.local/bin/claude`), `${HOME}/.local/bin/claude`)
  assert.equal(resolveClaudeCli(HOME, () => false), 'claude')
})

test('sessions are grouped by whose turn it is, with goal, progress and the step in progress', () => {
  const lists = [{ listId: SESSION_A, cwd: '/w/a', goal: 'Build the panel', tasks: [task(1, 'Read', 'completed'), task(2, 'Write', 'in_progress', { activeForm: 'Writing' }), task(3, 'Test', 'pending')], updatedAt: 1 }]
  const model = buildHubModel(
    [
      agent({ sessionId: SESSION_A, id: 'aaaaaaaa', name: 'impl-a', kind: 'background', cwd: '/w/a', state: 'working', job: { state: 'working', detail: 'writing code', updatedAt: 10 } }),
      agent({ sessionId: SESSION_B, id: 'bbbbbbbb', name: 'impl-b', kind: 'background', cwd: `${HOME}/hub/workers/impl-b`, state: 'blocked', job: { state: 'blocked', detail: 'push waits', needs: 'approve the push', updatedAt: 5 }, report: `${HOME}/hub/workers/impl-b/report.md` }),
      agent({ sessionId: 'c', id: 'cccccccc', name: 'research-c', kind: 'background', state: 'done', alive: false, job: { state: 'done', detail: 'done', updatedAt: 3 } }),
      agent({ sessionId: 'd', name: 'orchestrator', cwd: `${HOME}/hub`, status: 'idle' })
    ],
    lists,
    [],
    { home: HOME, now: 20 }
  )
  assert.deepEqual(model.attention.map((row) => row.name), ['impl-b'])
  assert.equal(model.attention[0].detail, 'approve the push', 'a blocked worker shows what it needs')
  assert.equal(model.attention[0].report, `${HOME}/hub/workers/impl-b/report.md`)
  assert.equal(model.attention[0].where, '~/hub/workers/impl-b')
  assert.deepEqual(model.working.map((row) => [row.name, row.goal, row.done, row.total, row.step]), [['impl-a', 'Build the panel', 1, 3, 'Writing']])
  assert.deepEqual(model.idle.map((row) => row.name), ['orchestrator'])
  assert.ok(![...model.attention, ...model.working, ...model.idle].some((row) => row.name === 'research-c'), 'finished workers are not shown')
  assert.deepEqual(model.watcher, { state: 'missing', detail: null })
})

test('a team lead finds its list by the prefix of its session id', () => {
  const lists = [{ listId: 'session-11111111', cwd: '/w', goal: 'Team goal', tasks: [task(1, 'Plan', 'completed')], updatedAt: 1 }]
  const model = buildHubModel([agent({ sessionId: SESSION_A, name: 'lead', status: 'busy' })], lists)
  assert.equal(model.working[0].goal, 'Team goal')
})

test('an interactive session takes the Orca workspace it works in; other Orca agents get rows of their own', () => {
  const orcaAgents = [
    { workspace: 'dotfiles', path: '/r/dotfiles', state: 'waiting', since: 7, focused: true },
    { workspace: 'feat-x', path: '/r/dotfiles/.wt/feat-x', state: 'working', since: 8 },
    { workspace: 'codex-y', path: '/r/other', state: 'done', since: 9 }
  ]
  const model = buildHubModel(
    [
      agent({ sessionId: SESSION_A, cwd: '/r/dotfiles/.wt/feat-x/sub', status: 'busy' }),
      agent({ sessionId: SESSION_B, cwd: '/r/dotfiles', status: 'idle' }),
      agent({ sessionId: 'w', name: 'impl-w', kind: 'background', cwd: '/r/dotfiles/x', state: 'working' })
    ],
    [],
    orcaAgents,
    { focusedPath: '/r/dotfiles' }
  )
  const all = [...model.attention, ...model.working, ...model.idle]
  const byKind = (kind) => all.filter((row) => row.kind === kind).map((row) => [row.name, row.state, row.open])
  assert.deepEqual(byKind('orca').toSorted(), [
    ['codex-y', 'idle', '/r/other'],
    ['dotfiles', 'attention', '/r/dotfiles'],
    ['feat-x', 'working', '/r/dotfiles/.wt/feat-x']
  ])
  assert.deepEqual(byKind('worker'), [['impl-w', 'working', null]], 'a background worker is never paired with a workspace')
})

test('the watcher has no row, and a line only when it is not running well', () => {
  const watcher = (fields) => agent({ sessionId: 'w', name: WATCHER, kind: 'background', ...fields })
  assert.equal(buildHubModel([watcher({ state: 'working', alive: true })], []).watcher, null)
  assert.deepEqual(buildHubModel([watcher({ state: 'blocked', job: { needs: 'reconnect Slack' } })], []).watcher, { state: 'blocked', detail: 'reconnect Slack' })
  assert.equal(buildHubModel([watcher({ alive: false })], []).watcher.state, 'stopped')
  const model = buildHubModel([watcher({ state: 'working' })], [])
  assert.equal([...model.attention, ...model.working, ...model.idle].length, 0)
})

test('workers go under the project that links them, names them in its ask, or whose name they hold', () => {
  const project = (slug, extra = {}) => ({ slug, title: slug, short: slug, path: null, todo: [], waiting: [], later: 0, workers: [], ...extra })
  const projects = [project('orca-setup', { workers: ['research-hub-orca-policy'] }), project('ai-mania')]
  const agents = [
    agent({ sessionId: 'a', name: 'research-hub-orca-policy', kind: 'background', state: 'blocked' }),
    agent({ sessionId: 'b', name: 'impl-hub-orca-setup', kind: 'background', state: 'working', status: 'busy' }),
    agent({ sessionId: 'c', name: 'impl-x', kind: 'background', state: 'blocked' }),
    agent({ sessionId: 'd', name: 'impl-y', kind: 'background', state: 'blocked' }),
    agent({ sessionId: 'e', name: 'impl-hub-orca-setup-old', kind: 'background', state: 'done', alive: false }),
    agent({ sessionId: 'f', name: 'orchestrator', cwd: '/h/hub', status: 'idle' })
  ]
  const cards = [{ id: '20261119-000000-deadbeef', kind: 'decide', sessionId: 'c', case: 'ai-mania', check: { ok: true }, pressed: null, question: 'q', options: [] }]
  const model = buildHubModel(agents, [], [], { projects, cards })
  assert.deepEqual(model.projects.map((p) => [p.slug, p.rows.map((row) => row.name)]), [
    ['orca-setup', ['research-hub-orca-policy', 'impl-hub-orca-setup']],
    ['ai-mania', ['impl-x']]
  ])
  assert.deepEqual(model.attention.map((row) => row.name), ['impl-y'], 'outside the projects')
  assert.deepEqual(model.idle.map((row) => row.name), ['orchestrator'])
})

test('a project shows its TODO with dates and marks, what it waits for, and links its case file', () => {
  const projects = [
    { slug: 'quiet', title: '静かな案件', short: '静か', path: null, todo: [], waiting: [], later: 0, workers: [] },
    {
      slug: 'orca-setup', title: 'Orca で仕事を進める', short: 'Orca', path: '/h/hub/state/cases/orca-setup.md', later: 0, workers: ['impl-a'],
      todo: [{ text: '[資料](https://x/y) を読む', due: '2026-11-18', bang: false, overdue: true, today: false }, { text: '出す', due: '2026-11-19', bang: true, overdue: false, today: true }],
      waiting: [{ text: 'レビュー待ち', next: '直す' }]
    }
  ]
  const model = buildHubModel([agent({ sessionId: 'a', name: 'impl-a', kind: 'background', state: 'blocked' })], [], [], { projects })
  assert.deepEqual(model.projects.map((p) => p.slug), ['orca-setup', 'quiet'], 'a project waiting for the user comes first')
  const html = renderHub(model)
  assert.ok(html.includes('<div class="project-head" role="button" tabindex="0" data-report="/h/hub/state/cases/orca-setup.md"><span class="name">Orca</span>'))
  assert.ok(html.includes('<span class="badge">あなたの番 1</span>'))
  assert.ok(html.includes('<span class="due overdue">過ぎた 11/18</span><span class="md-link">資料</span> を読む'))
  assert.ok(html.includes('<span class="due today">今日 11/19</span><span class="bang">!</span>出す'))
  assert.ok(html.includes('レビュー待ち<span class="then"> → 直す</span>'))
  assert.ok(html.includes('<p class="quiet">TODO も待ちもありません</p>'))
  assert.ok(!html.includes('あなたの番（プロジェクトの外）'), 'the worker is under its project')
})

test('the render escapes what sessions write and links a row to its workspace or report', () => {
  const model = buildHubModel(
    [
      agent({ sessionId: 'a', name: 'impl-<b>', kind: 'background', state: 'blocked', job: { needs: '<script>x</script>' }, report: '/h/hub/workers/impl-b/report.md' }),
      agent({ sessionId: 'b', cwd: '/r/x', status: 'busy' })
    ],
    [],
    [{ workspace: 'x', path: '/r/x', state: 'working' }]
  )
  const html = renderHub(model)
  assert.ok(!html.includes('<script>'))
  assert.ok(html.includes('impl-&lt;b&gt;'))
  assert.ok(html.includes('data-report="/h/hub/workers/impl-b/report.md"'))
  assert.ok(html.includes('data-open="/r/x"'))
  assert.ok(html.includes('あなたの番'))
  assert.equal(renderHub(model), html, 'the same model renders the same bytes')
  assert.ok(renderHub(buildHubModel([], [])).includes('セッションはありません'))
})

test('the worker joins claude agents, job states, task lists and reports into one post', async () => {
  const home = await makeHome()
  const hubRoot = join(home, 'hub')
  await mkdir(join(hubRoot, 'workers', 'impl-a'), { recursive: true })
  await writeFile(join(hubRoot, 'workers', 'impl-a', 'report.md'), '# report\n')
  await writeTranscript(home, SESSION_A, { cwd: join(hubRoot, 'workers', 'impl-a'), prompt: 'Make the hub panel' })
  await writeTasks(home, SESSION_A, [task(1, 'Read', 'completed', { metadata: { goal: 'Hub panel' } }), task(2, 'Build', 'in_progress', { metadata: { goal: 'Hub panel' } })])
  const orca = fakeOrca()
  let claudeCalls = 0
  let clock = 1_000_000
  const worker = createHubWorker({
    orca,
    home,
    hubRoot,
    cli: 'orca',
    readOrca: async () => ({ active: null, agents: [] }),
    readClaude: async () => {
      claudeCalls += 1
      return [{ sessionId: SESSION_A, id: 'aaaaaaaa', name: 'impl-a', kind: 'background', cwd: join(hubRoot, 'workers', 'impl-a'), state: 'working', status: 'busy', waitingFor: null, alive: true, startedAt: 1 }]
    },
    readJob: async (id) => (id === 'aaaaaaaa' ? { state: 'working', detail: 'building', needs: null, intent: null, inFlight: 0, updatedAt: 2 } : null),
    now: () => clock,
    watchDir: () => {}
  })
  await worker.refresh(true)
  const html = orca.shown()
  assert.ok(html.includes('impl-a'))
  assert.ok(html.includes('Hub panel'))
  assert.ok(html.includes('1 / 2'))
  assert.ok(html.includes(`data-report="${join(hubRoot, 'workers', 'impl-a', 'report.md')}"`))
  await worker.refresh()
  assert.equal(claudeCalls, 1, 'a task change alone does not ask claude again within a few seconds')
  clock += 6_000
  await worker.refresh()
  assert.equal(claudeCalls, 2)
})

test('openReport opens only a report of a hub worker, in the workspace that holds it', async () => {
  const home = await makeHome()
  const hubRoot = join(home, 'hub')
  const orca = fakeOrca([{ id: 'ws-hub', path: hubRoot }, { id: 'ws-home', path: home }])
  const worker = createHubWorker({ orca, home, hubRoot, cli: 'orca', readClaude: async () => [], watchDir: () => {} })
  const report = join(hubRoot, 'workers', 'impl-a', 'report.md')
  assert.deepEqual(await worker.openReport(report), { opened: true })
  assert.deepEqual(orca.calls.slice(-2), [
    { method: 'workspace.open', params: { workspaceId: 'ws-hub' } },
    { method: 'editor.open', params: { workspaceId: 'ws-hub', path: 'workers/impl-a/report.md' } }
  ], 'Orca takes the path inside the workspace')
  assert.deepEqual(await worker.openReport(join(hubRoot, 'state', 'cases', 'orca-setup.md')), { opened: true }, 'a case opens too')
  for (const path of [join(hubRoot, 'state', 'cases', 'done', 'x.md'), join(hubRoot, 'state', 'approvals', 'x.md'), join(hubRoot, 'workers', 'impl-a', '..', '..', 'CLAUDE.md'), join(hubRoot, 'workers', 'a', 'b', 'report.md'), join(home, '.ssh', 'report.md'), 42]) {
    assert.deepEqual(await worker.openReport(path), { opened: false }, String(path))
  }
})

test('what a session says is never cut: in full when it needs the user, and in the expansion otherwise', () => {
  const long = `${'あ'.repeat(300)}おわり`
  const model = buildHubModel(
    [
      agent({ sessionId: 'a', id: 'aaaaaaaa', name: 'impl-a', kind: 'background', cwd: `${HOME}/hub/workers/impl-a`, state: 'blocked', job: { state: 'blocked', needs: long, inFlight: 0, updatedAt: 1 } }),
      agent({ sessionId: 'b', id: 'bbbbbbbb', name: 'impl-b', kind: 'background', cwd: `${HOME}/hub/workers/impl-b`, state: null, status: 'idle', alive: true, job: { state: 'idle', detail: long, inFlight: 0, updatedAt: 1 } })
    ],
    [],
    [],
    { home: HOME }
  )
  const html = renderHub(model)
  const [attention, done] = html.split('<div class="group idle">')
  assert.ok(attention.includes(`<div class="sub md-sub">${md(long)}</div>`), 'the need in full')
  assert.ok(done.includes(`<div class="said">${md(long)}</div>`), 'the expansion has the whole line')
  assert.ok(done.includes('<p class="where">~/hub/workers/impl-b</p>'), 'the place moved off the name line')
  assert.ok(!html.includes('<span class="repo">'))
})

test('the focused workspace shows its own agent, not the workers working inside its folder', () => {
  const lists = [
    { listId: SESSION_A, cwd: `${HOME}/hub`, goal: 'hub の作業', tasks: [task(1, 'a', 'pending')], updatedAt: 2 },
    { listId: SESSION_B, cwd: `${HOME}/hub/workers/impl-x`, goal: 'worker の作業', tasks: [task(1, 'b', 'pending')], updatedAt: 3 }
  ]
  const agents = [agent({ sessionId: SESSION_B, name: 'impl-x', kind: 'background', cwd: `${HOME}/hub/workers/impl-x` })]
  const model = buildHubModel(agents, lists, [], { home: HOME, focused: { path: `${HOME}/hub`, displayName: 'hub', agentStates: [] } })
  assert.deepEqual(model.focused.sessions.map((s) => s.goal), ['hub の作業'])
})

test('cards are shaped as orca-milestone draws them, and the panel has their styles', async () => {
  const offer = { kind: 'permission', id: 'o1', path: '/w', question: 'Bash を許可しますか？ touch a', risk: 'write', where: '', dangerous: false, suggestions: [{ label: '許可', action: 'allow', detail: '今回だけ実行します' }] }
  const html = renderHub(buildHubModel([], [], [], { focused: { path: '/w', displayName: 'w', agentStates: ['waiting'] }, offers: [offer] }))
  assert.ok(html.includes(`<button type="button" class="action" data-next="o1" data-index="0"><span class="label">許可</span><span class="detail">${md('今回だけ実行します')}</span></button>`))
  const { readFile } = await import('node:fs/promises')
  const css = await readFile(join(import.meta.dirname, '..', 'panel', 'style.css'), 'utf8')
  // The label and its line sit one under the other only with these.
  for (const rule of ['.action {', '.action .label', '.next h2 {', '.actions {', '.submit {']) assert.ok(css.includes(rule), rule)
})

test('parseCases keeps the fields the panel uses and drops what cases.py would not write', async () => {
  const { parseCases, readCases } = await import('../src/cases.mjs')
  const parsed = parseCases({ today: '2026-11-19', cases: [
    { slug: 'a', title: 'A', short: 'A', path: '/h/a.md', todo: [{ text: 'x', due: '2026-11-19', bang: true, overdue: false, today: true }, { text: '' }], waiting: [{ text: 'w', next: null }], later: 2, workers: ['impl-a', '../x'] },
    { slug: '../bad' },
    null
  ] })
  assert.deepEqual(parsed, [{ slug: 'a', title: 'A', short: 'A', path: '/h/a.md', todo: [{ text: 'x', due: '2026-11-19', bang: true, overdue: false, today: true }], waiting: [{ text: 'w', next: null }], later: 2, workers: ['impl-a'] }])
  assert.deepEqual(parseCases({ not: 'cases' }), [])
  const runs = []
  await readCases('python3', '/s/cases.py', { AGENT_ORCHESTRATOR_HOME: '/h' }, async (...args) => {
    runs.push(args)
    return { cases: [] }
  })
  assert.deepEqual(runs, [['python3', '/s/cases.py', { AGENT_ORCHESTRATOR_HOME: '/h' }]])
})
