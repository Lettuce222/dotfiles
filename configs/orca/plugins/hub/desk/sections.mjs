// The boxes of the desk's left column, as in lazygit: one per list, then the migration. The box
// being worked in is large and the others show their first rows only, so that the desk fits one
// screen. desk/desk.mjs keeps the state and draws; these only decide, so that the tests can run them.

/** How many rows a box shows while another one is worked in. */
export const SMALL_ROWS = 3

/** The boxes in order: the lists, then the migration. */
export function boxOrder(lists) {
  return [...lists.map(([id]) => id), 'migrate']
}

/** The box `delta` boxes from `cur`, round the column (h, l, Tab, Shift+Tab). */
export function nextBox(order, cur, delta) {
  const i = Math.max(0, order.indexOf(cur))
  return order[(((i + delta) % order.length) + order.length) % order.length]
}

/** The rows a box shows: all of them while it is worked in, else its first SMALL_ROWS. */
export function shownRows(rows, focused) {
  return focused ? rows : rows.slice(0, SMALL_ROWS)
}

/** The rows whose text holds every word of the query (/ in a box), case aside. */
export function filterRows(rows, query, textOf = (row) => row.title ?? '') {
  const words = String(query ?? '').toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return rows
  return rows.filter((row) => {
    const text = String(textOf(row)).toLowerCase()
    return words.every((word) => text.includes(word))
  })
}

/** The row `delta` rows from the selected one in a box (the first when none is), kept within it. */
export function stepRow(rows, sel, delta) {
  if (!rows.length) return null
  const i = rows.findIndex((row) => row.id === sel)
  return rows[Math.max(0, Math.min(rows.length - 1, i < 0 ? 0 : i + delta))]
}
