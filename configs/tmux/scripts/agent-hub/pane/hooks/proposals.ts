import type { Proposal } from '../types'

// ~/hub/proposals.md の 1 行 1 件の提案を読む。書き換えは hub（モデル）がする。
// - [ ] P1 タイトル source:: … plan:: … since:: …
const LINE = /^- \[(.)\] (P\d+) (.*)$/

export function splitAttrs(text: string): { title: string; attrs: Record<string, string> } {
  const idx = text.search(/\s\S+:: /)
  if (idx === -1) return { title: text.trim(), attrs: {} }
  const title = text.slice(0, idx).trim()
  const attrs: Record<string, string> = {}
  const re = /(\S+):: (.*?)(?=\s\S+:: |$)/g
  let m: RegExpExecArray | null
  const rest = text.slice(idx)
  while ((m = re.exec(rest)) !== null) {
    const key = m[1]
    const val = m[2]
    if (key !== undefined && val !== undefined) attrs[key] = val.trim()
  }
  return { title, attrs }
}

export function parseProposals(text: string): Proposal[] {
  const out: Proposal[] = []
  for (const line of text.split('\n')) {
    const m = LINE.exec(line)
    if (m === null) continue
    const mark = m[1] ?? ' '
    const id = m[2] ?? ''
    const { title, attrs } = splitAttrs(m[3] ?? '')
    out.push({ id, mark, title, attrs })
  }
  return out
}

export function openProposals(all: Proposal[]): Proposal[] {
  const pending = all.filter(p => p.mark === ' ')
  const later = all.filter(p => p.mark === '>')
  return [...pending, ...later]
}
