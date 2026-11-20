// The orchestrator's permission dialogs that approval-gate.py writes as asks while it waits: their
// cards, and the answer the panel writes for the hook.
import assert from 'node:assert/strict'
import { mkdir, readdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { test } from 'node:test'
import { setUpActions } from '../panel/act.mjs'
import { checkAsk, parseAsk, readAsks, sha256 } from '../src/asks.mjs'
import { buildHubModel } from '../src/hub-model.mjs'
import { renderHub } from '../src/hub-render.mjs'
import { createHubWorker } from '../src/hub-worker.mjs'
import { makeHome } from './helpers.mjs'
import { view } from './mini-dom.mjs'

const NOW = 1_763_620_000
const ORCH = { sessionId: 'sess-orch', name: 'orchestrator', kind: 'interactive', cwd: '/h/hub' }

function permission(extra = {}) {
  return {
    id: '20261120-153012-1a2b3c4d', kind: 'permission', created_at: NOW, expires_at: NOW + 120, worker: 'orchestrator',
    session_id: 'sess-orch', job_id: null, cwd: '/h/hub', case: null, report: null, level: 'B',
    tool_name: 'Bash', tool_input: { command: 'make build\u202e', description: 'build する' }, agent_type: null, permission_mode: 'auto',
    ...extra
  }
}

function card(raw, extra = {}) {
  return { ...parseAsk(raw), sha: 'a'.repeat(64), check: { ok: true, reason: null }, pressed: null, failure: null, ...extra }
}

function press(html, pick, times = 1) {
  const root = view(html)
  const calls = []
  const notice = {}
  const composer = { hidden: true, addEventListener: () => {}, querySelector: () => ({ addEventListener: () => {}, focus: () => {}, value: '', textContent: '' }) }
  setUpActions({ view: root, notice, composer, request: async (name, params) => (calls.push([name, params]), { ok: true }) })
  const button = pick(root)
  assert.ok(button, 'the button is rendered')
  for (let i = 0; i < times; i += 1) root.click(button)
  return { calls, notice }
}

test('a permission is read only from the orchestrator, with the call whole and what it would do', () => {
  const ask = parseAsk(permission())
  assert.equal(ask.kind, 'permission')
  assert.deepEqual(ask.input, { command: 'make build\u202e', description: 'build する' })
  assert.equal(ask.expiresAt, (NOW + 120) * 1000)
  assert.equal(ask.risk, 'write')
  assert.equal(parseAsk(permission({ worker: 'impl-x' })), null, 'a worker never asks this way')
  assert.equal(parseAsk(permission({ tool_input: 'ls' })), null)
  assert.equal(parseAsk(permission({ tool_name: 'Bash; rm' })), null)
  assert.equal(parseAsk(permission({ expires_at: undefined })), null)
  assert.equal(parseAsk(permission({ tool_input: { command: 'x'.repeat(60000) } })), null, 'too long to show in full')
  assert.equal(parseAsk(permission({ tool_input: { command: 'rm -rf build' } })).dangerous, true)
  assert.equal(parseAsk(permission({ tool_input: { command: 'git push origin HEAD' } })).risk, 'outside')
})

test('a permission has buttons only for the orchestrator, until its time', () => {
  const ask = parseAsk(permission())
  assert.deepEqual(checkAsk(ask, [ORCH], NOW * 1000), { ok: true, reason: null })
  assert.deepEqual(checkAsk(ask, [{ ...ORCH, name: 'impl-x' }], NOW * 1000), { ok: false, reason: 'identity' })
  assert.deepEqual(checkAsk(ask, [ORCH], (NOW + 120) * 1000), { ok: false, reason: 'expired' })
})

test('the card shows the call in full, hidden characters made visible, and the four answers', () => {
  const html = renderHub(buildHubModel([], [], [], { orchestratorAsks: [card(permission())] }))
  assert.ok(html.includes('<h2>許可の確認<span class="risk write">書き換える</span>'))
  assert.ok(html.includes('<pre class="preview">make build<span class="hidden-char">⟨U+202E⟩</span></pre>'))
  assert.ok(html.includes('build する'))
  for (const choice of ['allow', 'deny', 'terminal']) assert.ok(html.includes(`data-answer data-permission data-id="20261120-153012-1a2b3c4d" data-sha="${'a'.repeat(64)}" data-choice="${choice}"`), choice)
  assert.ok(html.includes('data-to="許可の確認を拒否する理由" data-ask="20261120-153012-1a2b3c4d"'), 'deny with a reason')
  assert.match(html, /\d\d:\d\d:\d\d までに答えないと、窓口のターミナルに確認ダイアログが出ます/)

  const write = renderHub(buildHubModel([], [], [], { orchestratorAsks: [card(permission({ tool_name: 'Write', tool_input: { file_path: '/h/x.md', content: '1\n2\n' } }))] }))
  assert.ok(write.includes('<pre class="preview">/h/x.md</pre>') && write.includes('<pre class="preview">1\n2\n</pre>'))
  const mcp = renderHub(buildHubModel([], [], [], { orchestratorAsks: [card(permission({ tool_name: 'mcp__x__get_y', tool_input: { a: '<b>' } }))] }))
  assert.ok(mcp.includes('&lt;b&gt;'), 'escaped')
})

test('a call that reaches past this machine cannot be allowed from the card, and an expired one has no buttons', () => {
  const outside = renderHub(buildHubModel([], [], [], { orchestratorAsks: [card(permission({ tool_input: { command: 'git push origin HEAD' } }))] }))
  assert.ok(!outside.includes('data-choice="allow"'))
  assert.ok(outside.includes('data-choice="deny"'))
  assert.ok(outside.includes('外に出る操作です'))
  const expired = renderHub(buildHubModel([], [], [], { orchestratorAsks: [card(permission(), { check: { ok: false, reason: 'expired' } })] }))
  assert.ok(!expired.includes('data-answer'))
  assert.ok(expired.includes('期限が過ぎました'))
})

test('pressing sends the word; allowing a dangerous command takes a second press', () => {
  const html = renderHub(buildHubModel([], [], [], { orchestratorAsks: [card(permission())] }))
  const pick = (choice) => (root) => root.querySelectorAll('button').find((b) => b.dataset.choice === choice)
  assert.deepEqual(press(html, pick('deny')).calls, [['ask.answer', { id: '20261120-153012-1a2b3c4d', sha: 'a'.repeat(64), choice: 'deny' }]])
  const danger = renderHub(buildHubModel([], [], [], { orchestratorAsks: [card(permission({ tool_input: { command: 'rm -rf build' } }))] }))
  const once = press(danger, pick('allow'))
  assert.deepEqual(once.calls, [])
  assert.match(once.notice.textContent, /もう一度押して/)
  assert.deepEqual(press(danger, pick('allow'), 2).calls, [['ask.answer', { id: '20261120-153012-1a2b3c4d', sha: 'a'.repeat(64), choice: 'allow', confirmed: true }]])
})

async function hubWith(raw, { offers = [] } = {}) {
  const home = await makeHome()
  const hubRoot = join(home, 'hub')
  const dir = join(hubRoot, 'state', 'asks')
  await mkdir(dir, { recursive: true })
  const bytes = JSON.stringify(raw)
  await writeFile(join(dir, `${raw.id}.json`), bytes)
  const calls = []
  const delivery = {
    take: async (ask, choice, text) => (calls.push(['take', choice, text]), 'taken'),
    send: async () => assert.fail('nothing is sent to a session'),
    release: async () => assert.fail('nothing to give back'),
    log: async () => {},
    logCase: async () => {}
  }
  const posted = []
  const hub = createHubWorker({
    orca: { log: () => {}, host: { call: async () => ({ workspaces: [] }) }, panels: { post: (_n, body) => posted.push(body) } },
    home, hubRoot, cli: 'orca', now: () => NOW * 1000 + 1000,
    runCli: async () => assert.fail('nothing is typed into the orchestrator'),
    readOrca: async () => ({ active: { path: hubRoot, displayName: 'hub', agentStates: ['waiting'], background: false }, agents: [], offers: offers.map((offer) => ({ ...offer, path: offer.path ?? hubRoot })) }),
    readClaude: async () => [ORCH], watchDir: () => {}, delivery, readCases: async () => []
  })
  return { hub, calls, sha: sha256(Buffer.from(bytes)), dir, posted }
}

test('an answer is written for the hook through asks.py, and nothing is typed into the orchestrator', async () => {
  const { hub, calls, sha } = await hubWith(permission())
  assert.deepEqual(await hub.answerAsk({ id: permission().id, sha, choice: 'terminal' }), { ok: true })
  assert.deepEqual(await hub.answerAsk({ id: permission().id, sha, text: 'まだ' }), { ok: true })
  assert.deepEqual(calls, [['take', 'terminal', null], ['take', 'deny', 'まだ']])
  assert.deepEqual(await hub.answerAsk({ id: permission().id, sha, choice: 1 }), { ok: false, reason: 'invalid' })
  assert.deepEqual(await hub.answerAsk({ id: permission().id, sha, choice: 'maybe' }), { ok: false, reason: 'invalid' })
  assert.deepEqual(await hub.answerAsk({ id: permission().id, sha: '0'.repeat(64), choice: 'allow' }), { ok: false, reason: 'stale' })
})

test('the worker refuses to allow what the card does not offer', async () => {
  const outside = await hubWith(permission({ tool_input: { command: 'git push origin HEAD' } }))
  assert.deepEqual(await outside.hub.answerAsk({ id: permission().id, sha: outside.sha, choice: 'allow', confirmed: true }), { ok: false, reason: 'invalid' })
  const danger = await hubWith(permission({ tool_input: { command: 'rm -rf build' } }))
  assert.deepEqual(await danger.hub.answerAsk({ id: permission().id, sha: danger.sha, choice: 'allow' }), { ok: false, reason: 'confirm' })
  assert.deepEqual(await danger.hub.answerAsk({ id: permission().id, sha: danger.sha, choice: 'allow', confirmed: true }), { ok: true })
  assert.deepEqual(danger.calls, [['take', 'allow', null]])
  const expired = await hubWith(permission({ expires_at: NOW }))
  assert.deepEqual(await expired.hub.answerAsk({ id: permission().id, sha: expired.sha, choice: 'deny' }), { ok: false, reason: 'expired' })
  assert.deepEqual(expired.calls, [])
})

test("while a permission waits on the panel, the orchestrator's menu gets no card of its own", async () => {
  const offer = { kind: 'permission', id: 'o1', agent: 'claude', paneKey: 't1:l1', question: 'Bash を許可しますか？ make build', suggestions: [{ label: '許可', action: 'allow', detail: '今回だけ実行します' }] }
  const { hub, dir, posted } = await hubWith(permission(), { offers: [offer] })
  await hub.refresh(true)
  const html = posted.at(-1).html
  assert.ok(html.includes('data-permission'), 'the card of the ask')
  assert.ok(!html.includes('data-next="o1"'), 'no card that types into the menu')
  assert.equal((await readAsks(dir)).length, 1)
  assert.ok((await readdir(dir)).length === 1)
  // Without one, the menu's card is there as before.
  const before = await hubWith(permission({ expires_at: NOW }), { offers: [offer] })
  await before.hub.refresh(true)
  assert.ok(before.posted.at(-1).html.includes('data-next="o1"'))
})
