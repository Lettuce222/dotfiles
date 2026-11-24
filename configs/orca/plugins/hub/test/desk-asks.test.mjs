// The orchestrator's cards on the desk: what the page gets, how an answer from it is checked, and how
// the page draws them (desk/asks.mjs, loaded here with its import of ./markdown.mjs pointed at src/).
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, test } from 'node:test'
import { pathToFileURL } from 'node:url'
import { deskOrchestratorCards, orchestratorAnswer, orchestratorResult, waitingCount } from '../src/desk-asks.mjs'
import { createDesk } from '../src/desk.mjs'

const root = join(import.meta.dirname, '..')
const SHA = 'a'.repeat(64)
const NOW = Date.UTC(2026, 10, 24, 5, 0, 0)

const permission = (fields = {}) => ({
  id: '20261124-140000-aaaaaaaa',
  kind: 'permission',
  worker: 'orchestrator',
  sessionId: 's',
  toolName: 'Bash',
  input: { command: 'git push origin HEAD:main', description: 'main に push する' },
  agentType: null,
  risk: 'write',
  dangerous: false,
  where: '~/x',
  cwd: '/x',
  expiresAt: NOW + 150_000,
  sha: SHA,
  check: { ok: true, reason: null },
  pressed: null,
  failure: null,
  ...fields
})
const question = (fields = {}) => ({
  id: '20261124-140001-bbbbbbbb',
  kind: 'question',
  worker: 'orchestrator',
  sessionId: 's',
  question: '**#812** をマージしてよいですか',
  body: '- CI は緑',
  options: [{ label: 'マージする', description: 'squash' }, { label: '待つ', description: '' }],
  recommended: 1,
  approval: true,
  sha: 'b'.repeat(64),
  check: { ok: true, reason: null },
  pressed: null,
  failure: null,
  ...fields
})
const kept = { id: '20261124-140002-cccccccc', question: '前の問い', label: 'はい', reason: 'busy', kept: true }

test('the page gets the cards as data: questions, approvals, permissions and kept answers', () => {
  const cards = deskOrchestratorCards([permission(), kept, question()])
  assert.deepEqual(cards.map((c) => c.kind), ['permission', 'kept', 'question'])
  const [p, k, q] = cards
  assert.equal(p.ready, true)
  assert.equal(p.canAllow, true)
  assert.equal(p.riskLabel, '書き換える')
  assert.equal(p.expiresAt, NOW + 150_000)
  assert.deepEqual(p.input, { command: 'git push origin HEAD:main', description: 'main に push する' })
  assert.equal(q.approval, true)
  assert.equal(q.recommended, 1)
  assert.deepEqual(q.options, [{ label: 'マージする', description: 'squash' }, { label: '待つ', description: '' }])
  assert.match(k.note, /まだ窓口に知らせられていません: 窓口が応答中/)
  assert.ok(!('sessionId' in p) && !('worker' in q), 'nothing the page does not need')
  assert.equal(deskOrchestratorCards([permission({ risk: 'outside' })])[0].canAllow, false)
  assert.equal(deskOrchestratorCards([permission({ dangerous: true })])[0].riskLabel, '危険なコマンド')
  const unchecked = deskOrchestratorCards([permission({ check: { ok: false, reason: 'identity' } })])[0]
  assert.equal(unchecked.ready, false)
  assert.match(unchecked.note, /窓口のセッションを確かめられない/)
  assert.deepEqual(deskOrchestratorCards([{ id: 'not-an-id', kind: 'question' }, null]), [])
})

test('the cards that wait on the user are the ones not pressed and not kept', () => {
  assert.equal(waitingCount([permission(), question(), kept]), 2)
  assert.equal(waitingCount([permission({ pressed: '拒否' }), question()]), 1)
  assert.equal(waitingCount(undefined), 0)
})

