// The talk with the orchestrator on an item, read out of its body (gtd.py writes it there):
//   ## あなたの番            - MM/DD: what the orchestrator or a worker asks of the user (handback)
//   ## あなたの番への返事    - MM/DD HH:MM: the user's reply (gtd.py say, from the desk)
//   ## 窓口の返事            ### MM/DD HH:MM, then the orchestrator's answer in Markdown (gtd.py reply)
// The desk shows them as one conversation in time order, and the rest of the body under it.
// Whether an answer is unread, or the user waits for one, is told by the item's times (asked,
// answered, read): see talkState.

export const SECTIONS = { ask: 'あなたの番', user: 'あなたの番への返事', orchestrator: '窓口の返事' }
const OF_SECTION = Object.fromEntries(Object.entries(SECTIONS).map(([who, title]) => [title, who]))
const LINE = /^- (\d{2}\/\d{2}(?: \d{2}:\d{2})?):\s?(.*)$/
const BLOCK = /^### (\d{2}\/\d{2}(?: \d{2}:\d{2})?)\s*$/
const FENCE = /^ {0,3}(`{3,}|~{3,})/

/** The level of a heading line, or 0. */
function headingLevel(line) {
  const m = /^(#{1,6}) /.exec(line)
  return m ? m[1].length : 0
}

/** The body cut into its level-2 sections, code blocks kept whole: [{ title, lines }], title null before the first. */
function sections(body) {
  const out = [{ title: null, lines: [] }]
  let fence = null
  for (const line of String(body ?? '').split('\n')) {
    const f = FENCE.exec(line)
    if (f) fence = fence ? (line.trim().startsWith(fence) ? null : fence) : f[1]
    if (!fence && !f && headingLevel(line) === 2) out.push({ title: line.slice(3).trim(), lines: [] })
    else if (!fence && !f && headingLevel(line) === 1) out.push({ title: `# ${line.slice(2).trim()}`, lines: [] })
    else out.at(-1).lines.push(line)
  }
  return out
}

const trim = (lines) => lines.join('\n').replace(/^\n+|\s+$/g, '')

/** "MM/DD" or "MM/DD HH:MM" as a key that sorts in time (a date alone before that day's times). */
const sortKey = (when) => (when.length === 5 ? `${when} --:--` : when)

/**
 * The conversation and the rest of the body.
 * @returns {{ entries: { who: 'ask'|'user'|'orchestrator', when: string, text: string }[], rest: string }}
 */
export function parseTalk(body) {
  const entries = []
  const rest = []
  for (const section of sections(body)) {
    const who = OF_SECTION[section.title]
    if (!who) {
      if (section.title !== null) rest.push(section.title.startsWith('# ') ? section.title : `## ${section.title}`)
      rest.push(...section.lines)
      continue
    }
    if (who === 'orchestrator') {
      let current = null
      let fence = null
      for (const line of section.lines) {
        const f = FENCE.exec(line)
        if (f) fence = fence ? (line.trim().startsWith(fence) ? null : fence) : f[1]
        const m = !fence && !f ? BLOCK.exec(line) : null
        if (m) {
          current = { who, when: m[1], lines: [] }
          entries.push(current)
        } else if (current) current.lines.push(line)
        else if (line.trim()) entries.push((current = { who, when: '', lines: [line] }))
      }
    } else {
      for (const line of section.lines) {
        const m = LINE.exec(line)
        if (m) entries.push({ who, when: m[1], lines: [m[2]] })
        else if (line.trim() && entries.at(-1)?.who === who) entries.at(-1).lines.push(line)
      }
    }
  }
  const sorted = entries
    .map((entry, i) => ({ who: entry.who, when: entry.when, text: trim(entry.lines), i }))
    .toSorted((a, b) => sortKey(a.when).localeCompare(sortKey(b.when)) || a.i - b.i)
    .map(({ who, when, text }) => ({ who, when, text }))
  return { entries: sorted, rest: trim(rest) }
}

/** "YYYY-MM-DDTHH:MM" as "MM/DD HH:MM", to compare with the conversation's times. */
export const shortTime = (iso) => (typeof iso === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(iso) ? `${iso.slice(5, 7)}/${iso.slice(8, 10)} ${iso.slice(11, 16)}` : '')

/**
 * Where the talk of an item stands: an answer of the orchestrator not read yet (answered later
 * than read), or the user waiting for one (asked later than answered).
 */
export function talkState(item) {
  const asked = String(item?.asked ?? '')
  const answered = String(item?.answered ?? '')
  const read = String(item?.read ?? '')
  return { unread: Boolean(answered) && read < answered, waiting: Boolean(asked) && answered < asked }
}
