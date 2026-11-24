import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import { TAB_KEYS, deskKey, keyHints } from '../desk/keys.mjs'
import { SMALL_ROWS, boxOrder, filterRows, nextBox, shownRows, stepRow } from '../desk/sections.mjs'

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
  assert.equal(onList(key('m')), null, 'm no longer acts')
  assert.deepEqual(onList(key('o')), { do: 'list', list: 'talk' }, 'o is the box of the talk with the orchestrator')
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

test('the page shows the keys it takes: on each box, on the buttons, and on the bottom line', () => {
  assert.match(page, /\[\$\{key\}\] \$\{label\} \(\$\{all\.length\}\)/, 'a box is named [q] あなたの番 (3) on its frame')
  assert.match(page, /成果物を開く <kbd>d<\/kbd>/)
  assert.match(page, /エディタで開く <kbd>s<\/kbd>/)
  assert.match(page, /移す <kbd>f<\/kbd>/)
  const list = keyHints({ pane: 'list' }).map(([k]) => k)
  for (const k of ['j/k', 'Enter', 's', 'd', 'f', 'x', 'v', 'a', '/', 'h/l', '?']) assert.ok(list.includes(k), k)
  assert.deepEqual(keyHints({ pane: 'list', card: true }).slice(0, 2), [['⇧Q〜⇧R', '答える'], ['Enter', '書いて答える']])
  assert.deepEqual(keyHints({ pane: 'migrate' })[1], ['i n t w s r c -', '移す先'])
  assert.deepEqual(keyHints({ pane: 'list', filtering: true }), [['Enter', '絞り込んだまま戻る'], ['Esc', '絞り込みをやめる']])
  const html = readFileSync(join(root, 'desk', 'index.html'), 'utf8')
  assert.match(html, /<div class="keys" id="keys"><\/div>/, 'the bottom line is drawn by the page')
  assert.match(html, /<input id="filter"/)
})

test('Esc on the migration goes back to the item', () => {
  assert.deepEqual(onMigrate(key('Escape')), { do: 'back' })
})

test('h and l (and Tab, Shift+Tab) go to the box above and below; ? shows the keys; / narrows the box', () => {
  assert.deepEqual(onList(key('l')), { do: 'box', delta: 1 })
  assert.deepEqual(onList(key('h')), { do: 'box', delta: -1 })
  assert.deepEqual(onList({ key: 'Tab', code: 'Tab', shiftKey: false }), { do: 'box', delta: 1 })
  assert.deepEqual(onList({ key: 'Tab', code: 'Tab', shiftKey: true }), { do: 'box', delta: -1 })
  assert.deepEqual(onMigrate(key('l')), { do: 'box', delta: 1 }, 'from the migration too')
  assert.deepEqual(onList({ key: '?', code: 'Slash', shiftKey: true }), { do: 'help' })
  assert.deepEqual(onList({ key: '/', code: 'Slash', shiftKey: false }), { do: 'filter' })
  assert.deepEqual(onList(key('h'), { menuOpen: true }), { do: 'none' }, 'the menu takes its keys')
  assert.equal(onList({ key: 'H', code: 'KeyH', shiftKey: true }), null)
  const taken = ['a', 's', 'd', 'f', 'x', 'v', 'j', 'k', 'g', ...TAB_KEYS]
  assert.ok(!taken.includes('h') && !taken.includes('l'), 'h and l were free')
})

test('the boxes go round the column, the one worked in shows every row and the others their first', () => {
  const order = boxOrder(LISTS)
  assert.deepEqual(order, ['mine', 'inbox', 'next', 'project', 'waiting', 'someday', 'reference', 'migrate'])
  assert.equal(nextBox(order, 'inbox', 1), 'next')
  assert.equal(nextBox(order, 'mine', -1), 'migrate', 'round from the top')
  assert.equal(nextBox(order, 'migrate', 1), 'mine', 'round from the bottom')
  const rows = Array.from({ length: 7 }, (_, i) => ({ id: `r${i}` }))
  assert.equal(shownRows(rows, true).length, 7)
  assert.equal(shownRows(rows, false).length, SMALL_ROWS)
  assert.equal(SMALL_ROWS, 3)
})

test('j and k go up and down in the box and stop at its ends; / keeps the rows that hold every word', () => {
  const rows = [{ id: 'a', title: 'API のテストを足す' }, { id: 'b', title: '週次の振り返り' }, { id: 'c', title: 'api の設計' }]
  assert.equal(stepRow(rows, 'a', 1).id, 'b')
  assert.equal(stepRow(rows, 'c', 1).id, 'c', 'stops at the last row')
  assert.equal(stepRow(rows, 'a', -1).id, 'a', 'stops at the first row')
  assert.equal(stepRow(rows, null, 1).id, 'a', 'nothing selected: the first row')
  assert.equal(stepRow([], 'a', 1), null)
  assert.deepEqual(filterRows(rows, 'api').map((r) => r.id), ['a', 'c'], 'case aside')
  assert.deepEqual(filterRows(rows, 'api テスト').map((r) => r.id), ['a'], 'every word')
  assert.deepEqual(filterRows(rows, '  ').map((r) => r.id), ['a', 'b', 'c'])
})

test('the page draws the boxes in frames, with no tabs and no folding', () => {
  const html = readFileSync(join(root, 'desk', 'index.html'), 'utf8')
  assert.doesNotMatch(html, /id="tabs"/)
  assert.doesNotMatch(page, /\$\('tabs'\)|data-fold|setFold/)
  assert.match(page, /<fieldset class="box \$\{focused \? 'focused' : ''\} /)
  assert.match(page, /LISTS\.map\(\(\[k, label\], i\) => boxHtml\(k, label, TAB_KEYS\[i\]\)\)/)
  assert.match(page, /boxes\.splice\(1, 0, boxHtml\('talk', '窓口', TALK_KEY\)\)/, 'the talk box under あなたの番')
  assert.match(page, /data-sec="migrate"><legend data-box="migrate">/, 'the migration is the last box')
  const css = readFileSync(join(root, 'desk', 'desk.css'), 'utf8')
  assert.match(css, /\.box\.focused \{ border-color: var\(--focus\); flex: 1 1 auto;/, 'the box worked in is the large one, its frame colored')
  assert.match(css, /\.row\.sel \{ background: var\(--fg\); color: var\(--bg\);/, 'the selected row reversed')
  assert.match(css, /\.alert-go \{ display: block; background: var\(--orange\);/, 'the strip of the orchestrator\'s cards stays loud')
  assert.match(css, /\.alert-talk \{[^}]*background: var\(--blue\);/, 'the orchestrator\'s answers in a color of their own')
})