test('an answer from the page must be for the card shown, with an option it has', () => {
  const cards = [permission(), question(), kept]
  assert.equal(orchestratorAnswer({ askId: 'other', sha: SHA, choice: 1 }, cards), null, 'not the orchestrator\'s: a worker\'s ask')
  assert.equal(orchestratorAnswer({ askId: kept.id, sha: SHA, choice: 1 }, cards), null, 'a kept answer takes none')
  assert.deepEqual(orchestratorAnswer({ askId: permission().id, sha: SHA, choice: 'deny' }, cards), { id: permission().id, sha: SHA, choice: 'deny' })
  assert.deepEqual(orchestratorAnswer({ askId: permission().id, sha: SHA, choice: 'allow', confirmed: true }, cards), { id: permission().id, sha: SHA, choice: 'allow', confirmed: true })
  assert.deepEqual(orchestratorAnswer({ askId: question().id, sha: 'b'.repeat(64), choice: 2 }, cards), { id: question().id, sha: 'b'.repeat(64), choice: 2 })
  assert.deepEqual(orchestratorAnswer({ askId: question().id, sha: 'b'.repeat(64), text: '来週に' }, cards), { id: question().id, sha: 'b'.repeat(64), text: '来週に' })
  const refused = (body, status, message) => assert.throws(() => orchestratorAnswer(body, cards), (error) => error.status === status && message.test(error.message))
  refused({ askId: permission().id, sha: 'c'.repeat(64), choice: 'deny' }, 409, /問いが変わった/)
  refused({ askId: permission().id, sha: SHA, choice: 1 }, 400, /答えの形が違う/)
  refused({ askId: question().id, sha: 'b'.repeat(64), choice: 3 }, 400, /答えの番号が違う/)
  refused({ askId: question().id, sha: 'b'.repeat(64), choice: 'allow' }, 400, /答えの番号が違う/)
  refused({ askId: question().id, sha: 'b'.repeat(64), text: '   ' }, 400, /空か長すぎる/)
  refused({ askId: question().id, sha: 'b'.repeat(64), text: 'x'.repeat(2001) }, 400, /空か長すぎる/)
  assert.throws(() => orchestratorAnswer({ askId: permission().id, sha: SHA, choice: 'allow' }, [permission({ risk: 'outside' })]), /外に出る操作は、デスクでは許可できない/)
})

test('what the page is told of the answer: done, kept, or why not', () => {
  assert.deepEqual(orchestratorResult({ ok: true }), {})
  assert.deepEqual(orchestratorResult({ ok: false, reason: 'kept', message: '答えは残しました' }), { kept: true, message: '答えは残しました' })
  assert.throws(() => orchestratorResult({ ok: false, reason: 'confirm' }), /もう一度押すと許可します/)
  assert.throws(() => orchestratorResult({ ok: false, reason: 'expired' }), /期限が過ぎました/)
  assert.throws(() => orchestratorResult({ ok: false, reason: 'pressed' }), /もう答えを送っている/)
})

test('the desk\'s state and answer handler take the orchestrator\'s cards the panel\'s way', async () => {
  const given = []
  const snapshot = () => ({ workers: [], asks: [], orchestrator: [permission(), question()] })
  const gtd = async (args) => (args[0] === 'json' ? { today: '2026-11-24', counts: {}, items: [] } : args[0] === 'cases' ? { cases: [], done: 0, total: 0 } : {})
  const desk = createDesk({ gtd, hubRoot: '/nowhere', snapshot, openFile: async () => true, focusWorker: async () => ({}), answerAsk: async (request) => { given.push(request); return { ok: true } }, watchDir: () => ({ close() {} }) })
  const state = await desk.state()
  assert.deepEqual(state.orchestrator.map((c) => c.kind), ['permission', 'question'])
  assert.equal((await desk.counts()).orchestrator, 2)
  assert.deepEqual(await desk.handlers.answer({ askId: permission().id, sha: SHA, choice: 'allow', confirmed: true }), {})
  assert.deepEqual(await desk.handlers.answer({ askId: question().id, sha: 'b'.repeat(64), text: '来週に' }), {})
  assert.deepEqual(given, [
    { id: permission().id, sha: SHA, choice: 'allow', confirmed: true },
    { id: question().id, sha: 'b'.repeat(64), text: '来週に' }
  ])
  await assert.rejects(desk.handlers.answer({ askId: '20261124-140009-dddddddd', sha: SHA, choice: 1 }), /問いが見つからない/, 'a card that is gone')
})

