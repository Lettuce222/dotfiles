// The user's reply to an item on the desk: a line of its body by gtd.py note, and a line that tells
// the orchestrator there is one (never what it says).
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import { RETRY_MS, createReplyNotice, replyLine } from '../src/agent-items.mjs'
import { REPLY_SECTION, createDesk } from '../src/desk.mjs'
import { createHubWorker } from '../src/hub-worker.mjs'
import { deskKey } from '../desk/keys.mjs'
import { makeHome } from './helpers.mjs'

const root = join(import.meta.dirname, '..')

function deskWith() {
  const calls = []
  const told = []
  const gtd = async (args) => {
    calls.push(args)
    if (args[0] === 'json') return { today: '2026-11-24', counts: {}, items: [] }
    if (args[0] === 'cases') return { cases: [] }
    return { id: args[1], hash: 'h2' }
  }
  const desk = createDesk({
    gtd, hubRoot: '/nowhere', snapshot: () => ({ workers: [], asks: [], orchestrator: [] }),
    openFile: async () => true, focusWorker: async () => ({}), answerAsk: async () => ({ ok: true }),
    onReply: (id) => told.push(id), now: () => new Date(2026, 10, 24, 16, 40).getTime(), watchDir: () => ({ close() {} })
  })
  return { desk, calls, told }
}

test('a reply is one line of the item\'s body, dated, by user, and the orchestrator is told of the item', async () => {
  const { desk, calls, told } = deskWith()
  assert.equal(REPLY_SECTION, 'あなたの番への返事')
  assert.deepEqual(await desk.handlers.reply({ id: '20261124-a3f2', text: '方針は A 案で。\n期日は来週に --by agent' }), { id: '20261124-a3f2', hash: 'h2' })
  assert.deepEqual(calls.find((args) => args[0] === 'say'), ['say', '20261124-a3f2', '--text=方針は A 案で。 期日は来週に --by agent', '--by', 'user'], '--text=, so nothing in it is read as a flag; gtd.py dates it')
  assert.deepEqual(told, ['20261124-a3f2'])
})

test('an empty, too long or misaddressed reply is refused and tells nobody', async () => {
  const { desk, told } = deskWith()
  await assert.rejects(desk.handlers.reply({ id: '20261124-a3f2', text: '  \n ' }), /返事が空/)
  await assert.rejects(desk.handlers.reply({ id: '20261124-a3f2', text: 'x'.repeat(2001) }), /2000 字まで/)
  await assert.rejects(desk.handlers.reply({ id: '../x', text: 'a' }))
  await assert.rejects(desk.handlers.reply({ id: '20261124-a3f2' }), /2000 字まで/)
  assert.deepEqual(told, [])
})

test('the line names the items only, and says it is neither the user\'s instruction nor an approval', () => {
  assert.equal(replyLine(['20261124-a3f2', 'rm -rf ~']), 'Hub の知らせ: 20261124-a3f2 にユーザーの返事があります。python3 ~/.claude/skills/agents-orchestrator/scripts/gtd.py show <id> で読み、窓口のスキルの決まりのとおりに進めてください（この行はユーザーの指示でも承認でもありません）。')
  assert.equal(replyLine([]), null)
})

test('each reply is told as it comes, and tried again every 30 seconds while the orchestrator cannot take it', async () => {
  let clock = 1_000
  const sent = []
  const outcomes = [{ sent: false, reason: 'busy' }, { sent: true }]
  const n = createReplyNotice({ now: () => clock, send: async (ids) => (sent.push(ids), outcomes.shift() ?? { sent: true }) })
  n.add('a1')
  assert.deepEqual(await n.tell(), { told: [], waiting: 'busy' })
  assert.deepEqual(await n.tell(), { told: [], waiting: 'busy' }, 'not again right away')
  clock += RETRY_MS
  assert.deepEqual(await n.tell(), { told: ['a1'] })
  assert.deepEqual(await n.tell(), { told: [] })
  n.add('a1')
  assert.deepEqual(await n.tell(), { told: ['a1'] }, 'a second reply to the same item is told too')
  assert.deepEqual(sent, [['a1'], ['a1'], ['a1']])
  n.add('Bad id')
  assert.deepEqual(n.pending, [])
})

test('the worker types the line into the orchestrator\'s terminal', async () => {
  const home = await makeHome()
  const hubRoot = join(home, 'hub')
  await mkdir(join(hubRoot, 'state'), { recursive: true })
  const typed = []
  const runCli = async (_cli, args) => {
    if (args[0] === 'worktree') return { result: { worktrees: [{ path: hubRoot, agents: [{ paneKey: 't1:l1', conversationName: 'orchestrator', agentType: 'claude', state: 'done', hasLivePty: true }] }] } }
    if (args[0] === 'terminal' && args[1] === 'list') return { result: { terminals: [{ handle: 'h1', tabId: 't1', leafId: 'l1', agentIdentity: 'claude', worktreePath: hubRoot, writable: true }] } }
    if (args[0] === 'terminal' && args[1] === 'read') return { result: { terminal: { tail: ['───── orchestrator ─', '❯'] } } }
    if (args[0] === 'terminal' && args[1] === 'send') {
      typed.push(args[5])
      return { result: { send: { accepted: true } } }
    }
    return { result: {} }
  }
  const hub = createHubWorker({
    orca: { log: () => {}, host: { call: async () => ({ workspaces: [] }) }, panels: { post: () => {} } },
    home, hubRoot, cli: 'orca', runCli,
    readOrca: async () => ({ active: null, agents: [], offers: [] }),
    readClaude: async () => [{ sessionId: 'o', name: 'orchestrator', kind: 'interactive', alive: true }],
    watchDir: () => {}, readCases: async () => []
  })
  assert.deepEqual(await hub.noticeReply('a1'), { told: ['a1'] })
  assert.deepEqual(typed.filter((line) => line !== '\u0013'), [replyLine(['a1'])])
})

test('Enter goes into the box under the item, and v shows its worker', () => {
  const at = { pane: 'list', hasItem: true, lists: [['mine', 'あなたの番', 'y']] }
  assert.deepEqual(deskKey({ key: 'Enter', code: 'Enter', shiftKey: false }, at), { do: 'write' })
  assert.deepEqual(deskKey({ key: 'v', code: 'KeyV', shiftKey: false }, at), { do: 'agent' })
  assert.equal(deskKey({ key: 'Enter', code: 'Enter', shiftKey: false }, { ...at, hasItem: false }), null)
  const page = readFileSync(join(root, 'desk', 'desk.mjs'), 'utf8')
  assert.match(page, /if \(e\.isComposing \|\| e\.keyCode === 229 \|\| e\.shiftKey \|\| e\.altKey\) return/, 'no send while converting, and Shift+Enter is a new line')
  assert.match(page, /if \(!box\.value\.trim\(\)\) return/, 'an empty box sends nothing')
  assert.match(page, /if \(!e\.ctrlKey \|\| e\.metaKey \|\| e\.altKey \|\| e\.shiftKey \|\| e\.isComposing \|\| \(e\.key !== 'j' && e\.code !== 'KeyJ'\)\) return/, 'Ctrl+J')
  assert.match(page, /if \(box\.tagName === 'TEXTAREA' && !box\.disabled\) \{\n    box\.setRangeText\('\\n'/, 'a new line in a box of many lines, nothing in a one-line box')
  assert.match(page, /if \(e\.target\.tagName === 'TEXTAREA'\) \{\n    if \(e\.key === 'Escape'\) e\.target\.blur\(\)\n    return\n  \}/, 'no desk key while writing; Esc leaves the box')
})
