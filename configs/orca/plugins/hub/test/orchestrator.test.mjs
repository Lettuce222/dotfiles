// A project's latest action, and handing the orchestrator a line from the panel.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { actionText, latestAction } from '../src/case-actions.mjs'
import { buildHubModel } from '../src/hub-model.mjs'
import { renderHub } from '../src/hub-render.mjs'
import { createOrchestratorChannel, createOrchestratorSender, findOrchestrator, fullQuestions, orchestratorLine, questionKeys } from '../src/orchestrator.mjs'
import { PREFIX } from '../src/deliver.mjs'
import { renderMarkdown as md } from '../src/markdown.mjs'

const HUB = '/Users/me/hub'
const project = (extra = {}) => ({ slug: 'orca-setup', title: 'Orca で仕事を進める', short: 'Orca', path: null, todo: [], waiting: [], later: 0, workers: [], ...extra })
const todo = (text, extra = {}) => ({ text, due: null, bang: false, overdue: false, today: false, ...extra })

test('the latest action is the first TODO, else the first Waiting', () => {
  assert.equal(latestAction(project()), null)
  assert.deepEqual(latestAction(project({ waiting: [{ text: '返事待ち', next: '直す' }] })), { kind: 'waiting', text: '返事待ち', next: '直す' })
  assert.equal(latestAction(project({ todo: [todo('出す', { bang: true })], waiting: [{ text: 'w', next: null }] })).text, '出す')
})

test('the latest action shows in full with its choices, and the rest is folded', () => {
  const p = project({ todo: [todo('[11/19] の資料を出す', { due: '2026-11-19', today: true }), todo('読む')], waiting: [{ text: '返事待ち', next: null }] })
  const html = renderHub(buildHubModel([], [], [], { projects: [p] }))
  assert.ok(html.includes('<p class="latest-text"><span class="due today">今日 11/19</span>[11/19] の資料を出す</p>'))
  for (const label of ['進めて', '後回し', '済んだ', '指示を書く…']) assert.ok(html.includes(`<span class="label">${label}</span>`), label)
  assert.ok(html.includes('data-case-act data-case="orca-setup" data-kind="todo" data-text="[11/19] の資料を出す" data-choice="go"'))
  assert.ok(html.includes('ほか 2 件（TODO 1・待ち 1）'))
  assert.ok(html.includes('<ol class="items rest">'))
  const sending = renderHub(buildHubModel([], [], [], { projects: [{ ...p, sending: '進めて' }] }))
  assert.ok(sending.includes('<span class="label">進めて</span><span class="detail">窓口に届けています…'))
  assert.ok(!sending.includes('data-case-act'))
  const failed = renderHub(buildHubModel([], [], [], { projects: [{ ...p, failure: 'asking' }] }))
  assert.ok(failed.includes('届けられませんでした: 窓口が問いや確認の途中です'))
})

test('the line names the case and the item, says it is no approval, and stays on one line', () => {
  const p = project({ waiting: [{ text: 'レビュー待ち', next: null }] })
  const action = latestAction(p)
  assert.equal(actionText(p, action, { choice: 'resolved' }), '案件「Orca」（orca-setup.md）のWaiting「レビュー待ち」について、ユーザーの指示: 待ちが解けた（消して、→ のあとを TODO に移す）')
  assert.equal(actionText(p, action, { choice: 'go' }), null, 'a choice of the other kind')
  assert.match(actionText(p, action, { note: '先方に聞いて' }), /ユーザーの指示: 先方に聞いて$/)
  const line = orchestratorLine('a\nb\u202e c')
  assert.equal(line, `${PREFIX} a b c`)
  assert.equal(orchestratorLine('x'.repeat(2000)), null)
})

// The orchestrator's input box, as Claude Code draws it.
const PROMPT = '──────── orchestrator ─\n❯\n────────'

function orca({ terminals, state = 'done', sessions, agent = {}, screen = PROMPT }) {
  const sent = []
  const run = async (args) => {
    if (args[0] === 'terminal' && args[1] === 'list') return { result: { terminals } }
    if (args[0] === 'terminal' && args[1] === 'read') return { result: { terminal: { tail: [typeof screen === 'function' ? screen() : screen] } } }
    if (args[0] === 'worktree') {
      const extra = typeof agent === 'function' ? agent() : agent
      return { result: { worktrees: [{ path: HUB, agents: [{ paneKey: 't1:l1', conversationName: 'orchestrator', agentType: 'claude', state, hasLivePty: true, ...extra }] }] } }
    }
    if (args[0] === 'terminal' && args[1] === 'send') {
      sent.push(args)
      return { result: { send: { accepted: true } } }
    }
    throw new Error(`unexpected ${args.join(' ')}`)
  }
  return { run, sent, readSessions: async () => sessions }
}

