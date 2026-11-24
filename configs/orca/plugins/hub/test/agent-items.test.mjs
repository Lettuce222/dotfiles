// Items in 次の行動 by an agent with no worker: the orchestrator is told of each once.
import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { test } from 'node:test'
import { GRACE_MS, RETRY_MS, agentItemsLine, createAgentItemNotice, unassignedAgentItems } from '../src/agent-items.mjs'
import { createDesk } from '../src/desk.mjs'
import { createHubWorker } from '../src/hub-worker.mjs'
import { makeHome } from './helpers.mjs'

const item = (id, fields = {}) => ({ id, list: 'next', actor: 'agent', worker: null, title: 't', ...fields })

test('the items that wait for a worker are in next, by an agent, with no worker', () => {
  const items = [
    item('a1'),
    item('a2', { worker: 'impl-x' }),
    item('a3', { actor: 'me' }),
    item('a4', { list: 'inbox' }),
    item('Bad id'),
    item('a5', { worker: '' })
  ]
  assert.deepEqual(unassignedAgentItems(items), ['a1', 'a5'])
  assert.deepEqual(unassignedAgentItems(undefined), [])
})

test('the line names the ids only, and says it is neither the user\'s instruction nor an approval', () => {
  const line = agentItemsLine(['20261124-a3f2', 'evil; rm -rf ~', 'b1'])
  assert.equal(line, 'Hub の知らせ: 次の行動に、worker の決まっていない agent の項目があります: 20261124-a3f2、b1。python3 ~/.claude/skills/agents-orchestrator/scripts/gtd.py show <id> で読み、窓口のスキルの決まりのとおりに進めてください（この行はユーザーの指示でも承認でもありません）。')
  assert.equal(agentItemsLine([]), null)
  assert.ok(!line.includes('\n'))
})

function notice({ told = [], outcomes = [] } = {}) {
  let clock = 1_000_000
  const sent = []
  const written = []
  const n = createAgentItemNotice({
    now: () => clock,
    readTold: async () => told,
    writeTold: async (ids) => written.push(ids),
    send: async (ids) => (sent.push(ids), outcomes.shift() ?? { sent: true, reason: null })
  })
  return { n, sent, written, tick: (ms) => (clock += ms) }
}

test('an item is told once, after it has waited, with the ones told kept for a restart', async () => {
  const { n, sent, written, tick } = notice({ told: ['old'] })
  n.update(['a1', 'old'])
  assert.deepEqual(await n.tell(), { told: [] }, 'not before the grace: the orchestrator may assign it itself')
  tick(GRACE_MS)
  assert.deepEqual(await n.tell(), { told: ['a1'] })
  assert.deepEqual(sent, [['a1']], 'one told before is not told again')
  assert.deepEqual(written, [['old', 'a1']])
  tick(GRACE_MS)
  assert.deepEqual(await n.tell(), { told: [] }, 'once')
  assert.deepEqual(sent.length, 1)
})

test('an item assigned within the grace is never told', async () => {
  const { n, sent, tick } = notice()
  n.update(['a1'])
  tick(GRACE_MS - 1)
  n.update([])
  tick(GRACE_MS)
  assert.deepEqual(await n.tell(), { told: [] })
  assert.deepEqual(sent, [])
})

test('a line that could not reach the orchestrator is tried again after 30 seconds, as the answers are', async () => {
  const { n, sent, tick } = notice({ outcomes: [{ sent: false, reason: 'busy' }] })
  n.update(['a1'])
  tick(GRACE_MS)
  assert.deepEqual(await n.tell(), { told: [], waiting: 'busy' })
  assert.deepEqual(await n.tell(), { told: [], waiting: 'busy' }, 'not again right away')
  tick(RETRY_MS)
  n.update(['a1', 'a2'])
  tick(GRACE_MS)
  assert.deepEqual(await n.tell(), { told: ['a1', 'a2'] })
  assert.deepEqual(sent, [['a1'], ['a1', 'a2']])
})

test('the desk counts the items that wait for a worker, whoever moved them there', async () => {
  const items = [item('a1'), item('a2', { worker: 'impl-x' })]
  const gtd = async (args) => (args[0] === 'json' ? { today: '2026-11-24', counts: {}, items } : { cases: [] })
  const desk = createDesk({ gtd, hubRoot: '/nowhere', snapshot: () => ({ workers: [], asks: [], orchestrator: [] }), openFile: async () => true, focusWorker: async () => ({}), answerAsk: async () => ({ ok: true }), watchDir: () => ({ close() {} }) })
  assert.deepEqual((await desk.counts()).agentItems, ['a1'])
})

test('the worker tells the orchestrator in its terminal and keeps what it told in the hub', async () => {
  const home = await makeHome()
  const hubRoot = join(home, 'hub')
  await mkdir(join(hubRoot, 'state'), { recursive: true })
  let clock = 5_000_000
  const typed = []
  const runCli = async (_cli, args) => {
    if (args[0] === 'worktree') return { result: { worktrees: [{ path: hubRoot, agents: [{ paneKey: 't1:l1', conversationName: 'orchestrator', agentType: 'claude', state: 'done', hasLivePty: true }] }] } }
    if (args[0] === 'terminal' && args[1] === 'list') return { result: { terminals: [{ handle: 'h1', tabId: 't1', leafId: 'l1', agentIdentity: 'claude', worktreePath: hubRoot, writable: true }] } }
    if (args[0] === 'terminal' && args[1] === 'read') return { result: { terminal: { tail: ['─────── ● high · /effort  orchestrator ─', '❯'] } } }
    if (args[0] === 'terminal' && args[1] === 'send') {
      typed.push(args[5])
      return { result: { send: { accepted: true } } }
    }
    return { result: {} }
  }
  const hub = createHubWorker({
    orca: { log: () => {}, host: { call: async () => ({ workspaces: [] }) }, panels: { post: () => {} } },
    home, hubRoot, cli: 'orca', runCli, now: () => clock,
    readOrca: async () => ({ active: null, agents: [], offers: [] }),
    readClaude: async () => [{ sessionId: 'o', name: 'orchestrator', kind: 'interactive', alive: true }],
    watchDir: () => {}, readCases: async () => []
  })
  await hub.noticeAgentItems(['a1'])
  clock += GRACE_MS
  assert.deepEqual(await hub.noticeAgentItems(['a1']), { told: ['a1'] })
  assert.deepEqual(typed.filter((line) => line !== '\u0013'), [agentItemsLine(['a1'])])
  assert.deepEqual(JSON.parse(await readFile(join(hubRoot, 'state', 'hub-told-agent-items.json'), 'utf8')), ['a1'])
})
