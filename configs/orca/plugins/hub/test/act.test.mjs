// The composer of panel/act.mjs: Cmd+Enter sends, Enter alone makes a new line.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import { setUpActions } from '../panel/act.mjs'

function element() {
  const listeners = {}
  return {
    listeners,
    addEventListener: (type, fn) => {
      listeners[type] = fn
    },
    querySelectorAll: () => []
  }
}

test('Cmd+Enter or Ctrl+Enter sends what is written; Enter alone and an IME composition do not', () => {
  const textarea = element()
  const composer = { ...element(), submitted: 0, requestSubmit() { this.submitted += 1 }, querySelector: (q) => (q === 'textarea' ? textarea : element()) }
  setUpActions({ view: element(), notice: {}, composer, request: async () => ({ ok: true }) })
  const key = (fields) => {
    let prevented = false
    textarea.listeners.keydown({ key: 'Enter', metaKey: false, ctrlKey: false, isComposing: false, preventDefault: () => { prevented = true }, ...fields })
    return prevented
  }
  assert.equal(key({}), false)
  assert.equal(key({ metaKey: true, isComposing: true }), false)
  assert.equal(composer.submitted, 0)
  assert.equal(key({ metaKey: true }), true)
  assert.equal(key({ ctrlKey: true }), true)
  assert.equal(composer.submitted, 2)
})

test('the composer buttons sit in one row', () => {
  const css = readFileSync(join(import.meta.dirname, '..', 'panel', 'style.css'), 'utf8')
  assert.match(css, /#composer \.actions \{[^}]*flex-direction: row/)
})

import { parseAsk } from '../src/asks.mjs'
import { buildHubModel } from '../src/hub-model.mjs'
import { renderHub } from '../src/hub-render.mjs'
import { view } from './mini-dom.mjs'

function press(html, pick) {
  const root = view(html)
  const calls = []
  const composer = { hidden: true, addEventListener: () => {}, querySelector: () => ({ addEventListener: () => {}, focus: () => {}, value: '' }) }
  setUpActions({ view: root, notice: {}, composer, request: async (name, params) => (calls.push([name, params]), { ok: true }) })
  const button = pick(root)
  assert.ok(button, 'the button is rendered')
  root.click(button)
  return { calls, button, composer }
}

const QUESTION = {
  id: '20261119-175511-79e664a8', kind: 'question', created_at: 1, worker: 'orchestrator', session_id: 'sess-orch',
  question: 'パネルの問いの試しです。どちらかを押してください', body: '試しの本文\n2 行目\n',
  options: [{ label: '届いた', description: '試しを終える' }, { label: 'ほかで試す', description: 'もう一度試す' }], recommended: 1, approval: false
}

test("pressing an option of the orchestrator's question sends the answer, and the card shows it", () => {
  const card = { ...parseAsk(QUESTION), sha: 'b'.repeat(64), check: { ok: true, reason: null }, pressed: null, failure: null }
  const html = renderHub(buildHubModel([], [], [], { orchestratorAsks: [card] }))
  const { calls, button } = press(html, (root) => root.querySelectorAll('button').find((b) => b.dataset.choice === '1'))
  assert.deepEqual(calls, [['ask.answer', { id: QUESTION.id, sha: 'b'.repeat(64), choice: 1 }]])
  assert.ok(button.classList.contains('chosen'))
  assert.ok(button.closest('.orchestrator-question').classList.contains('sending'))
})

test("a worker's ask in its row and on its own are pressed the same way", () => {
  const raw = { ...QUESTION, kind: 'decide', worker: 'impl-x', session_id: 'sess-w', question: 'どこに置きますか', options: [{ label: 'x', description: 'x に置く' }, { label: 'y', description: 'y に置く' }] }
  const card = { ...parseAsk(raw), sha: 'c'.repeat(64), check: { ok: true, reason: null }, pressed: null, failure: null }
  const worker = { sessionId: 'sess-w', id: 'aaaaaaaa', name: 'impl-x', kind: 'background', cwd: '/w', state: 'blocked', status: 'idle', waitingFor: null, alive: true, startedAt: 1, job: null, report: null }
  for (const agents of [[worker], []]) {
    const html = renderHub(buildHubModel(agents, [], [], { cards: [card] }))
    const { calls } = press(html, (root) => root.querySelectorAll('button').find((b) => b.dataset.choice === '2'))
    assert.deepEqual(calls, [['ask.answer', { id: raw.id, sha: 'c'.repeat(64), choice: 2 }]], agents.length ? 'in its row' : 'on its own')
  }
})

test('a button outside any known card still sends its answer', () => {
  const html = `<div><button type="button" data-answer data-id="${QUESTION.id}" data-sha="${'d'.repeat(64)}" data-choice="1">x</button></div>`
  const { calls } = press(html, (root) => root.querySelectorAll('button')[0])
  assert.equal(calls.length, 1)
})