const ORCH = { name: 'orchestrator', kind: 'interactive', alive: true, cwd: HUB, sessionId: 'sess-orch' }
const TERM = { handle: 'h1', title: 'orchestrator', agentIdentity: 'claude', writable: true, worktreePath: HUB, tabId: 't1', leafId: 'l1' }

test('the line goes only to the one orchestrator terminal, and only while it waits for a prompt', async () => {
  const ok = orca({ terminals: [TERM, { ...TERM, handle: 'h2', title: 'hub-49', tabId: 't2' }], sessions: [ORCH] })
  assert.deepEqual(await findOrchestrator({ ...ok, hubRoot: HUB }), { ok: true, reason: null, handle: 'h1', since: null })
  const send = createOrchestratorSender({ ...ok, hubRoot: HUB, sleep: async () => {} })
  assert.deepEqual(await send('案件の指示'), { sent: true, reason: null })
  assert.deepEqual(ok.sent.map((args) => args.slice(2, 6)), [['--terminal', 'h1', '--text', '\u0013'], ['--terminal', 'h1', '--text', `${PREFIX} 案件の指示`]])

  const moved = orca({ terminals: [TERM], sessions: [{ ...ORCH, cwd: '/tmp/elsewhere' }] })
  assert.equal((await findOrchestrator({ ...moved, hubRoot: HUB })).ok, true, 'the folder follows its shell and is not checked')
  const titled = orca({ terminals: [{ ...TERM, handle: 'h3', tabId: 't3' }, TERM], sessions: [ORCH] })
  assert.equal((await findOrchestrator({ ...titled, hubRoot: HUB })).handle, 'h1', 'the pane of the conversation, not a title')
  const covered = orca({ terminals: [TERM], sessions: [ORCH], screen: '~\n~\n"/private/tmp/claude-prompt-1.md" 3L' })
  assert.equal((await findOrchestrator({ ...covered, hubRoot: HUB })).reason, 'covered', 'an editor over it would take the keys')
  const staleTitle = orca({ terminals: [{ ...TERM, title: 'claude-prompt-1.md (/private/tmp) - Nvim' }], sessions: [ORCH] })
  assert.equal((await findOrchestrator({ ...staleTitle, hubRoot: HUB })).ok, true, 'the title an editor left behind does not matter')
  const none = orca({ terminals: [TERM], sessions: [] })
  assert.equal((await findOrchestrator({ ...none, hubRoot: HUB })).reason, 'no-orchestrator')
  const two = orca({ terminals: [TERM], sessions: [ORCH, { ...ORCH, sessionId: 'other' }] })
  assert.equal((await findOrchestrator({ ...two, hubRoot: HUB })).reason, 'many-orchestrators')
  const notMine = orca({ terminals: [TERM], sessions: [ORCH], agent: { conversationName: 'hub-49' } })
  assert.equal((await findOrchestrator({ ...notMine, hubRoot: HUB })).reason, 'not-in-orca')
  const otherWorkspace = orca({ terminals: [{ ...TERM, worktreePath: '/elsewhere' }], sessions: [ORCH] })
  assert.equal((await findOrchestrator({ ...otherWorkspace, hubRoot: HUB })).reason, 'not-in-hub')
  const asking = orca({ terminals: [TERM], state: 'waiting', sessions: [ORCH] })
  assert.equal((await findOrchestrator({ ...asking, hubRoot: HUB })).reason, 'asking', 'a menu would take the text')
  const sendAsking = createOrchestratorSender({ ...asking, hubRoot: HUB, sleep: async () => {} })
  assert.deepEqual(await sendAsking('x'), { sent: false, reason: 'asking' })
  assert.deepEqual(asking.sent, [], 'nothing is typed')
})

test('a working orchestrator is waited for, then refused', async () => {
  let clock = 0
  const busy = orca({ terminals: [TERM], state: 'working', sessions: [ORCH] })
  const send = createOrchestratorSender({ ...busy, hubRoot: HUB, sleep: async (ms) => { clock += ms }, now: () => clock })
  assert.deepEqual(await send('x'), { sent: false, reason: 'busy' })
  assert.ok(clock >= 180_000)
  assert.deepEqual(busy.sent, [])
})

