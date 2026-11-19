// A project's latest action, and handing the orchestrator a line from the panel.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { actionText, latestAction } from '../src/case-actions.mjs'
import { buildHubModel } from '../src/hub-model.mjs'
import { renderHub } from '../src/hub-render.mjs'
import { createOrchestratorSender, findOrchestrator, orchestratorLine } from '../src/orchestrator.mjs'
import { PREFIX } from '../src/deliver.mjs'

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
  assert.ok(failed.includes('窓口が問いや確認の途中なので'))
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

function orca({ terminals, state = 'done', sessions }) {
  const sent = []
  const run = async (args) => {
    if (args[0] === 'terminal' && args[1] === 'list') return { result: { terminals } }
    if (args[0] === 'worktree') return { result: { worktrees: [{ path: HUB, agents: [{ paneKey: 't1:l1', state, hasLivePty: true }] }] } }
    if (args[0] === 'terminal' && args[1] === 'send') {
      sent.push(args)
      return { result: { send: { accepted: true } } }
    }
    throw new Error(`unexpected ${args.join(' ')}`)
  }
  return { run, sent, readSessions: async () => sessions }
}

const ORCH = { name: 'orchestrator', kind: 'interactive', alive: true, cwd: HUB }
const TERM = { handle: 'h1', title: 'orchestrator', agentIdentity: 'claude', writable: true, worktreePath: HUB, tabId: 't1', leafId: 'l1' }

test('the line goes only to the one orchestrator terminal, and only while it waits for a prompt', async () => {
  const ok = orca({ terminals: [TERM, { ...TERM, handle: 'h2', title: 'hub-49', tabId: 't2' }], sessions: [ORCH] })
  assert.deepEqual(await findOrchestrator({ ...ok, hubRoot: HUB }), { ok: true, reason: null, handle: 'h1' })
  const send = createOrchestratorSender({ ...ok, hubRoot: HUB, sleep: async () => {} })
  assert.deepEqual(await send('案件の指示'), { sent: true, reason: null })
  assert.deepEqual(ok.sent.map((args) => args.slice(2, 6)), [['--terminal', 'h1', '--text', '\u0013'], ['--terminal', 'h1', '--text', `${PREFIX} 案件の指示`]])

  const twice = orca({ terminals: [TERM, { ...TERM, handle: 'h3' }], sessions: [ORCH] })
  assert.equal((await findOrchestrator({ ...twice, hubRoot: HUB })).reason, 'no-orchestrator', 'two terminals claim the title')
  const elsewhere = orca({ terminals: [TERM], sessions: [{ ...ORCH, cwd: '/tmp' }] })
  assert.equal((await findOrchestrator({ ...elsewhere, hubRoot: HUB })).reason, 'no-orchestrator')
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
