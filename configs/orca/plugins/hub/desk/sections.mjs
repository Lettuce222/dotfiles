// The sections of the desk's left column: which are folded to their heading, and where j and k go.
// desk/desk.mjs keeps the state and draws; these only decide, so that the tests can run them.
//
// いつか and 資料 grow long and are read seldom: folded unless the selection is in them. A heading
// pressed folds or opens its section for good (`folds`, kept by the page); a section's key opens it.

export const BIG = new Set(['someday', 'reference'])

/** Folded by default: a big section, unless the selection is in it. */
export function foldedByDefault(name, { cur, sel }) {
  return BIG.has(name) && !(name === cur && sel)
}

export function isFolded(name, { cur, sel, folds }) {
  return Object.hasOwn(folds, name) ? folds[name] : foldedByDefault(name, { cur, sel })
}

/** The folds after a heading of `name` is pressed to fold (`on`) or open it; the default is not kept. */
export function withFold(folds, name, on, at) {
  const next = { ...folds }
  if (on === foldedByDefault(name, at)) delete next[name]
  else next[name] = on
  return next
}

/**
 * The rows j and k go through, in order: those of every open section.
 * @param lists [id, ...] of the sections in order; rowsOf(id) their items
 */
export function visibleRows(lists, rowsOf, at) {
  return lists.flatMap(([k]) => (isFolded(k, at) ? [] : rowsOf(k).map((t) => ({ sec: k, t }))))
}

/** The row `delta` rows from the selected one (the first when none is), kept within the rows. */
export function stepRow(rows, { cur, sel }, delta) {
  if (!rows.length) return null
  const i = rows.findIndex((r) => r.sec === cur && r.t.id === sel)
  return rows[Math.max(0, Math.min(rows.length - 1, i < 0 ? 0 : i + delta))]
}