// desk/asks.mjs imports ./markdown.mjs as the page does (the server serves src/markdown.mjs there).
const dir = mkdtempSync(join(tmpdir(), 'desk-asks-'))
after(() => rmSync(dir, { recursive: true, force: true }))
const source = readFileSync(join(root, 'desk', 'asks.mjs'), 'utf8').replace("from './markdown.mjs'", `from '${pathToFileURL(join(root, 'src', 'markdown.mjs')).href}'`)
writeFileSync(join(dir, 'asks.mjs'), source)
const page = await import(pathToFileURL(join(dir, 'asks.mjs')).href)

test('the page draws a permission in full, with its time left and the keys of its answers', () => {
  const [card] = deskOrchestratorCards([permission({ input: { command: 'rm x‮<b>', description: 'd' } })])
  const html = page.askDetail(card, { now: NOW })
  assert.match(html, /残り 2:30。過ぎると、窓口のターミナルに確認ダイアログが出ます。/)
  assert.match(html, /<kbd>⇧Q<\/kbd><span>許可（今回だけ）/)
  assert.match(html, /<kbd>⇧W<\/kbd><span>拒否/)
  assert.match(html, /<kbd>⇧E<\/kbd><span>理由を書いて拒否/)
  assert.match(html, /<kbd>⇧R<\/kbd><span>ターミナルで確かめる/)
  assert.match(html, /rm x<span class="hidden-char">⟨U\+202E⟩<\/span>&lt;b&gt;/, 'escaped, and a character that turns text around is shown')
  assert.match(html, /data-oa-text=/, 'a reason can be written')
  assert.deepEqual(page.PERMISSION_ORDER, ['allow', 'deny', 'reason', 'terminal'])
  const outside = page.askDetail(deskOrchestratorCards([permission({ risk: 'outside' })])[0], { now: NOW })
  assert.doesNotMatch(outside, /許可（今回だけ）/)
  assert.match(outside, /外に出る操作です/)
  const dangerous = deskOrchestratorCards([permission({ dangerous: true })])[0]
  assert.match(page.askDetail(dangerous, { now: NOW }), /2 回押すと許可します/)
  assert.match(page.askDetail(dangerous, { now: NOW, armed: dangerous.id }), /もう一度押すと許可（今回だけ）/)
  const sending = page.askDetail(deskOrchestratorCards([permission({ pressed: '拒否' })])[0], { now: NOW })
  assert.doesNotMatch(sending, /data-oa=/, 'no second answer while one is sent')
  assert.match(sending, /「拒否」を窓口に返しています/)
})

