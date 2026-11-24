// The desk's keys, as a function of the key pressed and where the page is: desk/desk.mjs does
// what it returns. Kept apart from the page so that the tests can run it without a browser.
//
// The lists and the migration are on the row q w e r t y u i, which a keyboard whose digits need a
// layer key can press alone. Where a key means something else, the more specific place wins:
// - the menu of where to move an item (MOVE_TO's keys) takes every key while it is open;
// - after g, the letters are the lists' initials (y i n p w s r, and m for the migration);
// - on the migration, the keys of where to move a line (CASE_TO's: i n t w s r c -) win over the
//   tabs; the other keys of the row (q e y u) still switch, and g + an initial reaches every list.
// The acts on the selected item are on the home row from the left: a adds, s opens it in the
// editor, d its deliverables, f moves it; x (done) stays on the row below, away from the keys
// pressed most; j and k go up and down. The keys do not follow the words' initials: a key easy to
// reach comes first.
// Shift with the first four keys of the row (or Shift with 1-4) answers the selected item's first
// question; by e.code, so that Caps Lock does not turn a tab key into an answer.

/** The tab keys: the seven lists in order, then the migration. */
export const TAB_KEYS = ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i']
const ANSWER_CODES = { KeyQ: 1, KeyW: 2, KeyE: 3, KeyR: 4, Digit1: 1, Digit2: 2, Digit3: 3, Digit4: 4 }
const ITEM_KEYS = { s: 'open', d: 'deliv', f: 'move', x: 'done' }

function tab(key, lists) {
  const i = TAB_KEYS.indexOf(key)
  if (i < 0) return null
  return i < lists.length ? { do: 'list', list: lists[i][0] } : { do: 'migrate' }
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
  if (k === 'g') return { do: 'g' }
  if (k === 'a') return { do: 'add' }
  if (pane === 'migrate') {
    if (k === 'j') return { do: 'migMove', delta: 1 }
    if (k === 'k') return { do: 'migMove', delta: -1 }
    const hit = caseTo.find(([, , key]) => key === k)
    if (hit) return { do: 'fromCase', to: hit[0] }
    return e.shiftKey ? null : tab(k, lists)
  }
  const answer = ANSWER_CODES[e.code]
  if (e.shiftKey && answer) return hasItem ? { do: 'answer', choice: answer } : null
  if (!e.shiftKey) {
    const hit = tab(k, lists)
    if (hit) return hit
  }
  if (k === 'j') return { do: 'move', delta: 1 }
  if (k === 'k') return { do: 'move', delta: -1 }
  if (k === 'Enter') return hasItem ? { do: 'focus' } : null
  if (ITEM_KEYS[k]) return hasItem ? { do: 'act', act: ITEM_KEYS[k] } : null
  return null
}
