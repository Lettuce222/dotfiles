import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import { TAB_KEYS, deskKey } from '../desk/keys.mjs'
import { BIG, isFolded, stepRow, visibleRows, withFold } from '../desk/sections.mjs'

const root = join(import.meta.dirname, '..')
const page = readFileSync(join(root, 'desk', 'desk.mjs'), 'utf8')
// The tables of the page, read from its source: the page itself runs only in a browser.
const table = (name) => JSON.parse(page.match(new RegExp(`const ${name} = (\\[[\\s\\S]*?\\]\\])\\n`))[1].replace(/'/g, '"'))
const LISTS = table('LISTS')
const MOVE_TO = table('MOVE_TO')
const CASE_TO = table('CASE_TO')

const key = (k, extra = {}) => ({ key: k, code: /^[a-z]$/.test(k) ? `Key${k.toUpperCase()}` : '', shiftKey: false, ...extra })
const onList = (e, at = {}) => deskKey(e, { pane: 'list', hasItem: true, lists: LISTS, moveTo: MOVE_TO, caseTo: CASE_TO, ...at })
const onMigrate = (e, at = {}) => deskKey(e, { pane: 'migrate', hasItem: true, lists: LISTS, moveTo: MOVE_TO, caseTo: CASE_TO, ...at })

test('q w e r t y u switch the seven lists in order, and i shows the migration', () => {
  assert.equal(LISTS.length, 7)
  assert.deepEqual(TAB_KEYS.slice(0, 7).map((k) => onList(key(k))), LISTS.map(([id]) => ({ do: 'list', list: id })))
  assert.deepEqual(onList(key('i')), { do: 'migrate' })
  for (const digit of ['1', '7', '8']) assert.equal(onList(key(digit)), null, `${digit} no longer switches`)
})

test('on a list, the acts are on the home row: a s d f, then x; j and k go up and down', () => {
  assert.deepEqual(onList(key('a')), { do: 'add' })
  assert.deepEqual(onList(key('s')), { do: 'act', act: 'open' })
  assert.deepEqual(onList(key('d')), { do: 'act', act: 'deliv' })
  assert.deepEqual(onList(key('f')), { do: 'act', act: 'move' })
  assert.deepEqual(onList(key('x')), { do: 'act', act: 'done' })
  assert.deepEqual(onList(key('j')), { do: 'move', delta: 1 })
  assert.deepEqual(onList(key('k')), { do: 'move', delta: -1 })
  assert.deepEqual(onList(key('e')), { do: 'list', list: 'next' }, 'e is the third list')
  for (const old of ['o', 'm']) assert.equal(onList(key(old)), null, `${old} no longer acts`)
  assert.equal(onList(key('x'), { hasItem: false }), null, 'nothing to act on')
  const itemKeys = ['a', 's', 'd', 'f', 'x', 'j', 'k', 'g']
  assert.deepEqual(itemKeys.filter((k) => TAB_KEYS.includes(k)), [], 'no tab key is an act key')
})

test('Shift with q w e r (or 1-4) answers, by the key\'s position; Caps Lock alone never does', () => {
  assert.deepEqual(onList({ key: 'Q', code: 'KeyQ', shiftKey: true }), { do: 'answer', choice: 1 })
  assert.deepEqual(onList({ key: 'R', code: 'KeyR', shiftKey: true }), { do: 'answer', choice: 4 })
  assert.deepEqual(onList({ key: '!', code: 'Digit1', shiftKey: true }), { do: 'answer', choice: 1 })
  assert.equal(onList({ key: 'T', code: 'KeyT', shiftKey: true }), null, 'only four choices have a key')
  assert.deepEqual(onList({ key: 'Q', code: 'KeyQ', shiftKey: false }), null, 'Caps Lock: not an answer, and not a tab either')
  assert.equal(onList({ key: 'Q', code: 'KeyQ', shiftKey: true }, { hasItem: false }), null)
})

test('the menu of where to move takes its own keys, and g takes the lists\' initials', () => {
  for (const [to, , k] of MOVE_TO) assert.deepEqual(onList(key(k), { menuOpen: true }), { do: 'menu', to }, k)
  assert.deepEqual(onList(key('q'), { menuOpen: true }), { do: 'none' }, 'no tab while the menu is open')
  assert.deepEqual(onList(key('Escape'), { menuOpen: true }), { do: 'close' })
  assert.deepEqual(onList(key('g')), { do: 'g' })
  for (const [id, , initial] of LISTS) assert.deepEqual(onList(key(initial), { gPending: true }), { do: 'list', list: id }, `g ${initial}`)
  assert.deepEqual(onList(key('m'), { gPending: true }), { do: 'migrate' })
})

test('on the migration, where to move a line wins over the tabs; the other keys of the row still switch', () => {
  for (const [to, , k] of CASE_TO) assert.deepEqual(onMigrate(key(k)), { do: 'fromCase', to }, k)
  const free = TAB_KEYS.filter((k) => !CASE_TO.some(([, , c]) => c === k))
  assert.deepEqual(free, ['q', 'e', 'y', 'u'])
  for (const k of free) assert.equal(onMigrate(key(k)).do, 'list', k)
  assert.deepEqual(onMigrate(key('j')), { do: 'migMove', delta: 1 })
  assert.deepEqual(onMigrate(key('w'), { gPending: true }), { do: 'list', list: 'waiting' }, 'g + an initial reaches every list')
})

test('the page and its help show the keys it takes', () => {
  assert.match(page, /<kbd>\$\{TAB_KEYS\[i\]\}<\/kbd>/, 'the tabs')
  assert.match(page, /成果物を開く <kbd>d<\/kbd>/)
  assert.match(page, /エディタで開く <kbd>s<\/kbd>/)
  assert.match(page, /移す <kbd>f<\/kbd>/)
  const html = readFileSync(join(root, 'desk', 'index.html'), 'utf8')
  assert.ok(html.includes(TAB_KEYS.map((k) => `<kbd>${k}</kbd>`).join('')), 'the help line of the tabs')
  assert.match(html, /<kbd>s<\/kbd> エディタ<\/span><span><kbd>d<\/kbd> 成果物<\/span><span><kbd>f<\/kbd> 移す/)
  assert.doesNotMatch(html, /<kbd>1<\/kbd>〜<kbd>8<\/kbd>/)
})

test('Esc on the migration goes back to the item', () => {
  assert.deepEqual(onMigrate(key('Escape')), { do: 'back' })
})

test('one screen: いつか and 資料 are folded unless the selection is in them; a pressed heading is kept', () => {
  assert.deepEqual([...BIG], ['someday', 'reference'])
  const at = { cur: 'inbox', sel: 'a', folds: {} }
  assert.equal(isFolded('someday', at), true)
  assert.equal(isFolded('reference', at), true)
  assert.equal(isFolded('next', at), false)
  assert.equal(isFolded('someday', { cur: 'someday', sel: 's1', folds: {} }), false, 'open while selected in it')
  assert.equal(isFolded('someday', { cur: 'someday', sel: null, folds: {} }), true, 'nothing selected in it: folded')
  const shut = withFold({}, 'next', true, at)
  assert.deepEqual(shut, { next: true })
  assert.equal(isFolded('next', { ...at, folds: shut }), true)
  assert.deepEqual(withFold(shut, 'next', false, at), {}, 'back to the default: nothing kept')
  assert.deepEqual(withFold({}, 'someday', false, at), { someday: false }, 'a big section opened for good')
})

test('j and k go through the rows of the open sections, across them, and stop at the ends', () => {
  const items = { mine: [{ id: 'm1' }], inbox: [{ id: 'i1' }, { id: 'i2' }], next: [], project: [{ id: 'p1' }], waiting: [], someday: [{ id: 's1' }], reference: [{ id: 'r1' }] }
  const at = { cur: 'inbox', sel: 'i2', folds: { project: true } }
  const rows = visibleRows(LISTS, (k) => items[k], at)
  const name = (r) => `${r.sec}:${r.t.id}`
  assert.deepEqual(rows.map(name), ['mine:m1', 'inbox:i1', 'inbox:i2'], 'a folded project, いつか and 資料 are passed over')
  assert.equal(name(stepRow(rows, at, -1)), 'inbox:i1')
  assert.equal(name(stepRow(rows, at, 1)), 'inbox:i2', 'stops at the last row')
  const top = { cur: 'mine', sel: 'm1' }
  assert.equal(name(stepRow(rows, top, -1)), 'mine:m1', 'stops at the first row')
  assert.equal(name(stepRow(rows, top, 1)), 'inbox:i1', 'crosses from あなたの番 into inbox')
  assert.equal(name(stepRow(rows, { cur: 'next', sel: null }, 1)), 'mine:m1', 'nothing selected: the first row')
  assert.equal(stepRow([], top, 1), null)
})

test('the page draws every list as a section of one screen, with no tabs', () => {
  const html = readFileSync(join(root, 'desk', 'index.html'), 'utf8')
  assert.doesNotMatch(html, /id="tabs"/)
  assert.doesNotMatch(page, /\$\('tabs'\)/)
  assert.match(page, /LISTS\.map\(\(\[k, label\], i\) => sectionHtml\(k, label, i\)\)/)
  assert.match(page, /data-fold="\$\{k\}"/, 'a heading folds or opens its section')
  assert.match(page, /data-pane="migrate"/, 'the migration has a heading of its own, last')
})
