// How the desk's browser tab is found and why it could not be shown. src/hub-worker.mjs runs the
// Orca CLI; this module only reads its answers. The desk's URL carries its token (`?t=`), and the
// CLI repeats the arguments it ran in an error, so every text that leaves here is redacted.

const TOKEN = /([?&]t=)[^\s&#'"`]+/g

/** A text with the desk's token taken out. */
export function redact(text) {
  return String(text ?? '').replace(TOKEN, '$1…')
}

/** The page id of a tab of `orca tab list --json`: browserPageId (older builds named it pageId or id). */
export function pageIdOf(tab) {
  const page = tab?.browserPageId ?? tab?.pageId ?? tab?.id ?? null
  return typeof page === 'string' && page.length > 0 ? page : null
}

/**
 * The desk's tab among the tabs of `orca tab list --json`: one whose URL is on the desk's origin, the
 * active one if several are open, else the last opened.
 */
export function findDeskTab(tabs, origin) {
  const desks = (Array.isArray(tabs) ? tabs : []).filter((tab) => typeof tab?.url === 'string' && tab.url.startsWith(`${origin}/`) && pageIdOf(tab))
  return desks.find((tab) => tab.active) ?? desks.at(-1) ?? null
}

/** Why a CLI call failed, in one line: the CLI's own error when it printed one, else the process's. */
export function failureOf(errorOrResponse) {
  const response = errorOrResponse?.response ?? errorOrResponse
  const error = response?.error
  if (error && typeof error === 'object') {
    const text = [error.code, error.message?.split('\n')[0]].filter(Boolean).join(': ')
    if (text) return redact(text)
  }
  if (errorOrResponse instanceof Error) {
    // execFile's message starts with "Command failed: <the command>", which holds the URL.
    const lines = errorOrResponse.message.split('\n').filter((line) => line && !line.startsWith('Command failed:'))
    return redact(lines[0] ?? errorOrResponse.code ?? 'failed')
  }
  return 'ok でない応答'
}

const MESSAGES = {
  'no-desk': 'デスクのサーバーが動いていません',
  'no-hub': 'Orca に hub のワークスペースが見つかりません',
  'create-failed': 'デスクのタブを作れませんでした',
  'focus-failed': 'デスクのタブはありますが、前に出せませんでした',
  failed: 'デスクを開く途中で失敗しました'
}

/** The text the panel and Orca's toast show for a result of openDesk. */
export function deskMessage(result) {
  if (result?.opened) return result.reused ? 'デスクを前に出しました' : 'デスクを開きました'
  const what = MESSAGES[result?.reason] ?? MESSAGES.failed
  return result?.detail ? `${what}（${result.detail}）` : what
}