test('lines go one at a time, and the next waits until the orchestrator took the one before', async () => {
  let since = 100
  const busy = orca({ terminals: [TERM], sessions: [ORCH], agent: () => ({ stateStartedAt: since }) })
  let clock = 0
  const channel = createOrchestratorChannel({ ...busy, hubRoot: HUB, sleep: async (ms) => { clock += ms; if (clock >= 6000) since = 200 }, now: () => clock })
  const [first, second] = await Promise.all([channel.send('一つ目'), channel.send('二つ目')])
  assert.deepEqual([first, second], [{ sent: true, reason: null }, { sent: true, reason: null }])
  const lines = busy.sent.filter((args) => args.includes('--enter')).map((args) => args[5])
  assert.deepEqual(lines, [`${PREFIX} 一つ目`, `${PREFIX} 二つ目`])
  assert.ok(clock >= 6000, 'the second waited for a new turn')
})

const ASKED = {
  toolUseId: 'toolu_1',
  questions: [{ question: '送りますか\n本文は下のとおり', header: '承認', multiSelect: false, options: [
    { label: '送る（推奨）', description: 'gh pr comment で送る', preview: '全文\u200bの本文\n2 行目' },
    { label: '見送る', description: '送らない' }
  ] }]
}

test('the question is read in full, and only while the orchestrator waits on AskUserQuestion', async () => {
  const waiting = orca({ terminals: [TERM], state: 'waiting', sessions: [ORCH], agent: { toolName: 'AskUserQuestion', stateStartedAt: 5 } })
  const channel = createOrchestratorChannel({ ...waiting, hubRoot: HUB, readPending: async (id) => (id === 'sess-orch' ? ASKED : null) })
  const offer = await channel.readQuestion()
  assert.equal(offer.kind, 'orchestrator-question')
  assert.deepEqual(offer.questions[0].options[0], { label: '送る（推奨）', description: 'gh pr comment で送る', preview: '全文\u200bの本文\n2 行目' }, 'nothing shortened')
  const html = renderHub(buildHubModel([], [], [], { orchestratorQuestion: offer }))
  assert.ok(html.includes(`<div class="ask full">${md('送りますか\n本文は下のとおり')}</div>`))
  assert.ok(html.includes('<pre class="preview">全文<span class="hidden-char">⟨U+200B⟩</span>の本文\n2 行目</pre>'))
  assert.ok(html.includes(`data-next="${offer.id}" data-index="1"`))
  const permission = orca({ terminals: [TERM], state: 'waiting', sessions: [ORCH], agent: { toolName: 'Bash' } })
  assert.equal(await createOrchestratorChannel({ ...permission, hubRoot: HUB, readPending: async () => ASKED }).readQuestion(), null)
  assert.equal(fullQuestions({ questions: [{ question: 'q', options: Array.from({ length: 10 }, (_, i) => ({ label: `o${i}` })) }] }), null, 'more options than keys')
})

test('an answer presses the menu keys once, and not after the question was answered at the terminal', async () => {
  let pending = ASKED
  const waiting = orca({ terminals: [TERM], state: 'waiting', sessions: [ORCH], agent: { toolName: 'AskUserQuestion', stateStartedAt: 5 } })
  const channel = createOrchestratorChannel({ ...waiting, hubRoot: HUB, readPending: async () => pending, sleep: async () => {} })
  const offer = await channel.readQuestion()
  assert.deepEqual(await channel.answer({ offer: offer.id, index: 1 }), { sent: true, reason: null })
  assert.deepEqual(waiting.sent.map((args) => args[5]), ['2'])
  assert.deepEqual(await channel.answer({ offer: offer.id, index: 0 }), { sent: false, reason: 'stale' }, 'answered once')
  pending = { ...ASKED, toolUseId: 'toolu_2' }
  const next = await channel.readQuestion()
  pending = null
  assert.deepEqual(await channel.answer({ offer: next.id, index: 0 }), { sent: false, reason: 'stale' }, 'answered at the terminal first')
  assert.deepEqual(waiting.sent.map((args) => args[5]), ['2'])
})

