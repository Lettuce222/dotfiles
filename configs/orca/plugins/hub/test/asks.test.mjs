// The asks workers write with asks.py, as cards in their rows, and how an answer reaches the worker.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { test } from 'node:test'
import { checkAsk, parseAsk, readAsks, sha256 } from '../src/asks.mjs'
import { PREFIX, answerText, createDelivery, refusal, writtenAnswerText } from '../src/deliver.mjs'
import { buildHubModel } from '../src/hub-model.mjs'
import { renderHub } from '../src/hub-render.mjs'
import { createHubWorker } from '../src/hub-worker.mjs'
import { makeHome } from './helpers.mjs'
import { renderMarkdown as md } from '../src/markdown.mjs'

const ID = '20261119-160000-deadbeef'
const SESSION = 'sess-worker'

function rawAsk(extra = {}) {
  return {
    id: ID,
    kind: 'decide',
    created_at: 1795068000,
    worker: 'impl-x',
    session_id: SESSION,
    cwd: '/Users/me/hub/workers/impl-x',
    case: 'orca-setup',
    report: null,
    level: 'B',
    question: '設定をどこに置きますか',
    options: [{ label: 'configs/x', description: 'configs/x に置く' }, { label: 'configs/y', description: 'configs/y に置く' }],
    recommended: 1,
    ...extra
  }
}

const worker = (extra = {}) => ({ sessionId: SESSION, id: 'aaaaaaaa', name: 'impl-x', kind: 'background', cwd: '/Users/me/hub/workers/impl-x', state: 'blocked', status: 'idle', waitingFor: null, alive: true, startedAt: 1, job: { state: 'blocked', needs: '設定の置き場所を決めてください', inFlight: 0, updatedAt: 1 }, report: null, ...extra })

test('an ask is read only in the shape asks.py writes, and offers buttons only to the worker it names', () => {
  const ask = parseAsk(rawAsk())
  assert.equal(ask.question, '設定をどこに置きますか')
  assert.equal(parseAsk(rawAsk({ options: [{ label: 'a', description: 'b' }] })), null, 'two options at least')
  assert.equal(parseAsk(rawAsk({ question: 'q‮' })), null, 'no hidden characters')
  assert.equal(parseAsk(rawAsk({ worker: 'orchestrator' })), null)
  assert.deepEqual(checkAsk(ask, [worker()]), { ok: true, reason: null })
  assert.deepEqual(checkAsk(ask, [worker({ name: 'impl-y' })]), { ok: false, reason: 'identity' })
  assert.deepEqual(checkAsk({ ...ask, level: 'A' }, [worker()]), { ok: false, reason: 'level' })
})

test('readAsks skips answered asks and keeps the hash of the bytes', async () => {
  const dir = join(await makeHome(), 'asks')
  await mkdir(dir, { recursive: true })
  const bytes = JSON.stringify(rawAsk())
  await writeFile(join(dir, `${ID}.json`), bytes)
  const [ask] = await readAsks(dir)
  assert.equal(ask.sha, sha256(Buffer.from(bytes)))
  await writeFile(join(dir, `${ID}.answer.json`), '{}')
  assert.deepEqual(await readAsks(dir), [])
})

test('the ask shows inside its worker row, which waits for the user, with every option and another answer', () => {
  const card = { ...parseAsk(rawAsk()), sha: 'f'.repeat(64), check: { ok: true, reason: null }, pressed: null }
  const orphan = { ...card, id: '20261119-160000-0badf00d', sessionId: 'sess-gone' }
  const model = buildHubModel([worker({ state: 'done', job: null })], [], [], { cards: [card, orphan] })
  assert.equal(model.attention.length, 1)
  assert.equal(model.attention[0].card.id, ID)
  assert.deepEqual(model.cards.map((c) => c.sessionId), ['sess-gone'], 'only an ask without a row shows on its own')
  const html = renderHub(model)
  const start = html.indexOf('<div class="group attention">')
  const next = html.indexOf('<div class="group', start + 1)
  const row = html.slice(start, next === -1 ? undefined : next)
  assert.ok(row.includes(`<div class="ask">${md('設定をどこに置きますか')}</div>`))
  assert.ok(row.includes(`data-answer data-id="${ID}" data-sha="${'f'.repeat(64)}" data-choice="1"><span class="label">1. configs/x<span class="recommended">推奨</span></span><span class="detail">${md('configs/x に置く')}</span>`))
  assert.ok(row.includes(`class="action other" data-say="${SESSION}" data-name="impl-x" data-ask="${ID}"`))
})

