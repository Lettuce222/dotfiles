// The talk with the orchestrator on an item: the conversation read out of its body, what is unread
// or waits, and how the desk shows and reads it.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import { parseTalk, shortTime, talkState } from '../desk/talk.mjs'
import { createDesk } from '../src/desk.mjs'

const root = join(import.meta.dirname, '..')

const BODY = `前置き

## あなたの番

- 11/24: どちらの案にするか決めてください

## あなたの番への返事

- 11/24 16:40: A 案で。来週まで

## 窓口の返事

### 11/24 16:52

了解です。

- 手順 1
- 手順 2

\`\`\`sh
### コードの中は区切りでない
\`\`\`

### 11/24 17:05

worker を起動しました。

## メモ

- 残り`

test('the conversation comes out of the three sections in time order, and the rest of the body stays', () => {
  const { entries, rest } = parseTalk(BODY)
  assert.deepEqual(entries.map((e) => [e.who, e.when]), [
    ['ask', '11/24'],
    ['user', '11/24 16:40'],
    ['orchestrator', '11/24 16:52'],
    ['orchestrator', '11/24 17:05']
  ])
  assert.equal(entries[0].text, 'どちらの案にするか決めてください')
  assert.equal(entries[1].text, 'A 案で。来週まで')
  assert.equal(entries[2].text, '了解です。\n\n- 手順 1\n- 手順 2\n\n```sh\n### コードの中は区切りでない\n```')
  assert.equal(entries[3].text, 'worker を起動しました。')
  assert.equal(rest, '前置き\n\n## メモ\n\n- 残り')
})

test('a body with no talk is all rest', () => {
  assert.deepEqual(parseTalk('ただの本文\n\n## メモ\n\n- x'), { entries: [], rest: 'ただの本文\n\n## メモ\n\n- x' })
  assert.deepEqual(parseTalk(''), { entries: [], rest: '' })
})

test('an answer is unread while answered is later than read; the user waits while asked is later than answered', () => {
  assert.deepEqual(talkState({ answered: '2026-11-24T17:05' }), { unread: true, waiting: false })
  assert.deepEqual(talkState({ answered: '2026-11-24T17:05', read: '2026-11-24T17:10' }), { unread: false, waiting: false })
  assert.deepEqual(talkState({ asked: '2026-11-24T17:20', answered: '2026-11-24T17:05', read: '2026-11-24T17:10' }), { unread: false, waiting: true })
  assert.deepEqual(talkState({ asked: '2026-11-24T16:40', answered: '2026-11-24T17:05' }), { unread: true, waiting: false })
  assert.deepEqual(talkState({}), { unread: false, waiting: false })
  assert.equal(shortTime('2026-11-24T17:05'), '11/24 17:05')
  assert.equal(shortTime('11/24'), '')
})

function deskWith(items) {
  const calls = []
  const gtd = async (args) => {
    calls.push(args)
    if (args[0] === 'json') return { today: '2026-11-24', counts: {}, items }
    if (args[0] === 'cases') return { cases: [] }
    return { id: args[1], changed: true }
  }
  const desk = createDesk({ gtd, hubRoot: '/nowhere', snapshot: () => ({ workers: [], asks: [], orchestrator: [] }), openFile: async () => true, focusWorker: async () => ({}), answerAsk: async () => ({ ok: true }), watchDir: () => ({ close() {} }) })
  return { desk, calls }
}

test('the desk gives each item its talk, counts the answers not read, and reads one only when it is unread', async () => {
  const items = [
    { id: 'a1', list: 'next', title: '返事あり', answered: '2026-11-24T17:05' },
    { id: 'a2', list: 'next', title: '答え待ち', asked: '2026-11-24T17:20' },
    { id: 'a3', list: 'done', title: '済んだ', answered: '2026-11-24T17:05', done: '2026-11-24' }
  ]
  const { desk, calls } = deskWith(items)
  const state = await desk.state()
  assert.deepEqual(state.items.map((t) => [t.id, t.talk]), [['a1', { unread: true, waiting: false }], ['a2', { unread: false, waiting: true }], ['a3', { unread: true, waiting: false }]])
  assert.equal(state.counts.talk, 1, 'a done item is not counted')
  assert.equal((await desk.counts()).talk, 1)
  await desk.handlers.read({ id: 'a1' })
  assert.deepEqual(await desk.handlers.read({ id: 'a2' }), { changed: false }, 'nothing unread: gtd.py is not called')
  assert.deepEqual(calls.filter((args) => args[0] === 'read'), [['read', 'a1', '--by', 'user']])
})

test('the page has the talk box under あなたの番, the conversation, the reading, and a blue strip', () => {
  const page = readFileSync(join(root, 'desk', 'desk.mjs'), 'utf8')
  assert.match(page, /const BOXES = boxOrder\(LISTS\)\.toSpliced\(1, 0, 'talk'\)/)
  assert.match(page, /if \(t\.talk\?\.unread\) void markRead\(t\)/, 'opening an item reads its answer')
  assert.match(page, /窓口から返事が \$\{answers\} 件あります/)
  assert.match(page, /document\.title = count \? `\(\$\{count\}\) デスク` : 'デスク'/)
  const main = readFileSync(join(root, 'main.mjs'), 'utf8')
  assert.match(main, /const tone = waiting \? 'danger' : answers \? 'accent'/, 'the status bar: the cards first, then the answers, in a color of their own')
})