test('several questions or answers are ticked, then sent from the review page', () => {
  const two = fullQuestions({ questions: [
    { question: 'a', multiSelect: true, options: [{ label: 'x' }, { label: 'y' }] },
    { question: 'b', options: [{ label: 'z' }, { label: 'w' }] }
  ] })
  assert.deepEqual(questionKeys(two, { answers: [[0, 1], [1]] }), { keys: ['1', '2', '\t', '2'], review: true })
  assert.equal(questionKeys(two, { answers: [[0], [0, 1]] }), null, 'one answer for a single-select question')
  assert.equal(questionKeys(two, { index: 0 }), null)
})

test("the orchestrator's question for the panel shows in full, and an answer is written, then signalled", async () => {
  const { parseAsk, sha256 } = await import('../src/asks.mjs')
  const { createHubWorker } = await import('../src/hub-worker.mjs')
  const { signalLine } = await import('../src/orchestrator.mjs')
  const { mkdir, writeFile } = await import('node:fs/promises')
  const { join } = await import('node:path')
  const { makeHome } = await import('./helpers.mjs')
  const raw = { id: '20261119-180000-abcdef12', kind: 'question', created_at: 1, worker: 'orchestrator', session_id: 'sess-orch', question: '#809 への返信を送りますか', body: '本文 1 行目\n‮2 行目', options: [{ label: '送る', description: 'gh で送る' }, { label: '見送る', description: '' }], recommended: 1, approval: true }
  assert.equal(parseAsk({ ...raw, worker: 'impl-x' }), null, 'only the orchestrator asks it')
  const card = { ...parseAsk(raw), sha: 'a'.repeat(64), check: { ok: true, reason: null }, pressed: null, failure: null }
  const html = renderHub(buildHubModel([], [], [], { orchestratorAsks: [card] }))
  assert.ok(html.includes('<span class="q-header">承認の問い</span>'))
  assert.ok(html.includes('<div class="body"><div class="md"><div class="md-p"><div class="md-line">本文 1 行目</div><div class="md-line"><span class="hidden-char">⟨U+202E⟩</span>2 行目</div></div></div></div>'), 'the body whole, one text')
  assert.ok(html.includes(`data-answer data-id="${raw.id}" data-sha="${'a'.repeat(64)}" data-choice="1"`))
  assert.ok(html.includes(`data-ask="${raw.id}"`), 'a written answer too')
  assert.match(signalLine(raw.id), /^パネルの答え: 20261119-180000-abcdef12。python3 ~\/\.claude\/hooks\/asks\.py verify 20261119-180000-abcdef12 の出力だけを/)
  assert.equal(signalLine('x; rm -rf'), null)

  const home = await makeHome()
  const hubRoot = join(home, 'hub')
  const dir = join(hubRoot, 'state', 'asks')
  await mkdir(dir, { recursive: true })
  const bytes = JSON.stringify(raw)
  await writeFile(join(dir, `${raw.id}.json`), bytes)
  const calls = []
  const delivery = {
    check: async () => ({ ok: true }),
    take: async (ask, choice, text) => {
      calls.push(['take', choice, text])
      return 'taken'
    },
    send: async () => assert.fail('no resume for the orchestrator'),
    release: async () => calls.push(['release']),
    log: async () => {},
    logCase: async () => {}
  }
  const terminals = [TERM]
  const sent = []
  const runCli = async (_cli, args) => {
    if (args[0] === 'terminal' && args[1] === 'list') return { result: { terminals } }
    if (args[0] === 'worktree') return { result: { worktrees: [{ path: hubRoot, agents: [{ paneKey: 't1:l1', conversationName: 'orchestrator', agentType: 'claude', state: 'done', hasLivePty: true }] }] } }
    if (args[0] === 'terminal' && args[1] === 'read') return { result: { terminal: { tail: [PROMPT] } } }
    if (args[0] === 'terminal' && args[1] === 'send') {
      sent.push(args[5])
      return { result: { send: { accepted: true } } }
    }
    return { result: {} }
  }
  for (const t of terminals) t.worktreePath = hubRoot
  const orchestratorSession = { ...ORCH, cwd: hubRoot }
  const logs = []
  const hub = createHubWorker({
    orca: { log: (line) => logs.push(line), host: { call: async () => ({ workspaces: [] }) }, panels: { post: () => {} } },
    home, hubRoot, cli: 'orca', runCli, readOrca: async () => ({ active: null, agents: [], offers: [] }),
    readClaude: async () => [orchestratorSession], watchDir: () => {}, delivery, readCases: async () => []
  })
  const sha = sha256(Buffer.from(bytes))
  assert.deepEqual(await hub.answerAsk({ id: raw.id, sha, choice: 1 }), { ok: true })
  assert.deepEqual(calls, [['take', 1, null]])
  assert.deepEqual(sent.filter((line) => line !== '\u0013'), [signalLine(raw.id)], 'the line carries no answer')
  assert.ok(logs.some((line) => line.includes(`answered the orchestrator's question ${raw.id} (option 1)`)))
  for (const t of terminals) t.worktreePath = HUB
})