test('the text a worker gets says it comes from the panel and is no approval', () => {
  const ask = parseAsk(rawAsk())
  assert.equal(answerText(ask, 2), '要判断「設定をどこに置きますか」への答え: 2. configs/y: configs/y に置く')
  assert.equal(answerText(ask, 3), null)
  assert.match(writtenAnswerText(ask, 'configs/z に置く'), /ユーザーが書いた答え）: configs\/z に置く$/)
  assert.match(PREFIX, /承認ではありません/)
})

test('only a background worker that is not working takes text, and an idle one is stopped first', async () => {
  assert.equal(refusal(null, null), 'gone')
  assert.equal(refusal(worker({ name: 'orchestrator' }), null), 'not-worker')
  assert.equal(refusal(worker({ kind: 'interactive' }), null), 'not-worker')
  assert.equal(refusal(worker({ status: 'busy' }), null), 'busy')
  assert.equal(refusal(worker(), { inFlight: 1 }), 'busy')
  assert.equal(refusal(worker(), { inFlight: 0 }), null)

  let alive = true
  const runs = []
  const delivery = createDelivery({
    home: '/Users/me',
    hubRoot: await makeHome(),
    claudeCli: 'claude',
    python: 'python3',
    readSessions: async () => [worker({ alive })],
    readJob: async () => ({ inFlight: 0 }),
    run: async (file, args, options) => {
      runs.push([file, ...args, options?.cwd ?? ''])
      if (args[0] === 'stop') alive = false
      return { code: 0, stdout: '', stderr: '' }
    },
    sleep: async () => {}
  })
  assert.deepEqual(await delivery.send(SESSION, '答え'), { sent: true, reason: null })
  assert.deepEqual(runs, [
    ['claude', 'stop', 'aaaaaaaa', ''],
    ['claude', '--bg', '--resume', SESSION, '-n', 'impl-x', '--permission-mode', 'auto', `${PREFIX}\n答え`, '/Users/me/hub/workers/impl-x']
  ])
})

test('a written answer takes the ask once and reaches the worker; a changed ask is not answered', async () => {
  const home = await makeHome()
  const hubRoot = join(home, 'hub')
  const dir = join(hubRoot, 'state', 'asks')
  await mkdir(dir, { recursive: true })
  const bytes = JSON.stringify(rawAsk())
  await writeFile(join(dir, `${ID}.json`), bytes)
  const calls = []
  const delivery = {
    check: async () => ({ ok: true, reason: null }),
    take: async (ask, choice) => {
      calls.push(['take', ask.id, choice])
      return 'taken'
    },
    send: async (sessionId, text) => {
      calls.push(['send', sessionId, text])
      return { sent: true, reason: null }
    },
    release: async () => calls.push(['release']),
    log: async () => {},
    logCase: async () => {}
  }
  const orca = { log: () => {}, host: { call: async () => ({}) }, panels: { post: () => {} } }
  const hub = createHubWorker({ orca, home, hubRoot, cli: 'orca', readClaude: async () => [worker()], watchDir: () => {}, delivery })
  const sha = sha256(Buffer.from(bytes))
  assert.deepEqual(await hub.answerAsk({ id: ID, sha: '0'.repeat(64), text: 'x' }), { ok: false, reason: 'stale' })
  assert.deepEqual(await hub.answerAsk({ id: ID, sha, text: '  ' }), { ok: false, reason: 'invalid' })
  assert.deepEqual(await hub.answerAsk({ id: ID, sha, text: 'configs/z に置く' }), { ok: true })
  assert.deepEqual(calls, [
    ['take', ID, 'written'],
    ['send', SESSION, '要判断「設定をどこに置きますか」への答え（選択肢ではなく、ユーザーが書いた答え）: configs/z に置く']
  ])
})

