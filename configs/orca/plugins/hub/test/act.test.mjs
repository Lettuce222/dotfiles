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
