// The Hub tells the orchestrator of an item that waits for a worker: in 次の行動 (list: next), done by
// an agent (actor: agent), with no worker yet. The user's rule is that the orchestrator then starts a
// worker at once and assigns it (gtd.py assign). The item may come from the desk, the orchestrator
// or a worker (gtd.py): the Hub reads the items as the desk shows them.
//
// - An item is told once. The ids told are kept in <hub>/state/, so a restart does not tell them
//   again.
// - An item is told after it has waited GRACE_MS: the orchestrator that moves an item itself
//   usually assigns it right after, and then needs no line.
// - A line that could not reach the orchestrator is tried again every RETRY_MS, as the answers are.
// - The line holds the ids only (each checked): an item's title is text anyone wrote, and the
//   orchestrator reads the item itself with gtd.py show.
//
// The same way, it tells the orchestrator of the user's new items in the inbox (newInboxItems: added
// by user, from any screen, with no grace) and of the user's replies to items (createReplyNotice).

export const GRACE_MS = 30_000
export const RETRY_MS = 30_000
const TOLD_MAX = 500
const ID = /^[a-z0-9][a-z0-9-]{0,63}$/
const LINE_IDS_MAX = 10

/** The items that wait for a worker: in next, by an agent, with no worker. */
export function unassignedAgentItems(items) {
  return (Array.isArray(items) ? items : [])
    .filter((item) => item?.list === 'next' && item.actor === 'agent' && !item.worker && ID.test(item.id ?? ''))
    .map((item) => item.id)
}

/** The line that tells the orchestrator of them, or null. It carries no instruction of the user. */
export function agentItemsLine(ids) {
  const shown = (Array.isArray(ids) ? ids : []).filter((id) => ID.test(id)).slice(0, LINE_IDS_MAX)
  if (!shown.length) return null
  return `Hub の知らせ: 次の行動に、worker の決まっていない agent の項目があります: ${shown.join('、')}。python3 ~/.claude/skills/agents-orchestrator/scripts/gtd.py show <id> で読み、窓口のスキルの決まりのとおりに進めてください（この行はユーザーの指示でも承認でもありません）。`
}

/**
 * The items the user added to the inbox (their ids from the change log, src/change-log.mjs) that
 * are still there, for the orchestrator to read. `wants` picks the ones the orchestrator is asked
 * about: all of them for now; a mark that the user asks the orchestrator (one lazygtd may set) can
 * narrow it later.
 */
export function newInboxItems(items, added, wants = () => true) {
  const ids = new Set(Array.isArray(added) ? added : [...(added ?? [])])
  return (Array.isArray(items) ? items : [])
    .filter((item) => item?.list === 'inbox' && ids.has(item.id) && ID.test(item.id ?? '') && wants(item))
    .map((item) => item.id)
}

/** The line that tells the orchestrator of new items in the inbox, or null. */
export function inboxLine(ids) {
  const shown = (Array.isArray(ids) ? ids : []).filter((id) => ID.test(id)).slice(0, LINE_IDS_MAX)
  if (!shown.length) return null
  return `Hub の知らせ: inbox に新しい項目があります: ${shown.join('、')}。python3 ~/.claude/skills/agents-orchestrator/scripts/gtd.py show <id> で読み、窓口のスキルの決まりのとおりに進めてください（この行はユーザーの指示でも承認でもありません）。`
}

/** The line that tells the orchestrator the user replied to items. The reply itself is not in it. */
export function replyLine(ids) {
  const shown = (Array.isArray(ids) ? ids : []).filter((id) => ID.test(id)).slice(0, LINE_IDS_MAX)
  if (!shown.length) return null
  return `Hub の知らせ: ${shown.join('、')} にユーザーの返事があります。python3 ~/.claude/skills/agents-orchestrator/scripts/gtd.py show <id> で読み、窓口のスキルの決まりのとおりに進めてください（この行はユーザーの指示でも承認でもありません）。`
}