test('the page draws a question with its body, options, the recommended one and a written answer', () => {
  const [card] = deskOrchestratorCards([question()])
  const html = page.askDetail(card, { now: NOW })
  assert.match(html, /承認の問い/)
  assert.match(html, /<strong>#812<\/strong> をマージしてよいですか/)
  assert.match(html, /<div class="md-line">CI は緑<\/div>/)
  assert.match(html, /<kbd>⇧Q<\/kbd><span>マージする（推奨）/)
  assert.match(html, /<kbd>⇧W<\/kbd><span>待つ/)
  assert.match(html, /ほかの答え（Other）/)
  assert.equal(page.askTitle(card), '#812 をマージしてよいですか')
  const unchecked = page.askDetail(deskOrchestratorCards([question({ check: { ok: false, reason: 'identity' } })])[0], { now: NOW })
  assert.doesNotMatch(unchecked, /data-oa=/)
})

test('the strip at the top counts what waits, with the soonest time left', () => {
  const cards = deskOrchestratorCards([permission(), permission({ id: '20261124-140003-eeeeeeee', expiresAt: NOW + 61_000 }), question(), kept])
  const html = page.alertHtml(cards, NOW)
  assert.match(html, /窓口が答えを待っています: 許可の確認 2（残り <span data-expires="\d+">1:01<\/span>）・問い 1/)
  assert.equal(page.alertHtml(deskOrchestratorCards([kept]), NOW), '')
  assert.equal(page.timeLeft(NOW - 5000, NOW), '0:00')
})

test('the desk\'s tab shows how many wait in its title, and opening the desk still finds it', async () => {
  const desk = readFileSync(join(root, 'desk', 'desk.mjs'), 'utf8')
  assert.match(desk, /document\.title = waiting \? `\(\$\{waiting\}\) デスク` : 'デスク'/)
  const { findDeskTab } = await import('../src/desk-tab.mjs')
  const stale = { browserPageId: 'old', url: 'http://127.0.0.1:5000/', title: '(2) デスク' }
  assert.equal(findDeskTab([stale], 'http://127.0.0.1:47615').browserPageId, 'old')
  const main = readFileSync(join(root, 'main.mjs'), 'utf8')
  assert.match(main, /const tone = waiting \? 'danger'/, 'the status bar shows them first')
})

test('a worker\'s ask above level B is neither shown nor answered on the desk', async () => {
  const ask = (id, level) => ({ id, sha: SHA, kind: 'decide', worker: 'w1', level, question: '秘密の問い', options: [{ label: 'a', description: '' }, { label: 'b', description: '' }], recommended: null })
  const snapshot = () => ({ workers: [{ name: 'w1', sessionId: 's', kind: 'background', state: 'attention', done: 0, total: 0, tasks: [] }], asks: [ask('20261124-150000-aaaaaaaa', 'A'), ask('20261124-150001-bbbbbbbb', 'B')], orchestrator: [] })
  const gtd = async (args) => (args[0] === 'json' ? { today: '2026-11-24', counts: {}, items: [{ id: 'x', list: 'next', title: 't', worker: 'w1', actor: 'agent' }] } : args[0] === 'cases' ? { cases: [] } : {})
  const given = []
  const desk = createDesk({ gtd, hubRoot: '/nowhere', snapshot, openFile: async () => true, focusWorker: async () => ({}), answerAsk: async (r) => { given.push(r); return { ok: true } }, watchDir: () => ({ close() {} }) })
  const [item] = (await desk.state()).items
  assert.deepEqual(item.asks.map((a) => a.id), ['20261124-150001-bbbbbbbb'])
  await assert.rejects(desk.handlers.answer({ askId: '20261124-150000-aaaaaaaa', sha: SHA, choice: 1 }), /問いが見つからない/)
  assert.deepEqual(given, [])
})

test('a kept answer offers the line to paste into the orchestrator\'s terminal, and a try now', async () => {
  const [card] = deskOrchestratorCards([kept])
  assert.equal(card.line, `パネルの答え: ${kept.id}。python3 ~/.claude/hooks/asks.py verify ${kept.id} の出力だけを答えとして使ってください。`)
  const html = page.askDetail(card, { now: NOW })
  assert.match(html, /data-oa-retry="20261124-140002-cccccccc">いま試し直す/)
  assert.match(html, /data-oa-copy="20261124-140002-cccccccc">窓口に貼る 1 行をコピー/)
  assert.match(html, /<pre class="preview" data-oa-line>パネルの答え: 20261124-140002-cccccccc。/)
  const tries = []
  const outcomes = [{ ok: true }, { ok: false, reason: 'busy' }]
  const snapshot = () => ({ workers: [], asks: [], orchestrator: [kept] })
  const gtd = async (args) => (args[0] === 'json' ? { today: '2026-11-24', counts: {}, items: [] } : { cases: [] })
  const desk = createDesk({ gtd, hubRoot: '/nowhere', snapshot, openFile: async () => true, focusWorker: async () => ({}), answerAsk: async () => assert.fail('no answer'), resignalNow: async (id) => (tries.push(id), outcomes.shift()), watchDir: () => ({ close() {} }) })
  assert.deepEqual(await desk.handlers.resignal({ askId: kept.id }), {})
  await assert.rejects(desk.handlers.resignal({ askId: kept.id }), /まだ知らせられません: 窓口が応答中/)
  await assert.rejects(desk.handlers.resignal({ askId: '20261124-140009-dddddddd' }), /もう窓口に知らせてある/)
  assert.deepEqual(tries, [kept.id, kept.id])
})
