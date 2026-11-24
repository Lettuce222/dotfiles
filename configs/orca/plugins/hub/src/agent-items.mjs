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
 * @param deps { now, readTold: () => Promise<string[]>, writeTold: (ids) => Promise<void>,
 *   send: (ids) => Promise<{ sent, reason }>, log }
 */
export function createAgentItemNotice({ now = Date.now, readTold, writeTold, send, log = () => {} }) {
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

  /** The ids of the items that wait for a worker now (unassignedAgentItems): new ones start waiting, gone ones are forgotten. */
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
    return current.filter((id) => !done.has(id) && at - firstSeen.get(id) >= GRACE_MS)
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
        log(`hub: could not tell the orchestrator of the agent items ${ids.join(', ')}: ${lastFailure}`)
        return { told: [], waiting: lastFailure }
      }
      lastFailure = null
      for (const id of ids) told.add(id)
      const kept = [...told].slice(-TOLD_MAX)
      told = new Set(kept)
      await writeTold(kept).catch((error) => log(`hub: could not keep the agent items told: ${error.message}`))
      log(`hub: told the orchestrator of the agent items ${ids.join(', ')}`)
      return { told: ids }
    })().finally(() => {
      telling = null
    })
    return telling
  }

  return { update, tell }
}
