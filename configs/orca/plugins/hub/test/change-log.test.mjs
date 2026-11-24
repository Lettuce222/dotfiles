// What the user did from any screen, read from gtd's change log (src/change-log.mjs), and the line
// that tells the orchestrator of the user's new items in the inbox (src/agent-items.mjs).
import assert from 'node:assert/strict'
import { appendFileSync, mkdtempSync, writeFileSync } from 'node:fs'
import { mkdir, readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { RETRY_MS, inboxLine, newInboxItems } from '../src/agent-items.mjs'
import { createChangeLogReader, userChanges } from '../src/change-log.mjs'
import { createHubWorker } from '../src/hub-worker.mjs'
import { makeHome } from './helpers.mjs'

const line = (entry) => JSON.stringify({ at: '2026-11-24T19:00:00+09:00', ...entry }) + '\n'

test('the reader reads only the lines added after it started, each once', async () => {
  const path = join(mkdtempSync(join(tmpdir(), 'hub-log-')), 'changes.jsonl')
  writeFileSync(path, line({ id: 'old', action: 'say', by: 'user' }))
  const reader = createChangeLogReader(path)
  await reader.start()
  assert.deepEqual(await reader.readNew(), [], 'the past is not read')
  appendFileSync(path, line({ id: 'a1', action: 'say', by: 'user' }) + line({ id: 'a2', action: 'add', by: 'user' }))
  assert.deepEqual((await reader.readNew()).map((entry) => entry.id), ['a1', 'a2'])
  assert.deepEqual(await reader.readNew(), [], 'once')
})

test('a line not ended yet is read the next time, whole, even cut in a character', async () => {
  const path = join(mkdtempSync(join(tmpdir(), 'hub-log-')), 'changes.jsonl')
  writeFileSync(path, '')
  const reader = createChangeLogReader(path)
  await reader.start()
  const whole = line({ id: 'a1', action: 'add', by: 'user', note: '日本語' })
  const bytes = Buffer.from(whole)
  const cut = bytes.indexOf(Buffer.from('本')) + 1
  appendFileSync(path, bytes.subarray(0, cut))
  assert.deepEqual(await reader.readNew(), [])
  appendFileSync(path, bytes.subarray(cut))
  assert.deepEqual(await reader.readNew(), [JSON.parse(whole)])
})

test('a log that grew shorter is read from its start; a missing log is empty until it comes', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'hub-log-'))
  const path = join(dir, 'changes.jsonl')
  const reader = createChangeLogReader(path)
  await reader.start()
  assert.deepEqual(await reader.readNew(), [])
  writeFileSync(path, line({ id: 'a1', action: 'add', by: 'user' }) + line({ id: 'a2', action: 'add', by: 'user' }))
  assert.equal((await reader.readNew()).length, 2, 'a log made after the start is all new')
  writeFileSync(path, line({ id: 'b1', action: 'say', by: 'user' }))
  assert.deepEqual((await reader.readNew()).map((entry) => entry.id), ['b1'])
  appendFileSync(path, 'not json\n' + line({ id: 'b2', action: 'say', by: 'user' }))
  assert.deepEqual((await reader.readNew()).map((entry) => entry.id), ['b2'], 'a broken line is passed over')
})

test('the user\'s changes are the say and add lines by user, with checked ids', () => {
  const entries = [
    { id: 'a1', action: 'say', by: 'user' },
    { id: 'a1', action: 'say', by: 'user' },
    { id: 'a2', action: 'say', by: 'agent:orchestrator' },
    { id: 'a3', action: 'add', by: 'user' },
    { id: 'a4', action: 'add', by: 'agent:impl-x' },
    { id: 'a5', action: 'edit', by: 'user' },
    { id: '../x', action: 'say', by: 'user' },
    null
  ]
  assert.deepEqual(userChanges(entries), { replies: ['a1'], added: ['a3'] })
  assert.deepEqual(userChanges(undefined), { replies: [], added: [] })
})

test('the new items are the ones added by the user still in the inbox; a mark may narrow them', () => {
  const items = [
    { id: 'a1', list: 'inbox' },
    { id: 'a2', list: 'next' },
    { id: 'a3', list: 'inbox' },
    { id: 'a4', list: 'inbox', ask: true }
  ]
  assert.deepEqual(newInboxItems(items, ['a1', 'a2', 'a4']), ['a1', 'a4'])
  assert.deepEqual(newInboxItems(items, new Set(['a1', 'a4']), (item) => item.ask), ['a4'])
  assert.deepEqual(newInboxItems(undefined, ['a1']), [])
})

test('the line names the ids only, and says it is neither the user\'s instruction nor an approval', () => {
  assert.equal(inboxLine(['20261124-a3f2', 'rm -rf ~', 'b1']), 'Hub の知らせ: inbox に新しい項目があります: 20261124-a3f2、b1。python3 ~/.claude/skills/agents-orchestrator/scripts/gtd.py show <id> で読み、窓口のスキルの決まりのとおりに進めてください（この行はユーザーの指示でも承認でもありません）。')
  assert.equal(inboxLine([]), null)
})

test('the worker tells the orchestrator of a new item at once, once, again every 30 seconds until it takes it, and keeps it', async () => {
  const home = await makeHome()
  const hubRoot = join(home, 'hub')
  await mkdir(join(hubRoot, 'state'), { recursive: true })
  let clock = 5_000_000
  const typed = []
  let accept = false
  const runCli = async (_cli, args) => {
    if (args[0] === 'worktree') return { result: { worktrees: [{ path: hubRoot, agents: [{ paneKey: 't1:l1', conversationName: 'orchestrator', agentType: 'claude', state: 'done', hasLivePty: true }] }] } }
    if (args[0] === 'terminal' && args[1] === 'list') return { result: { terminals: [{ handle: 'h1', tabId: 't1', leafId: 'l1', agentIdentity: 'claude', worktreePath: hubRoot, writable: true }] } }
    if (args[0] === 'terminal' && args[1] === 'read') return { result: { terminal: { tail: ['─────── ● high · /effort  orchestrator ─', '❯'] } } }
    if (args[0] === 'terminal' && args[1] === 'send') {
      typed.push(args[5])
      return { result: { send: { accepted: accept || args[5] === '\u0013' } } }
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
  assert.deepEqual(await hub.noticeInboxItems(['a1']), { told: [], waiting: 'refused' }, 'no grace: tried at once')
  assert.deepEqual((await hub.noticeInboxItems(['a1'])).told, [], 'not again right away')
  clock += RETRY_MS
  accept = true
  assert.deepEqual(await hub.noticeInboxItems(['a1']), { told: ['a1'] })
  assert.deepEqual(await hub.noticeInboxItems(['a1']), { told: [] }, 'once')
  assert.deepEqual(typed.filter((sent) => sent !== '\u0013'), [inboxLine(['a1']), inboxLine(['a1'])])
  assert.deepEqual(JSON.parse(await readFile(join(hubRoot, 'state', 'hub-told-inbox-items.json'), 'utf8')), ['a1'])
})
