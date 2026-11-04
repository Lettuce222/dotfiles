// ペインの文に出る PR 番号・チケット ID・URL を markdown のリンクにする。
// #123 は、文脈のリポジトリ（owner/repo）が分かるときだけ PR へのリンクにする。
// チケット ID のリンク先は ~/hub/pane.json の "jira"（末尾にキーを足す URL）。

export type LinkContext = { repo?: string; jira?: string }

const GH_PR = /^https:\/\/github\.com\/([^/\s]+\/[^/\s]+)\/(?:pull|issues)\/(\d+)/
const JIRA_KEY = /^[A-Z][A-Z0-9]+-\d+$/

export function repoFromUrl(url: string | undefined): string | undefined {
  if (url === undefined) return undefined
  const m = GH_PR.exec(url)
  return m?.[1]
}

function urlLabel(url: string): string {
  const gh = GH_PR.exec(url)
  if (gh) return `${gh[1]?.split('/').pop() ?? ''}#${gh[2] ?? ''}`
  const jira = /\/browse\/([A-Z][A-Z0-9]+-\d+)/.exec(url)
  if (jira) return jira[1] ?? url
  if (/slack\.com\//.test(url)) return 'Slack'
  if (/confluence\./.test(url)) return 'Confluence'
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function escapeMd(text: string): string {
  return text.replace(/([\\`*_[\]<>])/g, '\\$1')
}

// 1 つの文を markdown にする。リンク以外の記号はエスケープする。
export function linkify(text: string, ctx: LinkContext): string {
  const re = /(https?:\/\/[^\s)）]+)|(?<![\w/])#(\d+)\b|(?<![\w-])([A-Z][A-Z0-9]+-\d+)(?![\w-])/g
  let out = ''
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    out += escapeMd(text.slice(last, m.index))
    const [whole, url, pr, key] = m
    if (url !== undefined) {
      out += `[${escapeMd(urlLabel(url))}](${url})`
    } else if (pr !== undefined && ctx.repo !== undefined) {
      out += `[#${pr}](https://github.com/${ctx.repo}/pull/${pr})`
    } else if (key !== undefined && ctx.jira !== undefined && JIRA_KEY.test(key)) {
      out += `[${key}](${ctx.jira}${key})`
    } else {
      out += escapeMd(whole)
    }
    last = m.index + whole.length
  }
  out += escapeMd(text.slice(last))
  return out
}