test('a worker still in its turn is waited for, and one that never ends it is refused', async () => {
  assert.equal(refusal(worker({ state: 'working', status: 'idle' }), { inFlight: 0 }), null, 'state can say working after the turn')
  let polls = 0
  let clock = 0
  const runs = []
  const make = (busyFor) =>
    createDelivery({
      home: '/Users/me',
      hubRoot: '/tmp/hub',
      claudeCli: 'claude',
      python: 'python3',
      readSessions: async () => [worker({ status: (polls += 1) <= busyFor ? 'busy' : 'idle', alive: false })],
      readJob: async () => ({ inFlight: 0 }),
      run: async (file, args) => {
        runs.push(args[0])
        return { code: 0, stdout: '', stderr: '' }
      },
      sleep: async (ms) => {
        clock += ms
      },
      now: () => clock
    })
  assert.deepEqual(await make(3).send(SESSION, '答え'), { sent: true, reason: null })
  assert.deepEqual(runs, ['--bg'])
  polls = 0
  runs.length = 0
  assert.deepEqual(await make(Infinity).send(SESSION, '答え'), { sent: false, reason: 'busy' })
  assert.deepEqual(runs, [], 'nothing runs for a worker that stays busy')
})

test('a pressed answer shows at once in place of the options, and a failure says why and gives them back', () => {
  const card = { ...parseAsk(rawAsk()), sha: 'f'.repeat(64), check: { ok: true, reason: null }, pressed: 'configs/x', failure: null }
  const sending = renderHub(buildHubModel([worker()], [], [], { cards: [card] }))
  assert.ok(sending.includes('<div class="row-card next sending"'))
  assert.ok(sending.includes('<span class="label">configs/x</span><span class="detail">届けています…'))
  assert.ok(!sending.includes('data-answer'), 'no option to press twice')
  const failed = renderHub(buildHubModel([worker()], [], [], { cards: [{ ...card, pressed: null, failure: 'busy' }] }))
  assert.ok(failed.includes('data-answer'))
  assert.ok(failed.includes('<p class="status">worker が作業を終えないので'))
})

test('an answer that is not delivered is logged, gives the ask back and says why in the row', async () => {
  const home = await makeHome()
  const hubRoot = join(home, 'hub')
  const dir = join(hubRoot, 'state', 'asks')
  await mkdir(dir, { recursive: true })
  const bytes = JSON.stringify(rawAsk())
  await writeFile(join(dir, `${ID}.json`), bytes)
  const logs = []
  const calls = []
  const delivery = {
    check: async () => ({ ok: true, reason: null }),
    take: async () => 'taken',
    send: async () => ({ sent: false, reason: 'resume-failed', detail: 'no such session' }),
    release: async () => calls.push('release'),
    log: async () => {},
    logCase: async () => {}
  }
  const posts = []
  const orca = { log: (line) => logs.push(line), host: { call: async () => ({ workspaces: [] }) }, panels: { post: (_e, payload) => posts.push(payload.html) } }
  const hub = createHubWorker({ orca, home, hubRoot, cli: 'orca', readOrca: async () => ({ active: null, agents: [], offers: [] }), readClaude: async () => [worker()], watchDir: () => {}, delivery })
  const sha = sha256(Buffer.from(bytes))
  assert.deepEqual(await hub.answerAsk({ id: ID, sha, choice: 1 }), { ok: false, reason: 'resume-failed' })
  assert.deepEqual(calls, ['release'])
  assert.ok(logs.some((line) => line.includes(`the answer to ${ID} was not delivered: resume-failed (no such session)`)))
  await hub.refresh(true)
  assert.ok(posts.at(-1).includes('worker を続けられず'))
})

test('a row that needs the user without an ask offers a line to the worker, or says where to answer', () => {
  const html = renderHub(buildHubModel([worker(), worker({ sessionId: 'sess-orch', id: null, name: 'orchestrator', kind: 'interactive', job: null, waitingFor: 'permission' })], [], [], {}))
  assert.ok(html.includes(`class="action other" data-say="${SESSION}" data-name="impl-x"><span class="label">指示を書く</span>`))
  assert.ok(!html.includes('data-ask='), 'no ask to answer')
  assert.ok(html.includes('<p class="hint answer-elsewhere">そのセッションの画面で答えてください</p>'))
})