test("an answer the orchestrator could not be told of is kept, shown, and told once it can take it", async () => {
  const { sha256 } = await import('../src/asks.mjs')
  const { createHubWorker } = await import('../src/hub-worker.mjs')
  const { signalLine } = await import('../src/orchestrator.mjs')
  const { mkdir, writeFile, rm } = await import('node:fs/promises')
  const { join } = await import('node:path')
  const { makeHome } = await import('./helpers.mjs')
  const raw = { id: '20261120-111010-9aa7d52f', kind: 'question', created_at: 1, worker: 'orchestrator', session_id: 'sess-orch', question: '- とても長い問い', body: null, options: [{ label: '進める', description: '' }, { label: 'やめる', description: '' }], recommended: 1, approval: false }
  const home = await makeHome()
  const hubRoot = join(home, 'hub')
  const dir = join(hubRoot, 'state', 'asks')
  await mkdir(dir, { recursive: true })
  const bytes = JSON.stringify(raw)
  await writeFile(join(dir, `${raw.id}.json`), bytes)
  const answerFile = join(dir, `${raw.id}.answer` + '.json')
  const calls = []
  const delivery = {
    check: async () => ({ ok: true }),
    take: async () => {
      await writeFile(answerFile, '{}')
      return 'taken'
    },
    send: async () => assert.fail('no resume for the orchestrator'),
    release: async () => calls.push('release'),
    log: async () => {},
    logCase: async () => {}
  }
  // Orca does not know the orchestrator's pane at first (it runs outside Orca, say).
  let conversationName = 'something-else'
  const sent = []
  const runCli = async (_cli, args) => {
    if (args[0] === 'terminal' && args[1] === 'list') return { result: { terminals: [{ ...TERM, worktreePath: hubRoot }] } }
    if (args[0] === 'worktree') return { result: { worktrees: [{ path: hubRoot, agents: [{ paneKey: 't1:l1', conversationName, agentType: 'claude', state: 'done', hasLivePty: true }] }] } }
    if (args[0] === 'terminal' && args[1] === 'read') return { result: { terminal: { tail: [PROMPT] } } }
    if (args[0] === 'terminal' && args[1] === 'send') {
      sent.push(args[5])
      return { result: { send: { accepted: true } } }
    }
    return { result: {} }
  }
  let clock = 1_000_000
  const posted = []
  const logs = []
  const hub = createHubWorker({
    orca: { log: (line) => logs.push(line), host: { call: async () => ({ workspaces: [] }) }, panels: { post: (_name, body) => posted.push(body.html) } },
    home, hubRoot, cli: 'orca', runCli, now: () => clock, readOrca: async () => ({ active: null, agents: [], offers: [] }),
    readClaude: async () => [{ ...ORCH, cwd: '/somewhere/else' }], watchDir: () => {}, delivery, readCases: async () => []
  })
  const result = await hub.answerAsk({ id: raw.id, sha: sha256(Buffer.from(bytes)), choice: 1 })
  assert.equal(result.reason, 'kept')
  assert.match(result.message, /^答えは残しました。まだ窓口に知らせられていません: 窓口が Orca のターミナルの中に見つかりません。/)
  assert.deepEqual(calls, [], 'the answer is not given back')
  await hub.refresh(true)
  const kept = posted.at(-1)
  assert.ok(kept.includes('<div class="next orchestrator-question kept"'))
  assert.ok(kept.includes('<span class="label">進める</span>'))
  assert.ok(kept.includes(md('- とても長い問い')), 'the question as Markdown')
  assert.deepEqual(sent, [])

  conversationName = 'orchestrator'
  await hub.resignal()
  assert.deepEqual(sent, [], 'not again right away')
  clock += 30_000
  await hub.resignal()
  assert.deepEqual(sent.filter((line) => line !== '\u0013'), [signalLine(raw.id)])
  assert.ok(logs.some((line) => line.includes(`told the orchestrator of the kept answer to ${raw.id}`)))
  await hub.refresh(true)
  assert.ok(!posted.at(-1).includes('kept'), 'the card is gone once told')
  await rm(home, { recursive: true, force: true })
})