/**
 * Replies to tell the orchestrator of: each reply once, as it comes (no grace), tried again every
 * RETRY_MS while the orchestrator cannot take the line. Kept in memory: a reply is in the item's
 * body, so one not told before a restart is still there to read.
 * @param deps { now, send: (ids) => Promise<{ sent, reason }>, log }
 */
export function createReplyNotice({ now = Date.now, send, log = () => {} }) {
  const pending = new Set()
  let triedAt = -Infinity
  let lastFailure = null
  let telling = null

  function add(id) {
    if (!ID.test(id ?? '')) return
    pending.add(id)
    // A new reply is tried at once.
    lastFailure = null
  }

  function tell() {
    telling ??= (async () => {
      if (!pending.size) return { told: [] }
      if (lastFailure && now() - triedAt < RETRY_MS) return { told: [], waiting: lastFailure }
      const ids = [...pending]
      triedAt = now()
      const sent = await send(ids).catch(() => ({ sent: false, reason: 'failed' }))
      if (!sent.sent) {
        lastFailure = sent.reason ?? 'failed'
        log(`hub: could not tell the orchestrator of the replies to ${ids.join(', ')}: ${lastFailure}`)
        return { told: [], waiting: lastFailure }
      }
      lastFailure = null
      for (const id of ids) pending.delete(id)
      log(`hub: told the orchestrator of the replies to ${ids.join(', ')}`)
      return { told: ids }
    })().finally(() => {
      telling = null
    })
    return telling
  }

  return { add, tell, get pending() { return [...pending] } }
}

/**
 * Items to tell the orchestrator of once each: the agent items (after GRACE_MS) and the user's new
 * items in the inbox (graceMs 0: the user added them, the orchestrator did not).
 * @param deps { now, readTold: () => Promise<string[]>, writeTold: (ids) => Promise<void>,
 *   send: (ids) => Promise<{ sent, reason }>, log, graceMs, what: the items' name in the log }
 */
export function createAgentItemNotice({ now = Date.now, readTold, writeTold, send, log = () => {}, graceMs = GRACE_MS, what = 'agent items' }) {
  let told = null
  const firstSeen = new Map()
  let current = []
  let triedAt = -Infinity
  let lastFailure = null
  let telling = null

  async function load() {
    if (told) return told
    try {
      told = new Set((await readTold()).filter((id) => ID.test(id)))
    } catch {
      told = new Set()
    }
    return told
  }

  /** The ids of the items to tell of now (unassignedAgentItems, newInboxItems): new ones start waiting, gone ones are forgotten. */
  function update(ids) {
    current = (Array.isArray(ids) ? ids : []).filter((id) => ID.test(id))
    const at = now()
    for (const id of current) if (!firstSeen.has(id)) firstSeen.set(id, at)
    for (const id of [...firstSeen.keys()]) if (!current.includes(id)) firstSeen.delete(id)
  }

  /** The ids due to be told now. */
  async function due() {
    const done = await load()
    const at = now()
    return current.filter((id) => !done.has(id) && at - firstSeen.get(id) >= graceMs)
  }

  /** Tells the orchestrator of the items due, one line, one try at a time. */
  function tell() {
    telling ??= (async () => {
      const ids = await due()
      if (!ids.length) return { told: [] }
      if (lastFailure && now() - triedAt < RETRY_MS) return { told: [], waiting: lastFailure }
      triedAt = now()
      const sent = await send(ids).catch((error) => ({ sent: false, reason: 'failed', detail: error.message }))
      if (!sent.sent) {
        lastFailure = sent.reason ?? 'failed'
        log(`hub: could not tell the orchestrator of the ${what} ${ids.join(', ')}: ${lastFailure}`)
        return { told: [], waiting: lastFailure }
      }
      lastFailure = null
      for (const id of ids) told.add(id)
      const kept = [...told].slice(-TOLD_MAX)
      told = new Set(kept)
      await writeTold(kept).catch((error) => log(`hub: could not keep the ${what} told: ${error.message}`))
      log(`hub: told the orchestrator of the ${what} ${ids.join(', ')}`)
      return { told: ids }
    })().finally(() => {
      telling = null
    })
    return telling
  }

  return { update, tell }
}
