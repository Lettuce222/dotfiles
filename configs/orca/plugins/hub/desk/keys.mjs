// The desk's keys, as a function of the key pressed and where the page is: desk/desk.mjs does
// what it returns. Kept apart from the page so that the tests can run it without a browser.
//
// The desk works as lazygit does: the lists are boxes of the left column (desk/sections.mjs), one
// of them is worked in, and the right box shows the selected item. h and l (and Tab, Shift+Tab)
// go to the box above and below; q w e r t y u jump to a list's box and i to the migration, on the
// row a keyboard whose digits need a layer key can press alone; j and k go up and down in the box.
// ? shows every key, / narrows the rows of the box. Where a key means something else, the more
// specific place wins:
// - the menu of where to move an item (MOVE_TO's keys) takes every key while it is open;
// - after g, the letters are the lists' initials (y i n p w s r, and m for the migration);
// - on the migration, the keys of where to move a line (CASE_TO's: i n t w s r c -) win over the
//   boxes; the other keys of the row (q e y u), h, l and Tab still go to a box, Esc goes back to
//   the box before, and g + an initial reaches every list.
// The acts on the selected item are on the home row from the left: a adds, s opens it in the
// editor, d its deliverables, f moves it; x (done) stays on the row below, away from the keys
// pressed most. h and l were free: no act took them. The keys do not follow the words' initials:
// a key easy to reach comes first.
// Enter goes into the box under the selected item: the reply to it (or the written answer to the
// orchestrator's card). In that box Enter sends and Shift+Enter starts a new line (desk/desk.mjs).
// v shows the item's worker in Orca's agent view.
// Shift with the first four keys of the row (or Shift with 1-4) answers the selected item's first
// question; by e.code, so that Caps Lock does not turn a tab key into an answer.

/** The keys of the boxes: the seven lists in order, then the migration. */
export const TAB_KEYS = ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i']
const ANSWER_CODES = { KeyQ: 1, KeyW: 2, KeyE: 3, KeyR: 4, Digit1: 1, Digit2: 2, Digit3: 3, Digit4: 4 }
const ITEM_KEYS = { s: 'open', d: 'deliv', f: 'move', x: 'done' }

function tab(key, lists) {
  const i = TAB_KEYS.indexOf(key)
  if (i < 0) return null
  return i < lists.length ? { do: 'list', list: lists[i][0] } : { do: 'migrate' }
}

/** h, l, Tab and Shift+Tab: the box above or below. */
function boxStep(e) {
  if (e.key === 'Tab') return { do: 'box', delta: e.shiftKey ? -1 : 1 }
  if (e.shiftKey) return null
  if (e.key === 'h') return { do: 'box', delta: -1 }
  if (e.key === 'l') return { do: 'box', delta: 1 }
  return null
}

/**
 * What a key does.
 * @param e { key, code, shiftKey } of the keydown (with no Cmd, Ctrl or Alt, outside the input)
 * @param at { pane: 'list'|'migrate', gPending, menuOpen, hasItem, lists, moveTo, caseTo }; lists
 *   are [id, label, initial], moveTo and caseTo [id, label, key]
 * @returns {{ do: string, [k: string]: unknown } | null}
 */
export function deskKey(e, { pane, gPending = false, menuOpen = false, hasItem = false, lists, moveTo = [], caseTo = [] }) {
  const k = e.key
  if (menuOpen) {
    if (k === 'Escape') return { do: 'close' }
    const hit = moveTo.find(([, , key]) => key === k)
    return hit ? { do: 'menu', to: hit[0] } : { do: 'none' }
  }
  if (gPending) {
    if (k === 'm') return { do: 'migrate' }
    const hit = lists.find((l) => l[2] === k)
    return hit ? { do: 'list', list: hit[0] } : { do: 'none' }
  }
  if (k === '?') return { do: 'help' }
  if (k === 'g') return { do: 'g' }
  if (k === 'a') return { do: 'add' }
  const step = boxStep(e)
  if (step) return step
  if (pane === 'migrate') {
    if (k === 'Escape') return { do: 'back' }
    if (k === 'j') return { do: 'migMove', delta: 1 }
    if (k === 'k') return { do: 'migMove', delta: -1 }
    const hit = caseTo.find(([, , key]) => key === k)
    if (hit) return { do: 'fromCase', to: hit[0] }
    return e.shiftKey ? null : tab(k, lists)
  }
  if (k === '/') return { do: 'filter' }
  const answer = ANSWER_CODES[e.code]
  if (e.shiftKey && answer) return hasItem ? { do: 'answer', choice: answer } : null
  if (!e.shiftKey) {
    const hit = tab(k, lists)
    if (hit) return hit
  }
  if (k === 'j') return { do: 'move', delta: 1 }
  if (k === 'k') return { do: 'move', delta: -1 }
  if (k === 'Enter') return hasItem ? { do: 'write' } : null
  if (k === 'v') return hasItem ? { do: 'agent' } : null
  if (ITEM_KEYS[k]) return hasItem ? { do: 'act', act: ITEM_KEYS[k] } : null
  return null
}

/** The keys the bottom line shows for where the page is, as [keys, what]. */
export function keyHints({ pane, card = false, filtering = false }) {
  if (filtering) return [['Enter', '絞り込んだまま戻る'], ['Esc', '絞り込みをやめる']]
  const boxes = [['h/l', '箱'], ['q〜i', '箱へ'], ['?', 'キー']]
  if (pane === 'migrate') return [['j/k', '行'], ['i n t w s r c -', '移す先'], ['Esc', '戻る'], ...boxes]
  if (card) return [['⇧Q〜⇧R', '答える'], ['Enter', '書いて答える'], ['j/k', '上下'], ...boxes]
  return [['j/k', '上下'], ['Enter', '返事'], ['s', '開く'], ['d', '成果物'], ['f', '移す'], ['x', '完了'], ['v', '画面'], ['a', '追加'], ['/', '絞り込み'], ...boxes]
}
